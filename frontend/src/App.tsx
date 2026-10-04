import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import Router from './router'
import { SyncStatusProvider } from './contexts/SyncStatusContext'
import SyncNotifications from './components/SyncNotifications'
import MilestoneNotifier from './components/MilestoneNotifier'
import SyncErrorHandler from './components/SyncErrorHandler'
import { AuthProvider, useAuth } from './contexts/AuthContext'

function MemberSyncBoundary({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  return user?.is_admin ? <SyncStatusProvider>{children}</SyncStatusProvider> : <>{children}</>
}

function App() {
  return (
    <AuthProvider>
      <MemberSyncBoundary>
        <BrowserRouter>
          <Router />
        </BrowserRouter>
        <SyncNotifications />
        <MilestoneNotifier />
        <SyncErrorHandler />
      </MemberSyncBoundary>
    </AuthProvider>
  )
}

export default App
