"""실제 AWS 변경 없이 전체 EC2 중지·시작, 계정 경계와 실패 처리를 검증한다."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


SOURCE = Path(__file__).resolve().parents[1]
SHELL = shutil.which(sys.argv[1] if len(sys.argv) > 1 else "powershell")
assert SHELL, "PowerShell 실행 파일이 필요합니다."
SUITE = SOURCE / ".local/tests" / ("power-" + uuid.uuid4().hex[:8])
SUITE.mkdir(parents=True)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def seed(name, state="running"):
    root = SUITE / name
    infra = root / "infra"
    shutil.copytree(SOURCE / "scripts", infra / "scripts")
    profile = infra / "config/profiles/current"
    topology = {"project": "power-test", "region": "ap-northeast-2", "accounts": {}, "nodes": {}}
    profile_hash = hashlib.sha256(str(profile).lower().encode()).hexdigest()[:16].upper()
    for number in range(1, 6):
        account = f"account{number}"
        owner = str(number) * 12
        topology["accounts"][account] = {"id": owner, "profile": account}
        names = ["bastion", "node1"] if number == 1 else [f"node{number}"]
        instances = []
        outputs = {}
        for index, node in enumerate(names):
            role = "bastion" if node == "bastion" else "mysql"
            instance_id = f"i-{number:015x}{index:02x}"
            topology["nodes"][node] = {"account": account, "role": role}
            tags = {"Project": "power-test", "Account": account, "ManagedBy": "Terraform", "Layout": "v2",
                    "Node": node, "Role": role}
            if role == "bastion":
                tags["Stage"] = "bastion"
            instances.append({"InstanceId": instance_id, "RootDeviceType": "ebs", "State": {"Name": state},
                              "PrivateIpAddress": f"10.{number}.0.{index + 1}",
                              "Tags": [{"Key": key, "Value": value} for key, value in tags.items()]})
            metadata = {"account": account, "account_id": owner, "region": "ap-northeast-2"}
            base = infra / f".local/profiles/{profile_hash}/{account}"
            if role == "bastion":
                write(base / "bastion/outputs.json", {"bastion": {"value": dict(metadata, id=instance_id)}})
            else:
                outputs[node] = {"id": instance_id}
        write(base / "workload/outputs.json", {"inventory": {"value": dict(metadata, instances=outputs)}})
        write(root / f"{account}.json", {"owner": owner, "instances": instances})
    write(profile / "topology.tfvars.json", {"topology": topology})
    (root / "bin").mkdir()
    (root / "bin/aws.cmd").write_text(
        f'@echo off\n"{sys.executable}" "{SOURCE / "tests/power_cli.py"}" %*\n', encoding="utf-8")
    return root


def calls(root):
    return [json.loads(line) for log in root.glob("account*.jsonl") for line in log.read_text(encoding="utf-8").splitlines()]


def mutations(root):
    return [entry for entry in calls(root) if entry["args"][1] in ("start-instances", "stop-instances")
            and "--dry-run" not in entry["args"]]


def run(root, action, fault="", what_if=False, success=True, timeout=30, file_entry=False):
    env = os.environ.copy()
    env.pop("PSModulePath", None)
    env.update(INFRA_POWER_TEST_ROOT=str(root), INFRA_POWER_TEST_FAULT=fault, PYTHONUTF8="1",
               AWS_ACCESS_KEY_ID="test-isolate", AWS_SECRET_ACCESS_KEY="test-isolate",
               AWS_ENDPOINT_URL="https://invalid.example", PATH=str(root / "bin") + os.pathsep + env["PATH"])
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    # 가짜 CLI 경로를 먼저 확인하여 테스트 실수로 실제 AWS가 호출되지 않게 한다.
    command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
    command += f"if ((Get-Command aws -CommandType Application | Select-Object -First 1).Source -ne {quote(root / 'bin/aws.cmd')}) {{ throw 'Mock CLI was not selected' }}; "
    command += f"& {quote(root / 'infra/scripts/power-all.ps1')} -Action {action} -TimeoutSeconds {timeout}"
    if what_if:
        command += " -WhatIf"
    command += "; if ($env:AWS_ACCESS_KEY_ID -ne 'test-isolate') { throw 'Parent environment changed' }"
    invocation = [SHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    if file_entry:
        # -File 진입의 기본 경로 평가도 별도 검사한다. 이 경로는 미리보기만 허용한다.
        assert what_if
        invocation += ["-File", str(root / "infra/scripts/power-all.ps1"), "-Action", action, "-WhatIf"]
    else:
        invocation += ["-Command", command]
    result = subprocess.run(invocation,
                            env=env, cwd=root, capture_output=True, timeout=120)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    (root / "last-output.txt").write_text(output, encoding="utf-8")
    assert (result.returncode == 0) == success, output
    for entry in calls(root):
        assert not entry["ambient"] and not entry["endpoint"] and entry["ignore_endpoints"] == "true"
    return output


root = seed("cycle", "stopped")
output = run(root, "Start")
assert "203.0.113.42" in output and len(mutations(root)) == 5
run(root, "Stop")
assert len(mutations(root)) == 10
run(root, "Stop")
assert len(mutations(root)) == 10
print("PASS: parallel account Start/Stop, current IP, repeated Stop and credential isolation", flush=True)

root = seed("preview")
run(root, "Stop", what_if=True)
assert not mutations(root)
assert sum("--dry-run" in entry["args"] for entry in calls(root)) == 5
print("PASS: WhatIf validates permissions without changing power", flush=True)

root = seed("file-entry")
run(root, "Stop", what_if=True, file_entry=True)
assert not mutations(root) and len(calls(root)) == 15
print("PASS: -File entry resolves the default profile outside the script directory", flush=True)

for fault in ("identity", "permission", "missing", "tags", "root", "terminated"):
    root = seed(fault)
    run(root, "Stop", fault=fault, success=False)
    assert not mutations(root)
    print(f"PASS: {fault} blocks all actual power requests", flush=True)

root = seed("bad-cache")
path = next((root / "infra/.local").glob("profiles/*/account5/workload/outputs.json"))
data = json.loads(path.read_text())
data["inventory"]["value"]["account_id"] = "000000000000"
write(path, data)
run(root, "Stop", success=False)
assert not calls(root)
print("PASS: mismatched deployment output rejected before AWS calls", flush=True)

root = seed("mixed-transition", "stopped")
for number, state in ((2, "running"), (3, "pending"), (4, "stopping")):
    path = root / f"account{number}.json"
    data = json.loads(path.read_text())
    for item in data["instances"]:
        item["State"]["Name"] = state
    write(path, data)
run(root, "Start", fault="transition")
assert len(mutations(root)) == 3
print("PASS: mixed states wait for transitions and skip running instances", flush=True)

root = seed("partial")
run(root, "Stop", fault="partial", success=False)
assert len(mutations(root)) == 5
for number in range(1, 5):
    assert all(item["State"]["Name"] == "stopped" for item in json.loads((root / f"account{number}.json").read_text())["instances"])
print("PASS: partial failure collects other account results and returns failure", flush=True)

root = seed("timeout")
run(root, "Stop", fault="timeout", timeout=1, success=False)
assert len(mutations(root)) == 5
print("PASS: timeout returns failure without forced shutdown or repeated requests", flush=True)
print("All 13 power scenarios passed. Fixture:", SUITE, flush=True)
