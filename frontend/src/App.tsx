import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import Router from './router'
import { SyncStatusProvider } from './contexts/SyncStatusContext'
import SyncNotifications from './components/SyncNotifications'
import MilestoneNotifier from './components/MilestoneNotifier'
import SyncErrorHandler from './components/SyncErrorHandler'
import { AuthProvider } from './contexts/AuthContext'

function App() {
  return (
    <AuthProvider>
      <SyncStatusProvider>
        <BrowserRouter>
          <Router />
        </BrowserRouter>
        <SyncNotifications />
        <MilestoneNotifier />
        <SyncErrorHandler />
      </SyncStatusProvider>
    </AuthProvider>
  )
}

export default App
