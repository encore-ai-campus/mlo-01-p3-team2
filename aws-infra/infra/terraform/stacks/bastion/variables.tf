variable "topology" { type = any }
variable "traffic" { type = any }
variable "account_key" {
  type    = string
  default = "account1"
  validation {
    condition     = var.account_key == "account1"
    error_message = "Bastion 전용 단계는 account1에서만 실행합니다."
  }
}
variable "state_backend" {
  type = object({ bucket = string, region = string, profile = string, key_prefix = string })
}
variable "ssh_public_key" { type = string }
module "model" {
  source   = "../../modules/model"
  topology = var.topology
  traffic  = var.traffic
}
