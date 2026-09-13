# Bare-minimum ECS module — EC2 launch type (container instances managed by an
# Auto Scaling group, no Fargate). Runs the container on our own instances to
# keep the platform's hosting cost down.
#
# Layout:
#   cluster <- capacity provider <- Auto Scaling group of ECS-optimized instances
#   service  <- task definition <- app security group (task ENIs, awsvpc)

data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2/recommended/image_id"
}

resource "aws_ecs_cluster" "this" {
  name = var.name
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.name}"
  retention_in_days = 7
}

# --- IAM: container instance role. The ECS agent and image pulls (ECR) run as
# this role on EC2 launch type. ---
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "instance" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name}-instance"
  role = aws_iam_role.instance.name
}

# --- IAM: task execution role (awslogs, secrets in the task definition) ---
data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- IAM: task role (what the app itself may call, e.g. SQS) ---
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "task" {
  count = length(var.task_role_policy_arns)

  role       = aws_iam_role.task.name
  policy_arn = var.task_role_policy_arns[count.index]
}

# --- Instances: security group, launch template, Auto Scaling group ---
resource "aws_security_group" "instance" {
  name        = "${var.name}-instance"
  description = "Security group for the ECS container instances"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_launch_template" "this" {
  name_prefix   = "${var.name}-"
  image_id      = data.aws_ssm_parameter.ecs_ami.value
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.this.name
  }

  vpc_security_group_ids = [aws_security_group.instance.id]

  user_data = base64encode(templatefile("${path.module}/user-data.sh", {
    cluster_name = var.name
  }))

  metadata_options {
    http_tokens = "required"
  }

  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "${var.name}-ecs" }
  }
}

resource "aws_autoscaling_group" "this" {
  name_prefix = "${var.name}-"
  min_size    = var.min_size
  max_size    = var.max_size
  # desired_capacity is deliberately NOT set: the ECS capacity provider's
  # managed scaling (below) owns this ASG's size. Pinning it here made every
  # apply fight the provider — during instance boot, pending tasks make the
  # provider scale out (one instance per evaluation), so the ASG sits at 2
  # while Terraform demanded exactly 1 healthy instance, and the scale-in
  # needed to shed the surplus is blocked by instance protection (required by
  # managed_termination_protection). With the attribute omitted, Terraform
  # neither writes nor waits on desired capacity and the provider converges
  # it (drain -> unprotect -> terminate). min/max remain the guardrails.
  vpc_zone_identifier   = var.subnet_ids
  protect_from_scale_in = true

  launch_template {
    id      = aws_launch_template.this.id
    version = aws_launch_template.this.latest_version
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }
}

resource "aws_ecs_capacity_provider" "this" {
  name = var.name

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.this.arn
    managed_draining               = "ENABLED"
    managed_termination_protection = "ENABLED"

    managed_scaling {
      maximum_scaling_step_size = 1
      minimum_scaling_step_size = 1
      status                    = "ENABLED"
      target_capacity           = 100
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = [aws_ecs_capacity_provider.this.name]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.this.name
    weight            = 1
  }
}

# --- Task: the app's own security group (task ENIs) + task definition ---
resource "aws_security_group" "app" {
  name        = "${var.name}-app"
  description = "Security group for ${var.name} task ENIs (awsvpc)"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "app"
      image     = var.container_image
      essential = true
      memory    = var.container_memory

      portMappings = [
        {
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        for k, v in var.environment : {
          name  = k
          value = v
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  name            = var.service_name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  # Terraform destroy must not wait for a graceful task drain: without this,
  # DeleteService on a service with RUNNING tasks errors and the provider
  # retries until its delete timeout. The ALB deregistration delay (30s) still
  # handles in-flight requests.
  force_delete = true

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.this.name
    weight            = 1
  }

  # Cloud Map service discovery: registers each task ENI's IP as an A record
  # (MULTIVALUE) so in-cluster callers reach the tasks by DNS name even as IPs
  # churn across deployments. The platform-UI nginx resolves this name per
  # request to proxy the API paths (the ALB fronts the UI, not this service).
  dynamic "service_registries" {
    for_each = var.service_registry_arn == null ? [] : [var.service_registry_arn]
    content {
      # No `port` here: the registry is an A-record (MULTIVALUE) service, and
      # ECS rejects a Port for A records (it's only meaningful for SRV).
      registry_arn = service_registries.value
    }
  }

  # Registers each task ENI's IP into the ALB target group — this is what lets
  # the load balancer actually reach the tasks. The control plane runs fully
  # private (null), with the ALB fronting the UI task below.
  dynamic "load_balancer" {
    for_each = var.target_group_arn == null ? [] : [var.target_group_arn]
    content {
      target_group_arn = load_balancer.value
      container_name   = "app"
      container_port   = var.container_port
    }
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.this,
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy_attachment.task,
  ]
}

# --- Platform UI: a second task definition + service in the SAME cluster ----
# Static SPA served by nginx, which also reverse-proxies the control-plane API
# paths (see app/frontend/nginx.conf). Disabled entirely while
# ui_container_image is empty, so callers that don't pass it see zero diff.
locals {
  ui_enabled = var.ui_container_image != ""
}

resource "aws_ecs_task_definition" "ui" {
  count = local.ui_enabled ? 1 : 0

  family                   = "${var.name}-ui"
  network_mode             = "awsvpc"
  requires_compatibilities = ["EC2"]
  # nginx makes no AWS calls, so the execution role doubles as the task role
  # (execution covers awslogs + the image pull — the only AWS the task does).
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.execution.arn

  container_definitions = jsonencode([
    {
      name              = "ui"
      image             = var.ui_container_image
      essential         = true
      memoryReservation = var.ui_container_memory_reservation

      portMappings = [
        {
          containerPort = var.ui_container_port
          protocol      = "tcp"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ui"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "ui" {
  count = local.ui_enabled ? 1 : 0

  name            = var.ui_service_name
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.ui[count.index].arn
  desired_count   = var.ui_desired_count
  force_delete    = true

  capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.this.name
    weight            = 1
  }

  # The UI tasks register into the ALB target group — this is what lets the
  # load balancer reach them (the ALB fronts the UI, not the control plane).
  load_balancer {
    target_group_arn = var.ui_target_group_arn
    container_name   = "ui"
    container_port   = var.ui_container_port
  }

  # nginx is up in under a second, but give the ALB health check a grace
  # period so the first probe of a fresh task doesn't flap it unhealthy.
  health_check_grace_period_seconds = 15

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.this,
    aws_iam_role_policy_attachment.execution,
  ]
}