data "terraform_remote_state" "foundation" {
  for_each = var.topology.accounts
  backend  = "s3"
  config = {
    bucket  = var.state_backend.bucket
    region  = var.state_backend.region
    profile = var.state_backend.profile
    key     = "${var.state_backend.key_prefix}/${each.key}/foundation/terraform.tfstate"
  }
  lifecycle {
    postcondition {
      condition = try(
        self.outputs.foundation.account_id == each.value.id &&
        self.outputs.foundation.account_key == each.key &&
        self.outputs.foundation.region == var.topology.region &&
        self.outputs.foundation.vpc_cidr == each.value.vpc_cidr &&
        self.outputs.foundation.az_ids == var.topology.az_ids, false
      )
      error_message = "foundation 상태의 계정·리전·CIDR·AZ가 현재 설정과 다릅니다. foundation을 먼저 확인하세요."
    }
  }
}
locals {
  foundations = { for account, state in data.terraform_remote_state.foundation : account => state.outputs.foundation }
}
output "foundation_vpcs" {
  value = { for account, foundation in local.foundations : account => foundation.vpc_id }
}
