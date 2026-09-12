/**
 * Session store for the JWT bearer token.
 *
 * The control plane issues 30-minute HS256 tokens with no refresh endpoint,
 * so the pragmatic contract is: keep the token in localStorage (a memory-only
 * token would log the user out on every page refresh), parse its `exp`
 * client-side, proactively clear the session 60s before expiry, and let the
 * API client's 401 interceptor catch anything that slips through (server-side
 * clock drift, a tampered token). Both paths land on /login with an
 * "expired" marker.
 */

const STORAGE_KEY = 'makeway.access_token'
const EXPIRY_MARGIN_MS = 60_000

/** JWT payload as issued by auth/jwt.py: {sub, email, iat, exp}. */
export interface TokenClaims {
  sub: string
  email?: string
  iat?: number
  exp?: number
}

function readToken(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    // Site data can be unavailable (private mode, blocked storage) — treat as
    // logged out and keep the app renderable.
    return null
  }
}

export function parseJwt(token: string): TokenClaims | null {
  try {
        const payload = token.split('.')[1]
    if (!payload) return null
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json) as TokenClaims
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Tiny external store — subscribers re-render on token changes.
// ---------------------------------------------------------------------------

const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

let expiryTimer: ReturnType<typeof setTimeout> | null = null

function scheduleExpiryCheck() {
  if (expiryTimer) clearTimeout(expiryTimer)
  expiryTimer = null

  const claims = claimsForToken()
  if (!claims?.exp) return

  const firesIn = claims.exp * 1000 - Date.now() - EXPIRY_MARGIN_MS
  if (firesIn <= 0) {
    expireNow()
    return
  }
  expiryTimer = setTimeout(expireNow, firesIn)
}

function expireNow() {
  if (token !== null) {
    setTokenInternal(null)
  }
}

function setTokenInternal(next: string | null) {
  token = next
  try {
    if (token === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, token)
  } catch {
    // Storage unavailable — keep the in-memory value for this page's lifetime.
  }
  sessionSnapshot = buildSessionSnapshot()
  scheduleExpiryCheck()
  emit()
}

// Initialise from storage on module load, then arm the expiry timer.
let token: string | null = readToken()

/**
 * Stable snapshot handed to useSyncExternalStore, rebuilt only on the single
 * write path above. React compares snapshots with Object.is, so returning a
 * fresh object per call would register as a change every render and loop
 * RequireAuth's <Navigate> forever ("getSnapshot should be cached").
 */
let sessionSnapshot: SessionInfo = buildSessionSnapshot()
scheduleExpiryCheck()

function claimsForToken(): TokenClaims | null {
  if (!token) return null
  return parseJwt(token)
}

/**
 * End the session without a redirect — used by the 401 interceptor and the
 * proactive expiry timer. Components observing `useSession` re-render.
 */
export function clearSession() {
  setTokenInternal(null)
}

/** Persist a fresh token from POST /auth/login. */
export function storeToken(newToken: string) {
  setTokenInternal(newToken)
}

export function subscribeToSession(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function getSessionSnapshot(): string | null {
  return token
}

/** Session-derived facts for components (all derived from the token). */
export interface SessionInfo {
  token: string | null
  isAuthenticated: boolean
  userId: string | null
  expiresAt: number | null
}

export function getSessionInfo(): SessionInfo {
  return sessionSnapshot
}

function buildSessionSnapshot(): SessionInfo {
  const claims = claimsForToken()
  return {
    token,
    isAuthenticated: token !== null,
    userId: claims?.sub ?? null,
    expiresAt: claims?.exp ? claims.exp * 1000 : null,
  }
}
