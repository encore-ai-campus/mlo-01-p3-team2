data "terraform_remote_state" "foundation" {
  for_each = { for key, account in var.topology.accounts : key => account if !var.edge_bootstrap_only || key == var.account_key }
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
  count   = var.edge_bootstrap_only ? 0 : 1
  backend = "s3"
  config = {
    bucket  = var.state_backend.bucket
    region  = var.state_backend.region
    profile = var.state_backend.profile
    key     = "${var.state_backend.key_prefix}/shared/connectivity/terraform.tfstate"
  }
}
resource "terraform_data" "connectivity_ready" {
  # 삭제가 중단돼도 모드를 복구할 수 있도록 EC2·규칙 뒤에 초기 구축 표식을 삭제한다.
  depends_on = [terraform_data.edge_bootstrap_guard]
  lifecycle {
    precondition {
      condition = var.edge_bootstrap_only ? true : try(alltrue([
        for account, foundation in local.foundations :
        data.terraform_remote_state.connectivity[0].outputs.foundation_vpcs[account] == foundation.vpc_id
      ]), false)
      error_message = "foundation VPC가 변경되었습니다. connectivity를 먼저 갱신하세요."
    }
    precondition {
      condition = var.edge_bootstrap_only ? true : try(alltrue([
        for name, flow in module.model.flows :
        contains(keys(data.terraform_remote_state.connectivity[0].outputs.connections), join("-", sort([flow.source_account, flow.target_account])))
        if flow.source_account != flow.target_account
      ]), false)
      error_message = "서비스 간 통신에 필요한 Peering이 없습니다. connectivity를 먼저 적용하세요."
    }
  }
}
