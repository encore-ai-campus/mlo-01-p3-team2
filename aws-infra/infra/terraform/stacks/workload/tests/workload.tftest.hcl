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
  # 빈 허용 목록이면 HTTPS는 닫고 인증서 검증용 HTTP만 허용한다.
  variables {
    traffic = merge(var.traffic, { admin_public_cidrs = [], game_client_cidrs = ["203.0.113.10/32"], public_http_cidrs = [] })
  }
  # 서비스 수와 역할을 유지하면서 선택 계정의 모든 노드를 A에 배치한다.
  assert {
    condition     = alltrue([for node in values(local.nodes) : node.az == "a"])
    error_message = "모든 서비스 노드는 논리 A(apne2-az1)를 사용해야 합니다."
  }
  assert {
    condition = (toset(keys(output.inventory.instances)) == toset(["front-a", "front-b", "game-server", "ad-server", "flatten-1"]) &&
      toset(keys(module.rules.public_ingress)) == toset(["game_frontend/80/0.0.0.0/0", "ad_frontend/80/0.0.0.0/0"]) &&
    alltrue([for rule in values(module.rules.public_ingress) : rule.port == 80 && rule.cidr == "0.0.0.0/0"]))
    error_message = "Account 1 서비스 5대는 유지하고 빈 허용 목록에서는 인증서 검증용 Front 80번만 공개해야 합니다."
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
      contains(keys(module.rules.ingress), "account1/${role}_frontend/account1/${role}/8000") &&
      contains(keys(module.rules.egress), "account1/${role}_frontend/account1/${role}/8000")
    ])
    error_message = "Front에서 게임·광고로 전달하는 기존 TCP 8000 연결은 유지해야 합니다."
  }
  assert {
    condition = (module.rules.egress["account1/game/account4/kafka/9092"].peer_id ==
    "${var.topology.accounts.account4.id}/${jsondecode(file("../../../tests/fixtures.json")).foundations.account4.sg_ids.kafka}")
    error_message = "game→Kafka는 해당 계정의 Kafka SG를 참조해야 합니다."
  }
}
run "account2_two_nodes" {
  state_key = "account2"
  command   = apply
  variables { account_key = "account2" }
  # 서비스 수와 역할을 유지하면서 선택 계정의 모든 노드를 A에 배치한다.
  assert {
    condition     = alltrue([for node in values(local.nodes) : node.az == "a"])
    error_message = "모든 서비스 노드는 논리 A(apne2-az1)를 사용해야 합니다."
  }
  assert {
    condition = (toset(keys(output.inventory.instances)) == toset(["mongo-1", "spark-2"]) &&
    output.inventory.alb_dns_name == null)
    error_message = "Account 2의 서버 배치 또는 ALB 범위가 잘못되었습니다."
  }
}
run "account3_three_nodes" {
  state_key = "account3"
  command   = apply
  variables { account_key = "account3" }
  # 서비스 수와 역할을 유지하면서 선택 계정의 모든 노드를 A에 배치한다.
  assert {
    condition     = alltrue([for node in values(local.nodes) : node.az == "a"])
    error_message = "모든 서비스 노드는 논리 A(apne2-az1)를 사용해야 합니다."
  }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["mysql-1", "spark-1", "mongo-2"])
    error_message = "Account 3의 서버 배치가 잘못되었습니다."
  }
}
run "account4_four_nodes" {
  state_key = "account4"
  command   = apply
  variables { account_key = "account4" }
  # 서비스 수와 역할을 유지하면서 선택 계정의 모든 노드를 A에 배치한다.
  assert {
    condition     = alltrue([for node in values(local.nodes) : node.az == "a"])
    error_message = "모든 서비스 노드는 논리 A(apne2-az1)를 사용해야 합니다."
  }
  assert {
    condition     = toset(keys(output.inventory.instances)) == toset(["kafka-1", "kafka-2", "spark-3", "mysql-3"])
    error_message = "Account 4의 서버 배치가 잘못되었습니다."
  }
  # 같은 계정의 브로커 두 대가 SG를 공유해도 broker·controller 통신을 허용한다.
  assert {
    condition = (
      module.rules.ingress["account4/kafka/account4/kafka/9092"].peer_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account4.sg_ids.kafka &&
      module.rules.ingress["account4/kafka/account4/kafka/9093"].peer_id == jsondecode(file("../../../tests/fixtures.json")).foundations.account4.sg_ids.kafka &&
      !contains(module.model.roles["account3"], "kafka") &&
      !contains(module.model.roles["account2"], "consumer")
    )
    error_message = "Account 4 Kafka 자체 통신을 유지하고 이전 계정의 Kafka·Consumer 역할을 제거해야 합니다."
  }
}
run "account5_three_nodes" {
  state_key = "account5"
  command   = apply
  variables { account_key = "account5" }
  # 서비스 수와 역할을 유지하면서 선택 계정의 모든 노드를 A에 배치한다.
  assert {
    condition     = alltrue([for node in values(local.nodes) : node.az == "a"])
    error_message = "모든 서비스 노드는 논리 A(apne2-az1)를 사용해야 합니다."
  }
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
    error_message = "ALB SG 제거 후에도 서비스 서버 5대를 유지해야 합니다."
  }
}

