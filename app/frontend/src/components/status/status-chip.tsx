/**
 * Status chips — the shared visual vocabulary for reconcile/runtime state.
 *
 * Colour semantics are stable across every chip:
 *   green = success/healthy, blue = progressing/in-progress, amber =
 *   degraded/pending, red = failed/unhealthy, muted = no data yet ("unknown"
 *   is an honest state, not an error).
 */

import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const chipVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-muted/50 text-muted-foreground',
        pending: 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400',
        progress: 'border-sky-500/25 bg-sky-500/10 text-sky-700 dark:text-sky-400',
        success: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
        degraded: 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-400',
        failure: 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-400',
        info: 'border-blue-500/25 bg-blue-500/10 text-blue-700 dark:text-blue-400',
      },
      pulse: {
        true: '',
        false: '',
      },
    },
    defaultVariants: { pulse: false },
  },
)

type Tone = NonNullable<VariantProps<typeof chipVariants>['tone']>

export interface StatusChipProps extends VariantProps<typeof chipVariants> {
  children: React.ReactNode
  /** Show a softly pulsing dot for in-flight states. */
  animate?: boolean
  className?: string
}

export function StatusChip({ tone = 'neutral', animate = false, className, children }: StatusChipProps) {
  return (
    <span className={cn(chipVariants({ tone, pulse: animate ? true : false }), className)}>
      <span
        aria-hidden
        className={cn(
          'size-1.5 rounded-full bg-current opacity-80',
          animate && tone === 'progress' && 'animate-pulse',
          animate && tone === 'pending' && 'animate-pulse',
        )}
      />
      {children}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Wire-value → chip mappings (all enums from dto/enums/)
// ---------------------------------------------------------------------------

const REQUEST_JOB_TONES: Record<string, Tone> = {
  pending: 'pending',
  in_progress: 'progress',
  success: 'success',
  failed: 'failure',
  partially_failed: 'failure',
}

const HEALTH_TONES: Record<string, Tone> = {
  unknown: 'neutral',
  healthy: 'success',
  degraded: 'degraded',
  unhealthy: 'failure',
}

const CONNECTIVITY_TONES: Record<string, Tone> = {
  unknown: 'neutral',
  configured: 'info',
  healthy: 'success',
  degraded: 'degraded',
  failed: 'failure',
}

function humanize(value: string): string {
  return value.replaceAll('_', ' ')
}

/** Request / job / capability reconcile states. */
export function ReconcileChip({ status, className }: { status: string; className?: string }) {
  const tone = REQUEST_JOB_TONES[status] ?? 'neutral'
  return (
    <StatusChip tone={tone} animate className={className}>
      {humanize(status)}
    </StatusChip>
  )
}

/** Service runtime health — `unknown` reads as "no reporter data", not failure. */
export function HealthChip({ health, className }: { health: string; className?: string }) {
  const tone = HEALTH_TONES[health] ?? 'neutral'
  const label = health === 'unknown' ? 'no reporter data' : humanize(health)
  return (
    <StatusChip tone={tone} className={className}>
      {label}
    </StatusChip>
  )
}

/** Service↔capability edge state. */
export function ConnectivityChip({ status, className }: { status: string; className?: string }) {
  const tone = CONNECTIVITY_TONES[status] ?? 'neutral'
  return (
    <StatusChip tone={tone} className={className}>
      {humanize(status)}
    </StatusChip>
  )
}
