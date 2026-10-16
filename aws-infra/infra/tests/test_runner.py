"""AWS 호출 없이 Windows PowerShell 실행기의 계정·계획 격리를 검증한다."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE / ".local" / "tests" / ("runner-" + uuid.uuid4().hex[:8])
ROOT.mkdir(parents=True)
# 현재 작업 파일과 완전히 분리한 복사본에서만 설정을 바꾼다.
for name in ("scripts", "config", "terraform"):
    origin, target = SOURCE / name, ROOT / name
    if origin.is_dir():
        shutil.copytree(origin, target, ignore=shutil.ignore_patterns(".terraform", "*.tfplan", "*.tfstate*"))
    else:
        shutil.copy2(origin, target)
backend = ROOT / "config" / "backend.json"
backend.write_text(json.dumps(dict(bucket="test-state-bucket", region="ap-northeast-2",
                                  profile="account1", key_prefix="test")), encoding="utf-8")
mock_dir = ROOT / "mock-bin"
mock_dir.mkdir()
log = ROOT / "calls.jsonl"
mock_source = r'''
import json, os, pathlib, sys
tool, args = sys.argv[1], sys.argv[2:]
entry = {"tool": tool, "args": args, "ambient_credentials": bool(os.getenv("AWS_ACCESS_KEY_ID")),
         "data_dir": os.getenv("TF_DATA_DIR")}
with open(os.environ["INFRA_TEST_LOG"], "a", encoding="utf-8") as out:
    out.write(json.dumps(entry) + "\n")
if tool == "aws":
    if args[:2] == ["sts", "get-caller-identity"]:
        profile = args[args.index("--profile") + 1]
        ids = {"account1":"541308265856","account2":"529088287882","account3":"667879771148",
               "account4":"688567306400","account5":"217016296352"}
        print(json.dumps({"Account": "000000000000" if os.getenv("INFRA_TEST_BAD_ACCOUNT") else ids[profile]}))
    elif args[:2] == ["s3api", "get-bucket-versioning"]:
        print('{"Status":"Enabled"}')
    else:
        raise SystemExit("Unexpected AWS command")
else:
    action = args[1]
    if action == "plan":
        if os.getenv("INFRA_TEST_FAIL_PLAN"):
            raise SystemExit(2)
        pathlib.Path(next(a[5:] for a in args if a.startswith("-out="))).write_bytes(b"mock saved plan")
    elif action not in ("init", "apply", "validate", "test", "output"):
        raise SystemExit("Unexpected Terraform command")
'''
(mock_dir / "mock.py").write_text(mock_source, encoding="utf-8")
for tool in ("aws", "terraform"):
    (mock_dir / (tool + ".cmd")).write_text(
        '@echo off\n"' + sys.executable + '" "%~dp0mock.py" ' + tool + ' %*\n', encoding="utf-8")
env = os.environ.copy()
# PowerShell 7에서 시작해도 자식 Windows PowerShell이 자기 기본 모듈을 찾게 한다.
env.pop("PSModulePath", None)
env.update(PATH=str(mock_dir) + os.pathsep + env["PATH"],
           INFRA_TEST_LOG=str(log), AWS_ACCESS_KEY_ID="test-ambient-marker",
           AWS_SECRET_ACCESS_KEY="test-ambient-marker", PYTHONIOENCODING="utf-8")
shell = shutil.which("powershell.exe")
if not shell:
    raise SystemExit("Windows PowerShell 5.1이 필요합니다.")
def run(action, account="account1", stage="foundation", extra=None, ok=True):
    run_env = env | (extra or {})
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(ROOT / "scripts" / "infra.ps1"), "-Account", account,
                             "-Stage", stage, "-Action", action],
                            env=run_env, capture_output=True)
    if (result.returncode == 0) != ok:
        print(result.stdout.decode("utf-8", errors="replace"))
        print(result.stderr.decode("utf-8", errors="replace"))
        raise AssertionError((action, account, stage, result.returncode))
    return result
def calls():
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
def count_apply():
    return sum(c["tool"] == "terraform" and c["args"][1] == "apply" for c in calls())

run("Plan")
plan = ROOT / ".local" / "account1" / "foundation" / "saved.tfplan"
assert plan.exists()
run("Apply")
assert not plan.exists() and count_apply() == 1
print("PASS: saved plan apply and consumption")

run("Plan")
topology_path = ROOT / "config" / "topology.tfvars.json"
original = topology_path.read_text(encoding="utf-8")
config = json.loads(original)
config["topology"]["nodes"]["game-server"]["instance_type"] = "t3a.xlarge"
topology_path.write_text(json.dumps(config), encoding="utf-8")
before = len(calls())
run("Apply", ok=False)
assert len(calls()) == before and count_apply() == 1
topology_path.write_text(original, encoding="utf-8")
print("PASS: changed config blocks apply before AWS calls")

run("Plan", extra={"INFRA_TEST_BAD_ACCOUNT": "1"}, ok=False)
assert not plan.exists()
run("Apply", ok=False)
print("PASS: wrong profile account invalidates old plan")

run("Plan")
run("Plan", extra={"INFRA_TEST_FAIL_PLAN": "1"}, ok=False)
assert not (plan.parent / "saved-plan.json").exists()
run("Apply", ok=False)
print("PASS: failed new plan cannot reuse old plan")

before = len(calls())
run("Plan", account="shared", ok=False)
run("Plan", account="account1", stage="connectivity", ok=False)
assert len(calls()) == before
print("PASS: account and stage scope validation")

run("Plan", account="account2")
second = ROOT / ".local" / "account2" / "foundation" / "saved-plan.json"
assert json.loads(second.read_text())["state_key"] == "test/account2/foundation/terraform.tfstate"
assert not any(c["ambient_credentials"] for c in calls())
print("PASS: per-account backend and ambient credential isolation")

# 호출한 PowerShell 프로세스 내부에서도 기존 환경 값이 복원되는지 확인한다.
command = (
    "$env:AWS_ACCESS_KEY_ID='restore-marker'; "
    "& '" + str(ROOT / "scripts" / "infra.ps1").replace("'", "''") + "' -Account account1 -Stage foundation -Action Validate; "
    "if ($env:AWS_ACCESS_KEY_ID -ne 'restore-marker') { throw 'Environment was not restored' }"
)
restored = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-Command", command], env=env, capture_output=True)
assert restored.returncode == 0, restored.stderr
print("PASS: environment restoration")

traffic_path = ROOT / "config" / "traffic.tfvars.json"
traffic = json.loads(traffic_path.read_text(encoding="utf-8"))
traffic["traffic"]["admin_public_cidrs"] = ["0.0.0.0/0"]
traffic_path.write_text(json.dumps(traffic), encoding="utf-8")
before = len(calls())
run("Plan", ok=False)
assert len(calls()) == before
print("PASS: public SSH blocks before AWS calls")
print("All 8 runner scenarios passed. Fixture:", ROOT)