# ALB 기능 자체는 보존한다. 사용할 프로필은 활성화와 세 연결을 함께 지정한다.
run "account1_alb_opt_in" {
  command = plan
  variables {
    topology = merge(var.topology, { alb = merge(var.topology.alb, { enabled = true, frontend_role = "game_frontend" }) })
    traffic = merge(var.traffic, { connections = merge(var.traffic.connections, {
      alb_front = { sources = ["alb"], targets = ["game_frontend"], port = "frontend" }
      alb_game  = { sources = ["alb"], targets = ["game"], port = "game" }
      alb_ad    = { sources = ["alb"], targets = ["ad"], port = "ad" }
    }) })
  }
  assert {
    condition = length(module.alb) == 1 && alltrue([for pair in ["game_frontend/80"] :
      contains(keys(module.rules.ingress), "account1/alb/account1/${pair}") &&
      contains(keys(module.rules.egress), "account1/alb/account1/${pair}")
    ])
    error_message = "명시적으로 활성화한 프로필에서는 기존 ALB와 대상 연결을 생성해야 합니다."
  }
}

# compute의 실제 EC2 서브넷 입력을 검사한다. C 서브넷도 제공해 잘못된 C 선택을 잡는다.
run "all_service_nodes_use_a_subnets" {
  command = plan
  module {
    source = "../../modules/compute"
  }
  variables {
    name       = "all-service-nodes-a"
    ami_id     = "ami-0123456789abcdef0"
    key_name   = "mock-service-key"
    public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
    nodes = { for name, node in jsondecode(file("../../../config/topology.tfvars.json")).topology.nodes :
      name => node if node.role != "bastion"
    }
    subnet_ids = {
      public_a  = "subnet-0000000000000000a"
      public_c  = "subnet-0000000000000000c"
      private_a = "subnet-1000000000000000a"
      private_c = "subnet-1000000000000000c"
    }
    sg_ids = merge([
      for foundation in values(jsondecode(file("../../../tests/fixtures.json")).foundations) : foundation.sg_ids
    ]...)
  }
  assert {
    condition = (
      length(aws_instance.this) == 17 &&
      alltrue([for name, node in var.nodes :
        node.az == "a" &&
        aws_instance.this[name].subnet_id == (
          node.subnet_tier == "public" ? "subnet-0000000000000000a" : "subnet-1000000000000000a"
        )
      ])
    )
    error_message = "기존 서비스 17대는 모두 Public A 또는 Private A 서브넷을 선택해야 합니다."
  }
}
