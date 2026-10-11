variable "topology" { type = any }
variable "traffic" { type = any }
variable "account_key" {
  type    = string
  default = "account1"
}
variable "state_backend" {
  type    = object({ bucket = string, region = string, profile = string, key_prefix = string })
  default = { bucket = "", region = "ap-northeast-2", profile = "", key_prefix = "aws-infra-v2" }
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

# 빈 환경에서 Public 진입 서버만 먼저 구축한다. 기존 서버가 있으면 실행기에서 축소 계획을 거부한다.
variable "edge_bootstrap_only" {
  type    = bool
  default = false
}
