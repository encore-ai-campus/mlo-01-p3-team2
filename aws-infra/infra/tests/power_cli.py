"""전원 스크립트 테스트 전용 AWS CLI. 계정별 파일로 병렬 호출을 격리한다."""
import json
import os
from pathlib import Path
import sys


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


root = Path(os.environ["INFRA_POWER_TEST_ROOT"])
args = sys.argv[1:]
profile = args[args.index("--profile") + 1]
path = root / f"{profile}.json"
data = read(path)
fault = os.environ.get("INFRA_POWER_TEST_FAULT", "")
operation = args[1]
with (root / f"{profile}.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps({"args": args, "ambient": bool(os.environ.get("AWS_ACCESS_KEY_ID")),
                          "endpoint": os.environ.get("AWS_ENDPOINT_URL"),
                          "ignore_endpoints": os.environ.get("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS")}) + "\n")

if args[:2] == ["sts", "get-caller-identity"]:
    owner = "000000000000" if fault == "identity" and profile == "account5" else data["owner"]
    print(json.dumps({"Account": owner}))
elif args[:2] == ["ec2", "describe-instances"]:
    offset = args.index("--instance-ids") + 1
    ids = args[offset:next(i for i in range(offset, len(args)) if args[i].startswith("--"))]
    assert set(ids) == {item["InstanceId"] for item in data["instances"]}
    data["reads"] = data.get("reads", 0) + 1
    # 최초 조회 뒤 외부에서 시작·중지 중이던 서버가 안정 상태로 바뀌는 상황을 재현한다.
    if fault == "transition" and data["reads"] >= 2:
        for item in data["instances"]:
            state = item["State"]["Name"]
            if state in ("pending", "stopping"):
                item["State"]["Name"] = "running" if state == "pending" else "stopped"
    write(path, data)
    instances = data["instances"]
    if profile == "account5":
        if fault == "missing":
            instances = []
        elif fault == "tags":
            instances[0]["Tags"][0]["Value"] = "another-project"
        elif fault == "root":
            instances[0]["RootDeviceType"] = "instance-store"
        elif fault == "terminated":
            instances[0]["State"]["Name"] = "terminated"
    print(json.dumps({"Reservations": [{"OwnerId": data["owner"], "Instances": instances}]}))
elif args[0] == "ec2" and operation in ("start-instances", "stop-instances"):
    # 테스트 CLI 자체도 강제 종료·삭제 등 전원 범위 밖의 호출을 허용하지 않는다.
    assert not set(args) & {"--force", "--skip-os-shutdown", "--hibernate"}
    if "--dry-run" in args:
        error = "UnauthorizedOperation" if fault == "permission" and profile == "account5" else "DryRunOperation"
        print(f"An error occurred ({error}) when calling the operation", file=sys.stderr)
        sys.exit(255)
    if fault == "partial" and profile == "account5":
        sys.exit("Simulated power request failure")
    offset = args.index("--instance-ids") + 1
    ids = args[offset:next(i for i in range(offset, len(args)) if args[i].startswith("--"))]
    for item in data["instances"]:
        if item["InstanceId"] in ids:
            item["State"]["Name"] = "running" if operation == "start-instances" else "stopped"
            if fault == "timeout" and profile == "account5":
                item["State"]["Name"] = "pending" if operation == "start-instances" else "stopping"
            if operation == "start-instances":
                item["PublicIpAddress"] = "203.0.113.42"
            else:
                item.pop("PublicIpAddress", None)
    write(path, data)
    print("{}")
else:
    sys.exit(f"Unexpected AWS command: {args[:2]}")
