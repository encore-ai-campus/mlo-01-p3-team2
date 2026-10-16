provider "aws" {
  alias               = "account1"
  region              = var.topology.region
  profile             = var.topology.accounts["account1"].profile
  allowed_account_ids = [var.topology.accounts["account1"].id]
  default_tags {
    tags = { Project = var.topology.project, Account = "account1", ManagedBy = "Terraform", Layout = "v2" }
  }
}


provider "aws" {
  alias               = "account2"
  region              = var.topology.region
  profile             = var.topology.accounts["account2"].profile
  allowed_account_ids = [var.topology.accounts["account2"].id]
  default_tags {
    tags = { Project = var.topology.project, Account = "account2", ManagedBy = "Terraform", Layout = "v2" }
  }
}


provider "aws" {
  alias               = "account3"
  region              = var.topology.region
  profile             = var.topology.accounts["account3"].profile
  allowed_account_ids = [var.topology.accounts["account3"].id]
  default_tags {
    tags = { Project = var.topology.project, Account = "account3", ManagedBy = "Terraform", Layout = "v2" }
  }
}


provider "aws" {
  alias               = "account4"
  region              = var.topology.region
  profile             = var.topology.accounts["account4"].profile
  allowed_account_ids = [var.topology.accounts["account4"].id]
  default_tags {
    tags = { Project = var.topology.project, Account = "account4", ManagedBy = "Terraform", Layout = "v2" }
  }
}


provider "aws" {
  alias               = "account5"
  region              = var.topology.region
  profile             = var.topology.accounts["account5"].profile
  allowed_account_ids = [var.topology.accounts["account5"].id]
  default_tags {
    tags = { Project = var.topology.project, Account = "account5", ManagedBy = "Terraform", Layout = "v2" }
  }
}
