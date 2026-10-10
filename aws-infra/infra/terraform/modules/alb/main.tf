variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "sg_id" { type = string }
variable "frontend_targets" { type = map(string) }
variable "game_targets" { type = map(string) }
variable "ad_targets" { type = map(string) }
variable "frontend_port" { type = number }
variable "game_port" { type = number }
variable "ad_port" { type = number }
variable "static_path" { type = string }
variable "ad_path" { type = string }
variable "frontend_health_path" { type = string }
variable "game_health_path" { type = string }
variable "ad_health_path" { type = string }
resource "aws_lb" "this" {
  name               = var.name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_id]
  subnets            = var.subnet_ids
}
resource "aws_lb_target_group" "this" {
  for_each = {
    frontend = { port = var.frontend_port, health_path = var.frontend_health_path }
    game     = { port = var.game_port, health_path = var.game_health_path }
    ad       = { port = var.ad_port, health_path = var.ad_health_path }
  }
  name     = "${var.name}-${each.key}"
  port     = each.value.port
  protocol = "HTTP"
  vpc_id   = var.vpc_id
  health_check {
    path    = each.value.health_path
    matcher = "200-399"
  }
}
resource "aws_lb_target_group_attachment" "frontend" {
  for_each         = var.frontend_targets
  target_group_arn = aws_lb_target_group.this["frontend"].arn
  target_id        = each.value
  port             = var.frontend_port
}
resource "aws_lb_target_group_attachment" "game" {
  for_each         = var.game_targets
  target_group_arn = aws_lb_target_group.this["game"].arn
  target_id        = each.value
  port             = var.game_port
}
resource "aws_lb_target_group_attachment" "ad" {
  for_each         = var.ad_targets
  target_group_arn = aws_lb_target_group.this["ad"].arn
  target_id        = each.value
  port             = var.ad_port
}
# 기본 요청은 HTTP 80에서 game-server 대상 그룹으로 전달한다.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["game"].arn
  }
}
# 같은 HTTP 리스너에서 정적 파일 경로만 Front 대상 그룹으로 보낸다.
resource "aws_lb_listener_rule" "static" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["frontend"].arn
  }
  condition {
    path_pattern { values = [var.static_path] }
  }
}
# 광고 경로는 접두사를 제거하지 않고 광고 Django 서버로 전달한다.
resource "aws_lb_listener_rule" "ad" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 20
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["ad"].arn
  }
  condition {
    path_pattern { values = [var.ad_path] }
  }
}
output "dns_name" { value = aws_lb.this.dns_name }
