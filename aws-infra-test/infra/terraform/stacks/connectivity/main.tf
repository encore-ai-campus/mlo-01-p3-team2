module "account1_account2" {
  count     = contains(var.topology.peerings, "account1-account2") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account1, aws.accepter = aws.account2 }
  name      = "${var.topology.project}-account1-account2"
  requester = local.foundations.account1
  accepter  = local.foundations.account2
}

module "account1_account3" {
  count     = contains(var.topology.peerings, "account1-account3") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account1, aws.accepter = aws.account3 }
  name      = "${var.topology.project}-account1-account3"
  requester = local.foundations.account1
  accepter  = local.foundations.account3
}

module "account1_account4" {
  count     = contains(var.topology.peerings, "account1-account4") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account1, aws.accepter = aws.account4 }
  name      = "${var.topology.project}-account1-account4"
  requester = local.foundations.account1
  accepter  = local.foundations.account4
}

module "account1_account5" {
  count     = contains(var.topology.peerings, "account1-account5") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account1, aws.accepter = aws.account5 }
  name      = "${var.topology.project}-account1-account5"
  requester = local.foundations.account1
  accepter  = local.foundations.account5
}

module "account2_account3" {
  count     = contains(var.topology.peerings, "account2-account3") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account2, aws.accepter = aws.account3 }
  name      = "${var.topology.project}-account2-account3"
  requester = local.foundations.account2
  accepter  = local.foundations.account3
}

module "account2_account4" {
  count     = contains(var.topology.peerings, "account2-account4") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account2, aws.accepter = aws.account4 }
  name      = "${var.topology.project}-account2-account4"
  requester = local.foundations.account2
  accepter  = local.foundations.account4
}

module "account2_account5" {
  count     = contains(var.topology.peerings, "account2-account5") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account2, aws.accepter = aws.account5 }
  name      = "${var.topology.project}-account2-account5"
  requester = local.foundations.account2
  accepter  = local.foundations.account5
}

module "account3_account4" {
  count     = contains(var.topology.peerings, "account3-account4") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account3, aws.accepter = aws.account4 }
  name      = "${var.topology.project}-account3-account4"
  requester = local.foundations.account3
  accepter  = local.foundations.account4
}

module "account3_account5" {
  count     = contains(var.topology.peerings, "account3-account5") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account3, aws.accepter = aws.account5 }
  name      = "${var.topology.project}-account3-account5"
  requester = local.foundations.account3
  accepter  = local.foundations.account5
}

module "account4_account5" {
  count     = contains(var.topology.peerings, "account4-account5") ? 1 : 0
  source    = "../../modules/peering"
  providers = { aws.requester = aws.account4, aws.accepter = aws.account5 }
  name      = "${var.topology.project}-account4-account5"
  requester = local.foundations.account4
  accepter  = local.foundations.account5
}

output "connections" {
  value = merge(contains(var.topology.peerings, "account1-account2") ? { "account1-account2" = module.account1_account2[0].id } : {},
    contains(var.topology.peerings, "account1-account3") ? { "account1-account3" = module.account1_account3[0].id } : {},
    contains(var.topology.peerings, "account1-account4") ? { "account1-account4" = module.account1_account4[0].id } : {},
    contains(var.topology.peerings, "account1-account5") ? { "account1-account5" = module.account1_account5[0].id } : {},
    contains(var.topology.peerings, "account2-account3") ? { "account2-account3" = module.account2_account3[0].id } : {},
    contains(var.topology.peerings, "account2-account4") ? { "account2-account4" = module.account2_account4[0].id } : {},
    contains(var.topology.peerings, "account2-account5") ? { "account2-account5" = module.account2_account5[0].id } : {},
    contains(var.topology.peerings, "account3-account4") ? { "account3-account4" = module.account3_account4[0].id } : {},
    contains(var.topology.peerings, "account3-account5") ? { "account3-account5" = module.account3_account5[0].id } : {},
  contains(var.topology.peerings, "account4-account5") ? { "account4-account5" = module.account4_account5[0].id } : {})
}
