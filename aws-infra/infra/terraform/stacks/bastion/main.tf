locals {
  account    = module.model.topology.accounts[var.account_key]
  node       = module.model.topology.nodes.bastion
  foundation = data.terraform_remote_state.foundation.outputs.foundation
  key_name   = "${local.account.key_pair_name}-bastion"
}

module "bastion" {
  source        = "../../modules/bastion"
  name          = "${var.topology.project}-${var.account_key}-bastion"
  account_key   = var.account_key
  ami_id        = local.account.ami_id
  instance_type = local.node.instance_type
  root_gib      = local.node.root_gib
  subnet_id     = local.foundation.subnet_ids.public_a
  sg_id         = local.foundation.sg_ids.bastion
  key_name      = local.key_name
  public_key    = var.ssh_public_key
}

output "bastion" {
  value = merge(module.bastion.instance, {
    account        = var.account_key
    account_id     = local.account.id
    region         = var.topology.region
    ssh_port       = var.traffic.ports.ssh
    ssh_command    = "ssh -p ${var.traffic.ports.ssh} -i <개인키_경로> ubuntu@${module.bastion.instance.public_ip}"
    proxy_endpoint = "http://${module.bastion.instance.private_ip}:${var.traffic.ports.proxy}"
  })
  precondition {
    condition = (local.node.account == var.account_key && local.node.role == "bastion" &&
      local.node.subnet_tier == "public" && local.node.az == "a" &&
    local.account.public_subnets && local.node.public_ip && length(local.node.data_disks) == 0)
    error_message = "Bastion은 Account 1 Public A·자동 공인 IP·OS 디스크만 사용하는 구성이어야 합니다."
  }
}
