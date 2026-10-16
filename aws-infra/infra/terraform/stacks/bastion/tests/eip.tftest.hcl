# AWS와 S3를 모의 처리해 고정 IP 출력과 SSH 안내를 확인한다.
mock_provider "aws" {
  mock_resource "aws_eip" {
    defaults = { public_ip = "203.0.113.10" }
  }
  mock_resource "aws_instance" {
    defaults = { public_ip = "203.0.113.99", private_ip = "10.10.0.10" }
  }
}
variables {
  state_backend = { bucket = "mock-state-bucket", region = "ap-northeast-2", profile = "unused", key_prefix = "test" }
  topology = merge(jsondecode(file("../../../config/topology.tfvars.json")).topology, {
    accounts = { for name, account in jsondecode(file("../../../config/topology.tfvars.json")).topology.accounts :
      name => merge(account, { ami_id = "ami-0123456789abcdef0" })
    }
  })
  traffic        = jsondecode(file("../../../config/traffic.tfvars.json")).traffic
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFixturenotarealkey"
}
override_data {
  target = data.terraform_remote_state.foundation
  values = { outputs = { foundation = jsondecode(file("../../../tests/fixtures.json")).foundations.account1 } }
}
run "bastion_elastic_ip_output" {
  command = apply
  assert {
    condition     = output.bastion.public_ip == "203.0.113.10"
    error_message = "자동 공인 IP가 아니라 EIP를 출력해야 합니다."
  }
  assert {
    condition     = endswith(output.bastion.ssh_command, "ubuntu@203.0.113.10")
    error_message = "SSH 안내는 EIP를 사용해야 합니다."
  }
  assert {
    condition     = output.bastion.private_ip == "10.10.0.10" && startswith(output.bastion.proxy_endpoint, "http://10.10.0.10:")
    error_message = "내부 프록시는 기존 사설 IP를 사용해야 합니다."
  }
}
