/**
 * App detail — live reconcile view. Polls /app/{name}/status every 5s while
 * the latest request (or any capability) is still pending/in_progress, fires
 * exactly one terminal toast per request id, and renders per-environment
 * tabs: services, capabilities, connectivity edges, and env-level errors.
 */

import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Boxes,
  Cable,
  ExternalLink,
  Layers,
  Loader2,
  Pencil,
  RefreshCw,
  Server,
  ShieldAlert,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { DeleteAppDialog } from '@/components/apps/delete-app-dialog'
import { DeleteEnvDialog } from '@/components/apps/delete-env-dialog'
import { UpdateAppSheet } from '@/components/apps/update-app-sheet'
import { CapabilityCard, ConnectivityRow, DataSourceHint, ServiceCard } from '@/components/status/env-sections'
import { ReconcileChip, StatusChip } from '@/components/status/status-chip'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAppStatus } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import { isReconciling } from '@/lib/api/types'

const POLL_MS = 5_000

/** Anything not still in flight is terminal — success or failure alike. */
function isTerminal(status: string | null | undefined): boolean {
  return status === 'success' || status === 'failed' || status === 'partially_failed'
}

function LatestRequestStrip({ request }: { request: NonNullable<import('@/lib/api/types').AppStatusResponse['request']> }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border bg-card px-4 py-3"
    >
      <div className="flex items-center gap-2 text-sm">
        <span className="text-muted-foreground">Latest request</span>
        <span className="font-mono text-xs text-muted-foreground">#{request.requestId}</span>
      </div>
      <ReconcileChip status={request.requestStatus} />
      {request.jobStep && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Server className="size-3.5" />
          {request.jobStep.replaceAll('_', ' ')}
          {request.jobStatus && <ReconcileChip status={request.jobStatus} />}
        </div>
      )}
      {request.executionArn && (
        <code className="max-w-64 truncate rounded-md bg-muted/60 px-2 py-0.5 font-mono text-[11px] text-muted-foreground" title={request.executionArn}>
          {request.executionArn}
        </code>
      )}
      {request.error && <p className="w-full text-sm text-destructive">{request.error}</p>}
    </motion.div>
  )
}

function EnvErrors({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null
  return (
    <div className="space-y-2">
      {errors.map((error, index) => (
        <div
          key={index}
          role="alert"
          className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400"
        >
          {error}
        </div>
      ))}
    </div>
  )
}

function SectionHeading({ icon, label, count }: { icon: React.ReactNode; label: string; count: number }) {
  return (
    <h3 className="flex items-center gap-2 text-sm font-medium">
      {icon}
      {label}
      <span className="rounded-full bg-muted px-1.5 text-xs text-muted-foreground">{count}</span>
    </h3>
  )
}

function EnvTab({ status }: { status: import('@/lib/api/types').EnvStatus }) {
  const serviceNames = new Map(status.services.map((svc) => [svc.svcId, svc.svcName]))
  const capabilityNames = new Map(
    status.capabilities.map((capability) => [
      capability.capabilityId,
      { capabilityType: capability.capabilityType, name: capability.name },
    ]),
  )

  return (
    <div className="space-y-6">
      <EnvErrors errors={status.errors} />

      <div className="space-y-3">
        <SectionHeading icon={<Server className="size-3.5 text-muted-foreground" />} label="Services" count={status.services.length} />
        {status.services.length === 0 ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
            No services in this environment.
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {status.services.map((service) => (
              <ServiceCard key={service.svcId} service={service} />
            ))}
          </div>
        )}
      </div>

      <div className="space-y-3">
        <SectionHeading icon={<Layers className="size-3.5 text-muted-foreground" />} label="Capabilities" count={status.capabilities.length} />
        {status.capabilities.length === 0 ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
            No capabilities provisioned here.
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {status.capabilities.map((capability) => (
              <CapabilityCard key={capability.capabilityId} capability={capability} />
            ))}
          </div>
        )}
      </div>

      <div className="space-y-3">
        <SectionHeading icon={<Cable className="size-3.5 text-muted-foreground" />} label="Connectivity" count={status.connectivity.length} />
        {status.connectivity.length === 0 ? (
          <p className="rounded-lg border border-dashed px-3 py-4 text-center text-sm text-muted-foreground">
            No service↔capability bindings in this environment.
          </p>
        ) : (
          <div className="space-y-2">
            {status.connectivity.map((edge, index) => (
              <ConnectivityRow key={`${edge.serviceSvcId}-${edge.capabilityId}-${index}`} edge={edge} serviceNames={serviceNames} capabilityNames={capabilityNames} />
            ))}
          </div>
        )}
        <DataSourceHint />
      </div>
    </div>
  )
}

