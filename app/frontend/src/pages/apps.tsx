import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowUpRight, Boxes, Plus, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useApps } from '@/hooks/use-api'
import { ApiError } from '@/lib/api/client'

function PageHeader() {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h1 className="font-heading text-xl font-semibold tracking-tight">Apps</h1>
        <p className="text-sm text-muted-foreground">
          Applications onboarded onto the platform for your teams.
        </p>
      </div>
      <Button asChild>
        <Link to="/apps/new">
          <Plus /> New app
        </Link>
      </Button>
    </div>
  )
}

function AppCard({ app }: { app: { appId: number; appName: string; teamName?: string | null; createdAt: string; appRepoUrl?: string | null } }) {
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0 } }}
      whileHover={{ y: -2 }}
      transition={{ type: 'spring', stiffness: 320, damping: 28 }}
    >
      <Link to={`/apps/${app.appName}`} className="block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
        <Card className="group h-full transition-colors hover:border-primary/30">
          <CardHeader>
            <div className="flex items-start justify-between gap-2">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary">
                <Boxes className="size-4.5" />
              </span>
              <ArrowUpRight className="size-4 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground" />
            </div>
            <CardTitle className="truncate group-hover:underline group-hover:decoration-primary/30 group-hover:underline-offset-4">
              {app.appName}
            </CardTitle>
            <CardDescription>
              {app.teamName ?? 'Unknown team'} · created {new Date(app.createdAt).toLocaleDateString()}
            </CardDescription>
          </CardHeader>
        </Card>
      </Link>
    </motion.div>
  )
}

export function AppsPage() {
  const { data: apps, isPending, isError, error, refetch } = useApps()

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader />

      {isPending && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Card key={index} className="h-36">
              <CardHeader className="gap-3">
                <Skeleton className="size-9 rounded-lg" />
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-24" />
              </CardHeader>
            </Card>
          ))}
        </div>
      )}

      {isError && (
        <Card className="border-destructive/30">
          <CardHeader className="items-start gap-2">
            <CardTitle className="text-destructive">Couldn’t load apps</CardTitle>
            <CardDescription>{(error as ApiError).message}</CardDescription>
            <Button variant="outline" size="sm" className="mt-1 w-fit" onClick={() => refetch()}>
              <RefreshCw /> Retry
            </Button>
          </CardHeader>
        </Card>
      )}

      {apps && (
        apps.length === 0 ? (
          <div className="grid place-items-center rounded-xl border border-dashed py-20 text-center">
            <div className="flex max-w-sm flex-col items-center gap-2">
              <span className="grid size-11 place-items-center rounded-xl bg-muted text-muted-foreground">
                <Boxes className="size-5" />
              </span>
              <p className="font-medium">No apps yet</p>
              <p className="text-sm text-muted-foreground">
                Apps you create for your teams will appear here.
              </p>
              <Button asChild size="sm" className="mt-2">
                <Link to="/apps/new">
                  <Plus /> Create your first app
                </Link>
              </Button>
            </div>
          </div>
        ) : (
          <motion.div
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
            initial="hidden"
            animate="show"
            variants={{ show: { transition: { staggerChildren: 0.05 } } }}
          >
            {apps.map((app) => (
              <AppCard key={app.appId} app={app} />
            ))}
          </motion.div>
        )
      )}
    </div>
  )
}
