import { clearNavigationSession } from '../navigation/sessionContext'
import { clearLibraryCache } from '../services/libraryCache'
import { clearCodeSummaryCache } from '../services/codeSummariesApi'
import { clearCodeCommunityCache } from '../services/codeCommunityApi'
import { clearIntentData } from '../services/intentCache'
import { resetPlaybackWarming } from '../utils/playbackWarming'
import type { AvatarIdentity } from '../components/MemberAvatar'
import React, { createContext, useContext, useEffect, useRef, useState } from 'react'

export interface AuthUser extends AvatarIdentity {
  user_id: number
  email: string
  display_name: string
  role: 'owner' | 'friend'
  is_admin?: boolean
  divers: { diver_id: number; access_kind: string }[]
  /** Server-side default-off feature switches. */
  features?: { calendar?: boolean }
}

export function isFriend(user: AuthUser | null): boolean {
  return user?.role === 'friend'
}

interface AuthState {
  user: AuthUser | null
  checking: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState>({
  user: null,
  checking: true,
  refresh: async () => {},
  signOut: async () => {},
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [checking, setChecking] = useState(true)

  const generation = useRef(0)
  const signingOut = useRef(false)

  const clearDerivedReads = () => {
    clearIntentData()
    clearLibraryCache()
    clearCodeSummaryCache()
    clearCodeCommunityCache()
  }

  const refresh = async () => {
    if (signingOut.current) return
    const started = ++generation.current
    clearDerivedReads()
    try {
      const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      if (started !== generation.current) return
      if (res.ok) {
        const data = await res.json()
        if (started !== generation.current) return
        clearDerivedReads()
        setUser({
          user_id: data.user_id,
          email: data.email,
          display_name: data.display_name ?? data.email,
          avatar_url: data.avatar_url ?? null,
          avatar_hud: data.avatar_hud ?? 'reticle',
          is_admin: data.is_admin === true,
          role: data.role === 'friend' ? 'friend' : 'owner',
          divers: Array.isArray(data.divers) ? data.divers : [],
          features: { calendar: data.features?.calendar === true },
        })
      } else {
        // Signed-out responses tear down media authorization; any warm in
        // flight must not keep pulling potentially signed URLs after that.
        if (res.status === 401 || res.status === 403) clearNavigationSession()
        clearLibraryCache()
        resetPlaybackWarming()
        setUser(null)
      }
    } catch {
      if (started !== generation.current) return
      clearLibraryCache()
      // A transport error resolving /me leaves us signed out locally; warms
      // started while authenticated must still be torn down.
      resetPlaybackWarming()
      setUser(null)
    } finally {
      if (started === generation.current) {
        clearDerivedReads()
        setChecking(false)
      }
    }
  }

  const signOut = async () => {
    if (signingOut.current) return
    signingOut.current = true
    ++generation.current
    clearNavigationSession(user?.user_id)
    clearDerivedReads()
    setUser(null)
    setChecking(false)
    // Sign-out begins here: tear warm transfers down before the network
    // round-trip, so a stalled logout cannot keep signed-URL pulls running.
    resetPlaybackWarming()
    try {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      })
    } catch {
      // Cookie is HttpOnly; a network failure still means dropping local state.
    } finally {
      signingOut.current = false
      clearDerivedReads()
      resetPlaybackWarming()
      setUser(null)
    }
  }

  useEffect(() => {
    refresh()
    return () => { ++generation.current }
  }, [])

  return (
    <AuthContext.Provider value={{ user, checking, refresh, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
