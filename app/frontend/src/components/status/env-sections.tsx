/**
 * Cards rendering one environment's reconcile state: services, capabilities,
 * and the connectivity edges between them. Shapes mirror
 * dto/response/app_status.py. `persisted` values are labelled "last known";
 * `realtime` ones came from a live ArgoCD/probe check.
 */

import { ChevronDown, Cloud, Database, Info, Layers, MessageSquare, Radar } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  ConnectivityChip,
  HealthChip,
  ReconcileChip,
  StatusChip,
} from '@/components/status/status-chip'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type {
  CapabilityStatusInfo,
  ConnectivityStatusInfo,
  DataSource,
  ServiceStatus,
} from '@/lib/api/types'
import { cn } from '@/lib/utils'

const CAPABILITY_ICONS: Record<string, React.ReactNode> = {
  rel_database: <Database className="size-4" />,
  storage: <Cloud className="size-4" />,
  messaging: <MessageSquare className="size-4" />,
}

function SourceBadge({ source }: { source: DataSource }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-help items-center gap-1 text-[11px] text-muted-foreground">
          {source === 'realtime' ? <Radar className="size-3" /> : <Layers className="size-3" />}
          {source === 'realtime' ? 'live' : 'last known'}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">
        {source === 'realtime'
          ? 'Filled by a live cluster / ArgoCD check'
          : 'Last state recorded by the reconcile workers'}
      </TooltipContent>
    </Tooltip>
  )
}

function SourceDot({ source, label }: { source: DataSource; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <SourceBadge source={source} />
      {label && <span>· {label}</span>}
    </span>
  )
}

export function ServiceCard({ service }: { service: ServiceStatus }) {
  const [expanded, setExpanded] = useState(false)
  const deployment = service.deployment

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="gap-1.5 px-4">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <span className="font-mono text-xs text-muted-foreground">{service.serviceType}</span>
            {service.svcName}
          </CardTitle>
          <div className="flex items-center gap-2">
            <HealthChip health={service.health} />
            <SourceBadge source={service.healthSource} />
          </div>
        </div>
        {service.error && (
          <CardDescription className="text-destructive">{service.error}</CardDescription>
        )}
      </CardHeader>

      {deployment && (
        <CardContent className="px-4 pt-0">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex w-full items-center gap-1.5 rounded-md text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronDown
              className={cn('size-3.5 transition-transform', expanded && 'rotate-180')}
            />
            ArgoCD rollout · {deployment.argocdAppName ?? '—'}
            {deployment.status && (
              <StatusChip tone={deployment.status === 'success' ? 'success' : deployment.status === 'failed' ? 'failure' : 'progress'}>
                {deployment.status}
              </StatusChip>
            )}
          </button>
          {expanded && (
            <dl className="mt-2 space-y-1 rounded-lg bg-muted/50 p-3 text-xs">
              {deployment.lastSyncedAt && (
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Last synced</dt>
                  <dd className="font-mono">{new Date(deployment.lastSyncedAt).toLocaleString()}</dd>
                </div>
              )}
              {deployment.errorMessage && (
                <div className="text-destructive">{deployment.errorMessage}</div>
              )}
            </dl>
          )}
        </CardContent>
      )}
    </Card>
  )
}

export function CapabilityCard({ capability }: { capability: CapabilityStatusInfo }) {
  const [expanded, setExpanded] = useState(false)
  const hasInfra = capability.infra !== null && capability.infra !== undefined

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="gap-1.5 px-4">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <span className="grid size-7 place-items-center rounded-md bg-muted text-muted-foreground">
              {CAPABILITY_ICONS[capability.capabilityType] ?? <Layers className="size-4" />}
            </span>
            <span className="font-mono text-xs text-muted-foreground">{capability.capabilityType}</span>
            {capability.name}
          </CardTitle>
          <div className="flex items-center gap-2">
            <ReconcileChip status={capability.status} />
            <SourceDot source={capability.statusSource} label="" />
          </div>
        </div>
        {capability.error && (
          <CardDescription className="text-destructive">{capability.error}</CardDescription>
        )}
      </CardHeader>

      {hasInfra && (
        <CardContent className="px-4 pt-0">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex w-full items-center gap-1.5 rounded-md text-left text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronDown
              className={cn('size-3.5 transition-transform', expanded && 'rotate-180')}
            />
            Provisioned infra
          </button>
          {expanded && capability.infra && (
            <div className="mt-2 space-y-2 rounded-lg bg-muted/50 p-3 text-xs">
              {capability.infra.config && (
                <div>
                  <p className="mb-1 font-medium text-muted-foreground">Desired config</p>
                  <pre className="overflow-x-auto rounded-md bg-background/80 p-2 font-mono text-[11px]">
                    {JSON.stringify(capability.infra.config, null, 2)}
                  </pre>
                </div>
              )}
              {capability.infra.outputRef && (
                <div>
                  <p className="mb-1 font-medium text-muted-foreground">Outputs</p>
                  <pre className="overflow-x-auto rounded-md bg-background/80 p-2 font-mono text-[11px]">
                    {JSON.stringify(capability.infra.outputRef, null, 2)}
                  </pre>
                </div>
              )}
              {capability.infra.secretRef && (
                <div className="flex items-center gap-1.5">
                  <p className="text-muted-foreground">Credentials:</p>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {capability.infra.secretRef}
                  </Badge>
                </div>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}

export function ConnectivityRow({
  edge,
  serviceNames,
  capabilityNames,
}: {
  edge: ConnectivityStatusInfo
  serviceNames: Map<number, string>
  capabilityNames?: Map<number, { capabilityType: string; name?: string | null }>
}) {
  const capability = capabilityNames?.get(edge.capabilityId)

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card/50 px-3 py-2 text-sm">
      <span className="font-medium">{serviceNames.get(edge.serviceSvcId) ?? `svc ${edge.serviceSvcId}`}</span>
      <span className="text-muted-foreground">→</span>
      {capability ? (
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-xs text-muted-foreground">{capability.capabilityType}</span>
          <span className="font-medium">{capability.name ?? `capability ${edge.capabilityId}`}</span>
        </span>
      ) : (
        <span className="font-medium">capability {edge.capabilityId}</span>
      )}
      {edge.accessConfigured ? (
        <ConnectivityChip status={edge.status} />
      ) : (
        <StatusChip tone="neutral">not bound</StatusChip>
      )}
      {edge.error && <span className="text-xs text-destructive">{edge.error}</span>}
    </div>
  )
}

export function DataSourceHint() {
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <Info className="size-3.5" />
      “last known” values come from persisted reconcile state; “live” values come from
      real-time cluster checks.
    </p>
  )
}
