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

# Kafka에서 Spark·Consumer로의 데이터 전달은 클라이언트가 시작한 9092 연결을 사용한다.
run "account1_application_flows" {
  command = plan
  variables { account_key = "account1" }
  assert {
    condition = alltrue([for key in ["account1/ad_frontend/account1/ad/8000", "account1/game_frontend/account1/game/8000"] : try(
      module.rules.ingress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] &&
      module.rules.ingress[key].peer_id == (split("/", key)[0] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] : "${var.topology.accounts[split("/", key)[0]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]]}") &&
      module.rules.ingress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.ingress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 ingress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for key in ["account1/ad/account1/game/8000", "account1/ad/account2/mongo/27017", "account1/ad/account3/kafka/9092", "account1/ad/account3/mongo/27017", "account1/ad/account3/mysql/3306", "account1/ad/account4/kafka/9092", "account1/ad/account4/mysql/3306", "account1/ad/account5/kafka/9092", "account1/ad/account5/mongo/27017", "account1/ad/account5/mysql/3306", "account1/ad_frontend/account1/ad/8000", "account1/game_frontend/account1/game/8000", "account1/game/account1/ad/8000", "account1/game/account3/kafka/9092", "account1/game/account3/mysql/3306", "account1/game/account4/kafka/9092", "account1/game/account4/mysql/3306", "account1/game/account5/kafka/9092", "account1/game/account5/mysql/3306"] : try(
      module.rules.egress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] &&
      module.rules.egress[key].peer_id == (split("/", key)[2] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] : "${var.topology.accounts[split("/", key)[2]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]]}") &&
      module.rules.egress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.egress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 egress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for flow in values(module.model.flows) :
      !(endswith(flow.source, "/kafka") && (endswith(flow.target, "/spark") || endswith(flow.target, "/consumer")))
    ])
    error_message = "Kafka 응답을 위해 Spark·Consumer에 별도 수신 포트를 열지 않아야 합니다."
  }
}

run "account2_application_flows" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition = alltrue([for key in ["account1/ad/account2/mongo/27017", "account2/consumer/account2/mongo/27017"] : try(
      module.rules.ingress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] &&
      module.rules.ingress[key].peer_id == (split("/", key)[0] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] : "${var.topology.accounts[split("/", key)[0]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]]}") &&
      module.rules.ingress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.ingress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 ingress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for key in ["account2/consumer/account2/mongo/27017", "account2/consumer/account3/kafka/9092", "account2/consumer/account3/mongo/27017", "account2/consumer/account4/kafka/9092", "account2/consumer/account5/kafka/9092", "account2/consumer/account5/mongo/27017", "account2/spark/account3/kafka/9092", "account2/spark/account3/mysql/3306", "account2/spark/account4/kafka/9092", "account2/spark/account4/mysql/3306", "account2/spark/account5/kafka/9092", "account2/spark/account5/mysql/3306"] : try(
      module.rules.egress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] &&
      module.rules.egress[key].peer_id == (split("/", key)[2] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] : "${var.topology.accounts[split("/", key)[2]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]]}") &&
      module.rules.egress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.egress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 egress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for flow in values(module.model.flows) :
      !(endswith(flow.source, "/kafka") && (endswith(flow.target, "/spark") || endswith(flow.target, "/consumer")))
    ])
    error_message = "Kafka 응답을 위해 Spark·Consumer에 별도 수신 포트를 열지 않아야 합니다."
  }
}

run "account3_application_flows" {
  command = plan
  variables { account_key = "account3" }
  assert {
    condition = alltrue([for key in ["account1/ad/account3/kafka/9092", "account1/ad/account3/mongo/27017", "account1/ad/account3/mysql/3306", "account1/game/account3/kafka/9092", "account1/game/account3/mysql/3306", "account2/consumer/account3/kafka/9092", "account2/consumer/account3/mongo/27017", "account2/spark/account3/kafka/9092", "account2/spark/account3/mysql/3306", "account3/mysql/account3/kafka/9092", "account3/spark/account3/kafka/9092", "account3/spark/account3/mysql/3306", "account4/mysql/account3/kafka/9092", "account4/spark/account3/kafka/9092", "account4/spark/account3/mysql/3306", "account5/mysql/account3/kafka/9092"] : try(
      module.rules.ingress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] &&
      module.rules.ingress[key].peer_id == (split("/", key)[0] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] : "${var.topology.accounts[split("/", key)[0]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]]}") &&
      module.rules.ingress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.ingress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 ingress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for key in ["account3/mysql/account1/ad/8000", "account3/mysql/account1/game/8000", "account3/mysql/account3/kafka/9092", "account3/mysql/account4/kafka/9092", "account3/mysql/account5/kafka/9092", "account3/spark/account3/kafka/9092", "account3/spark/account3/mysql/3306", "account3/spark/account4/kafka/9092", "account3/spark/account4/mysql/3306", "account3/spark/account5/kafka/9092", "account3/spark/account5/mysql/3306"] : try(
      module.rules.egress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] &&
      module.rules.egress[key].peer_id == (split("/", key)[2] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] : "${var.topology.accounts[split("/", key)[2]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]]}") &&
      module.rules.egress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.egress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 egress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for flow in values(module.model.flows) :
      !(endswith(flow.source, "/kafka") && (endswith(flow.target, "/spark") || endswith(flow.target, "/consumer")))
    ])
    error_message = "Kafka 응답을 위해 Spark·Consumer에 별도 수신 포트를 열지 않아야 합니다."
  }
}

