/**
 * New-app wizard — three steps: details → environments → review.
 *
 * Draft state is looser than the wire format (string inputs for capacity,
 * comma-separated queue names) and is converted to `AppConfig` on submit.
 * Field names mirror the wire so backend 422 `details[].field` paths map back
 * onto the draft entries directly.
 */

import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Cloud,
  Database,
  GitBranch,
  Layers,
  Loader2,
  MessageSquare,
  Plus,
  Server,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { useClusters, useCreateApp } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import type {
  AppConfig,
  CapabilityConfig,
  ClusterSummary,
  EnvConfig,
  Environment,
  ServiceType,
  ValidationErrorDetail,
} from '@/lib/api/types'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Draft model
// ---------------------------------------------------------------------------

interface ServiceDraft {
  service_type: ServiceType
  service_name: string
}

type CapabilityDraft =
  | { kind: 'rel_database'; name: string; username: string; capacity: string }
  | { kind: 'storage'; region: string; cloudfront: boolean }
  | { kind: 'messaging'; notification: boolean; queues: string }

interface EnvDraft {
  env: Environment
  services: ServiceDraft[]
  capabilities: { draft: CapabilityDraft; access_to: string[] }[]
}

const SERVICE_TYPES: ServiceType[] = ['fast-api', 'node-js', 'spring-boot']
const CAPABILITY_KINDS = [
  { kind: 'rel_database', label: 'Database', icon: <Database className="size-4" />, blurb: 'Managed relational store with credentials' },
  { kind: 'storage', label: 'Object storage', icon: <Cloud className="size-4" />, blurb: 'S3 bucket, optional CloudFront CDN' },
  { kind: 'messaging', label: 'Messaging', icon: <MessageSquare className="size-4" />, blurb: 'SQS queues and outbound notifications' },
] as const

const APP_NAME_PATTERN = /^[a-z0-9]([a-z0-9 -]*[a-z0-9])?$/

/** Effective name the backend resolves for a service (name or type fallback). */
function effectiveServiceName(service: ServiceDraft): string {
  return service.service_name.trim() || service.service_type
}

function capabilityValid(draft: CapabilityDraft): string | null {
  if (draft.kind === 'rel_database') {
    if (!draft.name.trim()) return 'Database needs a name.'
    const capacity = draft.capacity.trim()
    if (capacity) {
      const n = Number(capacity)
      if (!Number.isInteger(n) || n < 1 || n > 10) return 'Capacity must be an integer from 1 to 10.'
    }
  }
  if (draft.kind === 'storage' && draft.region.trim() && draft.region.trim().length < 3) {
    return 'Region looks too short.'
  }
  return null
}

function toConfig(draft: CapabilityDraft): CapabilityConfig {
  switch (draft.kind) {
    case 'rel_database':
      return {
        type: 'rel_database',
        name: draft.name.trim(),
        username: draft.username.trim() || undefined,
        capacity: draft.capacity.trim() ? Number(draft.capacity.trim()) : undefined,
      }
    case 'storage': {
      const region = draft.region.trim()
      return { type: 'storage', s3: region ? { region, cloudfront: draft.cloudfront } : undefined }
    }
    case 'messaging': {
      const queue = draft.queues
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean)
        .map((name) => ({ name }))
      return { type: 'messaging', notification: draft.notification, queue }
    }
  }
}

function toEnvConfig(env: EnvDraft): EnvConfig {
  return {
    env: env.env,
    services: env.services.length
      ? env.services.map((service) => ({
          service_type: service.service_type,
          service_name: service.service_name.trim() || undefined,
        }))
      : undefined,
    capabilities: env.capabilities.length
      ? env.capabilities.map(({ draft, access_to }) => ({ config: toConfig(draft), access_to }))
      : undefined,
  }
}

// ---------------------------------------------------------------------------
// Stepper chrome
// ---------------------------------------------------------------------------

const STEPS = ['Details', 'Environments', 'Review'] as const

