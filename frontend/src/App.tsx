import React from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import Router from './router'
import { SyncStatusProvider } from './contexts/SyncStatusContext'
import SyncNotifications from './components/SyncNotifications'
import MilestoneNotifier from './components/MilestoneNotifier'
import SyncErrorHandler from './components/SyncErrorHandler'
import AchievementToaster from './components/achievements/AchievementToaster'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { I18nProvider } from './i18n/I18nProvider'

function MemberSyncBoundary({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  return user?.is_admin ? <SyncStatusProvider>{children}</SyncStatusProvider> : <>{children}</>
}

// The toaster links to the profile, so it must render inside the router.
const appRouter = createBrowserRouter([{ path: '*', element: <><Router /><AchievementToaster /></> }])

function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <MemberSyncBoundary>
          <RouterProvider router={appRouter} />
          <SyncNotifications />
          <MilestoneNotifier />
          <SyncErrorHandler />
        </MemberSyncBoundary>
      </AuthProvider>
    </I18nProvider>
  )
}

export default App
