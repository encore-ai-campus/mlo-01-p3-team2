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
    accounts = { for name, a in jsondecode(file("../../../config/topology.tfvars.json")).topology.accounts :
      name => merge(a, { ami_id = "ami-0123456789abcdef0" })
    }
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
  # ALB가 꺼져 있으면 사용자 CIDR이 있어도 웹 공개 규칙을 만들지 않는다.
  variables {
    traffic = merge(var.traffic, { admin_public_cidrs = [], game_client_cidrs = ["203.0.113.10/32"], public_http_cidrs = [] })
  }
  assert {
    condition = (toset(keys(output.inventory.instances)) == toset(["front-a", "front-b", "game-server", "ad-server", "edge-1"]) &&
    length(module.rules.public_ingress) == 2 && alltrue([for rule in values(module.rules.public_ingress) : rule.group_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids.edge]))
    error_message = "Account 1 서비스 5대를 유지하고 ALB 비활성화만으로 Front의 웹 포트를 공개하지 않아야 합니다."
  }
  # 기존 foundation 상태에 ALB SG가 남아 있어도 ALB와 전용 연결은 생성하지 않는다.
  assert {
    condition = (
      length(module.alb) == 0 && output.inventory.alb_dns_name == null &&
      !contains(module.model.roles["account1"], "alb") &&
      alltrue([for flow in values(module.model.flows) : !endswith(flow.source, "/alb") && !endswith(flow.target, "/alb")]) &&
      !contains(keys(module.rules.public_ingress), "alb/80/203.0.113.10/32")
    )
    error_message = "ALB 모듈·DNS·역할·전용 연결이 비활성 상태여야 합니다."
  }
  assert {
    condition = alltrue([for role in ["game", "ad"] :
      contains(keys(module.rules.ingress), "account1/frontend/account1/${role}/8000") &&
      contains(keys(module.rules.egress), "account1/frontend/account1/${role}/8000")
    ])
    error_message = "Front에서 게임·광고로 전달하는 기존 TCP 8000 연결은 유지해야 합니다."
  }
  assert {
    condition = (module.rules.egress["account1/game/account3/kafka/9092"].peer_id ==
    "${var.topology.accounts.account3.id}/${jsondecode(file("../../../tests/fixtures.json")).foundations.account3.sg_ids.kafka}")
    error_message = "game→Kafka는 해당 계정의 Kafka SG를 참조해야 합니다."
  }
}
run "account2_three_nodes" {
  state_key = "account2"
  command   = apply
  variables { account_key = "account2" }
  assert {
    condition = (toset(keys(output.inventory.instances)) == toset(["mongo-1", "spark-2", "flatten-1"]) &&
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
run "account4_three_nodes" {
  state_key = "account4"
  command   = apply
  variables { account_key = "account4" }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["kafka-2", "spark-3", "mysql-3"])
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

# foundation에서 ALB SG까지 정리한 이후에도 같은 설정이 유효해야 한다.
run "account1_without_alb_sg" {
  command = plan
  override_data {
    target = data.terraform_remote_state.foundation["account1"]
    values = { outputs = { foundation = merge(jsondecode(file("../../../tests/fixtures.json")).foundations.account1, {
      sg_ids = { for role, id in jsondecode(file("../../../tests/fixtures.json")).foundations.account1.sg_ids : role => id if role != "alb" }
    }) } }
  }
  assert {
    condition     = length(module.alb) == 0 && output.inventory.alb_dns_name == null && length(output.inventory.instances) == 5
    error_message = "ALB SG 제거 후에도 기존 서비스 서버 4대와 진입 서버 1대를 유지해야 합니다."
  }
}

# ALB 기능 자체는 보존한다. 사용할 프로필은 활성화와 세 연결을 함께 지정한다.
run "account1_alb_opt_in" {
  command = plan
  variables {
    topology = merge(var.topology, { alb = merge(var.topology.alb, { enabled = true }) })
    traffic = merge(var.traffic, { connections = merge(var.traffic.connections, {
      alb_front = { sources = ["alb"], targets = ["frontend"], port = "frontend" }
      alb_game  = { sources = ["alb"], targets = ["game"], port = "game" }
      alb_ad    = { sources = ["alb"], targets = ["ad"], port = "ad" }
    }) })
  }
  assert {
    condition = length(module.alb) == 1 && alltrue([for pair in ["frontend/80", "game/8000", "ad/8000"] :
      contains(keys(module.rules.ingress), "account1/alb/account1/${pair}") &&
      contains(keys(module.rules.egress), "account1/alb/account1/${pair}")
    ])
    error_message = "명시적으로 활성화한 프로필에서는 기존 ALB와 대상 연결을 생성해야 합니다."
  }
}
