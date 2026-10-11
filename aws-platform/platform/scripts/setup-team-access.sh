#!/usr/bin/env bash
set -euo pipefail

# 실행 위치 대신 스크립트 위치를 사용한다. Python은 인벤토리와 설정 파일을 안전하게 다룬다.
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  printf '오류: WSL에 Python 3가 필요합니다. Ansible 가상환경을 활성화하세요.\n' >&2
  exit 1
fi
python3 - "$platform_dir" "$@" <<'PY'
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

MARKER = '# Managed by setup-team-access.sh'


def fail(message):
    raise ValueError(message)


def run(command, env, capture=False):
    return subprocess.run(command, env=env, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, timeout=90)


def ssh_value(value):
    # SSH 설정의 따옴표·토큰 해석 때문에 경로가 명령으로 바뀌지 않도록 처리한다.
    return '"' + str(value).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'


def managed_write(path, content, is_inventory=False):
    # 사용자 파일은 덮어쓰지 않고, 이 도구가 만든 파일만 원자적으로 교체한다.
    if path.is_symlink():
        fail(f'생성 대상이 심볼릭 링크입니다: {path}')
    if path.exists():
        previous = path.read_text(encoding='utf-8')
        owned = previous.startswith(MARKER + '\n')
        if is_inventory:
            try:
                owned = json.loads(previous).get('all', {}).get('vars', {}).get(
                    'project_access_managed_by') == 'setup-team-access.sh'
            except (ValueError, AttributeError):
                owned = False
        if not owned:
            fail(f'기존 사용자 파일을 덮어쓰지 않습니다: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.team-access-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if sys.version_info < (3, 8) or not sys.platform.startswith('linux'):
        fail('WSL/Linux의 Python 3.8 이상에서 실행하세요.')
    platform = Path(sys.argv[1]).resolve()
    parser = argparse.ArgumentParser(description='이미 준비한 Endpoint를 사용해 WSL의 SSH·Ansible 접속 설정을 생성합니다.')
    parser.add_argument('--inventory', required=True, help='입력 인벤토리. 상대 경로는 현재 디렉터리 기준')
    parser.add_argument('--aws-profile', required=True, help='현재 WSL에 준비된 AWS 프로필')
    parser.add_argument('--region', required=True)
    parser.add_argument('--endpoint-id', required=True)
    parser.add_argument('--key-directory', help='계정별 키 파일명은 유지하고 이 디렉터리에서 찾음')
    parser.add_argument('--output-inventory', help='기본: 입력 파일 옆 hosts.team.yml')
    parser.add_argument('--ssh-config', default='~/.ssh/project-access/config')
    parser.add_argument('--check-host', help='검사할 프라이빗 호스트명. 기본: 이름순 첫 호스트')
    args = parser.parse_args(sys.argv[2:])
    if not re.fullmatch(r'eice-[0-9a-f]+', args.endpoint_id):
        fail('--endpoint-id는 eice-로 시작하는 실제 Endpoint ID여야 합니다.')
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)+-\d+', args.region):
        fail('--region이 올바르지 않습니다.')
    if not re.fullmatch(r'[A-Za-z0-9_.@+-]+', args.aws_profile):
        fail('--aws-profile에는 영문·숫자와 _.@+-만 사용할 수 있습니다.')

    executables = {}
    for name in ('aws', 'ssh', 'ansible'):
        executables[name] = shutil.which(name)
        if not executables[name]:
            fail(f'{name}가 없습니다. WSL 도구 설치 및 Ansible 가상환경을 확인하세요.')
    source = Path(args.inventory).expanduser().resolve()
    destination = Path(args.output_inventory).expanduser().absolute() if args.output_inventory else source.with_name('hosts.team.yml')
    config = Path(args.ssh_config).expanduser().absolute()
    if source == destination.resolve() or config.resolve() in (source, destination.resolve()):
        fail('입력 인벤토리와 생성 파일은 서로 다른 경로여야 합니다.')
    for path in (source, destination, config):
        if any(character in str(path) for character in ('\n', '\r', '\x00')):
            fail('경로에 제어 문자를 사용할 수 없습니다.')
    # Secret과 group_vars를 읽거나 펼치지 않고 정적 인벤토리만 복사한다.
    raw = source.read_text(encoding='utf-8-sig')
    try:
        inventory = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError:
            fail('YAML 인벤토리에는 PyYAML이 필요합니다. Ansible 가상환경에서 실행하세요.')
        inventory = yaml.safe_load(raw)
    if not isinstance(inventory, dict) or '_meta' in inventory:
        fail('all/children/hosts 형식의 정적 YAML 또는 JSON 인벤토리를 지정하세요.')
    if 'all' not in inventory:
        inventory = {'all': {'children': inventory}}
    if not isinstance(inventory['all'], dict):
        fail('인벤토리 all은 매핑이어야 합니다.')

    hosts, bastions, occurrences = {}, set(), {}

    def collect(group, inherited, in_bastion=False):
        if not isinstance(group, dict):
            fail('인벤토리 그룹은 매핑이어야 합니다.')
        variables = group.get('vars') or {}
        members = group.get('hosts') or {}
        children = group.get('children') or {}
        if not all(isinstance(value, dict) for value in (variables, members, children)):
            fail('vars/hosts/children은 매핑이어야 합니다.')
        defaults = {**inherited, **variables}
        for name, fields in members.items():
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
                fail(f'지원하지 않는 SSH 호스트명: {name}')
            if fields is None:
                fields = {}
                members[name] = fields
            if not isinstance(fields, dict):
                fail(f'{name}의 호스트 변수는 매핑이어야 합니다.')
            # 여러 그룹에 같은 호스트가 있어도 명시한 호스트 변수를 우선한다.
            record = hosts.setdefault(name, {'defaults': {}, 'fields': {}})
            record['defaults'].update(defaults)
            for key, value in fields.items():
                if key in record['fields'] and record['fields'][key] != value:
                    fail(f'{name}의 호스트 변수 {key}가 그룹마다 다릅니다.')
                record['fields'][key] = value
            occurrences.setdefault(name, []).append(fields)
            if in_bastion:
                bastions.add(name)
        for name, child in children.items():
            collect(child, defaults, in_bastion or name == 'bastion')

    collect(inventory['all'], {})
    if len(bastions) != 1:
        fail('bastion 그룹에는 배스천 호스트가 정확히 1대 있어야 합니다.')
    bastion = next(iter(bastions))
    clients = sorted(set(hosts) - bastions)
    if not clients:
        fail('검사할 프라이빗 서버가 없습니다.')
    check_host = args.check_host or clients[0]
    if check_host not in clients:
        fail('--check-host는 인벤토리에 있는 배스천 외 호스트여야 합니다.')
    key_directory = Path(args.key_directory).expanduser().resolve() if args.key_directory else None
    connection = {}
    all_keys = set()
    for name, record in hosts.items():
        values = {**record['defaults'], **record['fields']}
        address = values.get('ip', values.get('ansible_host'))
        try:
            address = ipaddress.ip_address(str(address))
        except ValueError:
            fail(f'{name}: 실제 사설 IP를 ip 또는 ansible_host에 지정하세요.')
        if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified or address.is_multicast:
            fail(f'{name}: 내부 연결에 사용할 사설 IP가 필요합니다.')
        user = values.get('ansible_user')
        if not isinstance(user, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', user):
            fail(f'{name}: 실제 ansible_user를 인벤토리에 지정하세요.')
        port = values.get('ansible_port', 22)
        if str(port) != '22':
            fail(f'{name}: 이 스크립트는 SSH 포트 22를 사용합니다.')
        key = values.get('ansible_ssh_private_key_file')
        if not isinstance(key, str) or not key:
            fail(f'{name}: ansible_ssh_private_key_file이 필요합니다.')
        if key_directory:
            filename = key.replace('\\', '/').rsplit('/', 1)[-1]
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', filename):
                fail(f'{name}: 키 파일명을 해석할 수 없습니다.')
            key = str(key_directory / filename)
        else:
            key = re.sub(r"\{\{\s*lookup\(['\"]env['\"],\s*['\"]HOME['\"]\)\s*\}\}", str(Path.home()), key)
            if '{{' in key or '}}' in key or re.match(r'^[A-Za-z]:', key):
                fail(f'{name}: --key-directory로 WSL의 키 디렉터리를 지정하세요.')
        key = Path(key).expanduser()
        if not key.is_absolute():
            key = source.parent / key
        key = key.resolve()
        if not key.is_file() or not os.access(key, os.R_OK):
            fail(f'{name}: 키 파일이 없거나 읽을 권한이 없습니다: {key}')
        if any(character in str(key) for character in ('\n', '\r', '\x00')):
            fail('키 경로에 제어 문자를 사용할 수 없습니다.')
        all_keys.add(key)
        connection[name] = (str(address), user, key)

    env = dict(os.environ, AWS_PAGER='', AWS_CLI_AUTO_PROMPT='off', ANSIBLE_CONFIG=str(platform / 'ansible.cfg'))
    version = run([executables['aws'], '--version'], env, capture=True).stdout
    if not version.startswith('aws-cli/2.'):
        fail('WSL에 AWS CLI v2가 필요합니다.')
    aws_args = ['--profile', args.aws_profile, '--region', args.region, '--no-cli-pager', '--output', 'json']
    print('1/4 AWS 인증과 Endpoint 상태 확인', flush=True)
    identity = json.loads(run([executables['aws'], 'sts', 'get-caller-identity', *aws_args], env, capture=True).stdout)
    endpoints = json.loads(run([executables['aws'], 'ec2', 'describe-instance-connect-endpoints',
                               '--instance-connect-endpoint-ids', args.endpoint_id, *aws_args], env, capture=True).stdout)
    matches = endpoints.get('InstanceConnectEndpoints', [])
    if len(matches) != 1 or matches[0].get('InstanceConnectEndpointId') != args.endpoint_id or matches[0].get('State') != 'create-complete':
        fail('지정한 Endpoint가 준비 상태(create-complete)가 아닙니다.')
    print(f"AWS 계정: {identity['Account']} / 리전: {args.region}", flush=True)
    # 개인키 내용은 읽지 않는다. Windows 마운트에서 권한이 유지되지 않으면 Linux 홈으로 옮기도록 안내한다.
    for key in all_keys:
        os.chmod(key, 0o600)
        if stat.S_IMODE(key.stat().st_mode) & 0o077:
            fail(f'키 권한을 제한할 수 없습니다. WSL 홈에 키를 배치하세요: {key}')

    print('2/4 프로젝트 SSH 설정과 접속용 인벤토리 생성', flush=True)
    lines = [MARKER, '# Endpoint·IAM은 관리자가 먼저 준비한다. 기존 SSH 설정은 변경하지 않는다.']
    for name in sorted(connection):
        address, user, key = connection[name]
        lines.extend([f'Host {name}', f'    HostName {address}', f'    User {user}',
                      f'    IdentityFile {ssh_value(key)}', '    IdentitiesOnly yes', '    BatchMode yes',
                      '    StrictHostKeyChecking accept-new', '    ConnectTimeout 20'])
        if name == bastion:
            command = ['env', 'AWS_PAGER=', 'AWS_CLI_AUTO_PROMPT=off', executables['aws'],
                       'ec2-instance-connect', 'open-tunnel', '--instance-connect-endpoint-id', args.endpoint_id,
                       '--private-ip-address', address, '--remote-port', '22', '--max-tunnel-duration', '3600',
                       '--profile', args.aws_profile, '--region', args.region, '--no-cli-pager']
            proxy = shlex.join(command).replace('%', '%%')
        else:
            proxy = shlex.join([executables['ssh'], '-F', str(config), '-W']).replace('%', '%%')
            proxy += ' %h:%p ' + shlex.quote(bastion)
        lines.extend(['    ProxyCommand ' + proxy, ''])
        for fields in occurrences[name]:
            fields.update(ansible_host=name, ansible_user=user, ansible_port=22,
                          ansible_connection='ssh', ansible_ssh_private_key_file=str(key),
                          ansible_ssh_common_args='-F ' + shlex.quote(str(config)), ansible_ssh_extra_args='',
                          ansible_ssh_executable=executables['ssh'])
    # 재실행해도 원본을 변경하지 않는다. 역할 그룹·내부 IP·프록시 변수는 유지한다.
    inventory['all']['vars'] = inventory['all'].get('vars') or {}
    inventory['all']['vars']['project_access_managed_by'] = 'setup-team-access.sh'
    # 두 생성 파일 모두 기존 사용자 파일이 아닌지 쓰기 전에 확인한다.
    for target, is_inventory in ((config, False), (destination, True)):
        if target.is_symlink():
            fail(f'생성 대상이 심볼릭 링크입니다: {target}')
        if target.exists():
            previous = target.read_text(encoding='utf-8')
            if is_inventory:
                try:
                    owned = json.loads(previous).get('all', {}).get('vars', {}).get('project_access_managed_by') == 'setup-team-access.sh'
                except (ValueError, AttributeError):
                    owned = False
            else:
                owned = previous.startswith(MARKER + '\n')
            if not owned:
                fail(f'기존 사용자 파일을 덮어쓰지 않습니다: {target}')
    managed_write(config, '\n'.join(lines) + '\n')
    managed_write(destination, json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', True)
    print('3/4 배스천 SSH 접속 확인', flush=True)
    run([executables['ssh'], '-F', str(config), bastion, 'true'], env)
    print(f'4/4 {check_host}의 SSH·원격 Python 확인', flush=True)
    # Ansible 호출 때 기존 group_vars/Vault가 로드될 수 있으므로 사용자의 Vault 환경을 유지한다.
    run([executables['ansible'], '-i', str(destination), check_host, '-m', 'ansible.builtin.ping'], env)
    print(f'접속 준비 완료\nSSH 설정: {config}\n인벤토리: {destination}', flush=True)
    print('SSH: ' + shlex.join(['ssh', '-F', str(config), check_host]))
    print('Ansible: ' + shlex.join(['ansible', '-i', str(destination), check_host, '-m', 'ansible.builtin.ping']))


try:
    main()
except (ValueError, TypeError, OSError, subprocess.SubprocessError) as error:
    print(f'오류: {error}\n접속 준비를 완료하지 못했습니다. 생성된 설정이 있으면 입력을 확인하고 재실행하세요.', file=sys.stderr)
    sys.exit(1)
PY
