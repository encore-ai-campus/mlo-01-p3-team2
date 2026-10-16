terraform {
  required_providers {
    aws = {
      source                = "hashicorp/aws"
      version               = "~> 6.68"
      configuration_aliases = [aws.requester, aws.accepter]
    }
  }
}
variable "name" { type = string }
variable "requester" { type = any }
variable "accepter" { type = any }
resource "aws_vpc_peering_connection" "this" {
  provider      = aws.requester
  vpc_id        = var.requester.vpc_id
  peer_vpc_id   = var.accepter.vpc_id
  peer_owner_id = var.accepter.account_id
  peer_region   = var.accepter.region
  auto_accept   = false
  tags          = { Name = var.name }
}
resource "aws_vpc_peering_connection_accepter" "this" {
  provider                  = aws.accepter
  vpc_peering_connection_id = aws_vpc_peering_connection.this.id
  auto_accept               = true
  tags                      = { Name = var.name }
}
resource "aws_vpc_peering_connection_options" "requester" {
  provider                  = aws.requester
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.this.id
  requester { allow_remote_vpc_dns_resolution = true }
}
resource "aws_vpc_peering_connection_options" "accepter" {
  provider                  = aws.accepter
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.this.id
  accepter { allow_remote_vpc_dns_resolution = true }
}
resource "aws_route" "requester" {
  provider                  = aws.requester
  for_each                  = var.requester.route_table_ids
  route_table_id            = each.value
  destination_cidr_block    = var.accepter.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.this.id
}
resource "aws_route" "accepter" {
  provider                  = aws.accepter
  for_each                  = var.accepter.route_table_ids
  route_table_id            = each.value
  destination_cidr_block    = var.requester.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection_accepter.this.id
}
output "id" { value = aws_vpc_peering_connection_accepter.this.id }
output "requester_routes" {
  value = { for k, route in aws_route.requester : k => {
    destination = route.destination_cidr_block, route_table_id = route.route_table_id,
    peering_id  = route.vpc_peering_connection_id
  } }
}
output "accepter_routes" {
  value = { for k, route in aws_route.accepter : k => {
    destination = route.destination_cidr_block, route_table_id = route.route_table_id,
    peering_id  = route.vpc_peering_connection_id
  } }
}
