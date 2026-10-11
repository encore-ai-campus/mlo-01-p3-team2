# 실제 AWS·S3 대신 모의 provider와 고정 foundation 출력으로 평탄화 노드를 검사한다.
mock_provider "aws" {}

variables {
  topology       = jsondecode(file("../../../config/topology.tfvars.json")).topology
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  state_backend  = { bucket = "mock-state-bucket", region = "ap-northeast-2", profile = "unused", key_prefix = "test" }
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

run "account2_flatten_private_a" {
  command = plan
  variables { account_key = "account2" }
  assert {
    condition = (
      toset(keys(output.inventory.instances)) == toset(["mongo-1", "spark-2", "flatten-1"]) &&
      module.compute.instances["flatten-1"].instance_type == "t3a.medium" &&
      var.topology.nodes["flatten-1"].az == "a" &&
      var.topology.az_ids.a == "apne2-az1" &&
      var.topology.nodes["flatten-1"].subnet_tier == "private" &&
      !var.topology.nodes["flatten-1"].public_ip &&
      var.topology.nodes["flatten-1"].root_gib == 20 &&
      length(module.compute.instances["flatten-1"].data_volumes) == 0 &&
      module.compute.instances["flatten-1"].public_ip == null
    )
    error_message = "평탄화 노드는 기존 두 서버와 함께 Private A의 medium급 서버로 생성하며 공인 IP·별도 데이터 디스크를 추가하지 않아야 합니다."
  }
  # Consumer는 모든 브로커로 접속하되 Controller·MySQL·직접 인터넷 포트를 열지 않는다.
  assert {
    condition = (
      alltrue([for account in ["account3", "account4", "account5"] :
        module.rules.egress["account2/consumer/${account}/kafka/9092"].group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids.consumer &&
        module.rules.egress["account2/consumer/${account}/kafka/9092"].peer_id == "${var.topology.accounts[account].id}/${jsondecode(file("../../../tests/fixtures.json")).foundations[account].sg_ids.kafka}"
      ]) &&
      length([for rule in values(module.rules.egress) : rule if rule.group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids.consumer]) == 7 &&
      alltrue([for account in ["account2", "account3", "account5"] :
        module.rules.egress["account2/consumer/${account}/mongo/27017"].port == 27017
      ]) &&
      !contains(var.traffic.internet_https_roles, "consumer") &&
      module.rules.ingress["account1/bastion/account2/consumer/22"].port == 22 &&
      module.rules.egress["account2/consumer/account1/bastion/3128"].port == 3128 &&
      contains(keys(aws_vpc_security_group_ingress_rule.service_console_ssh), "consumer")
    )
    error_message = "평탄화 노드는 Kafka 9092·MongoDB 27017·프록시 3128 송신과 배스천·콘솔 SSH만 연결해야 합니다."
  }
}

run "account3_accepts_flatten_consumer" {
  command = plan
  variables { account_key = "account3" }
  assert {
    condition     = module.rules.ingress["account2/consumer/account3/kafka/9092"].peer_id == "${var.topology.accounts.account2.id}/${jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids.consumer}"
    error_message = "Account 3 Kafka SG는 Account 2 Consumer SG의 9092 연결을 허용해야 합니다."
  }
}
run "account4_accepts_flatten_consumer" {
  command = plan
  variables { account_key = "account4" }
  assert {
    condition     = module.rules.ingress["account2/consumer/account4/kafka/9092"].peer_id == "${var.topology.accounts.account2.id}/${jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids.consumer}"
    error_message = "Account 4 Kafka SG는 Account 2 Consumer SG의 9092 연결을 허용해야 합니다."
  }
}
run "account5_accepts_flatten_consumer" {
  command = plan
  variables { account_key = "account5" }
  assert {
    condition     = module.rules.ingress["account2/consumer/account5/kafka/9092"].peer_id == "${var.topology.accounts.account2.id}/${jsondecode(file("../../../tests/fixtures.json")).foundations.account2.sg_ids.consumer}"
    error_message = "Account 5 Kafka SG는 Account 2 Consumer SG의 9092 연결을 허용해야 합니다."
  }
}
