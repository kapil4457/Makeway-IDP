import { useSyncExternalStore } from 'react'

import { getSessionInfo, subscribeToSession, type SessionInfo } from '@/lib/auth/session'

export function useSession(): SessionInfo {
  return useSyncExternalStore(subscribeToSession, getSessionInfo, getSessionInfo)
}