export function AppDetailPage() {
  const { appName = '' } = useParams()
  const appStatus = useAppStatus(appName)

  // Poll only while the reconcile is still in flight.
  const data = appStatus.data
  const reconcilingNow =
    isReconciling(data?.request?.requestStatus) ||
    (data?.envStatuses.some((env) => env.capabilities.some((capability) => isReconciling(capability.status))) ?? false)
  useEffect(() => {
    if (!reconcilingNow) return
    const timer = window.setInterval(() => void appStatus.refetch(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [reconcilingNow, appStatus])

  // One terminal toast per request id.
  const lastToastedRequest = useRef<number | null>(null)
  useEffect(() => {
    const request = appStatus.data?.request
    if (!request || !isTerminal(request.requestStatus)) return
    if (lastToastedRequest.current === request.requestId) return
    lastToastedRequest.current = request.requestId
    if (request.requestStatus === 'success') {
      toast.success(`Request #${request.requestId} completed`, {
        description: `${appName} is fully reconciled.`,
      })
    } else {
      toast.error(`Request #${request.requestId} ${request.requestStatus.replaceAll('_', ' ')}`, {
        description: request.error ?? 'Check the environment tabs for details.',
      })
    }
  }, [appStatus.data, appName])

  const [updateOpen, setUpdateOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [purgeOpen, setPurgeOpen] = useState(false)

  // --- error / loading states ----------------------------------------------

  if (appStatus.isPending) {
    return (
      <div className="mx-auto max-w-5xl space-y-6 p-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-14 w-full rounded-xl" />
        <Skeleton className="h-9 w-72" />
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-28 rounded-xl" />
          <Skeleton className="h-28 rounded-xl" />
        </div>
      </div>
    )
  }

  if (appStatus.isError) {
    const error = appStatus.error
    const forbidden = error instanceof ApiError && error.status === 403
    const missing = error instanceof ApiError && error.status === 404
    return (
      <div className="mx-auto max-w-5xl p-6">
        <Card className={forbidden || missing ? '' : 'border-destructive/30'}>
          <CardHeader className="items-start gap-2">
            <CardTitle className={forbidden || missing ? '' : 'text-destructive'}>
              {forbidden ? (
                <span className="flex items-center gap-2">
                  <ShieldAlert className="size-4.5" /> You don’t have access to this app
                </span>
              ) : missing ? (
                'App not found'
              ) : (
                'Couldn’t load app status'
              )}
            </CardTitle>
            <CardDescription>
              {forbidden
                ? 'It belongs to a team you’re not an active member of.'
                : missing
                  ? `No app named “${appName}” is visible to you.`
                  : error.message}
            </CardDescription>
            <div className="mt-2 flex gap-2">
              {!forbidden && !missing && (
                <Button variant="outline" size="sm" onClick={() => void appStatus.refetch()}>
                  <RefreshCw /> Retry
                </Button>
              )}
              <Button variant="ghost" size="sm" asChild>
                <Link to="/apps">
                  <ArrowLeft /> All apps
                </Link>
              </Button>
            </div>
          </CardHeader>
        </Card>
      </div>
    )
  }

  const status = data
  if (!status) return null

  const hasEnvs = status.envStatuses.length > 0
  const reconciling = isReconciling(status.request?.requestStatus)

  // --- success --------------------------------------------------------------

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <Button variant="ghost" size="sm" className="-ml-2 h-7 text-muted-foreground" asChild>
            <Link to="/apps">
              <ArrowLeft /> All apps
            </Link>
          </Button>
          <h1 className="flex items-center gap-2 font-heading text-xl font-semibold tracking-tight">
            <Boxes className="size-5 text-muted-foreground" />
            {status.appName}
            {status.teamName && <StatusChip tone="info">{status.teamName}</StatusChip>}
          </h1>
          {status.appRepoUrl && (
            <a
              href={status.appRepoUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ExternalLink className="size-3.5" /> Repository
            </a>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setUpdateOpen(true)}>
            <Pencil /> Update
          </Button>
          {hasEnvs ? (
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 /> Remove env
            </Button>
          ) : (
            <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={() => setPurgeOpen(true)}>
              <Trash2 /> Delete app
            </Button>
          )}
        </div>
      </div>

      {status.request && <LatestRequestStrip request={status.request} />}

      {reconciling && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Reconciling — this page refreshes every {POLL_MS / 1000}s until the request settles.
        </p>
      )}

      {hasEnvs ? (
        <Tabs defaultValue={status.envStatuses[0].env}>
          <TabsList className="w-fit">
            {status.envStatuses.map((env) => {
              const envBusy = env.capabilities.some((capability) => isReconciling(capability.status))
              return (
                <TabsTrigger key={env.env} value={env.env} className="gap-2">
                  {env.env}
                  {envBusy && <Loader2 className="size-3 animate-spin" />}
                </TabsTrigger>
              )
            })}
          </TabsList>
          {status.envStatuses.map((env) => (
            <TabsContent key={env.env} value={env.env} className="mt-4">
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
                <EnvTab status={env} />
              </motion.div>
            </TabsContent>
          ))}
        </Tabs>
      ) : (
        <div className="grid place-items-center rounded-xl border border-dashed py-16 text-center">
          <p className="text-sm text-muted-foreground">
            No environments yet — use <strong>Update</strong> to build one on a registered
            environment, or <strong>Delete app</strong> to purge the record and free the name.
          </p>
        </div>
      )}

      <UpdateAppSheet appName={appName} status={status} open={updateOpen} onOpenChange={setUpdateOpen} />
      <DeleteEnvDialog appName={appName} status={status} open={deleteOpen} onOpenChange={setDeleteOpen} />
      <DeleteAppDialog appName={appName} open={purgeOpen} onOpenChange={setPurgeOpen} />
    </div>
  )
}
