# Application Load Balancer in front of an ECS service.
#
# Placement: public subnets (reached from the internet via the IGW), with a
# listener that forwards traffic to the ECS task ENIs — which live in the
# private subnets and are reachable only through this ALB.

# --- Security groups ---
resource "aws_security_group" "lb" {
  name        = "${var.name}-lb"
  description = "Load balancer security group: ${join(", ", var.listeners)}"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = toset(var.listeners) == [] ? toset(["__none__"]) : toset(var.listeners)
    content {
      from_port   = tonumber(split(":", ingress.value)[0])
      to_port     = tonumber(split(":", ingress.value)[0])
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- Target group -> ECS task ENIs on the container port ---
resource "aws_lb_target_group" "this" {
  name                 = var.name
  port                 = var.container_port
  protocol             = "HTTP"
  vpc_id               = var.vpc_id
  target_type          = "ip"
  ip_address_type      = "ipv4"
  deregistration_delay = 30
  slow_start           = 0

  health_check {
    enabled             = true
    port                = "traffic-port"
    protocol            = "HTTP"
    path                = var.health_check_path
    interval            = var.health_check_interval
    timeout             = var.health_check_timeout
    healthy_threshold   = var.health_check_healthy_threshold
    unhealthy_threshold = var.health_check_unhealthy_threshold
    matcher             = var.health_check_matcher
  }
}

# --- The load balancer itself ---
resource "aws_lb" "this" {
  name               = var.name
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.lb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = false
}

# --- HTTP listener (the one everyone needs to expose the API) ---
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}