function Stepper({ step }: { step: number }) {
  return (
    <div className="mx-auto flex w-fit items-center gap-2">
      {STEPS.map((label, index) => (
        <div key={label} className="flex items-center gap-2">
          <div
            className={cn(
              'flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors',
              index === step && 'border-primary/40 bg-primary/10 text-primary',
              index < step && 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
              index > step && 'text-muted-foreground',
            )}
          >
            <span className="grid size-4 place-items-center rounded-full bg-current/15 text-[10px] font-semibold">
              {index < step ? <Check className="size-3" /> : index + 1}
            </span>
            {label}
          </div>
          {index < STEPS.length - 1 && <span aria-hidden className="h-px w-10 shrink-0 bg-border sm:w-14" />}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Wizard
// ---------------------------------------------------------------------------

export function NewAppPage() {
  const navigate = useNavigate()
  const createApp = useCreateApp()
  const clusters = useClusters()

  const [step, setStep] = useState(0)
  const [appName, setAppName] = useState('')
  const [teamName, setTeamName] = useState('')
  const [envs, setEnvs] = useState<EnvDraft[]>([
    { env: 'qa', services: [{ service_type: 'fast-api', service_name: '' }], capabilities: [] },
  ])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const step1Errors = useMemo(() => {
    const errors: string[] = []
    if (appName.length < 3 || appName.length > 50 || !APP_NAME_PATTERN.test(appName)) {
      errors.push('App name: 3–50 chars, lowercase letters/digits with spaces or dashes; must start and end with a letter or digit.')
    }
    if (!teamName.trim()) errors.push('Team name is required.')
    return errors
  }, [appName, teamName])

  const step2Errors = useMemo(() => {
    const errors: string[] = []
    const used = new Set<Environment>()
    for (const env of envs) {
      if (used.has(env.env)) errors.push(`Environment ${env.env} is listed twice.`)
      used.add(env.env)
      for (const capability of env.capabilities) {
        const message = capabilityValid(capability.draft)
        if (message) errors.push(`${env.env}: ${message}`)
      }
    }
    return errors
  }, [envs])

  const canAdvance = step === 0 ? step1Errors.length === 0 : step2Errors.length === 0

  const submit = async () => {
    setSubmitError(null)
    setFieldErrors({})
    const payload: AppConfig = {
      app_name: appName.trim(),
      team_name: teamName.trim(),
      env_config: envs.map(toEnvConfig),
    }
    try {
      const response = await createApp.mutateAsync(payload)
      toast.success('App creation submitted', {
        description: `${response.message} — request #${response.request_id} is reconciling.`,
      })
      navigate(`/apps/${encodeURIComponent(payload.app_name)}`)
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 422 && error.fieldDetails.length > 0) {
          mapValidationDetails(error.fieldDetails, setFieldErrors, setSubmitError)
        } else {
          setSubmitError(error.message)
        }
        toast.error('Creation rejected', { description: error.message })
      } else {
        setSubmitError('Something went wrong. Please try again.')
      }
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div className="space-y-3">
        <Button variant="ghost" size="sm" className="-ml-2 h-7 text-muted-foreground" asChild>
          <Link to="/apps">
            <ArrowLeft /> All apps
          </Link>
        </Button>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-heading text-xl font-semibold tracking-tight">Onboard a new app</h1>
          <Stepper step={step} />
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
        >
          {step === 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">App details</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <FieldGroup>
                  <Field data-invalid={appName.length > 0 && step1Errors.some((e) => e.startsWith('App name'))}>
                    <FieldLabel htmlFor="app-name">App name</FieldLabel>
                    <Input
                      id="app-name"
                      value={appName}
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="orders"
                      onChange={(event) => setAppName(event.target.value.toLowerCase())}
                    />
                    <FieldDescription>
                      Names the repository, Kubernetes namespace, and cloud resources.
                    </FieldDescription>
                    {appName.length > 0 && step1Errors.some((e) => e.startsWith('App name')) && (
                      <FieldError>3–50 chars — lowercase letters, digits, spaces or dashes; starts and ends with a letter or digit.</FieldError>
                    )}
                  </Field>
                  <Field data-invalid={teamName.length > 0 && !teamName.trim()}>
                    <FieldLabel htmlFor="team-name">Team</FieldLabel>
                    <Input
                      id="team-name"
                      value={teamName}
                      autoComplete="off"
                      placeholder="platform"
                      onChange={(event) => setTeamName(event.target.value)}
                    />
                    <FieldDescription>Must be a team you’re an active member of.</FieldDescription>
                  </Field>
                </FieldGroup>
              </CardContent>
            </Card>
          )}

          {step === 1 && (
            <EnvironmentsStep
              envs={envs}
              onChange={setEnvs}
              otherEnvsUsed={envs.map((env) => env.env)}
              clusters={clusters.data}
            />
          )}

          {step === 2 && (
            <ReviewStep
              appName={appName.trim()}
              teamName={teamName.trim()}
              envs={envs}
              clusters={clusters.data}
              submitError={submitError}
              fieldErrors={fieldErrors}
              submitting={createApp.isPending}
              onSubmit={submit}
            />
          )}
        </motion.div>
      </AnimatePresence>

      <div className="flex items-center justify-between">
        <Button variant="ghost" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
          <ArrowLeft /> Back
        </Button>
        {step < 2 ? (
          <Button disabled={!canAdvance} onClick={() => setStep((s) => s + 1)}>
            Next <ArrowRight />
          </Button>
        ) : (
          <Button disabled={createApp.isPending} onClick={submit}>
            {createApp.isPending ? <Loader2 className="size-4 animate-spin" /> : <Check />}
            Create app
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step 2 — environments
// ---------------------------------------------------------------------------

function EnvironmentsStep({
  envs,
  onChange,
  clusters,
}: {
  envs: EnvDraft[]
  onChange: (envs: EnvDraft[]) => void
  otherEnvsUsed: Environment[]
  clusters: ClusterSummary[] | undefined
}) {
  const envOptions: Environment[] = ['qa', 'uat', 'prod']
  const registeredEnvs = new Set((clusters ?? []).map((cluster) => cluster.environment))

  const update = (index: number, next: EnvDraft) => {
    onChange(envs.map((env, i) => (i === index ? next : env)))
  }

  return (
    <div className="space-y-4">
      {envs.map((env, envIndex) => {
        const noCluster = !registeredEnvs.has(env.env)
        return (
          <Card key={envIndex}>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div className="flex items-center gap-2">
                <CardTitle className="text-base">Environment</CardTitle>
                <Select
                  value={env.env}
                  onValueChange={(value) =>
                    update(envIndex, { ...env, env: value as Environment })
                  }
                >
                  <SelectTrigger className="w-24" size="sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {envOptions
                      .filter((option) => option === env.env || !envs.some((other) => other.env === option))
                      .map((option) => (
                        <SelectItem key={option} value={option}>
                          {option}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
              {envs.length > 1 && (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove environment"
                  onClick={() => onChange(envs.filter((_, i) => i !== envIndex))}
                >
                  <Trash2 className="size-4" />
                </Button>
              )}
            </CardHeader>
            <CardContent className="space-y-5">
              {noCluster && (
                <p className="flex items-center gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                  <TriangleAlert className="size-3.5 shrink-0" />
                  No cluster registered for <strong>{env.env}</strong> — creation will be rejected.
                  <Link to="/clusters" className="underline underline-offset-2">Register one</Link>
                </p>
              )}

              <ServiceRepeater
                env={env}
                onChange={(services) => update(envIndex, { ...env, services })}
              />
              <Separator />
              <CapabilityRepeater env={env} onChange={(capabilities) => update(envIndex, { ...env, capabilities })} />
            </CardContent>
          </Card>
        )
      })}
      {envs.length < 3 && (
        <Button
          variant="outline"
          size="sm"
          onClick={() =>
            onChange([
              ...envs,
              { env: envOptions.find((option) => !envs.some((other) => other.env === option)) ?? 'qa', services: [], capabilities: [] },
            ])
          }
        >
          <Plus /> Add environment
        </Button>
      )}
    </div>
  )
}

function ServiceRepeater({
  env,
  onChange,
}: {
  env: EnvDraft
  onChange: (services: ServiceDraft[]) => void
}) {
  return (
    <FieldGroup>
      <FieldLabel className="flex items-center gap-1.5">
        <Server className="size-3.5 text-muted-foreground" /> Services
      </FieldLabel>
      {env.services.length === 0 && (
        <FieldDescription>No services — capabilities alone won’t have anything to bind to.</FieldDescription>
      )}
      <div className="space-y-2">
        {env.services.map((service, index) => (
          <div key={index} className="flex items-center gap-2">
            <Select
              value={service.service_type}
              onValueChange={(value) =>
                onChange(env.services.map((item, i) => (i === index ? { ...item, service_type: value as ServiceType } : item)))
              }
            >
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SERVICE_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              placeholder="Name (defaults to the type)"
              value={service.service_name}
              onChange={(event) =>
                onChange(env.services.map((item, i) => (i === index ? { ...item, service_name: event.target.value } : item)))
              }
            />
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Remove service"
              onClick={() => onChange(env.services.filter((_, i) => i !== index))}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ))}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        onClick={() => onChange([...env.services, { service_type: 'fast-api', service_name: '' }])}
      >
        <Plus /> Add service
      </Button>
    </FieldGroup>
  )
}

function CapabilityRepeater({
  env,
  onChange,
}: {
  env: EnvDraft
  onChange: (capabilities: EnvDraft['capabilities']) => void
}) {
  return (
    <FieldGroup>
      <FieldLabel className="flex items-center gap-1.5">
        <Layers className="size-3.5 text-muted-foreground" /> Capabilities
      </FieldLabel>
      {env.capabilities.length === 0 && (
        <FieldDescription>Databases, storage, messaging — provisioned per environment.</FieldDescription>
      )}
      <div className="space-y-3">
        {env.capabilities.map((capability, index) => {
          const error = capabilityValid(capability.draft)
          const serviceNames = env.services.map(effectiveServiceName)
          return (
            <div key={index} className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <div className="flex flex-wrap gap-1.5">
                  {CAPABILITY_KINDS.map(({ kind, label, icon }) => (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => {
                        const draft: CapabilityDraft =
                          kind === 'rel_database'
                            ? { kind, name: '', username: '', capacity: '' }
                            : kind === 'storage'
                              ? { kind, region: '', cloudfront: false }
                              : { kind, notification: false, queues: '' }
                        onChange(
                          env.capabilities.map((item, i) => (i === index ? { draft, access_to: item.access_to } : item)),
                        )
                      }}
                      className={cn(
                        'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors',
                        capability.draft.kind === kind
                          ? 'border-primary/40 bg-primary/10 text-primary'
                          : 'text-muted-foreground hover:bg-muted',
                      )}
                    >
                      {icon}
                      {label}
                    </button>
                  ))}
                </div>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Remove capability"
                  onClick={() => onChange(env.capabilities.filter((_, i) => i !== index))}
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </div>

              {capability.draft.kind === 'rel_database' && (
                <div className="grid gap-2 sm:grid-cols-3">
                  <Field>
                    <FieldLabel className="text-xs">Database name</FieldLabel>
                    <Input
                      value={capability.draft.name}
                      onChange={(event) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'rel_database', name: event.target.value } as CapabilityDraft }
                          : item)))
                      }
                      placeholder="orders"
                    />
                  </Field>
                  <Field>
                    <FieldLabel className="text-xs">Username</FieldLabel>
                    <Input
                      value={capability.draft.username}
                      onChange={(event) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'rel_database', username: event.target.value } as CapabilityDraft }
                          : item)))
                      }
                      placeholder="optional"
                    />
                  </Field>
                  <Field>
                    <FieldLabel className="text-xs">Capacity (1–10)</FieldLabel>
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      value={capability.draft.capacity}
                      onChange={(event) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'rel_database', capacity: event.target.value } as CapabilityDraft }
                          : item)))
                      }
                      placeholder="optional"
                    />
                  </Field>
                </div>
              )}

              {capability.draft.kind === 'storage' && (
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field>
                    <FieldLabel className="text-xs">S3 region</FieldLabel>
                    <Input
                      value={capability.draft.region}
                      onChange={(event) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'storage', region: event.target.value } as CapabilityDraft }
                          : item)))
                      }
                      placeholder="ap-south-1 (optional)"
                    />
                  </Field>
                  <label className="flex h-9 items-end gap-2 pb-1.5 text-sm text-muted-foreground">
                    <Checkbox
                      checked={capability.draft.cloudfront}
                      onCheckedChange={(checked) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'storage', cloudfront: checked === true } as CapabilityDraft }
                          : item)))
                      }
                    />
                    CloudFront CDN
                  </label>
                </div>
              )}

              {capability.draft.kind === 'messaging' && (
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Switch
                      checked={capability.draft.notification}
                      onCheckedChange={(checked) =>
                        onChange(env.capabilities.map((item, i) => (i === index
                          ? { ...item, draft: { ...item.draft, kind: 'messaging', notification: checked } as CapabilityDraft }
                          : item)))
                      }
                    />
                    Outbound notifications
                  </label>
                  <Input
                    placeholder="Queue names, comma-separated (optional)"
                    value={capability.draft.queues}
                    onChange={(event) =>
                      onChange(env.capabilities.map((item, i) => (i === index
                        ? { ...item, draft: { ...item.draft, kind: 'messaging', queues: event.target.value } as CapabilityDraft }
                        : item)))
                    }
                  />
                </div>
              )}

              {serviceNames.length > 0 && (
                <Field>
                  <FieldLabel className="text-xs">Access (empty = all services)</FieldLabel>
                  <div className="flex flex-wrap gap-2">
                    {serviceNames.map((name) => (
                      <label
                        key={name}
                        className={cn(
                          'flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors',
                          capability.access_to.includes(name)
                            ? 'border-primary/40 bg-primary/10 text-primary'
                            : 'text-muted-foreground hover:bg-muted',
                        )}
                      >
                        <Checkbox
                          checked={capability.access_to.includes(name)}
                          onCheckedChange={(checked) =>
                            onChange(env.capabilities.map((item, i) => (i === index
                              ? {
                                  ...item,
                                  access_to: checked
                                    ? [...item.access_to, name]
                                    : item.access_to.filter((existing) => existing !== name),
                                }
                              : item)))
                          }
                        />
                        {name}
                      </label>
                    ))}
                  </div>
                </Field>
              )}

              {error && <FieldError>{error}</FieldError>}
            </div>
          )
        })}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        onClick={() =>
          onChange([
            ...env.capabilities,
            { draft: { kind: 'rel_database', name: '', username: '', capacity: '' }, access_to: [] },
          ])
        }
      >
        <Plus /> Add capability
      </Button>
    </FieldGroup>
  )
}

