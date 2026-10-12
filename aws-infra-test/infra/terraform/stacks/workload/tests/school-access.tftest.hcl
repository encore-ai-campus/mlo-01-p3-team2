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
run "school_account1" {
  command = plan
  variables { account_key = "account1" }
  assert {
    condition     = length(local.private_admin_ingress) == 2 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
  assert {
    condition     = module.rules.public_ingress["front/80/0.0.0.0/0"].port == 80 && module.rules.public_ingress["admin/222.112.208.69/32"].port == 22 && alltrue([for rule in values(module.rules.public_ingress) : rule.port == 80 if rule.cidr == "0.0.0.0/0"])
    error_message = "HTTP 80만 전체 공개하고 Bastion SSH는 학원 IP만 허용해야 합니다."
  }
}
run "school_account2" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition     = length(local.private_admin_ingress) == 3 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
}
run "school_account3" {
  command = plan
  variables { account_key = "account3" }
  assert {
    condition     = length(local.private_admin_ingress) == 4 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
}
run "school_account4" {
  command = plan
  variables { account_key = "account4" }
  assert {
    condition     = length(local.private_admin_ingress) == 3 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
}
run "school_account5" {
  command = plan
  variables { account_key = "account5" }
  assert {
    condition     = length(local.private_admin_ingress) == 3 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
}
