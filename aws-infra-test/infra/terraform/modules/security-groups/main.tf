variable "name" { type = string }
variable "vpc_id" { type = string }
variable "roles" { type = set(string) }
resource "aws_security_group" "this" {
  for_each    = var.roles
  name        = "${var.name}-${each.key}"
  description = "Role ${each.key}"
  vpc_id      = var.vpc_id
  # 규칙은 workload의 독립 리소스가 소유한다.
  tags = { Name = "${var.name}-${each.key}", Role = each.key }
}
output "ids" { value = { for role, sg in aws_security_group.this : role => sg.id } }
