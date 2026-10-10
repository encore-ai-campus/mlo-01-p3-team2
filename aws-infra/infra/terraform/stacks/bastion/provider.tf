provider "aws" {
  region              = var.topology.region
  profile             = var.topology.accounts[var.account_key].profile
  allowed_account_ids = [var.topology.accounts[var.account_key].id]
  default_tags {
    tags = { Project = var.topology.project, Account = var.account_key, ManagedBy = "Terraform", Layout = "v2", Stage = "bastion" }
  }
}
