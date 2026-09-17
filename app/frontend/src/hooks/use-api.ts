/**
 * React Query hooks over the typed endpoints. Query keys follow the plan:
 * ["me"], ["apps"], ["app", appName], ["clusters"]. No optimistic updates —
 * mutations invalidate and refetch, which keeps the UI honest with an
 * eventually-consistent backend.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from '@tanstack/react-query'

import * as api from '@/lib/api/endpoints'
import { ApiError } from '@/lib/api/client'
import type { AppConfig, ClusterRegisterRequest, CurrentUser, EnvConfig, Environment } from '@/lib/api/types'
import { getSessionSnapshot } from '@/lib/auth/session'

const fiveMinutes = 5 * 60 * 1000

// --- queries ---------------------------------------------------------------

export function useMe(options: Partial<UseQueryOptions<CurrentUser, ApiError>> = {}) {
  return useQuery({
    queryKey: ['me'],
    queryFn: api.getMe,
    enabled: getSessionSnapshot() !== null,
    staleTime: fiveMinutes,
    retry: false,
    ...options,
  })
}

export function useApps() {
  return useQuery({
    queryKey: ['apps'],
    queryFn: api.listApps,
    enabled: getSessionSnapshot() !== null,
    staleTime: 30_000,
  })
}

export function useAppStatus(appName: string) {
  return useQuery({
    queryKey: ['app', appName],
    queryFn: () => api.getAppStatus(appName),
    enabled: getSessionSnapshot() !== null && appName.length > 0,
    staleTime: 5_000,
    // Live polling while a reconcile is still running; the detail page also
    // nudges this with refetchInterval — see app-detail.tsx.
  })
}

export function useClusters() {
  return useQuery({
    queryKey: ['clusters'],
    queryFn: api.listClusters,
    enabled: getSessionSnapshot() !== null,
    staleTime: 30_000,
  })
}

// --- mutations -------------------------------------------------------------

function useInvalidator() {
  const queryClient = useQueryClient()
  return (keys: readonly unknown[][]) => {
    for (const key of keys) queryClient.invalidateQueries({ queryKey: key })
  }
}

export function useCreateApp() {
  const invalidate = useInvalidator()
  return useMutation({
    mutationFn: (config: AppConfig) => api.createApp(config),
    onSuccess: () => invalidate([['apps']]),
  })
}

export function useUpdateApp(appName: string) {
  const invalidate = useInvalidator()
  return useMutation({
    mutationFn: (vars: { updates: EnvConfig[]; confirm: boolean }) =>
      api.updateApp(appName, vars.updates, { confirm: vars.confirm }),
    onSuccess: () => invalidate([['apps'], ['app', appName]]),
  })
}

export function useDeleteAppEnv(appName: string) {
  const invalidate = useInvalidator()
  return useMutation({
    mutationFn: (vars: { env: Environment; confirm: boolean }) =>
      api.deleteAppEnv(appName, vars.env, { confirm: vars.confirm }),
    onSuccess: () => invalidate([['apps'], ['app', appName]]),
  })
}

export function useDeleteApp(appName: string) {
  const invalidate = useInvalidator()
  return useMutation({
    mutationFn: (vars: { confirm: boolean }) => api.deleteApp(appName, { confirm: vars.confirm }),
    // The app row is gone — only the list is left to refresh; the detail
    // query is abandoned (the dialog navigates away on success).
    onSuccess: () => invalidate([['apps']]),
  })
}

export function useRegisterCluster() {
  const invalidate = useInvalidator()
  return useMutation({
    mutationFn: (request: ClusterRegisterRequest) => api.registerCluster(request),
    onSuccess: () => invalidate([['clusters']]),
  })
}
