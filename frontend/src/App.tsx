import React from 'react'
import { BrowserRouter } from 'react-router-dom'
import Router from './router'
import { SyncStatusProvider } from './contexts/SyncStatusContext'
import SyncNotifications from './components/SyncNotifications'
import MilestoneNotifier from './components/MilestoneNotifier'
import SyncErrorHandler from './components/SyncErrorHandler'
import './App.css'

function App() {
  return (
    <SyncStatusProvider>
      <BrowserRouter>
        <Router />
      </BrowserRouter>
      <SyncNotifications />
      <MilestoneNotifier />
      <SyncErrorHandler />
    </SyncStatusProvider>
  )
}

export default App
