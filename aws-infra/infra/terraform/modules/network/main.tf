variable "name" { type = string }
variable "cidr" { type = string }
variable "az_ids" { type = map(string) }
variable "public_subnets" { type = bool }
variable "egress" { type = string }
locals {
  subnets = merge(
    { for az, index in { a = 10, c = 11 } : "private_${az}" => { az = az, cidr = cidrsubnet(var.cidr, 8, index), public = false } },
    var.public_subnets ? { for az, index in { a = 0, c = 1 } : "public_${az}" => { az = az, cidr = cidrsubnet(var.cidr, 8, index), public = true } } : {}
  )
}
resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}
resource "aws_subnet" "this" {
  for_each                = local.subnets
  vpc_id                  = aws_vpc.this.id
  cidr_block              = each.value.cidr
  availability_zone_id    = var.az_ids[each.value.az]
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-${each.key}" }
}
resource "aws_internet_gateway" "this" {
  count  = var.public_subnets ? 1 : 0
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-igw" }
}
resource "aws_route_table" "this" {
  for_each = local.subnets
  vpc_id   = aws_vpc.this.id
  tags     = { Name = "${var.name}-${each.key}" }
}
resource "aws_route_table_association" "this" {
  for_each       = local.subnets
  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.this[each.key].id
}
resource "aws_route" "public" {
  for_each               = { for k, s in local.subnets : k => s if s.public }
  route_table_id         = aws_route_table.this[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this[0].id
}
resource "aws_eip" "nat" {
  for_each = var.egress == "nat" ? var.az_ids : {}
  domain   = "vpc"
  tags     = { Name = "${var.name}-nat-${each.key}" }
}
resource "aws_nat_gateway" "this" {
  for_each          = var.egress == "nat" ? var.az_ids : {}
  allocation_id     = aws_eip.nat[each.key].id
  subnet_id         = aws_subnet.this["public_${each.key}"].id
  connectivity_type = "public"
  tags              = { Name = "${var.name}-nat-${each.key}" }
  depends_on        = [aws_internet_gateway.this]
}
resource "aws_route" "private_nat" {
  for_each               = var.egress == "nat" ? var.az_ids : {}
  route_table_id         = aws_route_table.this["private_${each.key}"].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[each.key].id
}
output "vpc_id" { value = aws_vpc.this.id }
output "subnet_ids" { value = { for k, s in aws_subnet.this : k => s.id } }
output "route_table_ids" { value = { for k, r in aws_route_table.this : k => r.id } }
output "nat_gateway_ids" { value = { for k, n in aws_nat_gateway.this : k => n.id } }
output "nat_routes" {
  value = { for az, route in aws_route.private_nat : az => {
    nat_gateway_id = route.nat_gateway_id
    route_table_id = route.route_table_id
  } }
}
