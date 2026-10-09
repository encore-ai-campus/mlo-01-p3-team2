locals {
  account = module.model.topology.accounts[var.account_key]
  name    = "${var.topology.project}-${var.account_key}"
}
module "network" {
  source         = "../../modules/network"
  name           = local.name
  cidr           = local.account.vpc_cidr
  az_ids         = var.topology.az_ids
  public_subnets = local.account.public_subnets
  egress         = local.account.egress
}
module "groups" {
  source = "../../modules/security-groups"
  name   = local.name
  vpc_id = module.network.vpc_id
  roles  = module.model.roles[var.account_key]
}
output "foundation" {
  value = {
    account_key     = var.account_key
    account_id      = local.account.id
    region          = var.topology.region
    vpc_cidr        = local.account.vpc_cidr
    az_ids          = var.topology.az_ids
    vpc_id          = module.network.vpc_id
    subnet_ids      = module.network.subnet_ids
    route_table_ids = module.network.route_table_ids
    sg_ids          = module.groups.ids
    nat_gateway_ids = module.network.nat_gateway_ids
  }
}
