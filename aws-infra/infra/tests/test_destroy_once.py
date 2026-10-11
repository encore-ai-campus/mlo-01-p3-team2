"""실제 AWS 없이 한 번의 전체 삭제와 데이터 EBS 보호 복원을 검증한다."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import uuid

import test_destroy_all as harness


def apply_steps(root):
    # 적용 후 삭제되는 계획 파일 대신 가짜 CLI 호출 기록으로 순서를 확인한다.
    log = root / 'calls.jsonl'
    if not log.exists():
        return []
    steps = []
    for line in log.read_text(encoding='utf-8').splitlines():
        call = json.loads(line)
        if call['kind'] == 'terraform' and 'apply' in call['args']:
            directory = Path(call['args'][-1]).parent
            steps.append(directory.parent.name + '/' + directory.name)
    return steps


def mock_cli(kind, args):
    # 기존 가짜 CLI 앞에서 실패·외부 변경을 주입한다. 실제 CLI는 호출하지 않는다.
    root = Path(os.environ['DESTROY_MOCK_ROOT'])
    fault = os.environ.get('DESTROY_ONCE_FAULT', '')
    if kind == 'terraform' and 'plan' in args:
        if fault == 'protected' and any('workload' in arg for arg in args):
            source = root / 'infra/terraform/modules/compute/main.tf'
            if 'prevent_destroy = true' in source.read_text(encoding='utf-8-sig'):
                print('Mock Terraform: data EBS prevent_destroy blocks deletion', file=sys.stderr)
                return 1
        if fault == 'plan_failure':
            print('Injected plan failure', file=sys.stderr)
            return 1
        if fault in ('source_conflict', 'backup_conflict'):
            marker = root / 'fault-injected'
            if not marker.exists():
                if fault == 'source_conflict':
                    target = root / 'infra/terraform/modules/compute/main.tf'
                else:
                    target = next((root / 'infra/.local/destroy-all').glob('*/data-protection.original.tf'))
                with target.open('ab') as stream:
                    stream.write(b'\n# external test edit\n')
                marker.write_text('injected', encoding='utf-8')
    if kind == 'terraform' and 'apply' in args and fault == 'apply_failure':
        if apply_steps(root):
            print('Injected apply failure', file=sys.stderr)
            return 1
    return subprocess.run([sys.executable, str(Path(harness.__file__).with_name('destroy_cli.py')), kind, *args]).returncode


def make_fixture(root, infra, protected=True, full=False):
    harness.seed(root, infra)
    # 시험 조건은 작업 파일의 현재 true/false와 무관하게 사본에서만 지정한다.
    source = root / 'infra/terraform/modules/compute/main.tf'
    text = source.read_text(encoding='utf-8-sig')
    text = text.replace('prevent_destroy = false', 'prevent_destroy = true')
    if not protected:
        text = text.replace('prevent_destroy = true', 'prevent_destroy = false')
    source.write_bytes(b'\xef\xbb\xbf' + text.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
    if not full:
        states = harness.read(root / 'states.json')
        harness.write(root / 'states.json', {key: value for key, value in states.items() if key in ('account1/bastion', 'account1/workload')})
    for kind in ('aws', 'terraform'):
        (root / f'bin/{kind}.cmd').write_text(
            f'@echo off\n"{sys.executable}" "{Path(__file__).resolve()}" --mock-cli {kind} %*\n', encoding='utf-8')
    return source


def invoke_once(root, shell, action='Destroy', run_id=None, fault='', consent=True, disable=True, success=True):
    # 실행 전에 가짜 CLI 선택을 검사하여 실제 AWS/Terraform으로의 이탈을 차단한다.
    env = os.environ.copy()
    env.update(PATH=str(root / 'bin') + os.pathsep + env['PATH'], DESTROY_MOCK_ROOT=str(root),
               DESTROY_MOCK_FAULT='', DESTROY_ONCE_FAULT=fault, PYTHONUTF8='1')
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
               "foreach ($n in @('aws','terraform')) { if (-not (Get-Command $n -CommandType Application).Source.StartsWith("
               + quote(root / 'bin') + ")) { throw 'Mock CLI was not selected' } }; & "
               + quote(root / 'infra/scripts/destroy-all.ps1') + ' -Action ' + action)
    if run_id:
        command += ' -RunId ' + quote(run_id)
    if consent:
        command += ' -DeleteDataVolumes'
    if disable:
        command += ' -DisableDataVolumeProtection'
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', command],
                            env=env, capture_output=True, timeout=240)
    output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    (root / 'last-output.txt').write_text(output, encoding='utf-8')
    assert (result.returncode == 0) == success, output
    records = list((root / 'infra/.local/destroy-all').glob('*/run.json'))
    return harness.read(max(records, key=lambda path: path.stat().st_mtime_ns)) if records else None


def main():
    shell = shutil.which(sys.argv[1] if len(sys.argv) > 1 else 'powershell')
    assert shell, 'PowerShell executable not found'
    infra = Path(__file__).resolve().parents[1]
    original = (infra / 'terraform/modules/compute/main.tf').read_bytes()
    suite = infra / '.local/tests' / ('destroy-once-' + uuid.uuid4().hex)
    count = 0

    # 정상 실행은 12개 단계 순서·동일 실행 ID·바이트 복원과 이후 Verify까지 검사한다.
    root = suite / 'complete'
    source = make_fixture(root, infra, full=True)
    before = source.read_bytes()
    run = invoke_once(root, shell)
    assert run['status'] == 'Complete' and run['data_protection']['state'] == 'Restored'
    assert source.read_bytes() == before
    expected = ['account1/bastion', *[f'account{i}/workload' for i in range(1, 6)],
                'shared/connectivity', *[f'account{i}/foundation' for i in range(1, 6)]]
    assert apply_steps(root) == expected
    assert all(step['status'] == 'Deleted' for step in run['steps'])
    invoke_once(root, shell, 'Status', run['run_id'], disable=False)
    invoke_once(root, shell, 'Verify', run['run_id'], disable=False)
    count += 1
    # 복원 후 다른 코드 변경은 Verify에서도 거부하며 삭제를 재실행하지 않는다.
    with source.open('ab') as stream:
        stream.write(b'\n# verify drift\n')
    invoke_once(root, shell, 'Verify', run['run_id'], disable=False, success=False)
    assert apply_steps(root) == expected
    count += 1

    for name, fault, expected_status, expected_calls in (
        ('plan-failure', 'plan_failure', 'Failed', 0),
        ('apply-failure', 'apply_failure', 'Failed', 1),
    ):
        root = suite / name
        source = make_fixture(root, infra)
        before = source.read_bytes()
        run = invoke_once(root, shell, fault=fault, success=False)
        assert run['status'] == expected_status and source.read_bytes() == before
        assert run['data_protection']['state'] == 'Restored'
        assert len(apply_steps(root)) == expected_calls
        count += 1

    for name, action, consent, disable, run_id in (
        ('missing-consent', 'Destroy', False, True, None),
        ('wrong-action', 'Plan', True, True, None),
        ('old-run-id', 'Destroy', True, True, 'a' * 32),
    ):
        root = suite / name
        source = make_fixture(root, infra)
        before = source.read_bytes()
        invoke_once(root, shell, action, run_id, consent=consent, disable=disable, success=False)
        assert source.read_bytes() == before and not apply_steps(root)
        assert not (root / 'calls.jsonl').exists()
        count += 1

    root = suite / 'already-disabled'
    source = make_fixture(root, infra, protected=False)
    before = source.read_bytes()
    run = invoke_once(root, shell)
    assert run['status'] == 'Complete' and run['data_protection']['state'] == 'AlreadyDisabled'
    assert source.read_bytes() == before
    count += 1

    root = suite / 'no-disable-option'
    source = make_fixture(root, infra)
    before = source.read_bytes()
    invoke_once(root, shell, fault='protected', disable=False, success=False)
    assert source.read_bytes() == before and not apply_steps(root)
    count += 1

    root = suite / 'unsupported-layout'
    source = make_fixture(root, infra)
    source.write_bytes(source.read_bytes().replace(b'prevent_destroy = true', b'prevent_destroy = local.protect'))
    before = source.read_bytes()
    invoke_once(root, shell, success=False)
    assert source.read_bytes() == before and not apply_steps(root)
    count += 1

    for fault in ('source_conflict', 'backup_conflict'):
        root = suite / fault
        source = make_fixture(root, infra)
        run = invoke_once(root, shell, fault=fault, success=False)
        assert run['status'] == 'ProtectionRestoreFailed'
        assert not apply_steps(root)
        if fault == 'source_conflict':
            assert b'external test edit' in source.read_bytes()
        assert (root / f"infra/.local/destroy-all/{run['run_id']}/data-protection.original.tf").exists()
        count += 1

    assert (infra / 'terraform/modules/compute/main.tf').read_bytes() == original
    print(f'PASS: {count} destroy-once scenarios ({Path(shell).name}); fixtures: {suite}', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--mock-cli':
        raise SystemExit(mock_cli(sys.argv[2], sys.argv[3:]))
    main()
