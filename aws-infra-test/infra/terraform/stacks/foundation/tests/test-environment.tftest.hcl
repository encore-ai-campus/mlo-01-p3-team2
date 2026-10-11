# 실제 AWS 접속 없이 provider와 원격 상태를 모의 실행한다.
mock_provider "aws" {}
variables {
  topology       = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  state_backend  = jsondecode(file("../../../config/backend.json"))
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
}
run "account1_single_az" {
  command = plan
  variables { account_key = "account1" }
  assert {
    condition     = toset(keys(module.network.subnet_ids)) == toset(["private_a", "public_a"]) && length(module.network.nat_gateway_ids) == 0 && !contains(keys(module.groups.ids), "alb")
    error_message = "A 서브넷만 생성하고 NAT와 ALB SG는 생성하지 않아야 합니다."
  }
}
run "account2_single_az" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition     = toset(keys(module.network.subnet_ids)) == toset(["private_a"]) && length(module.network.nat_gateway_ids) == 0 && !contains(keys(module.groups.ids), "alb")
    error_message = "A 서브넷만 생성하고 NAT와 ALB SG는 생성하지 않아야 합니다."
  }
}
