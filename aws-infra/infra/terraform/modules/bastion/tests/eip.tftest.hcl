# EC2 생성 옵션을 유지하면서 같은 인스턴스에 EIP를 연결하는지 검사한다.
mock_provider "aws" {}
variables {
  name          = "test-bastion"
  account_key   = "account1"
  ami_id        = "ami-0123456789abcdef0"
  instance_type = "t3a.small"
  root_gib      = 20
  subnet_id     = "subnet-00000000000000001"
  sg_id         = "sg-00000000000000001"
  key_name      = "test-bastion"
  public_key    = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
}
run "connect_existing_instance" {
  command = apply
  assert {
    condition = (
      aws_eip.this.domain == "vpc" &&
      aws_eip_association.this.allocation_id == aws_eip.this.id &&
      aws_eip_association.this.instance_id == aws_instance.this.id &&
      aws_instance.this.associate_public_ip_address == true
    )
    error_message = "기존 EC2 옵션을 유지하고 같은 EC2에 VPC EIP를 연결해야 합니다."
  }
  assert {
    condition     = aws_eip.this.tags.Stage == "bastion" && output.instance.public_ip == aws_eip.this.public_ip
    error_message = "EIP는 Bastion 소유 태그와 출력 주소를 가져야 합니다."
  }
}
