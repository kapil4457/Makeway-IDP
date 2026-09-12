/**
 * Cluster management — list registered clusters and register new ones.
 * Credential values are never returned by the API; only presence flags.
 */

import { motion } from 'framer-motion'
import { KeyRound, RefreshCw, Server, ShieldCheck } from 'lucide-react'

import { RegisterClusterSheet } from '@/components/clusters/register-cluster-sheet'
import { EnvironmentChip } from '@/components/status/env-chip'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useClusters } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'

function PresenceBadge({ present, label, icon }: { present: boolean; label: string; icon: React.ReactNode }) {
  return (
    <Badge variant={present ? 'secondary' : 'outline'} className="gap-1 font-normal text-muted-foreground">
      {icon}
      {label} {present ? '✓' : '—'}
    </Badge>
  )
}

export function ClustersPage() {
  const { data: clusters, isPending, isError, error, refetch } = useClusters()

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-semibold tracking-tight">Clusters</h1>
          <p className="text-sm text-muted-foreground">
            Kubernetes clusters the platform deploys into — one per environment.
          </p>
        </div>
        <RegisterClusterSheet />
      </div>

      {isPending && (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-16 rounded-xl" />
          ))}
        </div>
      )}

      {isError && (
        <Card className="border-destructive/30">
          <CardHeader className="items-start gap-2">
            <CardTitle className="text-destructive">Couldn’t load clusters</CardTitle>
            <CardDescription>{(error as ApiError).message}</CardDescription>
            <Button variant="outline" size="sm" className="mt-1 w-fit" onClick={() => refetch()}>
              <RefreshCw /> Retry
            </Button>
          </CardHeader>
        </Card>
      )}

      {clusters &&
        (clusters.length === 0 ? (
          <div className="grid place-items-center rounded-xl border border-dashed py-20 text-center">
            <div className="flex max-w-sm flex-col items-center gap-2">
              <span className="grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground">
                <Server className="size-5" />
              </span>
              <p className="font-medium">No clusters registered</p>
              <p className="text-sm text-muted-foreground">
                Apps can only be created once a cluster is registered for their target
                environment (qa, uat, or prod).
              </p>
              <div className="mt-2">
                <RegisterClusterSheet />
              </div>
            </div>
          </div>
        ) : (
          <motion.div
            className="space-y-3"
            initial="hidden"
            animate="show"
            variants={{ show: { transition: { staggerChildren: 0.04 } } }}
          >
            {clusters.map((cluster) => (
              <motion.div
                key={cluster.clusterId}
                variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0 } }}
                whileHover={{ x: 2 }}
                transition={{ type: 'spring', stiffness: 320, damping: 28 }}
              >
                <Card className="py-4">
                  <CardHeader className="flex-row items-center justify-between gap-3 space-y-0 px-4">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                      <CardTitle className="text-sm">{cluster.clusterName}</CardTitle>
                      <EnvironmentChip environment={cluster.environment} />
                      <a
                        href={cluster.kubeApiEndpoint}
                        target="_blank"
                        rel="noreferrer"
                        className="max-w-72 truncate font-mono text-xs text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {cluster.kubeApiEndpoint}
                      </a>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <PresenceBadge present={cluster.hasToken} label="Token" icon={<KeyRound className="size-3" />} />
                      <PresenceBadge present={cluster.hasCaCert} label="CA" icon={<ShieldCheck className="size-3" />} />
                    </div>
                  </CardHeader>
                </Card>
              </motion.div>
            ))}
          </motion.div>
        ))}
    </div>
  )
}