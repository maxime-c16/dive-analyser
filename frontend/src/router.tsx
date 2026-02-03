import React from 'react'
import { Routes, Route, Link, useLocation, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Analytics from './pages/Analytics'
import Dives from './pages/Dives'
import Sessions from './pages/Sessions'
import Journey from './pages/Journey'

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const location = useLocation()
  const isActive = location.pathname === to

  return (
    <Link
      to={to}
      className={`px-3 py-2 rounded-lg text-sm font-medium transition ${
        isActive
          ? 'bg-cyan-500/20 text-cyan-400'
          : 'text-gray-300 hover:text-white hover:bg-gray-800'
      }`}
    >
      {children}
    </Link>
  )
}

function Router() {
  return (
    <div className="min-h-screen bg-gray-900">
      {/* Navigation */}
      <nav className="bg-gray-900/80 backdrop-blur-lg border-b border-gray-800 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-8">
              <Link to="/" className="flex items-center gap-2 group">
                <span className="text-2xl">🤿</span>
                <span className="text-xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent group-hover:from-cyan-300 group-hover:to-blue-400 transition">
                  Diving Analytics
                </span>
              </Link>
              <div className="hidden md:flex items-center gap-1">
                <NavLink to="/">Dashboard</NavLink>
                <NavLink to="/journey">Journey</NavLink>
                <NavLink to="/analytics">Analytics</NavLink>
                <NavLink to="/dives">Dives</NavLink>
                <NavLink to="/sessions">Sessions</NavLink>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-xs text-gray-500 hidden sm:block">
                Powered by your training data
              </span>
            </div>
          </div>
        </div>
      </nav>

      {/* Mobile Navigation */}
      <div className="md:hidden bg-gray-800/50 border-b border-gray-700 px-4 py-2">
        <div className="flex gap-2 overflow-x-auto">
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/journey">Journey</NavLink>
          <NavLink to="/analytics">Analytics</NavLink>
          <NavLink to="/dives">Dives</NavLink>
          <NavLink to="/sessions">Sessions</NavLink>
        </div>
      </div>

      {/* Routes */}
      <main className="max-w-7xl mx-auto">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/journey" element={<Journey />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/dives" element={<Dives />} />
          <Route path="/sessions" element={<Sessions />} />
        </Routes>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-12 py-6 text-center text-gray-500 text-sm">
        <p>Diving Analytics Dashboard • Track your progress, improve your performance</p>
      </footer>
    </div>
  )
}

export default Router
