/**
 * Cluster edit sheet — patches name/endpoint/credentials in place via
 * PUT /cluster/{id}. The environment is deliberately not editable here: it is
 * the routing key app creation resolves clusters by, so moving a cluster
 * means delete-and-re-register. Token/CA left blank keep the stored values —
 * the backend never wipes a credential on None, and clearing one is not
 * supported.
 */

import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, Pencil } from 'lucide-react'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useUpdateCluster } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import type { ClusterSummary } from '@/lib/api/types'

const CLUSTER_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/

const schema = z.object({
  clusterName: z
    .string()
    .min(3, 'At least 3 characters.')
    .regex(CLUSTER_NAME_PATTERN, 'Lowercase letters, digits and dashes; starts and ends with a letter or digit.'),
  kubeApiEndpoint: z.string().url('Enter a full URL, e.g. https://k8s.example.com:6443.'),
  kubeToken: z.string().optional(),
  kubeCaCert: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

export function EditClusterSheet({ cluster }: { cluster: ClusterSummary }) {
  const updateCluster = useUpdateCluster(cluster.clusterId)
  const [open, setOpen] = useState(false)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      clusterName: cluster.clusterName,
      kubeApiEndpoint: cluster.kubeApiEndpoint,
      kubeToken: '',
      kubeCaCert: '',
    },
  })

  // Re-seed on every open so a previous edit round (or a background refetch
  // that changed the cluster) can't leak stale values into the form.
  useEffect(() => {
    if (open) {
      form.reset({
        clusterName: cluster.clusterName,
        kubeApiEndpoint: cluster.kubeApiEndpoint,
        kubeToken: '',
        kubeCaCert: '',
      })
    }
  }, [open, cluster, form])

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const updated = await updateCluster.mutateAsync({
        clusterName: values.clusterName,
        kubeApiEndpoint: values.kubeApiEndpoint,
        // Blank = keep the stored credential (the backend never wipes on None).
        ...(values.kubeToken ? { kubeToken: values.kubeToken } : {}),
        ...(values.kubeCaCert ? { kubeCaCert: values.kubeCaCert } : {}),
      })
      toast.success('Cluster updated', {
        description: `${updated.clusterName} now serves ${updated.environment}.`,
      })
      setOpen(false)
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(`Update rejected: ${error.message}`, {
          description:
            error.code === 'VALIDATION_ERROR'
              ? 'Check the highlighted fields.'
              : error.code === 'CLUSTER_NAME_CONFLICT'
                ? 'That name belongs to another cluster — pick a different one.'
                : undefined,
        })
      } else {
        toast.error('Something went wrong updating the cluster.')
      }
    }
  })

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-foreground"
          aria-label={`Edit ${cluster.clusterName}`}
        >
          <Pencil />
        </Button>
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Edit {cluster.clusterName}</SheetTitle>
          <SheetDescription>
            Patch the endpoint after a tunnel change, rename the cluster, or rotate credentials.
            The environment (currently {cluster.environment}) is not editable — re-register to move.
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={onSubmit} className="flex-1 space-y-4 px-4 pb-6" noValidate>
          <FieldGroup>
            <Field data-invalid={!!form.formState.errors.clusterName}>
              <FieldLabel htmlFor="edit-cluster-name">Cluster name</FieldLabel>
              <Input
                id="edit-cluster-name"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!form.formState.errors.clusterName}
                {...form.register('clusterName')}
              />
              {form.formState.errors.clusterName && (
                <FieldError>{form.formState.errors.clusterName.message}</FieldError>
              )}
            </Field>

            <Field data-invalid={!!form.formState.errors.kubeApiEndpoint}>
              <FieldLabel htmlFor="edit-kube-endpoint">API endpoint</FieldLabel>
              <Input
                id="edit-kube-endpoint"
                placeholder="https://k8s.example.com:6443"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!form.formState.errors.kubeApiEndpoint}
                {...form.register('kubeApiEndpoint')}
              />
              {form.formState.errors.kubeApiEndpoint && (
                <FieldError>{form.formState.errors.kubeApiEndpoint.message}</FieldError>
              )}
              <FieldDescription>
                Update this when the cluster’s tunnel endpoint changes — workers pick it up on the
                next request.
              </FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-kube-token">
                Service-account token <span className="text-muted-foreground">(leave blank to keep)</span>
              </FieldLabel>
              <textarea
                id="edit-kube-token"
                className="min-h-20 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
                placeholder={cluster.hasToken ? 'Stored — paste a new token to replace it' : 'Not stored'}
                aria-invalid={!!form.formState.errors.kubeToken}
                {...form.register('kubeToken')}
              />
              <FieldDescription>Stored server-side; never returned by the API.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="edit-kube-ca">
                CA certificate <span className="text-muted-foreground">(leave blank to keep)</span>
              </FieldLabel>
              <textarea
                id="edit-kube-ca"
                className="min-h-20 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
                placeholder={cluster.hasCaCert ? 'Stored — paste a new certificate to replace it' : 'Not stored'}
                aria-invalid={!!form.formState.errors.kubeCaCert}
                {...form.register('kubeCaCert')}
              />
            </Field>
          </FieldGroup>
        </form>

        <SheetFooter className="border-t">
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => void onSubmit()} disabled={updateCluster.isPending}>
            {updateCluster.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Save changes
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}
