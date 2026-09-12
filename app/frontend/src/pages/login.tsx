import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { motion } from 'framer-motion'
import { Hexagon, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api/client'
import { login } from '@/lib/api/endpoints'
import { storeToken } from '@/lib/auth/session'
import { useSession } from '@/hooks/use-session'

const loginSchema = z.object({
  email: z.string().min(1, 'Email is required.').email('Enter a valid email address.'),
  password: z.string().min(1, 'Password is required.'),
})

type LoginForm = z.infer<typeof loginSchema>

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { isAuthenticated } = useSession()
  const [expired, setExpired] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const form = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  })

  useEffect(() => {
    setExpired(new URLSearchParams(location.search).get('expired') === '1')
  }, [location.search])

  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/'

  // Already signed in (e.g. visiting /login directly) — go to the dashboard.
  if (isAuthenticated) {
    return <Navigate to={from} replace />
  }

  const onSubmit = form.handleSubmit(async (values) => {
    setSubmitError(null)
    try {
      const response = await login(values)
      storeToken(response.access_token)
      toast.success('Signed in', { description: 'Welcome to Makeway.' })
      navigate(from, { replace: true })
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          // The backend folds both wrong email and wrong password into
          // INVALID_CREDENTIALS — never hint which one failed.
          setSubmitError('Incorrect email or password.')
        } else {
          setSubmitError(error.message)
        }
      } else {
        setSubmitError('Something went wrong. Please try again.')
      }
    }
  })

  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden bg-muted/40 px-4">
      {/* Ambient glow — the only flourish on an otherwise quiet page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-32 left-1/2 size-[32rem] -translate-x-1/2 rounded-full bg-primary/10 blur-3xl"
      />
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.99 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        className="w-full max-w-sm rounded-2xl border bg-card p-6 shadow-sm"
      >
        <div className="mb-6 flex flex-col items-center gap-2 text-center">
          <span className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
            <Hexagon className="size-5" />
          </span>
          <h1 className="font-heading text-lg font-semibold tracking-tight">Sign in to Makeway</h1>
          <p className="text-sm text-muted-foreground">Your platform control plane</p>
        </div>

        {expired && (
          <div className="mb-4 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
            Your session expired. Sign in again to continue.
          </div>
        )}

        <form onSubmit={onSubmit} noValidate>
          <FieldGroup>
            <Field data-invalid={!!form.formState.errors.email}>
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                aria-invalid={!!form.formState.errors.email}
                {...form.register('email')}
              />
              {form.formState.errors.email && (
                <FieldError>{form.formState.errors.email.message}</FieldError>
              )}
            </Field>

            <Field data-invalid={!!form.formState.errors.password}>
              <FieldLabel htmlFor="password">Password</FieldLabel>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                aria-invalid={!!form.formState.errors.password}
                {...form.register('password')}
              />
              {form.formState.errors.password && (
                <FieldError>{form.formState.errors.password.message}</FieldError>
              )}
              <FieldDescription>
                Accounts are provisioned by the platform team.
              </FieldDescription>
            </Field>

            {submitError && (
              <div
                role="alert"
                className="rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400"
              >
                {submitError}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? (
                <>
                  <Loader2 className="size-4 animate-spin" /> Signing in…
                </>
              ) : (
                'Sign in'
              )}
            </Button>
          </FieldGroup>
        </form>
      </motion.div>
    </div>
  )
}
