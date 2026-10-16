"""전체 삭제 테스트용 AWS/Terraform CLI. 실제 서비스나 네트워크를 호출하지 않는다."""
import json
import os
from pathlib import Path
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def main():
    kind, *args = sys.argv[1:]
    root = Path(os.environ["DESTROY_MOCK_ROOT"])
    config = read(root / "infra/config/topology.tfvars.json")["topology"]
    states = read(root / "states.json")
    live = read(root / "live.json")
    fault = os.environ.get("DESTROY_MOCK_FAULT", "")
    with (root / "calls.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps({"kind": kind, "args": args}) + "\n")

    def option(name):
        return args[args.index(name) + 1]

    def fail(code):
        print(f"An error occurred ({code}) when calling the mock operation", file=sys.stderr)
        raise SystemExit(2)

    if kind == "aws":
        service, action = args[:2]
        if os.environ.get("AWS_ACCESS_KEY_ID"):
            raise AssertionError("환경 자격 증명이 격리되지 않았습니다.")
        if action == "get-caller-identity":
            owner = option("--profile")
            print(json.dumps({"Account": "000000000000" if fault == "wrong-account" else config["accounts"][owner]["id"]}))
        elif action == "get-bucket-versioning":
            print('{"Status":"Enabled"}')
        elif action == "get-object":
            if fault == "access-denied":
                fail("AccessDenied")
            key = "/".join(option("--key").split("/")[-3:-1])
            if key not in states:
                fail("NoSuchKey")
            # 호출자가 지정한 출력 파일에만 모의 S3 상태를 기록한다.
            output = args[args.index("--region") + 2]
            write(output, states[key])
            print('{"ContentLength":100}')
        elif action == "describe-instances" and "--filters" in args:
            instances = []
            if "i-bastion" in live:
                instances = [{"InstanceId": "i-bastion"}]
            print(json.dumps({"Reservations": [{"Instances": instances}]}))
        else:
            lookups = {
                "describe-instances": ("--instance-ids", "Reservations", "InvalidInstanceID.NotFound"),
                "describe-volumes": ("--volume-ids", "Volumes", "InvalidVolume.NotFound"),
                "describe-vpcs": ("--vpc-ids", "Vpcs", "InvalidVpcID.NotFound"),
                "describe-vpc-peering-connections": ("--vpc-peering-connection-ids", "VpcPeeringConnections", "InvalidVpcPeeringConnectionID.NotFound"),
            }
            if action not in lookups:
                raise AssertionError(f"허용하지 않은 AWS 호출: {service} {action}")
            flag, collection, error = lookups[action]
            resource_id = option(flag)
            if resource_id not in live:
                fail(error)
            value = {"Id": resource_id}
            if collection == "Reservations":
                value = {"Instances": [{"InstanceId": resource_id, "State": {"Name": "running"}}]}
            if collection == "VpcPeeringConnections":
                value = {"Status": {"Code": "active"}}
            print(json.dumps({collection: [value]}))
        return

    # Terraform도 모의 JSON 계획과 상태 파일만 다룬다.
    assert kind == "terraform"
    stack = Path(args[0].split("=", 1)[1])
    action = args[1]
    data_dir = Path(os.environ["TF_DATA_DIR"])
    if action == "init":
        key = next(x.split("=", 2)[2] for x in args if x.startswith("-backend-config=key="))
        write(data_dir / "backend.json", {"key": "/".join(key.split("/")[-3:-1])})
        print("Mock initialized")
        return
    key = read(data_dir / "backend.json")["key"]
    account, stage = key.split("/")
    if action == "plan":
        assert "-destroy" in args
        if stage == "workload" and account != "account1":
            compute = (stack / "../../modules/compute/main.tf").resolve().read_text(encoding="utf-8-sig")
            if "prevent_destroy = true" in compute:
                print("Error: Instance cannot be destroyed: lifecycle.prevent_destroy", file=sys.stderr)
                raise SystemExit(1)
        changes = []
        for resource in states[key]["resources"]:
            if resource["mode"] != "managed":
                continue
            for instance in resource["instances"]:
                address = resource["address"]
                before = instance["attributes"]
                actions = ["update"] if fault == "plan-update" else ["delete"]
                if fault == "foreign-resource":
                    address = "aws_s3_bucket.unrelated"
                changes.append({"address": address, "mode": "managed", "type": resource["type"], "change": {"actions": actions, "before": before, "after": None}})
        plan = {"format_version": "1.2", "complete": True, "planned_values": {"root_module": {}}, "resource_changes": changes, "mock_key": key}
        output = next(x.split("=", 1)[1] for x in args if x.startswith("-out="))
        write(output, plan)
        print(f"Plan: 0 to add, 0 to change, {len(changes)} to destroy.")
    elif action == "show":
        print(json.dumps(read(args[-1])))
    elif action == "apply":
        plan = read(args[-1])
        assert plan["mock_key"] == key
        if fault == "apply-fail" and key == "account3/workload":
            states[key]["serial"] += 1
            write(root / "states.json", states)
            print("Error: simulated partial apply failure", file=sys.stderr)
            raise SystemExit(1)
        for resource in plan["resource_changes"]:
            before = resource["change"]["before"]
            resource_id = before["id"]
            if not (fault == "retain-volume" and resource["type"] == "aws_ebs_volume"):
                live.pop(resource_id, None)
            for volume in before.get("root_block_device", []):
                live.pop(volume["volume_id"], None)
        states[key]["resources"] = []
        states[key]["outputs"] = {}
        states[key]["serial"] += 1
        if fault == "state-not-empty" and key == "account1/workload":
            states[key]["resources"] = [{"mode": "managed", "instances": [{"attributes": {"id": "remaining"}}]}]
        write(root / "states.json", states)
        write(root / "live.json", live)
        print("Apply complete!")
    else:
        raise AssertionError(f"허용하지 않은 Terraform 호출: {action}")


if __name__ == "__main__":
    main()