run "account4_application_flows" {
  command = plan
  variables { account_key = "account4" }
  assert {
    condition = alltrue([for key in ["account1/ad/account4/kafka/9092", "account1/ad/account4/mysql/3306", "account1/game/account4/kafka/9092", "account1/game/account4/mysql/3306", "account2/consumer/account4/kafka/9092", "account2/spark/account4/kafka/9092", "account2/spark/account4/mysql/3306", "account3/mysql/account4/kafka/9092", "account3/spark/account4/kafka/9092", "account3/spark/account4/mysql/3306", "account4/mysql/account4/kafka/9092", "account4/spark/account4/kafka/9092", "account4/spark/account4/mysql/3306", "account5/mysql/account4/kafka/9092"] : try(
      module.rules.ingress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] &&
      module.rules.ingress[key].peer_id == (split("/", key)[0] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] : "${var.topology.accounts[split("/", key)[0]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]]}") &&
      module.rules.ingress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.ingress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 ingress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for key in ["account4/mysql/account1/ad/8000", "account4/mysql/account1/game/8000", "account4/mysql/account3/kafka/9092", "account4/mysql/account4/kafka/9092", "account4/mysql/account5/kafka/9092", "account4/spark/account3/kafka/9092", "account4/spark/account3/mysql/3306", "account4/spark/account4/kafka/9092", "account4/spark/account4/mysql/3306", "account4/spark/account5/kafka/9092", "account4/spark/account5/mysql/3306"] : try(
      module.rules.egress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] &&
      module.rules.egress[key].peer_id == (split("/", key)[2] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] : "${var.topology.accounts[split("/", key)[2]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]]}") &&
      module.rules.egress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.egress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 egress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for flow in values(module.model.flows) :
      !(endswith(flow.source, "/kafka") && (endswith(flow.target, "/spark") || endswith(flow.target, "/consumer")))
    ])
    error_message = "Kafka 응답을 위해 Spark·Consumer에 별도 수신 포트를 열지 않아야 합니다."
  }
}

run "account5_application_flows" {
  command = plan
  variables { account_key = "account5" }
  assert {
    condition = alltrue([for key in ["account1/ad/account5/kafka/9092", "account1/ad/account5/mongo/27017", "account1/ad/account5/mysql/3306", "account1/game/account5/kafka/9092", "account1/game/account5/mysql/3306", "account2/consumer/account5/kafka/9092", "account2/consumer/account5/mongo/27017", "account2/spark/account5/kafka/9092", "account2/spark/account5/mysql/3306", "account3/mysql/account5/kafka/9092", "account3/spark/account5/kafka/9092", "account3/spark/account5/mysql/3306", "account4/mysql/account5/kafka/9092", "account4/spark/account5/kafka/9092", "account4/spark/account5/mysql/3306", "account5/mysql/account5/kafka/9092"] : try(
      module.rules.ingress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] &&
      module.rules.ingress[key].peer_id == (split("/", key)[0] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] : "${var.topology.accounts[split("/", key)[0]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]]}") &&
      module.rules.ingress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.ingress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 ingress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for key in ["account5/mysql/account1/ad/8000", "account5/mysql/account1/game/8000", "account5/mysql/account3/kafka/9092", "account5/mysql/account4/kafka/9092", "account5/mysql/account5/kafka/9092"] : try(
      module.rules.egress[key].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[0]].sg_ids[split("/", key)[1]] &&
      module.rules.egress[key].peer_id == (split("/", key)[2] == var.account_key ? jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]] : "${var.topology.accounts[split("/", key)[2]].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[split("/", key)[2]].sg_ids[split("/", key)[3]]}") &&
      module.rules.egress[key].port == tonumber(split("/", key)[4]) &&
      module.rules.egress[key].port_end == tonumber(split("/", key)[4]), false
    )])
    error_message = "요청한 애플리케이션 연결의 egress SG·상대 계정·단일 포트가 일치해야 합니다."
  }
  assert {
    condition = alltrue([for flow in values(module.model.flows) :
      !(endswith(flow.source, "/kafka") && (endswith(flow.target, "/spark") || endswith(flow.target, "/consumer")))
    ])
    error_message = "Kafka 응답을 위해 Spark·Consumer에 별도 수신 포트를 열지 않아야 합니다."
  }
}
