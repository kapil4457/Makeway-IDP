resource "aws_db_instance" "this" {
  identifier = var.name

  engine         = var.engine
  engine_version = var.engine_version

  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_type      = "gp3"

  db_name  = var.database_name
  username = var.username
  password = var.password

  port = 5432

  db_subnet_group_name   = var.db_subnet_group_name
  vpc_security_group_ids = var.security_group_ids

  publicly_accessible = false

  storage_encrypted = true

  backup_retention_period = 1

  skip_final_snapshot = true

  tags = var.tags
}