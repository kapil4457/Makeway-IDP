variable "name" {
  description = "RDS instance identifier."
  type        = string
}

variable "engine" {
  description = "Type of RDS Instance. MYSQL, Aurora, Postgres"
  type        = string
}

variable "engine_version" {
  description = "PostgreSQL engine version."
  type        = string
  default     = "17"
}

variable "instance_class" {
  description = "RDS instance class selected by Makeway capacity mapping."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage" {
  description = "Allocated storage in GB."
  type        = number
  default     = 20

  validation {
    condition     = var.allocated_storage >= 20
    error_message = "allocated_storage must be at least 20 GB."
  }
}

variable "database_name" {
  description = "Initial database name."
  type        = string
}

variable "username" {
  description = "Database master username."
  type        = string
}

variable "password" {
  description = "Database master password."
  type        = string
  sensitive   = true
}

variable "db_subnet_group_name" {
  description = "Existing private DB subnet group."
  type        = string
}

variable "security_group_ids" {
  description = "Security groups allowed to access the database."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to the RDS instance."
  type        = map(string)
  default     = {}
}