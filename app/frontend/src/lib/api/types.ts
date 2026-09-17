/**
 * Wire-format types mirroring the control plane's Pydantic DTOs field-for-field.
 *
 * The backend has no global case transformer (no alias generator), so each
 * endpoint's casing is whatever its fields say:
 *   - app bodies are snake_case   (app_name, env_config, service_type, …)
 *   - cluster body is camelCase   (clusterName, kubeApiEndpoint, …)
 *   - login response is snake_case (access_token, token_type)
 *   - status/summary responses are camelCase
 * Form field names intentionally mirror the wire names so 422 `details[].field`
 * paths (e.g. `body.env_config.0.services.1.service_name`) map straight onto
 * react-hook-form paths after stripping the `body.` prefix.
 */

// ---------------------------------------------------------------------------
// Enums (wire values — all `str`-based enums on the backend)
// ---------------------------------------------------------------------------

export type Environment = 'qa' | 'uat' | 'prod'
export type ServiceType = 'spring-boot' | 'fast-api' | 'node-js'
export type CapabilityType = 'rel_database' | 'storage' | 'messaging'

export type RequestStatus = 'pending' | 'in_progress' | 'success' | 'failed' | 'partially_failed'
export type JobStatus = 'pending' | 'in_progress' | 'success' | 'failed'
export type JobStep = 'create_project' | 'provision_infra' | 'argocd_setup'
export type ServiceHealth = 'unknown' | 'healthy' | 'degraded' | 'unhealthy'
export type ConnectivityStatus = 'unknown' | 'configured' | 'healthy' | 'degraded' | 'failed'
export type DataSource = 'persisted' | 'realtime'

