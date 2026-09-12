import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

type Theme = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'makeway.theme'

interface ThemeContextValue {
  theme: Theme
  /** The theme actually applied — "system" resolved against the OS setting. */
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readStoredTheme(): Theme {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') return value
  } catch {
    // Storage unavailable (private mode, blocked site data) — use the OS setting.
  }
  return 'system'
}

/**
 * Client-only replacement for next-themes (which is Next.js-oriented and
 * renders a <script> tag from the provider — React 19 refuses to execute
 * scripts inside components). Class-on-<html> matches the Tailwind setup
 * (`@custom-variant dark (&:is(.dark *))`); the no-flash class itself is set
 * by a static script in index.html before React mounts.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme)
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  )

  const resolvedTheme: 'light' | 'dark' =
    theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', resolvedTheme === 'dark')
    root.style.colorScheme = resolvedTheme
  }, [resolvedTheme])

  // Track OS changes while following the system theme.
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const setTheme = useCallback((next: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Keep the in-memory theme for this page's lifetime.
    }
    // Suppress CSS transitions for one paint so the color swap snaps instead
    // of animating (the equivalent of next-themes' disableTransitionOnChange).
    const suppress = document.createElement('style')
    suppress.appendChild(
      document.createTextNode('*,*::before,*::after{transition:none!important}'),
    )
    document.head.appendChild(suppress)
    window.setTimeout(() => suppress.remove(), 100)
    setThemeState(next)
  }, [])

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme }),
    [theme, resolvedTheme, setTheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within ThemeProvider')
  return context
}
