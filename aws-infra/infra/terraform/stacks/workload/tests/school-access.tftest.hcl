# AWS API를 호출하지 않고 접두사 목록과 서비스 보안그룹의 허용 범위만 검사한다.
mock_provider "aws" {
  mock_data "aws_ec2_managed_prefix_list" {
    defaults = { id = "pl-0123456789abcdef0" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-northeast-2:541308265856:loadbalancer/app/test/1234567890123456" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-northeast-2:541308265856:targetgroup/test/1234567890123456" }
  }
  mock_resource "aws_lb_listener" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-northeast-2:541308265856:listener/app/test/1234567890123456/1234567890123456" }
  }
}
variables {
  state_backend = { bucket = "mock-state-bucket", region = "ap-northeast-2", profile = "unused", key_prefix = "test" }
  topology = merge(jsondecode(file("../../../config/topology.tfvars.json")).topology, {
    accounts = { for name, account in jsondecode(file("../../../config/topology.tfvars.json")).topology.accounts :
      name => merge(account, { ami_id = "ami-0123456789abcdef0" })
    }
  })
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
}

# 원격 상태도 고정된 모의 출력으로 대체해 S3에 접근하지 않는다.
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
    foundation_vpcs = { for name, account in jsondecode(file("../../../tests/fixtures.json")).foundations : name => account.vpc_id }
  } }
}

run "school_account1" {
  command = plan
  variables { account_key = "account1" }
  assert {
    condition     = length(local.private_admin_ingress) == 0 && alltrue([for rule in values(local.private_admin_ingress) : rule.cidr == "222.112.208.69/32" && rule.port == 22])
    error_message = "Private 역할마다 학원 IP의 TCP 22만 추가해야 합니다."
  }
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0 && !contains([for rule in values(module.rules.public_ingress) : rule.cidr if rule.port == 22], "0.0.0.0/0")
    error_message = "Bastion 콘솔 SSH 및 전체 공개 SSH를 만들면 안 됩니다."
  }
  assert {
    condition     = module.rules.public_ingress["game_frontend/80"].port == 80 && module.rules.public_ingress["admin/222.112.208.69/32"].port == 22 && alltrue([for rule in values(module.rules.public_ingress) : contains([80, 443], rule.port) if rule.cidr == "0.0.0.0/0"])
    error_message = "Front 80/443을 전체 공개하고 Bastion SSH는 관리자 IP만 허용해야 합니다."
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
