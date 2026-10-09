mock_provider "aws" {
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
    accounts = { for name, a in jsondecode(file("../../../config/topology.tfvars.json")).topology.accounts :
      name => merge(a, { ami_id = "ami-0123456789abcdef0" })
    }
    alb = merge(jsondecode(file("../../../config/topology.tfvars.json")).topology.alb, {
      certificate_arn = "arn:aws:acm:ap-northeast-2:541308265856:certificate/00000000-0000-0000-0000-000000000000"
    })
  })
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
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
    foundation_vpcs = { for name, a in jsondecode(file("../../../tests/fixtures.json")).foundations : name => a.vpc_id }
  } }
}
run "account1_default_closed" {
  state_key = "account1"
  command   = apply
  assert {
    condition     = length(output.inventory.instances) == 4 && length(module.rules.public_ingress) == 0
    error_message = "Account 1은 4대이며 CIDR을 정하기 전 외부 인바운드는 닫혀야 합니다."
  }
  assert {
    condition = (module.rules.egress["account1/game/account3/kafka/9092"].peer_id ==
    jsondecode(file("../../../tests/fixtures.json")).foundations.account3.sg_ids.kafka)
    error_message = "game→Kafka는 해당 계정의 Kafka SG를 참조해야 합니다."
  }
}
run "account2_three_nodes" {
  state_key = "account2"
  command   = apply
  variables { account_key = "account2" }
  assert {
    condition = (toset(keys(output.inventory.instances)) == toset(["mongo-1", "spark-2", "ad-server"]) &&
    output.inventory.alb_dns_name == null)
    error_message = "Account 2의 서버 배치 또는 ALB 범위가 잘못되었습니다."
  }
}
run "account3_four_nodes" {
  state_key = "account3"
  command   = apply
  variables { account_key = "account3" }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["kafka-1", "mysql-1", "spark-1", "mongo-2"])
    error_message = "Account 3의 서버 배치가 잘못되었습니다."
  }
}
run "account4_two_nodes" {
  state_key = "account4"
  command   = apply
  variables { account_key = "account4" }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["kafka-2", "spark-3"])
    error_message = "Account 4의 서버 배치가 잘못되었습니다."
  }
}
run "account5_three_nodes" {
  state_key = "account5"
  command   = apply
  variables { account_key = "account5" }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["mysql-2", "mongo-3", "kafka-3"])
    error_message = "Account 5의 서버 배치가 잘못되었습니다."
  }
}
run "missing_peering" {
  state_key = "missing_peering"
  command   = plan
  override_data {
    target = data.terraform_remote_state.connectivity
    values = { outputs = {
      connections     = {}
      foundation_vpcs = { for name, a in jsondecode(file("../../../tests/fixtures.json")).foundations : name => a.vpc_id }
    } }
  }
  expect_failures = [terraform_data.connectivity_ready]
}
