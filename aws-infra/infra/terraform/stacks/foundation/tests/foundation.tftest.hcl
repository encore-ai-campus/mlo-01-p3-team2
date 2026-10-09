# AWS 자원 생성 없이 provider를 모의 구현으로 대체한다.
mock_provider "aws" {}
variables {
  topology = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic  = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
}

run "account1_proxy" {
  command = apply
  assert {
    condition     = length(module.network.nat_gateway_ids) == 0 && length(module.network.subnet_ids) == 4
    error_message = "Proxy 기본값은 NAT 0개, Account 1 서브넷 4개여야 합니다."
  }
  assert {
    condition     = toset(keys(output.foundation.sg_ids)) == toset(["alb", "bastion", "frontend", "game"])
    error_message = "Account 1의 역할 SG가 잘못되었습니다."
  }
}
run "account2_private" {
  command = apply
  variables { account_key = "account2" }
  assert {
    condition     = toset(keys(module.network.subnet_ids)) == toset(["private_a", "private_c"])
    error_message = "Account 2 기본 구성은 Private A·C만 만듭니다."
  }
}
run "nat_per_az" {
  command = apply
  variables {
    topology = merge(var.topology, { accounts = merge(var.topology.accounts, {
      account1 = merge(var.topology.accounts.account1, { egress = "nat" })
    }) })
  }
  assert {
    condition = length(module.network.nat_routes) == 2 && alltrue([
      for az, route in module.network.nat_routes :
      route.nat_gateway_id == module.network.nat_gateway_ids[az] &&
      route.route_table_id == module.network.route_table_ids["private_${az}"]
    ])
    error_message = "각 Private 서브넷은 같은 AZ의 NAT로 라우팅해야 합니다."
  }
}
