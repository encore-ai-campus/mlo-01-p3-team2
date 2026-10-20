# 네트워크와 SG는 foundation 소유다. Bastion 삭제 계획에는 포함하지 않는다.
data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket  = var.state_backend.bucket
    region  = var.state_backend.region
    profile = var.state_backend.profile
    key     = "${var.state_backend.key_prefix}/${var.account_key}/foundation/terraform.tfstate"
  }
  lifecycle {
    postcondition {
      condition = try(
        self.outputs.foundation.account_id == var.topology.accounts[var.account_key].id &&
        self.outputs.foundation.account_key == var.account_key &&
        self.outputs.foundation.region == var.topology.region &&
        self.outputs.foundation.vpc_cidr == var.topology.accounts[var.account_key].vpc_cidr &&
        self.outputs.foundation.az_ids == var.topology.az_ids &&
        can(self.outputs.foundation.subnet_ids.public_a) &&
        can(self.outputs.foundation.sg_ids.bastion), false
      )
      error_message = "Account 1 foundation의 계정·리전·CIDR·AZ·Public A·Bastion SG를 확인하세요."
    }
  }
}
