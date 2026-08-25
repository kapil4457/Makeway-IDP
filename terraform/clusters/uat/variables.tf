variable "region" {
  description = "AWS region."
  type        = string
  default     = "ap-south-1"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "makeway-uat"
}

variable "cluster_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.33"
}

variable "node_groups" {
  description = "EKS managed node groups."

  type = map(object({
    instance_types = list(string)
    capacity_type  = string

    scaling_config = object({
      desired_size = number
      max_size     = number
      min_size     = number
    })
  }))

  default = {
    default = {
      instance_types = ["t3.small"]
      capacity_type  = "ON_DEMAND"

      scaling_config = {
        desired_size = 1
        min_size     = 1
        max_size     = 2
      }
    }
  }
}