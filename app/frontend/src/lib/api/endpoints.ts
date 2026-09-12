/**
 * Typed endpoint functions — one thin function per control-plane route the
 * dashboard uses. Wire casing follows each DTO exactly (see types.ts).
 */

import { apiFetch, apiSend } from './client'
import type {
  AppCreateResponse,
  AppStatusResponse,
  AppSummary,
  AppConfig,
  ClusterRegisterRequest,
  ClusterRegisterResponse,
  ClusterSummary,
  CurrentUser,
  EnvConfig,
  Environment,
  LoginRequest,
  LoginResponse,
} from './types'

// --- User Management (/auth) ---------------------------------------------

export function login(request: LoginRequest): Promise<LoginResponse> {
  // handleAuth=false: the 401 here means wrong credentials, not an expired
  // session — the login page shows it inline instead of redirecting.
  return apiSend<LoginResponse>('/auth/login', { method: 'POST', body: request, handleAuth: false })
}

export function getMe(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>('/auth/me')
}

// --- App Management (/app) ------------------------------------------------

export function listApps(): Promise<AppSummary[]> {
  return apiFetch<AppSummary[]>('/app')
}

export function getAppStatus(appName: string): Promise<AppStatusResponse> {
  return apiFetch<AppStatusResponse>(`/app/${encodeURIComponent(appName)}/status`)
}

export function createApp(config: AppConfig): Promise<AppCreateResponse> {
  return apiSend<AppCreateResponse>('/app/create', { method: 'POST', body: config, idempotencyKey: true })
}

export function updateApp(
  appName: string,
  updates: EnvConfig[],
  options: { confirm?: boolean } = {},
): Promise<AppCreateResponse> {
  const confirm = options.confirm ? '?confirm=true' : ''
  return apiSend<AppCreateResponse>(`/app/${encodeURIComponent(appName)}/update${confirm}`, {
    method: 'POST',
    body: updates,
    idempotencyKey: true,
  })
}

export function deleteAppEnv(
  appName: string,
  env: Environment,
  options: { confirm?: boolean } = {},
): Promise<AppCreateResponse> {
  const confirm = options.confirm ? '?confirm=true' : ''
  return apiSend<AppCreateResponse>(
    `/app/${encodeURIComponent(appName)}/envs/${env}${confirm}`,
    { method: 'DELETE', idempotencyKey: true },
  )
}

// --- Cluster Management (/cluster) ----------------------------------------

export function listClusters(): Promise<ClusterSummary[]> {
  return apiFetch<ClusterSummary[]>('/cluster')
}

export function registerCluster(request: ClusterRegisterRequest): Promise<ClusterRegisterResponse> {
  return apiSend<ClusterRegisterResponse>('/cluster/register', { method: 'POST', body: request })
}
