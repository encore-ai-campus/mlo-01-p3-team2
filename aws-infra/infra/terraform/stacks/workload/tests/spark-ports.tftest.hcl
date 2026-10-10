# AWS API와 원격 상태는 모의 처리하고 Spark 통신 범위의 전달만 검사한다.
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

run "account2_spark_ports" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition = (
      length([for rule in values(module.rules.ingress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      length([for rule in values(module.rules.egress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      alltrue([for rule in concat(values(module.rules.ingress), values(module.rules.egress)) :
        rule.port_end == (rule.port == 7078 ? 7094 : rule.port == 7079 ? 7095 : rule.port)
      ])
    )
    error_message = "Spark 세 계정 사이의 범위와 Worker·Master UI를 허용하고 나머지 포트는 유지해야 합니다."
  }
  assert {
    condition = (
      module.rules.ingress["account3/spark/account2/spark/7078"].port_end == 7094 &&
      module.rules.egress["account2/spark/account3/spark/7079"].port_end == 7095
    )
    error_message = "시작 포트 기반의 기존 Terraform 규칙 주소를 유지해야 합니다."
  }
}
run "account3_spark_ports" {
  command = plan
  variables { account_key = "account3" }
  assert {
    condition = (
      length([for rule in values(module.rules.ingress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      length([for rule in values(module.rules.egress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      alltrue([for rule in concat(values(module.rules.ingress), values(module.rules.egress)) :
        rule.port_end == (rule.port == 7078 ? 7094 : rule.port == 7079 ? 7095 : rule.port)
      ])
    )
    error_message = "Spark 세 계정 사이의 범위와 Worker·Master UI를 허용하고 나머지 포트는 유지해야 합니다."
  }
  assert {
    condition = (
      module.rules.ingress["account3/spark/account3/spark/7078"].port_end == 7094 &&
      module.rules.egress["account3/spark/account3/spark/7079"].port_end == 7095
    )
    error_message = "시작 포트 기반의 기존 Terraform 규칙 주소를 유지해야 합니다."
  }
}
run "account4_spark_ports" {
  command = plan
  variables { account_key = "account4" }
  assert {
    condition = (
      length([for rule in values(module.rules.ingress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      length([for rule in values(module.rules.egress) : rule if contains([7100, 8080], rule.port)]) == 6 &&
      alltrue([for rule in concat(values(module.rules.ingress), values(module.rules.egress)) :
        rule.port_end == (rule.port == 7078 ? 7094 : rule.port == 7079 ? 7095 : rule.port)
      ])
    )
    error_message = "Spark 세 계정 사이의 범위와 Worker·Master UI를 허용하고 나머지 포트는 유지해야 합니다."
  }
  assert {
    condition = (
      module.rules.ingress["account3/spark/account4/spark/7078"].port_end == 7094 &&
      module.rules.egress["account4/spark/account3/spark/7079"].port_end == 7095
    )
    error_message = "시작 포트 기반의 기존 Terraform 규칙 주소를 유지해야 합니다."
  }
}
# 동일한 시작 포트의 짧은 범위가 추가돼도 기존의 넓은 범위를 잃지 않아야 한다.
run "same_start_range_union" {
  command = plan
  variables {
    account_key = "account2"
    traffic = merge(var.traffic, { connections = merge(var.traffic.connections, {
      spark_driver_short = { sources = ["spark"], targets = ["spark"], port = "spark_driver", port_end = "spark_block" }
    }) })
  }
  assert {
    condition = (
      module.rules.ingress["account3/spark/account2/spark/7078"].port_end == 7094 &&
      module.rules.egress["account2/spark/account3/spark/7078"].port_end == 7094
    )
    error_message = "같은 시작 포트의 범위는 합집합으로 전달해야 합니다."
  }
}
