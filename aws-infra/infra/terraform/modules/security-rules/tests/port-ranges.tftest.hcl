# 실제 AWS 연결 없이 provider가 받을 TCP 시작·끝 포트를 검사한다.
mock_provider "aws" {}

variables {
  ingress = {
    single = { group_id = "sg-00000000000000001", peer_id = "sg-00000000000000002", port = 3888 }
    range  = { group_id = "sg-00000000000000001", peer_id = "sg-00000000000000002", port = 7079, port_end = 7095 }
  }
  egress = {
    single = { group_id = "sg-00000000000000001", peer_id = "sg-00000000000000002", port = 3888 }
    range  = { group_id = "sg-00000000000000001", peer_id = "sg-00000000000000002", port = 7078, port_end = 7094 }
  }
  public_ingress = {}
  public_egress  = {}
}

run "peer_port_bounds" {
  command = plan
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.peer["single"].from_port == 3888 &&
      aws_vpc_security_group_ingress_rule.peer["single"].to_port == 3888 &&
      aws_vpc_security_group_egress_rule.peer["single"].to_port == 3888
    )
    error_message = "기존 단일 포트 호출의 입출력 범위가 넓어지면 안 됩니다."
  }
  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.peer["range"].from_port == 7079 &&
      aws_vpc_security_group_ingress_rule.peer["range"].to_port == 7095 &&
      aws_vpc_security_group_egress_rule.peer["range"].from_port == 7078 &&
      aws_vpc_security_group_egress_rule.peer["range"].to_port == 7094 &&
      aws_vpc_security_group_ingress_rule.peer["range"].ip_protocol == "tcp" &&
      aws_vpc_security_group_egress_rule.peer["range"].ip_protocol == "tcp"
    )
    error_message = "지정한 TCP 범위를 SG 입출력 자원까지 전달해야 합니다."
  }
}
