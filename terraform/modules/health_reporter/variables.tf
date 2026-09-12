variable "name" {
  description = "Name of the ArgoCD health-reporter Lambda function."
  type        = string
  default     = "makeway-argocd-health-reporter"
}

variable "handler_source_dir" {
  description = "Directory containing the health reporter handler.py (zipped at the zip root, matching the step-1/step-2 packaging)."
  type        = string
}

variable "control_plane_url" {
  description = "Base URL of the control-plane internal API, reachable from this Lambda. The control plane is fully private, so this is the in-VPC Cloud Map URL (http://control-plane.makeway.internal:8000) — requires the VPC attachment below."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the Lambda's ENIs. The reporter must run in-VPC to reach the private control plane (and Cloud Map DNS); NAT provides its egress to the kube endpoint."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups for the Lambda's ENIs. Admitted to the control-plane task SG on the API port by the root's api_from_workers rule."
  type        = list(string)
}

variable "internal_api_key" {
  description = "Shared secret for the control-plane internal API (X-Internal-API-Key). Must match the control-plane's INTERNAL_API_KEY env var."
  type        = string
  sensitive   = true
}

variable "kube_api_endpoint" {
  description = "Base URL of the (exposed) cluster kube-apiserver the reporter reaches, e.g. https://k8s.makeway.dev."
  type        = string
}

variable "kube_ca_cert" {
  description = "Base64 CA bundle of the exposed cluster (KUBE_CA_CERT). Empty disables TLS verification — only for a local dev cluster behind a tunnel."
  type        = string
  default     = ""
  sensitive   = true
}

variable "kube_token" {
  description = "Bearer token for a 'makeway-worker' ServiceAccount on the cluster, scoped to list ArgoCD Applications in the argocd namespace."
  type        = string
  sensitive   = true
}

variable "argocd_namespace" {
  description = "Namespace ArgoCD (and the ApplicationSet) lives in."
  type        = string
  default     = "argocd"
}

variable "schedule_expression" {
  description = "EventBridge rate/cron expression for the health sweep, e.g. 'rate(5 minutes)'."
  type        = string
  default     = "rate(5 minutes)"
}

variable "timeout_seconds" {
  description = "Lambda timeout (one sweep over all ArgoCD Applications, each reporting per-service DeploymentSetup rows)."
  type        = number
  default     = 120
}

variable "memory_mb" {
  description = "Lambda memory (stdlib-only + boto3 — modest footprint)."
  type        = number
  default     = 256
}