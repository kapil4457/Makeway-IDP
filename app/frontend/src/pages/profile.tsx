/**
 * Profile — the signed-in user's own info: identity from GET /auth/me,
 * session facts derived from the token, and team memberships with roles.
 */

import { motion } from 'framer-motion'
import { Clock, RefreshCw, User, Users } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { useMe } from '@/hooks/use-api'
import { useSession } from '@/hooks/use-session'
import { ApiError } from '@/lib/api/client'

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 truncate font-medium">{children}</span>
    </div>
  )
}

export function ProfilePage() {
  const { data: me, isPending, isError, error, refetch } = useMe()
  const { expiresAt } = useSession()

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <div>
        <h1 className="font-heading text-xl font-semibold tracking-tight">Profile</h1>
        <p className="text-sm text-muted-foreground">Your account and the teams it belongs to.</p>
      </div>

      {isPending && (
        <div className="space-y-3">
          <Skeleton className="h-32 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
      )}

      {isError && (
        <Card className="border-destructive/30">
          <CardHeader className="items-start gap-2">
            <CardTitle className="text-destructive">Couldn’t load your profile</CardTitle>
            <CardDescription>{(error as ApiError).message}</CardDescription>
            <Button variant="outline" size="sm" className="mt-1 w-fit" onClick={() => refetch()}>
              <RefreshCw /> Retry
            </Button>
          </CardHeader>
        </Card>
      )}

      {me && (
        <motion.div
          className="space-y-4"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18, ease: 'easeOut' }}
        >
          <Card className="py-4">
            <CardHeader className="gap-4 px-4">
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-muted text-muted-foreground">
                  <User className="size-5" />
                </span>
                <div className="min-w-0">
                  <CardTitle className="truncate text-sm">{me.email}</CardTitle>
                  <CardDescription>Signed in to Makeway</CardDescription>
                </div>
              </div>
              <Separator />
              <div className="space-y-2">
                <Row label="Email">{me.email}</Row>
                <Row label="User ID">
                  <span className="font-mono text-xs">{me.userId}</span>
                </Row>
                <Row label="Session">
                  {expiresAt ? (
                    <span className="flex items-center gap-1.5">
                      <Clock className="size-3 text-muted-foreground" />
                      expires {new Date(expiresAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  ) : (
                    '—'
                  )}
                </Row>
              </div>
            </CardHeader>
          </Card>

          <Card className="py-4">
            <CardHeader className="gap-3 px-4">
              <div className="flex items-center gap-2">
                <span className="grid size-7 place-items-center rounded-md bg-muted text-muted-foreground">
                  <Users className="size-4" />
                </span>
                <CardTitle className="text-sm">Teams</CardTitle>
                <span className="rounded-full bg-muted px-1.5 text-xs text-muted-foreground">
                  {me.teams.length}
                </span>
              </div>

              {me.teams.length === 0 ? (
                <CardDescription>
                  No team memberships — ask an admin to add you to a team.
                </CardDescription>
              ) : (
                <div className="space-y-2">
                  {me.teams.map((team) => (
                    <div
                      key={team.teamId}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card/50 px-3 py-2 text-sm"
                    >
                      <span className="font-medium">{team.teamName}</span>
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="font-normal">
                          {team.role}
                        </Badge>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardHeader>
          </Card>
        </motion.div>
      )}
    </div>
  )
}
