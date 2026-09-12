/**
 * Cluster registration sheet — camelCase wire body (dto/request/register_cluster.py).
 * Re-registering an existing name+environment is an idempotent upsert on the
 * backend, so the copy frames it as safe to repeat.
 */

import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Loader2, Plus } from 'lucide-react'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useClusters, useRegisterCluster } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import type { Environment } from '@/lib/api/types'

const CLUSTER_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/

const schema = z.object({
  clusterName: z
    .string()
    .min(3, 'At least 3 characters.')
    .regex(CLUSTER_NAME_PATTERN, 'Lowercase letters, digits and dashes; starts and ends with a letter or digit.'),
  kubeApiEndpoint: z.string().url('Enter a full URL, e.g. https://k8s.example.com:6443.'),
  environment: z.enum(['qa', 'uat', 'prod']),
  kubeToken: z.string().optional(),
  kubeCaCert: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

export function RegisterClusterSheet() {
  const registerCluster = useRegisterCluster()
  const { data: clusters } = useClusters()
  const [open, setOpen] = useState(false)
  const [environment, setEnvironment] = useState<Environment>('qa')

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { clusterName: '', kubeApiEndpoint: '', environment: 'qa', kubeToken: '', kubeCaCert: '' },
  })

  const clusterName = form.watch('clusterName')

  // One cluster per environment: map env → registered names so the form can
  // tell "occupied by someone else" (blocked) from "this name re-registered"
  // (the idempotent update path).
  const occupantsByEnv = useMemo(() => {
    const map = new Map<Environment, string[]>()
    for (const cluster of clusters ?? []) {
      const names = map.get(cluster.environment) ?? []
      names.push(cluster.clusterName)
      map.set(cluster.environment, names)
    }
    return map
  }, [clusters])

  const occupantsOf = (env: Environment) =>
    (occupantsByEnv.get(env) ?? []).filter((name) => name !== clusterName)

  const selectedEnvOccupants = occupantsOf(environment)

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const response = await registerCluster.mutateAsync({
        clusterName: values.clusterName,
        kubeApiEndpoint: values.kubeApiEndpoint,
        environment,
        // Omit empty optionals rather than sending empty strings.
        ...(values.kubeToken ? { kubeToken: values.kubeToken } : {}),
        ...(values.kubeCaCert ? { kubeCaCert: values.kubeCaCert } : {}),
      })
      toast.success('Cluster registered', {
        description: response.message || `${response.cluster_name} is ready for app creation.`,
      })
      form.reset()
      setEnvironment('qa')
      setOpen(false)
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(`Registration rejected: ${error.message}`, {
          description:
            error.code === 'VALIDATION_ERROR'
              ? 'Check the highlighted fields.'
              : error.code === 'CLUSTER_ENVIRONMENT_CONFLICT'
                ? 'Pick another environment, or re-register the occupying cluster by its name.'
                : undefined,
        })
      } else {
        toast.error('Something went wrong registering the cluster.')
      }
    }
  })

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button size="sm">
          <Plus /> Register cluster
        </Button>
      </SheetTrigger>
      <SheetContent className="flex w-full flex-col gap-0 overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Register a cluster</SheetTitle>
          <SheetDescription>
            One cluster per environment. Re-registering an existing name is a safe, idempotent
            update.
          </SheetDescription>
        </SheetHeader>

        <form onSubmit={onSubmit} className="flex-1 space-y-4 px-4 pb-6" noValidate>
          <FieldGroup>
            <Field data-invalid={!!form.formState.errors.clusterName}>
              <FieldLabel htmlFor="cluster-name">Cluster name</FieldLabel>
              <Input
                id="cluster-name"
                placeholder="makeway-qa"
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
              <FieldLabel htmlFor="kube-endpoint">API endpoint</FieldLabel>
              <Input
                id="kube-endpoint"
                placeholder="https://k8s.example.com:6443"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={!!form.formState.errors.kubeApiEndpoint}
                {...form.register('kubeApiEndpoint')}
              />
              {form.formState.errors.kubeApiEndpoint && (
                <FieldError>{form.formState.errors.kubeApiEndpoint.message}</FieldError>
              )}
            </Field>

            <Field data-invalid={selectedEnvOccupants.length > 0}>
              <FieldLabel>Environment</FieldLabel>
              <input type="hidden" value={environment} {...form.register('environment')} />
              <Select
                value={environment}
                onValueChange={(value) => {
                  const next = value as Environment
                  setEnvironment(next)
                  form.setValue('environment', next, { shouldValidate: false })
                }}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(['qa', 'uat', 'prod'] as Environment[]).map((option) => {
                    const occupants = occupantsOf(option)
                    return (
                      <SelectItem key={option} value={option} disabled={occupants.length > 0}>
                        {option}
                        {occupants.length > 0 && (
                          <span className="text-muted-foreground"> · taken by {occupants.join(', ')}</span>
                        )}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
              {selectedEnvOccupants.length > 0 ? (
                <FieldError>
                  {environment} is already served by {selectedEnvOccupants.join(', ')} — re-register
                  that cluster by name to update it.
                </FieldError>
              ) : (
                <FieldDescription>Apps targeting this environment roll out on this cluster.</FieldDescription>
              )}
            </Field>

            <Field>
              <FieldLabel htmlFor="kube-token">
                Service-account token <span className="text-muted-foreground">(optional)</span>
              </FieldLabel>
              <textarea
                id="kube-token"
                className="min-h-20 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
                placeholder="eyJhbGciOi…"
                aria-invalid={!!form.formState.errors.kubeToken}
                {...form.register('kubeToken')}
              />
              <FieldDescription>Stored server-side; never returned by the API after registration.</FieldDescription>
            </Field>

            <Field>
              <FieldLabel htmlFor="kube-ca">CA certificate <span className="text-muted-foreground">(optional)</span></FieldLabel>
              <textarea
                id="kube-ca"
                className="min-h-20 w-full rounded-md border bg-transparent px-3 py-2 font-mono text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50"
                placeholder="-----BEGIN CERTIFICATE-----"
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
          <Button
            onClick={() => void onSubmit()}
            disabled={registerCluster.isPending || selectedEnvOccupants.length > 0}
          >
            {registerCluster.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Register
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}