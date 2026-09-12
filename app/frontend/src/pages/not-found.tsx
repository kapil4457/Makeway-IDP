import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'

import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <div className="grid min-h-dvh place-items-center p-6">
      <div className="flex max-w-sm flex-col items-center gap-3 text-center">
        <span className="grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground">
          <Compass className="size-5" />
        </span>
        <h1 className="font-heading text-lg font-semibold tracking-tight">Page not found</h1>
        <p className="text-sm text-muted-foreground">
          The route you followed doesn’t exist in this dashboard.
        </p>
        <Button asChild size="sm" className="mt-1">
          <Link to="/">Back to apps</Link>
        </Button>
      </div>
    </div>
  )
}