/**
 * Typed-confirmation dialog for purging an app's record once every
 * environment is gone. The backend refuses while any service row remains, so
 * this dialog is only reachable from that terminal (zombie) state; on success
 * the app no longer exists and the page navigates back to the list. The
 * services repository on GitHub is deliberately kept.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
import { useDeleteApp } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'

export function DeleteAppDialog({
  appName,
  open,
  onOpenChange,
}: {
  appName: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const deleteApp = useDeleteApp(appName)
  const navigate = useNavigate()

  const [typed, setTyped] = useState('')
  useEffect(() => {
    setTyped('')
  }, [open])

  const ready = typed.trim() === appName

  const submit = async () => {
    try {
      const response = await deleteApp.mutateAsync({ confirm: true })
      toast.success(`${response.appName} deleted`, {
        description: 'Record purged — the services repository on GitHub was kept.',
      })
      onOpenChange(false)
      navigate('/apps')
    } catch (error) {
      if (error instanceof ApiError) {
        toast.error(`Delete rejected: ${error.message}`)
      } else {
        toast.error('Something went wrong deleting the app.')
      }
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <TriangleAlert className="size-4.5 text-destructive" />
            Delete {appName}
          </AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes {appName}’s record and its request history, so the name
            becomes available again. Nothing is running — the services repository on GitHub
            stays, and tearing down live environments must happen first via “Remove env”.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-1.5 py-1">
          <Label htmlFor="delete-app-typed">
            Type <span className="font-mono text-destructive">{appName}</span> to confirm
          </Label>
          <Input
            id="delete-app-typed"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={appName}
            autoComplete="off"
          />
        </div>

        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button variant="destructive" onClick={submit} disabled={!ready || deleteApp.isPending}>
            {deleteApp.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Delete app
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
