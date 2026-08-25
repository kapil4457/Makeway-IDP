- Makeway maintains one centralized Terraform repository.

- Shared/platform infrastructure is managed from the Terraform root:
  - `terraform/main.tf`
  - Manages VPC, EKS and other shared platform resources.
  - Uses its own remote state key:
    `platform/terraform.tfstate`

- Reusable AWS capability modules live under:
  - `terraform/modules/`
  - `rds/`
  - `s3/`
  - `sqs/`
  - `sns/`
  - `cloudfront/`
  - `vpc/`
  - `eks/`
  - `remote_backend/`

- The Terraform state backend is created once as platform infrastructure.
  - One shared S3 bucket:
    `makeway-terraform-state`
  - Versioning enabled.
  - SSE-S3 encryption enabled.
  - Public access blocked.
  - Native S3 locking enabled with `use_lockfile = true`.
  - No DynamoDB locking.

- Each application/environment gets its own Terraform root.
  - Example:
    `terraform/app-infra/swiggy/prod/`
    `terraform/app-infra/swiggy/qa/`
    `terraform/app-infra/swiggy/uat/`

- Each application/environment root contains:
  - `main.tf`
  - `variables.tf`
  - `outputs.tf`
  - `backend.tf`

- Each application/environment has independent Terraform state.
  - `applications/swiggy/prod/terraform.tfstate`
  - `applications/swiggy/qa/terraform.tfstate`
  - `applications/swiggy/uat/terraform.tfstate`

- The application/environment `main.tf` does not define raw AWS resources.
  - It only calls approved Makeway modules.
  - Example:
    `rel_database → modules/rds`
    `storage → modules/s3`
    `messaging → modules/sqs / modules/sns`
    `storage + cloudfront=true → modules/cloudfront`

- Makeway generates the application/environment Terraform configuration from the developer's capability request.
  - Developer specifies the supported capability configuration.
  - Makeway translates that into module inputs.
  - AWS-specific implementation details use Makeway's low-cost defaults.

- Example:
  - `capacity`, `allocated_storage`, `name`, `username`, etc. are translated into the RDS module.
  - `region` determines which AWS provider/region is used.
  - `cloudfront=true` causes Makeway to instantiate the CloudFront module.
  - Queue names are passed to the SQS module.

- Terraform execution is isolated per application/environment.
  - Makeway runs Terraform from:
    `terraform/app-infra/<app>/<env>/`
  - Executes:
    `terraform init`
    `terraform plan`
    `terraform apply`
  - Only that application's environment state is affected.

- Application deletion follows the same boundary.
  - Makeway runs Terraform against that application's environment root.
  - Only that environment's resources are destroyed.
  - Shared VPC/EKS/platform infrastructure is untouched.

- Final Terraform architecture:

  `terraform/`
  → shared platform root + reusable modules

  `terraform/main.tf`
  → shared VPC/EKS/platform infrastructure

  `terraform/modules/*`
  → reusable capability/infrastructure modules

  `terraform/app-infra/<app>/<env>/`
  → independent application/environment Terraform root

  `S3 makeway-terraform-state`
  → centralized remote state storage

  `platform/terraform.tfstate`
  → shared platform state

  `applications/<app>/<env>/terraform.tfstate`
  → isolated application/environment state