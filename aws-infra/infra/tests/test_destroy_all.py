"""실제 AWS 없이 전체 삭제의 계획 검토·실행 순서·실패 경계를 검증한다."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def seed(root, infra, protected=False):
    shutil.copytree(infra, root / "infra", ignore=shutil.ignore_patterns(".local", ".terraform", "*.pem", "*.key"))
    (root / "bin").mkdir()
    for name in ("aws", "terraform"):
        (root / "bin" / f"{name}.cmd").write_text(
            f'@echo off\n"{sys.executable}" "{infra / "tests/destroy_cli.py"}" {name} %*\n', encoding="utf-8"
        )
    # 실제 설정값과 무관하게 테스트 사본에 해당 시나리오의 보호 상태를 지정한다.
    compute = root / "infra/terraform/modules/compute/main.tf"
    expected_setting = f"prevent_destroy = {str(protected).lower()}"
    compute_text = compute.read_text(encoding="utf-8-sig")
    compute.write_text(
        compute_text.replace("prevent_destroy = true", expected_setting)
        .replace("prevent_destroy = false", expected_setting),
        encoding="utf-8",
    )
    topology = read(root / "infra/config/topology.tfvars.json")["topology"]
    targets = [("account1", "bastion")] + [(f"account{n}", "workload") for n in range(1, 6)] + [("shared", "connectivity")] + [(f"account{n}", "foundation") for n in range(1, 6)]
    states, live = {}, {}
    for account, stage in targets:
        owner = "account1" if account == "shared" else account
        tags = {"Project": topology["project"], "Account": owner, "Layout": "v2", "ManagedBy": "Terraform"}
        if stage == "bastion":
            address, kind, resource_id = "module.bastion.aws_instance.this", "aws_instance", "i-bastion"
            tags["Stage"] = "bastion"
        elif stage == "workload":
            address, kind, resource_id = 'module.compute.aws_ebs_volume.data["data"]', "aws_ebs_volume", f"vol-{account}"
        elif stage == "foundation":
            address, kind, resource_id = "module.network.aws_vpc.this", "aws_vpc", f"vpc-{account}"
        else:
            address, kind, resource_id = "module.account1_account2[0].aws_vpc_peering_connection.this", "aws_vpc_peering_connection", "pcx-test"
        attributes = {"id": resource_id, "tags_all": tags}
        if kind == "aws_instance":
            attributes["root_block_device"] = [{"volume_id": "vol-root", "delete_on_termination": True}]
            live["vol-root"] = True
        states[f"{account}/{stage}"] = {"version": 4, "lineage": f"{account}-{stage}", "serial": 1, "outputs": {}, "resources": [{"address": address, "mode": "managed", "type": kind, "instances": [{"attributes": attributes}]}]}
        if stage == "connectivity":
            accepter_tags = dict(tags, Account="account2")
            states[f"{account}/{stage}"]["resources"].append({"address": "module.account1_account2[0].aws_vpc_peering_connection_accepter.this", "mode": "managed", "type": "aws_vpc_peering_connection_accepter", "instances": [{"attributes": {"id": resource_id, "tags_all": accepter_tags}}]})
        live[resource_id] = True
    write(root / "states.json", states)
    write(root / "live.json", live)
    return [f"{a}/{s}" for a, s in targets]


def invoke(root, shell, action, run_id=None, fault="", consent=True, success=True):
    env = os.environ.copy()
    env.update({"DESTROY_MOCK_ROOT": str(root), "DESTROY_MOCK_FAULT": fault, "AWS_ACCESS_KEY_ID": "must-be-isolated", "PYTHONUTF8": "1"})
    env["PATH"] = str(root / "bin") + os.pathsep + env["PATH"]
    script = root / "infra/scripts/destroy-all.ps1"
    # 가짜 실행 파일이 먼저 선택되지 않으면 실제 실행기에 진입하지 않는다.
    escape = lambda value: "'" + str(value).replace("'", "''") + "'"
    guard = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); " + f"foreach ($n in @('aws','terraform')) {{ if (-not (Get-Command $n -CommandType Application).Source.StartsWith({escape(root / 'bin')})) {{ throw 'Mock CLI was not selected' }} }}; "
    command = guard + f"& {escape(script)} -Action {action}"
    if run_id:
        command += f" -RunId {run_id}"
    if consent and action in ("Plan", "Apply"):
        command += " -DeleteDataVolumes"
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command], env=env, cwd=root, capture_output=True)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    (root / "last-output.txt").write_text(output, encoding="utf-8")
    assert (result.returncode == 0) == success, output
    if action == "Plan" and success:
        runs = list((root / "infra/.local/destroy-all").glob("*/run.json"))
        return max(runs, key=lambda p: p.stat().st_mtime_ns).parent.name
    return output


def apply_calls(root):
    path = root / "calls.jsonl"
    calls = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return [read(call["args"][-1])["mock_key"] for call in calls if call["kind"] == "terraform" and call["args"][1] == "apply" and Path(call["args"][-1]).exists()]


def main():
    infra = Path(__file__).resolve().parents[1]
    shell = shutil.which(sys.argv[1] if len(sys.argv) > 1 else "powershell")
    assert shell
    suite = infra / ".local/tests" / ("destroy-" + uuid.uuid4().hex)
    suite.mkdir(parents=True)
    template = suite / "template"
    expected = seed(template, infra)
    run_id = invoke(template, shell, "Plan")
    assert read(template / f"infra/.local/destroy-all/{run_id}/run.json")["status"] == "Ready"
    assert not apply_calls(template)
    print("PASS: all plans prepared without Apply", flush=True)

    def clone(name):
        path = suite / name
        shutil.copytree(template, path)
        (path / "calls.jsonl").write_text("", encoding="utf-8")
        return path

    # 준비된 동일 계획을 복사해 실패마다 앞 단계 삭제가 시작되지 않는지 검사한다.
    for name, mutate, fault, consent in [
        ("consent", None, "", False),
        ("wrong-account", None, "wrong-account", True),
        ("access-denied", None, "access-denied", True),
        ("tampered-plan", "plan", "", True),
        ("state-drift", "state", "", True),
        ("reordered", "order", "", True),
        ("changed-code", "code", "", True),
        ("changed-key", "key", "", True),
    ]:
        root = clone(name)
        directory = root / f"infra/.local/destroy-all/{run_id}"
        if mutate == "plan":
            with (directory / "account5/foundation/saved.tfplan").open("a") as f:
                f.write(" ")
        elif mutate == "state":
            states = read(root / "states.json")
            states["account5/foundation"]["serial"] += 1
            write(root / "states.json", states)
        elif mutate == "order":
            run = read(directory / "run.json")
            run["steps"].reverse()
            write(directory / "run.json", run)
        elif mutate in ("code", "key"):
            path = root / ("infra/scripts/lib/infra-common.ps1" if mutate == "code" else "infra/config/keys/account5.pub")
            with path.open("a", encoding="utf-8") as f:
                f.write("\n")
        invoke(root, shell, "Apply", run_id, fault=fault, consent=consent, success=False)
        assert not apply_calls(root), name
        print(f"PASS: rejects {name} before first Apply", flush=True)

    # 실제 적용 순서는 모의 CLI 로그의 계획 파일 안 대상 값으로 확인한다.
    root = clone("success")
    invoke(root, shell, "Apply", run_id)
    run = read(root / f"infra/.local/destroy-all/{run_id}/run.json")
    assert run["status"] == "Complete"
    calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
    actual = ["/".join(Path(c["args"][-1]).parts[-3:-1]) for c in calls if c["kind"] == "terraform" and c["args"][1] == "apply"]
    assert actual == expected, actual
    assert all(not state["resources"] for state in read(root / "states.json").values())
    assert not read(root / "live.json")
    invoke(root, shell, "Status", run_id)
    print("PASS: ordered deletion, empty states and AWS ID verification", flush=True)

    root = clone("partial-failure")
    invoke(root, shell, "Apply", run_id, fault="apply-fail", success=False)
    run = read(root / f"infra/.local/destroy-all/{run_id}/run.json")
    assert run["status"] == "Failed" and run["steps"][4]["status"] == "Planned"
    assert read(root / "states.json")["shared/connectivity"]["resources"]
    new_id = invoke(root, shell, "Plan")
    invoke(root, shell, "Apply", new_id)
    assert read(root / f"infra/.local/destroy-all/{new_id}/run.json")["status"] == "Complete"
    print("PASS: partial failure stops lower stages; new Plan resumes remaining work", flush=True)

    root = clone("state-not-empty")
    invoke(root, shell, "Apply", run_id, fault="state-not-empty", success=False)
    run = read(root / f"infra/.local/destroy-all/{run_id}/run.json")
    assert run["status"] == "Failed" and run["steps"][2]["status"] == "Planned"
    print("PASS: nonempty post-Apply state blocks later stages", flush=True)

    root = clone("verification-failure")
    invoke(root, shell, "Apply", run_id, fault="retain-volume", success=False)
    assert read(root / f"infra/.local/destroy-all/{run_id}/run.json")["status"] == "VerificationFailed"
    write(root / "live.json", {})
    invoke(root, shell, "Verify", run_id)
    assert read(root / f"infra/.local/destroy-all/{run_id}/run.json")["status"] == "Complete"
    print("PASS: remaining AWS IDs prevent completion; Verify retries read-only checks", flush=True)

    for name, fault, protected in [("protected", "", True), ("plan-update", "plan-update", False), ("foreign", "foreign-resource", False)]:
        root = suite / name
        seed(root, infra, protected=protected)
        invoke(root, shell, "Plan", fault=fault, success=False)
        assert not apply_calls(root)
        print(f"PASS: rejects {name} Plan without Apply", flush=True)

    root = suite / "missing-bastion"
    seed(root, infra)
    states, live = read(root / "states.json"), read(root / "live.json")
    states.pop("account1/bastion")
    live.pop("i-bastion")
    live.pop("vol-root")
    write(root / "states.json", states)
    write(root / "live.json", live)
    absent_id = invoke(root, shell, "Plan")
    invoke(root, shell, "Apply", absent_id)
    assert read(root / f"infra/.local/destroy-all/{absent_id}/run.json")["steps"][0]["status"] == "Skipped"
    print("PASS: absent Bastion state is skipped; AccessDenied is not", flush=True)
    print(f"All destruction tests passed ({Path(shell).name}). Artifacts: {suite}", flush=True)


if __name__ == "__main__":
    main()
