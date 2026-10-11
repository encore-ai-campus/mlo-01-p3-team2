# 실제 AWS 접속 없이 provider와 원격 상태를 모의 실행한다.
mock_provider "aws" {}
variables {
  topology       = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  state_backend  = jsondecode(file("../../../config/backend.json"))
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
}
override_data {
  target = data.terraform_remote_state.foundation
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account1 } }
}
run "test_bastion" {
  command = plan
  assert {
    condition     = output.bastion.key_name == "aws-infra-test-account1-bastion" && var.topology.nodes.bastion.instance_type == "t3a.small"
    error_message = "테스트 전용 Bastion과 키페어가 필요합니다."
  }
}
