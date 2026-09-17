/**
 * Typed-confirmation dialog for deregistering a cluster. The backend refuses
 * while any service row still deploys to it, so the destructive path is
 * guarded twice; on success the environment is freed for re-registration.
 * Nothing on the actual Kubernetes cluster is touched — only the platform's
 * record (and its stored credentials) is removed.
 */

import { useEffect, useState } from 'react'
import { Loader2, Trash2, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDeleteCluster } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import type { ClusterSummary } from '@/lib/api/types'

export function DeleteClusterDialog({ cluster }: { cluster: ClusterSummary }) {
  const deleteCluster = useDeleteCluster()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')

  useEffect(() => {
    setTyped('')
  }, [open])

  const ready = typed.trim() === cluster.clusterName

  const submit = async () => {
    try {
      const response = await deleteCluster.mutateAsync(cluster.clusterId)
      toast.success(`${response.clusterName} deregistered`, {
        description: `Environment ${response.environment} is free for a new cluster.`,
      })
      setOpen(false)
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(`Delete rejected: ${error.message}`, {
          description:
            error.code === 'CLUSTER_IN_USE'
              ? 'Remove the apps’ environments on this cluster first.'
              : undefined,
        })
      } else {
        toast.error('Something went wrong deleting the cluster.')
      }
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          aria-label={`Delete ${cluster.clusterName}`}
        >
          <Trash2 />
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <TriangleAlert className="size-4.5 text-destructive" />
            Delete {cluster.clusterName}
          </AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the platform’s record of{' '}
            {cluster.clusterName} — including its stored worker token and CA — and frees environment{' '}
            {cluster.environment} for re-registration. The cluster itself is untouched, but apps
            targeting {cluster.environment} can’t roll out until another cluster is registered for
            it.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-1.5 py-1">
          <Label htmlFor="delete-cluster-typed">
            Type <span className="font-mono text-destructive">{cluster.clusterName}</span> to confirm
          </Label>
          <Input
            id="delete-cluster-typed"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={cluster.clusterName}
            autoComplete="off"
          />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button variant="destructive" onClick={submit} disabled={!ready || deleteCluster.isPending}>
            {deleteCluster.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Delete cluster
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
