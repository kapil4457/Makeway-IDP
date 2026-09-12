import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '@/components/layout/app-shell'
import { RequireAuth } from '@/components/layout/require-auth'
import { Toaster } from '@/components/ui/sonner'
import { AppDetailPage } from '@/pages/app-detail'
import { AppsPage } from '@/pages/apps'
import { ClustersPage } from '@/pages/clusters'
import { LoginPage } from '@/pages/login'
import { NewAppPage } from '@/pages/new-app'
import { NotFoundPage } from '@/pages/not-found'
import { ProfilePage } from '@/pages/profile'

export default function App() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route index element={<AppsPage />} />
            {/* The dashboard IS the apps list — /apps has no page of its own. */}
            <Route path="/apps" element={<Navigate to="/" replace />} />
            <Route path="/apps/new" element={<NewAppPage />} />
            <Route path="/apps/:appName" element={<AppDetailPage />} />
            <Route path="/clusters" element={<ClustersPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
      <Toaster position="top-right" richColors closeButton />
    </>
  )
}
