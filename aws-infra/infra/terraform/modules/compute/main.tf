variable "name" { type = string }
variable "ami_id" {
  type = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]+$", var.ami_id))
    error_message = "확인한 Ubuntu x86_64 AMI ID를 설정하세요."
  }
}
variable "nodes" { type = any }
variable "subnet_ids" { type = map(string) }
variable "sg_ids" { type = map(string) }
variable "key_name" { type = string }
variable "public_key" {
  type = string
  validation {
    condition     = can(regex("^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+", trimspace(var.public_key)))
    error_message = "SSH 공개키가 필요합니다. 개인키를 입력하지 마세요."
  }
}
resource "aws_key_pair" "this" {
  key_name   = var.key_name
  public_key = trimspace(var.public_key)
}
resource "aws_instance" "this" {
  for_each               = var.nodes
  ami                    = var.ami_id
  instance_type          = each.value.instance_type
  subnet_id              = var.subnet_ids["${each.value.subnet_tier}_${each.value.az}"]
  vpc_security_group_ids = [var.sg_ids[each.value.role]]
  key_name               = aws_key_pair.this.key_name
  # EIP 연결 노드는 조회된 공인 IP 설정과 맞춰 불필요한 EC2 교체를 막는다.
  associate_public_ip_address = each.value.public_ip
  root_block_device {
    volume_type           = "gp3"
    volume_size           = each.value.root_gib
    encrypted             = true
    delete_on_termination = true
  }
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  credit_specification { cpu_credits = "unlimited" }
  # 초기 실행은 역할 메타데이터만 기록한다. 설치·포맷·DB 초기화는 하지 않는다.
  user_data = "#cloud-config\n${jsonencode({ write_files = [{
    path    = "/etc/aws-infra/node.json", permissions = "0644",
    content = jsonencode({ name = each.key, role = each.value.role, account = each.value.account })
  }] })}"
  tags = { Name = "${var.name}-${each.key}", Role = each.value.role, Node = each.key }
}
locals {
  disks = merge({}, [for name, n in var.nodes : {
    for disk, config in n.data_disks : "${name}/${disk}" => merge(config, { node = name, disk = disk })
  }]...)
}
resource "aws_ebs_volume" "data" {
  for_each          = local.disks
  availability_zone = aws_instance.this[each.value.node].availability_zone
  type              = each.value.type
  size              = each.value.size_gib
  encrypted         = true
  tags              = { Name = "${var.name}-${each.value.node}-${each.value.disk}" }
  # 배치 변경으로 데이터 볼륨이 자동 폐기되지 않도록 이전 절차를 요구한다.
  lifecycle { prevent_destroy = true }
}
resource "aws_volume_attachment" "data" {
  for_each    = local.disks
  device_name = each.value.device_name
  volume_id   = aws_ebs_volume.data[each.key].id
  instance_id = aws_instance.this[each.value.node].id
}
resource "aws_eip" "this" {
  for_each = { for k, n in var.nodes : k => n if n.public_ip }
  domain   = "vpc"
  tags     = { Name = "${var.name}-${each.key}" }
}
resource "aws_eip_association" "this" {
  for_each      = aws_eip.this
  allocation_id = each.value.id
  instance_id   = aws_instance.this[each.key].id
}
output "instances" {
  value = { for name, n in aws_instance.this : name => {
    id            = n.id, role = var.nodes[name].role, private_ip = n.private_ip,
    public_ip     = try(aws_eip.this[name].public_ip, null),
    instance_type = n.instance_type, availability_zone = n.availability_zone,
    data_volumes  = { for k, d in local.disks : d.disk => aws_ebs_volume.data[k].id if d.node == name }
  } }
}
