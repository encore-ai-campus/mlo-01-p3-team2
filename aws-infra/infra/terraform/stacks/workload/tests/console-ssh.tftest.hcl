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

run "account1_service_console_ssh" {
  state_key = "console_account1"
  command   = apply
  variables { account_key = "account1" }
  # 대상 역할을 명시해 Bastion·ALB 제외와 역할별 중복 제거를 확인한다.
  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["ad", "frontend", "game", "edge"])
    error_message = "account1 서비스 EC2 보안그룹만 한 번씩 선택해야 합니다."
  }
  assert {
    condition = (
      data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].name == "com.amazonaws.ap-northeast-2.ec2-instance-connect" &&
      alltrue([for role, rule in aws_vpc_security_group_ingress_rule.service_console_ssh :
        rule.security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids[role] &&
        rule.prefix_list_id == "pl-0123456789abcdef0" &&
        rule.ip_protocol == "tcp" && rule.from_port == 22 && rule.to_port == 22
      ])
    )
    error_message = "account1 규칙은 해당 서비스 SG에 EC2 Instance Connect 접두사 목록의 TCP 22만 허용해야 합니다."
  }
  # Bastion은 학원 IP의 직접 SSH 규칙만 사용한다.
  assert {
    condition = (
      length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0
    )
    error_message = "account1 Bastion의 콘솔 SSH는 생성하지 않아야 합니다."
  }
}

run "account2_service_console_ssh" {
  state_key = "console_account2"
  command   = apply
  variables { account_key = "account2" }
  # 대상 역할을 명시해 Bastion·ALB 제외와 역할별 중복 제거를 확인한다.
  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["mongo", "spark", "consumer"])
    error_message = "account2 서비스 EC2 보안그룹만 한 번씩 선택해야 합니다."
  }
  assert {
    condition = (
      data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].name == "com.amazonaws.ap-northeast-2.ec2-instance-connect" &&
      alltrue([for role, rule in aws_vpc_security_group_ingress_rule.service_console_ssh :
        rule.security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids[role] &&
        rule.prefix_list_id == "pl-0123456789abcdef0" &&
        rule.ip_protocol == "tcp" && rule.from_port == 22 && rule.to_port == 22
      ])
    )
    error_message = "account2 규칙은 해당 서비스 SG에 EC2 Instance Connect 접두사 목록의 TCP 22만 허용해야 합니다."
  }
  # Bastion은 학원 IP의 직접 SSH 규칙만 사용한다.
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0
    error_message = "account2의 기존 Bastion 규칙 범위를 유지해야 합니다."
  }
}

run "account3_service_console_ssh" {
  state_key = "console_account3"
  command   = apply
  variables { account_key = "account3" }
  # 대상 역할을 명시해 Bastion·ALB 제외와 역할별 중복 제거를 확인한다.
  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["kafka", "mongo", "mysql", "spark"])
    error_message = "account3 서비스 EC2 보안그룹만 한 번씩 선택해야 합니다."
  }
  assert {
    condition = (
      data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].name == "com.amazonaws.ap-northeast-2.ec2-instance-connect" &&
      alltrue([for role, rule in aws_vpc_security_group_ingress_rule.service_console_ssh :
        rule.security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account3.sg_ids[role] &&
        rule.prefix_list_id == "pl-0123456789abcdef0" &&
        rule.ip_protocol == "tcp" && rule.from_port == 22 && rule.to_port == 22
      ])
    )
    error_message = "account3 규칙은 해당 서비스 SG에 EC2 Instance Connect 접두사 목록의 TCP 22만 허용해야 합니다."
  }
  # Bastion은 학원 IP의 직접 SSH 규칙만 사용한다.
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0
    error_message = "account3의 기존 Bastion 규칙 범위를 유지해야 합니다."
  }
}

run "account4_service_console_ssh" {
  state_key = "console_account4"
  command   = apply
  variables { account_key = "account4" }
  # 대상 역할을 명시해 Bastion·ALB 제외와 역할별 중복 제거를 확인한다.
  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["kafka", "mysql", "spark"])
    error_message = "account4 서비스 EC2 보안그룹만 한 번씩 선택해야 합니다."
  }
  assert {
    condition = (
      data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].name == "com.amazonaws.ap-northeast-2.ec2-instance-connect" &&
      alltrue([for role, rule in aws_vpc_security_group_ingress_rule.service_console_ssh :
        rule.security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account4.sg_ids[role] &&
        rule.prefix_list_id == "pl-0123456789abcdef0" &&
        rule.ip_protocol == "tcp" && rule.from_port == 22 && rule.to_port == 22
      ])
    )
    error_message = "account4 규칙은 해당 서비스 SG에 EC2 Instance Connect 접두사 목록의 TCP 22만 허용해야 합니다."
  }
  # Bastion은 학원 IP의 직접 SSH 규칙만 사용한다.
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0
    error_message = "account4의 기존 Bastion 규칙 범위를 유지해야 합니다."
  }
}

run "account5_service_console_ssh" {
  state_key = "console_account5"
  command   = apply
  variables { account_key = "account5" }
  # 대상 역할을 명시해 Bastion·ALB 제외와 역할별 중복 제거를 확인한다.
  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["kafka", "mongo", "mysql"])
    error_message = "account5 서비스 EC2 보안그룹만 한 번씩 선택해야 합니다."
  }
  assert {
    condition = (
      data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].name == "com.amazonaws.ap-northeast-2.ec2-instance-connect" &&
      alltrue([for role, rule in aws_vpc_security_group_ingress_rule.service_console_ssh :
        rule.security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account5.sg_ids[role] &&
        rule.prefix_list_id == "pl-0123456789abcdef0" &&
        rule.ip_protocol == "tcp" && rule.from_port == 22 && rule.to_port == 22
      ])
    )
    error_message = "account5 규칙은 해당 서비스 SG에 EC2 Instance Connect 접두사 목록의 TCP 22만 허용해야 합니다."
  }
  # Bastion은 학원 IP의 직접 SSH 규칙만 사용한다.
  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.bastion_console_ssh) == 0
    error_message = "account5의 기존 Bastion 규칙 범위를 유지해야 합니다."
  }
}
