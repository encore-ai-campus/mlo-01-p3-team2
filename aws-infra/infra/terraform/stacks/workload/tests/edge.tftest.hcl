# AWS API를 호출하지 않고 접두사 목록과 서비스 보안그룹의 허용 범위만 검사한다.
mock_provider "aws" {
  mock_resource "aws_eip" {
    defaults = { public_ip = "203.0.113.20" }
  }
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

# 실제 AWS 없이 Front 두 대의 공개 범위·Backend 제한·EIP를 검증한다.
run "account1_independent_frontends" {
  command = apply
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["front-a", "front-b", "game-server", "ad-server", "flatten-1"]) && length(module.alb) == 0
    error_message = "Account 1은 edge 없이 네 서비스와 Consumer를 생성해야 합니다."
  }
  assert {
    condition     = alltrue([for name in ["front-a", "front-b"] : output.inventory.instances[name].public_ip == "203.0.113.20" && output.inventory.instances[name].instance_type == "t3.small"]) && alltrue([for name in ["game-server", "ad-server"] : output.inventory.instances[name].public_ip == null && output.inventory.instances[name].instance_type == "t3.large"])
    error_message = "Front 두 대만 EIP를 사용하고 요청한 사양을 유지해야 합니다."
  }
  assert {
    condition     = length(local.front_https_ingress) == 16 && alltrue([for role in ["game_frontend", "ad_frontend"] : alltrue([for port in [80, 443] : toset([for key, rule in module.rules.public_ingress : rule.cidr if startswith(key, "${role}/") && rule.port == port]) == (port == 80 ? toset(["0.0.0.0/0"]) : toset([for octet in range(66, 73) : "222.112.208.${octet}/32"]))])]) && length(aws_vpc_security_group_egress_rule.front_all) == 2 && alltrue([for rule in aws_vpc_security_group_egress_rule.front_all : rule.ip_protocol == "-1" && rule.cidr_ipv4 == "0.0.0.0/0" && rule.from_port == null && rule.to_port == null])
    error_message = "두 Front의 80번은 전체 IPv4, 443번은 지정한 7개 IP만 허용하고 전체 IPv4 송신은 유지해야 합니다."
  }
  assert {
    condition     = toset([for key, rule in module.rules.ingress : key if rule.port == 8000]) == toset(["account1/game_frontend/account1/game/8000", "account1/ad_frontend/account1/ad/8000", "account1/game/account1/ad/8000", "account1/ad/account1/game/8000"]) && length(local.private_admin_ingress) == length(toset(var.traffic.admin_public_cidrs)) && toset(keys(aws_vpc_security_group_ingress_rule.service_console_ssh)) == toset(["consumer"]) && alltrue([for key, rule in module.rules.ingress : startswith(key, "account1/bastion/") if rule.port == 22])
    error_message = "Backend 8000은 각 Front·상대 Backend만, Front·Backend SSH는 Bastion만, Consumer는 기존 관리자·콘솔 SSH 정책을 허용해야 합니다."
  }
  assert {
    condition     = length(local.edge_ingress) == 0 && length(local.front_ingress) == 0
    error_message = "원격 상태에 옛 SG가 남아도 edge와 구 Front 공개 규칙을 만들면 안 됩니다."
  }
}
