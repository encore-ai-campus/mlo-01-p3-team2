variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "sg_id" { type = string }
variable "certificate_arn" { type = string }
variable "frontend_targets" { type = map(string) }
variable "game_targets" { type = map(string) }
variable "frontend_port" { type = number }
variable "game_port" { type = number }
variable "static_path" { type = string }
variable "frontend_health_path" { type = string }
variable "game_health_path" { type = string }
resource "aws_lb" "this" {
  name               = var.name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.sg_id]
  subnets            = var.subnet_ids
  lifecycle {
    precondition {
      condition     = can(regex("^arn:aws:acm:ap-northeast-2:[0-9]{12}:certificate/", var.certificate_arn))
      error_message = "ALB의 서울 리전 ACM 인증서 ARN을 설정하세요."
    }
  }
}
resource "aws_lb_target_group" "this" {
  for_each = {
    frontend = { port = var.frontend_port, health_path = var.frontend_health_path }
    game     = { port = var.game_port, health_path = var.game_health_path }
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
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  certificate_arn   = var.certificate_arn
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["game"].arn
  }
}
resource "aws_lb_listener_rule" "static" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this["frontend"].arn
  }
  condition {
    path_pattern { values = [var.static_path] }
  }
}
output "dns_name" { value = aws_lb.this.dns_name }