// ---------------------------------------------------------------------------
// Step 3 — review
// ---------------------------------------------------------------------------

function ReviewStep({
  appName,
  teamName,
  envs,
  clusters,
  submitError,
  fieldErrors,
  submitting,
  onSubmit,
}: {
  appName: string
  teamName: string
  envs: EnvDraft[]
  clusters: ClusterSummary[] | undefined
  submitError: string | null
  fieldErrors: Record<string, string>
  submitting: boolean
  onSubmit: () => void
}) {
  const registeredEnvs = new Set((clusters ?? []).map((cluster) => cluster.environment))

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <GitBranch className="size-4 text-muted-foreground" />
            {appName} <span className="text-sm font-normal text-muted-foreground">· team {teamName}</span>
          </CardTitle>
        </CardHeader>
      </Card>

      {envs.map((env) => (
        <Card key={env.env}>
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="font-mono text-sm">{env.env}</CardTitle>
            {!registeredEnvs.has(env.env) && (
              <span className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                <TriangleAlert className="size-3.5" /> no cluster registered
              </span>
            )}
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <p>
              <span className="text-muted-foreground">Services:</span>{' '}
              {env.services.length === 0
                ? 'none'
                : env.services.map((service) => effectiveServiceName(service)).join(', ')}
            </p>
            <p>
              <span className="text-muted-foreground">Capabilities:</span>{' '}
              {env.capabilities.length === 0
                ? 'none'
                : env.capabilities.map(({ draft }) => draft.kind + describeDraft(draft)).join(' · ')}
            </p>
          </CardContent>
        </Card>
      ))}

      {submitError && (
        <div
          role="alert"
          className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400"
        >
          {submitError}
        </div>
      )}
      {Object.entries(fieldErrors).length > 0 && (
        <div className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400">
          {Object.entries(fieldErrors).map(([field, message]) => (
            <p key={field}>
              <span className="font-mono text-xs">{field}</span> — {message}
            </p>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        Submitting sends the desired state to the platform — the reconcile pipeline (GitHub repo,
        infrastructure, GitOps) runs asynchronously and the detail page tracks it live.
      </p>
      <Button onClick={onSubmit} disabled={submitting} className="w-full">
        {submitting ? <Loader2 className="size-4 animate-spin" /> : <Check />}
        Create app
      </Button>
    </div>
  )
}

function describeDraft(draft: CapabilityDraft): string {
  switch (draft.kind) {
    case 'rel_database':
      return draft.name.trim() ? ` (${draft.name.trim()})` : ''
    case 'storage':
      return draft.region.trim() ? ` (${draft.region.trim()})` : ''
    case 'messaging':
      return draft.notification ? ' (notifications)' : ''
  }
}

// ---------------------------------------------------------------------------
// 422 field mapping — backend paths like `body.env_config.0.services.1.service_name`
// ---------------------------------------------------------------------------

function mapValidationDetails(
  details: ValidationErrorDetail[],
  setFieldErrors: (errors: Record<string, string>) => void,
  setSubmitError: (message: string | null) => void,
) {
  const mapped: Record<string, string> = {}
  const unmatched: string[] = []
  for (const detail of details) {
    // Strip the `body.` prefix; `env_config.<i>.…` maps onto env cards
    // (wizard order == wire order).
    const path = detail.field.startsWith('body.') ? detail.field.slice('body.'.length) : detail.field
    if (/^env_config\.\d+/.test(path)) {
      mapped[path] = detail.message
    } else if (/^(app_name|team_name)$/.test(path)) {
      mapped[path] = detail.message
    } else {
      unmatched.push(`${path}: ${detail.message}`)
    }
  }
  setFieldErrors(mapped)
  setSubmitError(unmatched.length > 0 ? unmatched.join(' · ') : null)
}