/** `pending`/`in_progress` states that keep the app-detail page polling. */
export function isReconciling(status: string | null | undefined): boolean {
  return status === 'pending' || status === 'in_progress'
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface LoginRequest {
  email: string
  password: string
}

/** snake_case on the wire (dto/response/login.py). */
export interface LoginResponse {
  access_token: string
  token_type: string
}

export interface UserTeamMembership {
  teamId: number
  teamName: string
  role: string
}

export interface CurrentUser {
  userId: string
  email: string
  teams: UserTeamMembership[]
}

// ---------------------------------------------------------------------------
// App configuration (request bodies — snake_case)
// ---------------------------------------------------------------------------

export interface DatabaseConfig {
  type: 'rel_database'
  name: string
  username?: string | null
  /** Capacity tier 1–10. */
  capacity?: number | null
}

export interface S3Config {
  region: string
  cloudfront?: boolean
}

export interface StorageConfig {
  type: 'storage'
  s3?: S3Config | null
}

export interface QueueConfig {
  name?: string
}

export interface MessagingConfig {
  type: 'messaging'
  notification?: boolean
  queue?: QueueConfig[]
}

/** Discriminated union on `config.type` (dto/configs/capability.py). */
export type CapabilityConfig = DatabaseConfig | StorageConfig | MessagingConfig

export interface ServiceConfig {
  service_type: ServiceType
  service_name?: string | null
}

export interface CapabilityInput {
  config: CapabilityConfig
  /** Service names granted access; empty = all services in the environment. */
  access_to: string[]
}

/** Replaces one capability's access bindings for one environment
 * (dto/configs/env_config.py CapabilityAccessPatch). access_to is the FULL
 * desired list — bindings missing from it are torn down. */
export interface CapabilityAccessPatch {
  capability_id: number
  access_to: string[]
}

export interface EnvConfig {
  env: Environment
  services?: ServiceConfig[]
  capabilities?: CapabilityInput[]
  /** Update flow only — creation rejects removals. */
  remove_services?: string[]
  remove_capabilities?: string[]
  /** Update flow only — replaces existing capabilities' access bindings. */
  update_access?: CapabilityAccessPatch[]
}

export interface AppConfig {
  app_name: string
  team_name: string
  env_config: EnvConfig[]
}

/** snake_case on the wire (dto/response/create_app.py). */
export interface AppCreateResponse {
  message: string
  request_id: number
  job_id: number
  status: string
}

/** camelCase on the wire (dto/response/app_purge.py). */
export interface AppPurgeResponse {
  appName: string
  purged: Record<string, number>
}

// ---------------------------------------------------------------------------
// App status (response — camelCase, dto/response/app_status.py)
// ---------------------------------------------------------------------------

export interface ClusterStatus {
  clusterId: number
  clusterName: string
  environment: string
}

export interface DeploymentStatusInfo {
  status?: string | null
  argocdAppName?: string | null
  lastSyncedAt?: string | null
  errorMessage?: string | null
}

export interface ServiceStatus {
  svcId: number
  svcName: string
  serviceType: string
  health: ServiceHealth
  healthSource: DataSource
  lastUpdatedAt?: string | null
  deployment?: DeploymentStatusInfo | null
  error?: string | null
}

export interface InfraStatus {
  config?: Record<string, unknown> | null
  outputRef?: Record<string, unknown> | null
  secretRef?: string | null
}

export interface CapabilityStatusInfo {
  capabilityId: number
  capabilityType: string
  name?: string | null
  status: string
  statusSource: DataSource
  infra?: InfraStatus | null
  error?: string | null
}

export interface ConnectivityStatusInfo {
  serviceSvcId: number
  capabilityId: number
  accessConfigured: boolean
  status: ConnectivityStatus
  source: DataSource
  error?: string | null
}

export interface EnvStatus {
  env: Environment
  cluster: ClusterStatus
  services: ServiceStatus[]
  capabilities: CapabilityStatusInfo[]
  connectivity: ConnectivityStatusInfo[]
  errors: string[]
}

export interface RequestStatusBrief {
  requestId: number
  requestStatus: RequestStatus
  jobId?: number | null
  jobStep?: JobStep | null
  jobStatus?: JobStatus | null
  executionArn?: string | null
  error?: string | null
}

export interface AppStatusResponse {
  appId: number
  appName: string
  teamName?: string | null
  appRepoUrl?: string | null
  gitOpsPath?: string | null
  request?: RequestStatusBrief | null
  envStatuses: EnvStatus[]
}

// ---------------------------------------------------------------------------
// App summary (GET /app — camelCase, dto/response/app_summary.py)
// ---------------------------------------------------------------------------

export interface AppSummary {
  appId: number
  appName: string
  appRepoUrl?: string | null
  gitOpsPath?: string | null
  teamId: number
  teamName?: string | null
  createdBy: string
  createdAt: string
  modifiedBy: string
  modifiedAt: string
}

// ---------------------------------------------------------------------------
// Clusters (camelCase body, snake_case register response)
// ---------------------------------------------------------------------------

export interface ClusterRegisterRequest {
  clusterName: string
  kubeApiEndpoint: string
  environment: Environment
  kubeToken?: string
  kubeCaCert?: string
}

/** snake_case on the wire (dto/response/register_cluster.py). */
export interface ClusterRegisterResponse {
  message: string
  cluster_name: string
}

/** camelCase on the wire (dto/request/update_cluster.py). */
export interface ClusterUpdateRequest {
  clusterName?: string
  kubeApiEndpoint?: string
  kubeToken?: string
  kubeCaCert?: string
}

/** camelCase on the wire (dto/response/delete_cluster.py). */
export interface ClusterDeleteResponse {
  clusterName: string
  environment: Environment
}

export interface ClusterSummary {
  clusterId: number
  clusterName: string
  kubeApiEndpoint: string
  environment: Environment
  hasToken: boolean
  hasCaCert: boolean
  createdBy: string
  createdAt: string
  modifiedBy: string
  modifiedAt: string
}

// ---------------------------------------------------------------------------
// Error envelope (core/exception_handlers.py)
// ---------------------------------------------------------------------------

export interface ValidationErrorDetail {
  field: string
  message: string
  code: string
}

export interface ErrorEnvelope {
  success: false
  error: {
    code: string
    message: string
    details: ValidationErrorDetail[] | Record<string, unknown>[]
  }
}
