locals {
  account = module.model.topology.accounts[var.account_key]
  name    = "${var.topology.project}-${var.account_key}"
  # Bastion의 역할·보안규칙은 유지하고 EC2 생성만 전용 상태로 분리한다.
  nodes      = { for name, node in module.model.topology.nodes : name => node if node.account == var.account_key && node.role != "bastion" && (!var.edge_bootstrap_only || node.role == "edge") }
  foundation = local.foundations[var.account_key]
  # 초기 진입 서버는 같은 계정의 연결만 준비한다. 나머지 계정은 정규 배포에서 연결한다.
  active_flows = { for name, flow in module.model.flows : name => flow if !var.edge_bootstrap_only || (
    flow.source_account == var.account_key && flow.target_account == var.account_key &&
    (endswith(flow.source, "/edge") || endswith(flow.target, "/edge"))
  ) }
  # Account 1의 네 서비스에만 관리 SSH와 Backend 수신 제한을 적용한다.
  restricted_roles = var.account_key == "account1" ? toset(["game_frontend", "ad_frontend", "game", "ad"]) : toset([])
  front_sg_ids = { for role in ["game_frontend", "ad_frontend"] : role => local.foundation.sg_ids[role]
    if var.account_key == "account1" && contains([for n in values(local.nodes) : n.role], role)
  }
  edge_sg_id = contains([for n in values(local.nodes) : n.role], "edge") ? try(local.foundation.sg_ids["edge"], null) : null
  edge_ingress = local.edge_sg_id != null ? merge(
    { "edge/acme/80" = { group_id = local.edge_sg_id, cidr = "0.0.0.0/0", port = 80 } },
    { for cidr in toset(var.traffic.game_client_cidrs) : "edge/https/${cidr}" => { group_id = local.edge_sg_id, cidr = cidr, port = 443 } },
    { for cidr in toset(var.traffic.admin_public_cidrs) : "edge/ssh/${cidr}" => { group_id = local.edge_sg_id, cidr = cidr, port = 22 } }
  ) : {}
  # 서비스 EC2가 사용하는 역할만 선택해 Bastion·ALB를 제외하고 같은 SG는 한 번만 연다.
  service_console_ssh_sg_ids = {
    for role in toset([for node in values(local.nodes) : node.role]) : role => local.foundation.sg_ids[role] if !contains(local.restricted_roles, role)
  }
  # Private 서비스 SG에는 관리자 공인 IP의 SSH만 추가한다. 접속 경로는 별도로 필요하다.
  private_role_sg_ids = {
    for role in toset([for node in values(local.nodes) : node.role if node.subnet_tier == "private"]) : role => local.foundation.sg_ids[role] if !contains(local.restricted_roles, role)
  }
  private_admin_ingress = merge({}, [for role, sg_id in local.private_role_sg_ids : {
    for cidr in toset(var.traffic.admin_public_cidrs) : "private-admin/${role}/${cidr}" => {
      group_id = sg_id, cidr = cidr, port = 22
    }
  }]...)
  public_http_cidrs = coalesce(try(var.traffic.public_http_cidrs, null), var.traffic.game_client_cidrs)
  sg_ids = merge({}, [for account, foundation in local.foundations : {
    for role, id in foundation.sg_ids : "${account}/${role}" => id
  }]...)
  # 다른 계정의 SG 참조는 소유 계정 ID를 붙여 Provider가 조회한 형식과 맞춘다.
  peer_sg_ids = merge({}, [for account, foundation in local.foundations : {
    for role, id in foundation.sg_ids : "${account}/${role}" => account == var.account_key ? id : "${var.topology.accounts[account].id}/${id}"
  }]...)
  # 같은 SG 쌍·포트가 여러 역할 관계에 등장해도 AWS 규칙은 한 번만 만든다.
  ingress_grouped = { for flow in values(local.active_flows) :
    "${flow.source}/${flow.target}/${flow.port}" => {
      group_id = local.sg_ids[flow.target], peer_id = local.peer_sg_ids[flow.source], port = flow.port, port_end = flow.port_end
      }... if flow.target_account == var.account_key && !(
      var.account_key == "account1" && contains(["account1/game", "account1/ad"], flow.target) &&
      flow.port <= 8000 && flow.port_end >= 8000 &&
      flow.source != (flow.target == "account1/game" ? "account1/game_frontend" : "account1/ad_frontend")
    )
  }
  egress_grouped = { for flow in values(local.active_flows) :
    "${flow.source}/${flow.target}/${flow.port}" => {
      group_id = local.sg_ids[flow.source], peer_id = local.peer_sg_ids[flow.target], port = flow.port, port_end = flow.port_end
    }... if flow.source_account == var.account_key
  }
  alb_enabled = var.topology.alb.enabled && var.topology.alb.account == var.account_key
  admin_ingress = !var.edge_bootstrap_only && contains(keys(local.foundation.sg_ids), "bastion") ? {
    for cidr in toset(var.traffic.admin_public_cidrs) : "admin/${cidr}" => {
      group_id = local.foundation.sg_ids["bastion"], cidr = cidr, port = var.traffic.ports.ssh
    }
  } : {}
  # Public Front의 HTTP만 전체 공개한다. edge HTTPS 범위는 game_client_cidrs를 유지한다.
  front_ingress = contains([for node in values(local.nodes) : node.role if node.subnet_tier == "public"], "frontend") ? {
    for cidr in toset(local.public_http_cidrs) : "front/80/${cidr}" => {
      group_id = local.foundation.sg_ids["frontend"], cidr = cidr, port = 80
    }
  } : {}
  # 공개 Front는 HTTP 인증서 검증/리다이렉트와 HTTPS만 인터넷에 연다.
  front_https_ingress = merge({}, [for role, sg in local.front_sg_ids : {
    for port in [80, 443] : "${role}/${port}" => { group_id = sg, cidr = "0.0.0.0/0", port = port }
  }]...)
  # 허용한 사용자 CIDR에서 ALB의 HTTP 80으로 들어오는 요청만 연다.
  alb_ingress = local.alb_enabled ? merge({}, [for port in [80] : {
    for cidr in toset(local.public_http_cidrs) : "alb/${port}/${cidr}" => {
      group_id = local.foundation.sg_ids["alb"], cidr = cidr, port = port
    }
  }]...) : {}
}
# 콘솔 SSH는 관리자 PC가 아닌 해당 리전의 EC2 Instance Connect 서비스에서 들어온다.
data "aws_ec2_managed_prefix_list" "ec2_instance_connect" {
  count = contains(keys(local.foundation.sg_ids), "bastion") || length(local.service_console_ssh_sg_ids) > 0 ? 1 : 0
  name  = "com.amazonaws.${var.topology.region}.ec2-instance-connect"
}

