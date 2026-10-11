variable "topology" { type = any }
variable "traffic" { type = any }
variable "account_key" {
  type    = string
  default = "account1"
}
variable "state_backend" {
  type    = object({ bucket = string, region = string, profile = string, key_prefix = string })
  default = { bucket = "", region = "ap-northeast-2", profile = "", key_prefix = "aws-infra-test" }
}
variable "ssh_public_key" {
  type    = string
  default = ""
}
module "model" {
  source   = "../../modules/model"
  topology = var.topology
  traffic  = var.traffic
}
