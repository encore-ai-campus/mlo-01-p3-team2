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

data "terraform_remote_state" "connectivity" {
  backend = "s3"
  config = {
    bucket  = var.state_backend.bucket
    region  = var.state_backend.region
    profile = var.state_backend.profile
    key     = "${var.state_backend.key_prefix}/shared/connectivity/terraform.tfstate"
  }
}
resource "terraform_data" "connectivity_ready" {
  lifecycle {
    precondition {
      condition = try(alltrue([
        for account, foundation in local.foundations :
        data.terraform_remote_state.connectivity.outputs.foundation_vpcs[account] == foundation.vpc_id
      ]), false)
      error_message = "foundation VPC가 변경되었습니다. connectivity를 먼저 갱신하세요."
    }
    precondition {
      condition = try(alltrue([
        for name, flow in module.model.flows :
        contains(keys(data.terraform_remote_state.connectivity.outputs.connections), join("-", sort([flow.source_account, flow.target_account])))
        if flow.source_account != flow.target_account
      ]), false)
      error_message = "서비스 간 통신에 필요한 Peering이 없습니다. connectivity를 먼저 적용하세요."
    }
  }
}
