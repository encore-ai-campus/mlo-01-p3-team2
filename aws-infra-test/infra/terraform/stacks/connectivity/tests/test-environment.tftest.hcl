# 단일 AZ의 5계정 Peering과 양방향 라우팅을 모의 검사한다.
variables {
  topology      = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic       = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  state_backend = jsondecode(file("../../../config/backend.json"))
}
mock_provider "aws" { alias = "account1" }
override_data {
  target = data.terraform_remote_state.foundation["account1"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account1 } }
}
mock_provider "aws" { alias = "account2" }
override_data {
  target = data.terraform_remote_state.foundation["account2"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account2 } }
}
mock_provider "aws" { alias = "account3" }
override_data {
  target = data.terraform_remote_state.foundation["account3"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account3 } }
}
mock_provider "aws" { alias = "account4" }
override_data {
  target = data.terraform_remote_state.foundation["account4"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account4 } }
}
mock_provider "aws" { alias = "account5" }
override_data {
  target = data.terraform_remote_state.foundation["account5"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account5 } }
}
run "test_peering_routes" {
  command = plan
  assert {
    condition     = length(output.connections) == 10 && alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")])
    error_message = "10개 연결은 테스트 foundation 상태만 참조해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account1_account2[0].requester_routes)) == toset(["private_a", "public_a"]) && toset(keys(module.account1_account2[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account1_account2[0].requester_routes) : route.destination == var.topology.accounts.account2.vpc_cidr]) && alltrue([for route in values(module.account1_account2[0].accepter_routes) : route.destination == var.topology.accounts.account1.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account1_account3[0].requester_routes)) == toset(["private_a", "public_a"]) && toset(keys(module.account1_account3[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account1_account3[0].requester_routes) : route.destination == var.topology.accounts.account3.vpc_cidr]) && alltrue([for route in values(module.account1_account3[0].accepter_routes) : route.destination == var.topology.accounts.account1.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account1_account4[0].requester_routes)) == toset(["private_a", "public_a"]) && toset(keys(module.account1_account4[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account1_account4[0].requester_routes) : route.destination == var.topology.accounts.account4.vpc_cidr]) && alltrue([for route in values(module.account1_account4[0].accepter_routes) : route.destination == var.topology.accounts.account1.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account1_account5[0].requester_routes)) == toset(["private_a", "public_a"]) && toset(keys(module.account1_account5[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account1_account5[0].requester_routes) : route.destination == var.topology.accounts.account5.vpc_cidr]) && alltrue([for route in values(module.account1_account5[0].accepter_routes) : route.destination == var.topology.accounts.account1.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account2_account3[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account2_account3[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account2_account3[0].requester_routes) : route.destination == var.topology.accounts.account3.vpc_cidr]) && alltrue([for route in values(module.account2_account3[0].accepter_routes) : route.destination == var.topology.accounts.account2.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account2_account4[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account2_account4[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account2_account4[0].requester_routes) : route.destination == var.topology.accounts.account4.vpc_cidr]) && alltrue([for route in values(module.account2_account4[0].accepter_routes) : route.destination == var.topology.accounts.account2.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account2_account5[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account2_account5[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account2_account5[0].requester_routes) : route.destination == var.topology.accounts.account5.vpc_cidr]) && alltrue([for route in values(module.account2_account5[0].accepter_routes) : route.destination == var.topology.accounts.account2.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account3_account4[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account3_account4[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account3_account4[0].requester_routes) : route.destination == var.topology.accounts.account4.vpc_cidr]) && alltrue([for route in values(module.account3_account4[0].accepter_routes) : route.destination == var.topology.accounts.account3.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account3_account5[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account3_account5[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account3_account5[0].requester_routes) : route.destination == var.topology.accounts.account5.vpc_cidr]) && alltrue([for route in values(module.account3_account5[0].accepter_routes) : route.destination == var.topology.accounts.account3.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
  assert {
    condition     = toset(keys(module.account4_account5[0].requester_routes)) == toset(["private_a"]) && toset(keys(module.account4_account5[0].accepter_routes)) == toset(["private_a"]) && alltrue([for route in values(module.account4_account5[0].requester_routes) : route.destination == var.topology.accounts.account5.vpc_cidr]) && alltrue([for route in values(module.account4_account5[0].accepter_routes) : route.destination == var.topology.accounts.account4.vpc_cidr])
    error_message = "A 라우팅 테이블에 상대 VPC CIDR을 양방향으로 지정해야 합니다."
  }
}
