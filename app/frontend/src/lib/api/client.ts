/**
 * Thin fetch wrapper for the Makeway control plane.
 *
 * Responsibilities:
 *  - Prefix the API base (dev: `/api` via the Vite proxy; prod: VITE_API_BASE_URL).
 *  - Attach `Authorization: Bearer` from the session store.
 *  - Generate an `Idempotency-Key` per mutating call (the backend contract:
 *    retries with the same key never duplicate resources).
 *  - Normalise every failure into `ApiError` — the backend always answers
 *    errors with `{success: false, error: {code, message, details}}`, while
 *    2xx bodies are raw DTOs.
 *  - On any 401 that isn't the login call itself, tear the session down and
 *    send the browser to /login?expired=1 (the proactive expiry timer covers
 *    the common case; this catches server-side invalidation and clock drift).
 */

import type { ErrorEnvelope, ValidationErrorDetail } from './types'
import { getSessionSnapshot, clearSession } from '@/lib/auth/session'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: ValidationErrorDetail[] | Record<string, unknown>[]

  constructor(status: number, code: string, message: string, details: ApiError['details'] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** True when `details` carries field-level validation entries (422). */
  get isValidation(): boolean {
    return this.status === 422 && this.details.length > 0
  }

  /** `details` narrowed to field-level entries, when they are that shape. */
  get fieldDetails(): ValidationErrorDetail[] {
    return this.details.filter(
      (d): d is ValidationErrorDetail => typeof (d as ValidationErrorDetail).field === 'string',
    )
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  /** Set false for calls that legitimately return 401 (POST /auth/login). */
  handleAuth?: boolean
  idempotencyKey?: boolean
  signal?: AbortSignal
}

function buildHeaders(options: RequestOptions): Headers {
  const headers = new Headers({ Accept: 'application/json' })

  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json')
  }

  const token = getSessionSnapshot()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  if (options.idempotencyKey) {
    headers.set('Idempotency-Key', uuid())
  }

  return headers
}

/**
 * Random v4 UUID. `crypto.randomUUID` only exists in secure contexts
 * (HTTPS / localhost) — on the plain-HTTP ALB deployment it is undefined and
 * calling it would throw, so fall back to `getRandomValues` (available
 * everywhere). The backend treats the Idempotency-Key as an opaque string.
 */
function uuid(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40 // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`
}

/** A 401 outside the login flow means the session is dead — act on it. */
function handleUnauthorized() {
  clearSession()
  if (!window.location.pathname.startsWith('/login')) {
    window.location.assign('/login?expired=1')
  }
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', handleAuth = true } = options

  // Build headers outside the network try/catch: a bug here must surface as
  // itself, not masquerade as "backend unreachable" (that masking is exactly
  // how the crypto.randomUUID secure-context bug hid for a whole deploy).
  const headers = buildHeaders(options)
  const body = options.body !== undefined ? JSON.stringify(options.body) : undefined

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body,
      signal: options.signal,
    })
  } catch {
    // Fetch rejects on network failure / DNS / CORS blocks — present one
    // stable shape so callers can toast "backend unreachable".
    throw new ApiError(0, 'NETWORK_ERROR', 'The Makeway API is unreachable. Check that the control plane is running.')
  }

  if (response.status === 401 && handleAuth) {
    handleUnauthorized()
  }

  if (!response.ok) {
    throw await toApiError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return (await response.json()) as T
}

async function toApiError(response: Response): Promise<ApiError> {
  let code = `HTTP_${response.status}`
  let message = `Request failed with status ${response.status}.`
  let details: ApiError['details'] = []

  try {
    const body = (await response.json()) as ErrorEnvelope
    if (body?.error) {
      code = body.error.code ?? code
      message = body.error.message ?? message
      details = body.error.details ?? []
    }
  } catch {
    // Non-JSON error body (proxy 502 page, empty body) — keep defaults.
  }

  return new ApiError(response.status, code, message, details)
}

/** Convenience wrapper for JSON POST/PUT/DELETE calls. */
export function apiSend<T>(path: string, options: RequestOptions & { method: 'POST' | 'PUT' | 'DELETE' }): Promise<T> {
  return apiFetch<T>(path, options)
}
