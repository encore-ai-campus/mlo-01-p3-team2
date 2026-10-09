locals {
  account    = module.model.topology.accounts[var.account_key]
  name       = "${var.topology.project}-${var.account_key}"
  nodes      = { for name, node in module.model.topology.nodes : name => node if node.account == var.account_key }
  foundation = local.foundations[var.account_key]
  sg_ids = merge({}, [for account, foundation in local.foundations : {
    for role, id in foundation.sg_ids : "${account}/${role}" => id
  }]...)
  # 같은 SG 쌍·포트가 여러 역할 관계에 등장해도 AWS 규칙은 한 번만 만든다.
  ingress_grouped = { for flow in values(module.model.flows) :
    "${flow.source}/${flow.target}/${flow.port}" => {
      group_id = local.sg_ids[flow.target], peer_id = local.sg_ids[flow.source], port = flow.port
    }... if flow.target_account == var.account_key
  }
  egress_grouped = { for flow in values(module.model.flows) :
    "${flow.source}/${flow.target}/${flow.port}" => {
      group_id = local.sg_ids[flow.source], peer_id = local.sg_ids[flow.target], port = flow.port
    }... if flow.source_account == var.account_key
  }
  alb_enabled = var.topology.alb.enabled && var.topology.alb.account == var.account_key
  admin_ingress = contains(keys(local.foundation.sg_ids), "bastion") ? {
    for cidr in toset(var.traffic.admin_public_cidrs) : "admin/${cidr}" => {
      group_id = local.foundation.sg_ids["bastion"], cidr = cidr, port = var.traffic.ports.ssh
    }
  } : {}
  alb_ingress = local.alb_enabled ? merge({}, [for port in [80, 443] : {
    for cidr in toset(var.traffic.game_client_cidrs) : "alb/${port}/${cidr}" => {
      group_id = local.foundation.sg_ids["alb"], cidr = cidr, port = port
    }
  }]...) : {}
}
module "rules" {
  source         = "../../modules/security-rules"
  ingress        = { for k, rules in local.ingress_grouped : k => rules[0] }
  egress         = { for k, rules in local.egress_grouped : k => rules[0] }
  public_ingress = merge(local.admin_ingress, local.alb_ingress)
  public_egress = {
    for role, id in local.foundation.sg_ids : "https/${role}" => {
      group_id = id, cidr = "0.0.0.0/0", port = 443
    } if contains(var.traffic.internet_https_roles, role)
  }
  depends_on = [terraform_data.connectivity_ready]
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
  certificate_arn      = var.topology.alb.certificate_arn
  frontend_targets     = { for name, node in local.nodes : name => module.compute.instances[name].id if node.role == var.topology.alb.frontend_role }
  game_targets         = { for name, node in local.nodes : name => module.compute.instances[name].id if node.role == var.topology.alb.game_role }
  frontend_port        = var.traffic.ports.frontend
  game_port            = var.traffic.ports.game
  static_path          = var.topology.alb.static_path
  frontend_health_path = var.topology.alb.frontend_health_path
  game_health_path     = var.topology.alb.game_health_path
}
output "inventory" {
  value = {
    account        = var.account_key
    account_id     = local.account.id
    region         = var.topology.region
    instances      = module.compute.instances
    alb_dns_name   = try(module.alb[0].dns_name, null)
    proxy_endpoint = try("http://${module.compute.instances["bastion"].private_ip}:${var.traffic.ports.proxy}", null)
  }
}
