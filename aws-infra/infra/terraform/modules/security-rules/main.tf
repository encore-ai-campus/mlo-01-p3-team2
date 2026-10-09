variable "ingress" {
  type = map(object({ group_id = string, peer_id = string, port = number }))
}
variable "egress" {
  type = map(object({ group_id = string, peer_id = string, port = number }))
}
variable "public_ingress" {
  type = map(object({ group_id = string, cidr = string, port = number }))
}
variable "public_egress" {
  type = map(object({ group_id = string, cidr = string, port = number }))
}
resource "aws_vpc_security_group_ingress_rule" "peer" {
  for_each                     = var.ingress
  security_group_id            = each.value.group_id
  referenced_security_group_id = each.value.peer_id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  description                  = each.key
}
resource "aws_vpc_security_group_egress_rule" "peer" {
  for_each                     = var.egress
  security_group_id            = each.value.group_id
  referenced_security_group_id = each.value.peer_id
  ip_protocol                  = "tcp"
  from_port                    = each.value.port
  to_port                      = each.value.port
  description                  = each.key
}
resource "aws_vpc_security_group_ingress_rule" "public" {
  for_each          = var.public_ingress
  security_group_id = each.value.group_id
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  description       = each.key
}
resource "aws_vpc_security_group_egress_rule" "public" {
  for_each          = var.public_egress
  security_group_id = each.value.group_id
  cidr_ipv4         = each.value.cidr
  ip_protocol       = "tcp"
  from_port         = each.value.port
  to_port           = each.value.port
  description       = each.key
}
output "ingress" { value = var.ingress }
output "egress" { value = var.egress }
output "public_ingress" { value = var.public_ingress }
