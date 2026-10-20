variable "name" { type = string }
variable "account_key" { type = string }
variable "ami_id" {
  type = string
  validation {
    condition     = can(regex("^ami-[0-9a-f]+$", var.ami_id))
    error_message = "확인한 Ubuntu x86_64 AMI ID를 설정하세요."
  }
}
variable "instance_type" { type = string }
variable "root_gib" { type = number }
variable "subnet_id" { type = string }
variable "sg_id" { type = string }
variable "key_name" { type = string }
variable "public_key" {
  type = string
  validation {
    condition     = can(regex("^(ssh-rsa|ssh-ed25519) [A-Za-z0-9+/=]+", trimspace(var.public_key)))
    error_message = "Bastion용 SSH 공개키(.pub)가 필요합니다."
  }
}

# 서비스용 키페어를 삭제하지 않도록 Bastion 전용 이름으로 등록한다.
resource "aws_key_pair" "this" {
  key_name   = var.key_name
  public_key = trimspace(var.public_key)
  tags       = { Name = var.name, Role = "bastion", Node = "bastion", Stage = "bastion" }
}

resource "aws_instance" "this" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.sg_id]
  key_name               = aws_key_pair.this.key_name
  # 기존 EC2의 생성 옵션을 유지하고, 아래 별도 연결 자원으로 공인 주소를 EIP로 고정한다.
  associate_public_ip_address = true
  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_gib
    encrypted             = true
    delete_on_termination = true
  }
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  credit_specification { cpu_credits = "unlimited" }
  # 역할 정보만 기록한다. Proxy 설치와 클라이언트 설정은 별도 작업이다.
  user_data = "#cloud-config\n${jsonencode({ write_files = [{
    path    = "/etc/aws-infra/node.json", permissions = "0644",
    content = jsonencode({ name = "bastion", role = "bastion", account = var.account_key })
  }] })}"
  tags = { Name = var.name, Role = "bastion", Node = "bastion", Stage = "bastion" }
}

# Bastion 전용 상태가 EIP도 소유한다. 중지·시작에는 유지하고 Bastion 삭제 시 반환한다.
resource "aws_eip" "this" {
  domain = "vpc"
  tags   = { Name = var.name, Role = "bastion", Node = "bastion", Stage = "bastion" }
}

resource "aws_eip_association" "this" {
  allocation_id = aws_eip.this.id
  instance_id   = aws_instance.this.id
}

output "instance" {
  value = {
    id             = aws_instance.this.id
    public_ip      = aws_eip.this.public_ip
    private_ip     = aws_instance.this.private_ip
    root_volume_id = one(aws_instance.this.root_block_device).volume_id
    key_name       = aws_key_pair.this.key_name
  }
  # 출력 소비자는 EIP 연결이 끝난 뒤 고정 주소를 사용한다.
  depends_on = [aws_eip_association.this]
}
