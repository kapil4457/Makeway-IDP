import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Hexagon, LayoutGrid, LogOut, Moon, Server, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/components/layout/theme-provider'
import { Separator } from '@/components/ui/separator'
import { useMe } from '@/hooks/use-api'
import { useSession } from '@/hooks/use-session'
import { clearSession } from '@/lib/auth/session'

const NAV_ITEMS = [
  { to: '/', label: 'Apps', icon: LayoutGrid, end: true },
  { to: '/clusters', label: 'Clusters', icon: Server, end: false },
] as const

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme()
  const isDark = resolvedTheme === 'dark'
  return (
    <Button
      variant="ghost"
      size="sm"
      className="w-full justify-start gap-2 text-muted-foreground"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
    >
      {isDark ? <Moon className="size-4" /> : <Sun className="size-4" />}
      {isDark ? 'Dark' : 'Light'} theme
    </Button>
  )
}

/** Session-expired redirect lands here with ?expired=1 — show a friendly toast. */
function useExpiredNotice() {
  const location = useLocation()
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    if (params.get('expired') === '1') {
      import('sonner').then(({ toast }) => {
        toast.info('Session expired', { description: 'Sign in again to continue.' })
      })
    }
  }, [location.search])
}

export function AppShell() {
  const location = useLocation()
  const { isAuthenticated, expiresAt } = useSession()
  const { data: me } = useMe()
  useExpiredNotice()

  // Proactive logout when the parsed token expiry passes (60s margin armed in
  // the session store); this keeps the shell reactive without a page reload.
  useEffect(() => {
    if (expiresAt !== null && expiresAt <= Date.now()) {
      clearSession()
    }
  }, [expiresAt])

  if (!isAuthenticated) return null

  return (
    <div className="flex min-h-dvh">
      <aside className="fixed inset-y-0 z-20 flex w-60 flex-col border-r bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2.5 px-5">
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-primary-foreground">
            <Hexagon className="size-4" />
          </span>
          <span className="font-heading text-sm font-semibold tracking-tight">Makeway</span>
        </div>

        <Separator />

        <nav className="flex flex-1 flex-col gap-1 p-3">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              {({ isActive }) => (
                <motion.span
                  whileHover={{ x: 2 }}
                  className={
                    'flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-colors ' +
                    (isActive
                      ? 'bg-accent font-medium text-accent-foreground'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground')
                  }
                >
                  <Icon className="size-4" />
                  {label}
                </motion.span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-1 border-t p-3">
          <ThemeToggle />
          <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5">
            <NavLink to="/profile" className="min-w-0 flex-1 rounded-lg" title="View profile">
              <p className="truncate text-xs font-medium" title={me?.email}>
                {me?.email ?? '…'}
              </p>
              <p className="truncate text-[11px] text-muted-foreground transition-colors group-hover:text-foreground">
                {expiresAt
                  ? `Session until ${new Date(expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                  : 'Signed in'}
              </p>
            </NavLink>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Sign out"
              onClick={() => {
                clearSession()
                window.location.assign('/login')
              }}
            >
              <LogOut className="size-3.5" />
            </Button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pl-60">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="flex-1"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  )
}
