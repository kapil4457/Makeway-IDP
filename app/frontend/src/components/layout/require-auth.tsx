import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useSession } from '@/hooks/use-session'

/**
 * Guard for authenticated routes. Remembers where the user was heading so
 * login can return them there.
 */
export function RequireAuth() {
  const location = useLocation()
  const { isAuthenticated } = useSession()

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
