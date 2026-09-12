/**
 * Typed-confirmation dialog for tearing down one environment of an app.
 * Mirrors backend rules: non-prod needs the env name typed; prod removals
 * additionally need the app name typed AND `confirm=true` on the wire — the
 * backend rejects a prod delete without the explicit sign-off flag.
 */

import { useEffect, useState } from 'react'
import { Loader2, TriangleAlert } from 'lucide-react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useDeleteAppEnv } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'
import type { AppStatusResponse, Environment } from '@/lib/api/types'

export function DeleteEnvDialog({
  appName,
  status,
  open,
  onOpenChange,
}: {
  appName: string
  status: AppStatusResponse | undefined
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const deleteEnv = useDeleteAppEnv(appName)

  const [env, setEnv] = useState<Environment | null>(null)
  const [typed, setTyped] = useState('')
  const isProd = env === 'prod'
  const expected = isProd ? appName : (env ?? '')

  // Reset typing whenever the target env or dialog opens.
  useEffect(() => {
    setTyped('')
  }, [env, open])

  const envs = status?.envStatuses.map((item) => item.env) ?? []
  const ready = env !== null && typed.trim() === expected

  const submit = async () => {
    if (!env) return
    try {
      const response = await deleteEnv.mutateAsync({ env, confirm: isProd })
      toast.success('Environment removal submitted', {
        description: response.message || `${env} is being torn down from ${appName}.`,
      })
      onOpenChange(false)
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(`Removal rejected: ${error.message}`, {
          description:
            error.code === 'INVALID_REQUEST' && isProd
              ? 'Prod removals require explicit confirm — retry with the confirmation switch on.'
              : undefined,
        })
      } else {
        toast.error('Something went wrong submitting the removal.')
      }
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <TriangleAlert className="size-4.5 text-destructive" />
            Remove an environment
          </AlertDialogTitle>
          <AlertDialogDescription>
            This tears down {appName}’s environment: the namespace, all services, and every
            provisioned capability in it. This action cannot be undone from the UI.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-1">
          {envs.length > 0 ? (
            <div className="space-y-1.5">
              <Label>Environment</Label>
              <div className="flex flex-wrap gap-2">
                {envs.map((candidate) => (
                  <button
                    key={candidate}
                    type="button"
                    onClick={() => setEnv(candidate)}
                    className={
                      'rounded-lg border px-3 py-1.5 text-sm transition-colors ' +
                      (env === candidate
                        ? 'border-destructive/50 bg-destructive/10 text-destructive'
                        : 'hover:bg-muted')
                    }
                  >
                    {candidate}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              This app has no environments left to remove.
            </p>
          )}

          {env && (
            <div className="space-y-1.5">
              <Label htmlFor="delete-confirm-typed">
                Type <span className="font-mono text-destructive">{expected}</span> to confirm
              </Label>
              <Input
                id="delete-confirm-typed"
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                placeholder={expected}
                autoComplete="off"
              />
              {isProd && (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  Prod removal is sent with explicit confirm — the platform treats it as
                  signed-off.
                </p>
              )}
            </div>
          )}
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button
            variant="destructive"
            onClick={submit}
            disabled={!ready || deleteEnv.isPending}
          >
            {deleteEnv.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Remove {env ?? 'environment'}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
