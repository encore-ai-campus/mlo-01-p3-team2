mock_provider "aws" {
  alias = "account1"
}
mock_provider "aws" {
  alias = "account2"
}
mock_provider "aws" {
  alias = "account3"
}
mock_provider "aws" {
  alias = "account4"
}
mock_provider "aws" {
  alias = "account5"
}
variables {
  state_backend = { bucket = "mock-state-bucket", region = "ap-northeast-2", profile = "unused", key_prefix = "test" }
  topology      = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic       = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
}
override_data {
  target = data.terraform_remote_state.foundation["account1"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account1 } }
}
override_data {
  target = data.terraform_remote_state.foundation["account2"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account2 } }
}
override_data {
  target = data.terraform_remote_state.foundation["account3"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account3 } }
}
override_data {
  target = data.terraform_remote_state.foundation["account4"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account4 } }
}
override_data {
  target = data.terraform_remote_state.foundation["account5"]
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account5 } }
}

run "all_pairs" {
  command = apply
  assert {
    condition     = length(output.connections) == 10
    error_message = "현재 통신 구성에는 10개 계정 쌍의 Peering이 필요합니다."
  }
  assert {
    condition = (length(module.account1_account2[0].requester_routes) == 4 &&
      length(module.account1_account2[0].accepter_routes) == 2 &&
      alltrue([for r in values(module.account1_account2[0].requester_routes) :
        r.destination == "10.20.0.0/16" && r.peering_id == module.account1_account2[0].id
        ]) && alltrue([for r in values(module.account1_account2[0].accepter_routes) :
        r.destination == "10.10.0.0/16" && r.peering_id == module.account1_account2[0].id
    ]))
    error_message = "각 계정의 모든 라우팅 테이블에 상대 VPC 경로가 필요합니다."
  }
}
run "wrong_remote_account" {
  command = plan
  override_data {
    target = data.terraform_remote_state.foundation["account2"]
    values = { outputs = { foundation = merge(
      jsondecode(file("../../../tests/fixtures.json")).foundations.account2,
      { account_id = "000000000000" }
    ) } }
  }
  expect_failures = [data.terraform_remote_state.foundation]
}
