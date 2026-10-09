// Development-only navigation review. No backend, credentials or real accounts.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import Router from '../../src/router'
import { AuthProvider } from '../../src/contexts/AuthContext'
import { api } from '../../src/services/api'
import '../../src/index.css'
if (!import.meta.env.DEV) throw new Error('Review fixture is development-only')
const admin = new URLSearchParams(location.search).get('role') !== 'diver'
const attempts = [1, 2, 3].map(id => ({ id, dive_code: '103B', height: '3m', performance: 'G', performance_numeric: 3, dive_datetime: '2026-10-03T10:00:00', session_id: 1, diver_id: 1, is_lineup: false, is_sync: false, platform_type: 'springboard', official_dd: 1.6, video_uuid: null, notes: 'Local fixture', visibility: 'public' }))
window.fetch = async input => {
  const url = String(input)
  if (url.endsWith('/auth/me')) return Response.json({ user_id: 900001, email: 'fixture@example.test', display_name: 'Local reviewer', role: 'owner', is_admin: admin, divers: [{ diver_id: 1, access_kind: 'OWNER' }] })
  if (url.includes('/updates')) return Response.json({ schema: 1, version: 'v0.0.0', frontend_sha: 'a'.repeat(40), notes: [{ id: 'local-review', date: '2026-10-09', title: 'Navigation simplifiée', body: 'Données locales pour vérifier la navigation et les overlays.' }] })
  return Response.json({ items: [], unread_count: 0 })
}
api.defaults.adapter = async config => {
  const url = config.url || ''
  let data: unknown = []
  if (url.endsWith('/dives')) data = attempts
  else if (url.endsWith('/divers')) data = [{ id: 1, display_name: 'Fixture diver', is_primary_user: true }]
  else if (url.includes('/notifications')) data = { items: [], unread_count: 0 }
  else if (url.includes('/social')) data = { liked: false, like_count: 0, comment_count: 0 }
  else if (url.includes('/comments')) data = { items: [], next_before: null }
  else if (url.includes('/media/')) data = { status: 'missing', can_request: false, available_renditions: [] }
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}
const router = createMemoryRouter([{ path: '*', element: <Router /> }], { initialEntries: ['/dives'] })
createRoot(document.getElementById('root')!).render(<AuthProvider><RouterProvider router={router} /></AuthProvider>)