# Bastion 보안그룹에만 AWS 관리형 IPv4 접두사 목록의 SSH 22를 허용한다.
resource "aws_vpc_security_group_ingress_rule" "bastion_console_ssh" {
  # Bastion SSH는 관리자 CIDR만 허용하므로 콘솔 서비스 출처 규칙은 생성하지 않는다.
  count             = 0
  security_group_id = local.foundation.sg_ids["bastion"]
  prefix_list_id    = data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  description       = "EC2 Instance Connect console SSH"
  depends_on        = [terraform_data.connectivity_ready]
}

# 기존 Bastion 규칙과 별도로 서비스 SG에 EC2 Instance Connect의 SSH 22만 허용한다.
resource "aws_vpc_security_group_ingress_rule" "service_console_ssh" {
  for_each          = local.service_console_ssh_sg_ids
  security_group_id = each.value
  prefix_list_id    = data.aws_ec2_managed_prefix_list.ec2_instance_connect[0].id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  description       = "EC2 Instance Connect console SSH (${each.key})"
  depends_on        = [terraform_data.connectivity_ready]
}

module "rules" {
  source = "../../modules/security-rules"
  # 시작 포트가 같은 범위는 가장 큰 끝 포트까지 합치고 기존 자원 주소를 유지한다.
  ingress = { for k, rules in local.ingress_grouped : k => merge(rules[0], {
    port_end = max([for rule in rules : rule.port_end]...)
  }) }
  egress = { for k, rules in local.egress_grouped : k => merge(rules[0], {
    port_end = max([for rule in rules : rule.port_end]...)
  }) }
  public_ingress = merge(local.admin_ingress, local.alb_ingress, local.edge_ingress, local.front_ingress, local.front_https_ingress, local.private_admin_ingress)
  public_egress = {
    for role, id in local.foundation.sg_ids : "https/${role}" => {
      group_id = id, cidr = "0.0.0.0/0", port = 443
    } if contains(var.traffic.internet_https_roles, role) && (!var.edge_bootstrap_only || role == "edge")
  }
  depends_on = [terraform_data.connectivity_ready]
}
# 두 Front만 전체 IPv4 송신을 허용한다. 다른 역할의 송신 규칙은 유지한다.
resource "aws_vpc_security_group_egress_rule" "front_all" {
  for_each          = local.front_sg_ids
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Public frontend outbound"
  depends_on        = [terraform_data.connectivity_ready]
}
module "compute" {
  source     = "../../modules/compute"
  name       = local.name
  ami_id     = local.account.ami_id
  nodes      = local.nodes
  subnet_ids = local.foundation.subnet_ids
  sg_ids     = local.foundation.sg_ids
  key_name   = local.account.key_pair_name
  public_key = var.ssh_public_key
  depends_on = [module.rules]
}
module "alb" {
  count                = local.alb_enabled ? 1 : 0
  source               = "../../modules/alb"
  name                 = local.name
  vpc_id               = local.foundation.vpc_id
  subnet_ids           = [for az in sort(keys(var.topology.az_ids)) : local.foundation.subnet_ids["public_${az}"]]
  sg_id                = local.foundation.sg_ids["alb"]
  frontend_targets     = { for name, node in local.nodes : name => module.compute.instances[name].id if node.role == var.topology.alb.frontend_role }
  game_targets         = { for name, node in local.nodes : name => module.compute.instances[name].id if node.role == var.topology.alb.game_role }
  ad_targets           = { for name, node in local.nodes : name => module.compute.instances[name].id if node.role == var.topology.alb.ad_role }
  frontend_port        = var.traffic.ports.frontend
  game_port            = var.traffic.ports.game
  ad_port              = var.traffic.ports.ad
  static_path          = var.topology.alb.static_path
  ad_path              = var.topology.alb.ad_path
  frontend_health_path = var.topology.alb.frontend_health_path
  game_health_path     = var.topology.alb.game_health_path
  ad_health_path       = var.topology.alb.ad_health_path
}
output "inventory" {
  value = {
    account      = var.account_key
    account_id   = local.account.id
    region       = var.topology.region
    instances    = module.compute.instances
    alb_dns_name = try(module.alb[0].dns_name, null)
  }
}

resource "terraform_data" "edge_bootstrap_guard" {
  count = var.edge_bootstrap_only ? 1 : 0
  lifecycle {
    precondition {
      condition = var.account_key == "account1" && !var.topology.alb.enabled && try(
        toset(keys(local.nodes)) == toset(["edge-1"]) && local.nodes["edge-1"].subnet_tier == "public" &&
      local.nodes["edge-1"].public_ip && local.nodes["edge-1"].instance_type == "t3a.small", false)
      error_message = "초기 구축은 ALB가 없는 Account 1의 Public edge-1(t3a.small) 한 대만 허용합니다."
    }
  }
}
