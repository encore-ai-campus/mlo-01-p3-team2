# 실제 AWS 접속 없이 provider와 원격 상태를 모의 실행한다.
mock_provider "aws" {}
variables {
  topology       = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  state_backend  = jsondecode(file("../../../config/backend.json"))
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
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
override_data {
  target = data.terraform_remote_state.connectivity
  values = { outputs = {
    connections     = jsondecode(file("../../../tests/fixtures.json")).connections
    foundation_vpcs = { for k, f in jsondecode(file("../../../tests/fixtures.json")).foundations : k => f.vpc_id }
  } }
}
run "account1_test_workload" {
  command = plan
  variables { account_key = "account1" }
  assert {
    condition     = length(output.inventory.instances) == 3 && output.inventory.alb_dns_name == null && alltrue([for instance in values(output.inventory.instances) : instance.instance_type == "t3a.small"])
    error_message = "테스트 노드 수·small 사양·ALB 제외가 일치해야 합니다."
  }
  assert {
    condition     = alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")]) && startswith(data.terraform_remote_state.connectivity.config.key, "aws-infra-test/")
    error_message = "원격 상태는 테스트 prefix만 사용해야 합니다."
  }
  assert {
    condition     = length(local.front_ingress) == length(toset(var.traffic.game_client_cidrs)) && module.rules.ingress["account1/frontend/account1/game/8000"].port == 8000 && module.rules.ingress["account1/frontend/account1/ad/8000"].port == 8000 && !contains(keys(output.inventory.instances), "bastion") && !contains(keys(output.inventory.instances), "front-b")
    error_message = "Front 직접 HTTP·게임/광고 전달·Bastion 분리가 필요합니다."
  }
}
run "account2_test_workload" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition     = length(output.inventory.instances) == 3 && output.inventory.alb_dns_name == null && alltrue([for instance in values(output.inventory.instances) : instance.instance_type == "t3a.small"])
    error_message = "테스트 노드 수·small 사양·ALB 제외가 일치해야 합니다."
  }
  assert {
    condition     = alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")]) && startswith(data.terraform_remote_state.connectivity.config.key, "aws-infra-test/")
    error_message = "원격 상태는 테스트 prefix만 사용해야 합니다."
  }
}
run "account3_test_workload" {
  command = plan
  variables { account_key = "account3" }
  assert {
    condition     = length(output.inventory.instances) == 4 && output.inventory.alb_dns_name == null && alltrue([for instance in values(output.inventory.instances) : instance.instance_type == "t3a.small"])
    error_message = "테스트 노드 수·small 사양·ALB 제외가 일치해야 합니다."
  }
  assert {
    condition     = alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")]) && startswith(data.terraform_remote_state.connectivity.config.key, "aws-infra-test/")
    error_message = "원격 상태는 테스트 prefix만 사용해야 합니다."
  }
}
run "account4_test_workload" {
  command = plan
  variables { account_key = "account4" }
  assert {
    condition     = length(output.inventory.instances) == 3 && output.inventory.alb_dns_name == null && alltrue([for instance in values(output.inventory.instances) : instance.instance_type == "t3a.small"])
    error_message = "테스트 노드 수·small 사양·ALB 제외가 일치해야 합니다."
  }
  assert {
    condition     = alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")]) && startswith(data.terraform_remote_state.connectivity.config.key, "aws-infra-test/")
    error_message = "원격 상태는 테스트 prefix만 사용해야 합니다."
  }
}
run "account5_test_workload" {
  command = plan
  variables { account_key = "account5" }
  assert {
    condition     = length(output.inventory.instances) == 3 && output.inventory.alb_dns_name == null && alltrue([for instance in values(output.inventory.instances) : instance.instance_type == "t3a.small"])
    error_message = "테스트 노드 수·small 사양·ALB 제외가 일치해야 합니다."
  }
  assert {
    condition     = alltrue([for state in data.terraform_remote_state.foundation : startswith(state.config.key, "aws-infra-test/")]) && startswith(data.terraform_remote_state.connectivity.config.key, "aws-infra-test/")
    error_message = "원격 상태는 테스트 prefix만 사용해야 합니다."
  }
}
