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

# 모의 적용으로 Public A의 전용 진입 노드와 EIP 출력, 기존 노드 유지를 확인한다.
run "account1_edge_public_a" {
  command = apply
  assert {
    condition = (
      toset(keys(output.inventory.instances)) == toset(["edge-1", "front-a", "front-b", "game-server", "ad-server"]) &&
      local.nodes["edge-1"].role == "edge" && local.nodes["edge-1"].az == "a" &&
      local.nodes["edge-1"].subnet_tier == "public" && local.nodes["edge-1"].public_ip &&
      output.inventory.instances["edge-1"].public_ip == "203.0.113.20" &&
      output.inventory.instances["edge-1"].instance_type == "t3a.small" &&
      local.nodes["edge-1"].root_gib == 20 && length(output.inventory.instances["edge-1"].data_volumes) == 0 &&
      output.inventory.alb_dns_name == null
    )
    error_message = "전용 edge 노드는 Public A·small·OS 20GiB·EIP만 추가하고 기존 서비스 서버와 ALB 비활성 상태를 유지해야 합니다."
  }
  # 내부 연결은 Front 80·Bastion SSH/프록시이며 인증서·패키지용 HTTPS 송신도 허용한다.
  assert {
    condition = (
      module.rules.ingress["account1/edge/account1/frontend/80"].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.frontend &&
      module.rules.ingress["account1/edge/account1/frontend/80"].peer_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.edge &&
      module.rules.egress["account1/edge/account1/frontend/80"].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.edge &&
      module.rules.egress["account1/edge/account1/frontend/80"].peer_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.frontend &&
      module.rules.egress["account1/edge/account1/frontend/80"].port == 80 &&
      module.rules.egress["account1/edge/account1/frontend/80"].port_end == 80 &&
      module.rules.ingress["account1/bastion/account1/edge/22"].port == 22 &&
      module.rules.egress["account1/edge/account1/bastion/3128"].port == 3128 &&
      length([for f in values(module.model.flows) : f if endswith(f.source, "/edge")]) == 2 &&
      contains(var.traffic.internet_https_roles, "edge")
    )
    error_message = "진입 서버는 Front 80·Bastion 프록시 3128·관리 SSH만 연결하고 DB나 게임·광고에 직접 접속하지 않아야 합니다."
  }
  # 전용 SG의 콘솔 SSH와 ACME 80·사용자 CIDR 443을 검사한다.
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.service_console_ssh["edge"].security_group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.edge &&
      module.rules.public_ingress["edge/acme/80"].cidr == "0.0.0.0/0" && module.rules.public_ingress["edge/https/222.112.208.69/32"].port == 443 &&
      alltrue([for name in ["front-a", "front-b"] : output.inventory.instances[name].role == "frontend"]) &&
      length([for n in values(local.nodes) : n if n.public_ip]) == 3
    )
    error_message = "edge 전용 SG·콘솔 SSH·세 EIP 대상과 ACME 80·사용자 CIDR 443을 유지해야 합니다."
  }
}

# 원격 foundation은 Account 1만 필요하며 다른 EC2를 만들지 않는다.
run "edge_only_bootstrap" {
  command = apply
  variables { edge_bootstrap_only = true }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["edge-1"]) && length(data.terraform_remote_state.foundation) == 1 && length(data.terraform_remote_state.connectivity) == 0
    error_message = "초기 구축은 Account 1의 edge-1 한 대만 생성해야 합니다."
  }
  assert {
    condition     = length(module.rules.public_ingress) == 3 && contains(var.traffic.internet_https_roles, "edge")
    error_message = "초기 구축은 ACME·허용 HTTPS·관리 SSH와 HTTPS 송신만 공개해야 합니다."
  }
}
