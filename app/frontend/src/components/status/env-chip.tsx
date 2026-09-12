/**
 * Environment chip — qa/uat/prod with stable colour semantics: blue = shared
 * integration, amber = release candidate, red = production (treat with care).
 */

import { StatusChip } from '@/components/status/status-chip'
import type { Environment } from '@/lib/api/types'

const ENV_TONES: Record<Environment, 'info' | 'pending' | 'failure'> = {
  qa: 'info',
  uat: 'pending',
  prod: 'failure',
}

export function EnvironmentChip({ environment }: { environment: string }) {
  const tone = ENV_TONES[environment as Environment] ?? 'neutral'
  return <StatusChip tone={tone}>{environment}</StatusChip>
}