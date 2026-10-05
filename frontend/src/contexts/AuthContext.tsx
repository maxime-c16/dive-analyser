import { clearLibraryCache } from '../services/libraryCache'
import { clearIntentData } from '../services/intentCache'
import React, { createContext, useContext, useEffect, useState } from 'react'

export interface AuthUser {
  user_id: number
  email: string
  display_name: string
  role: 'owner' | 'friend'
  is_admin?: boolean
  divers: { diver_id: number; access_kind: string }[]
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

  const refresh = async () => {
    clearIntentData()
    try {
      const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      if (res.ok) {
        const data = await res.json()
        setUser({
          user_id: data.user_id,
          email: data.email,
          display_name: data.display_name ?? data.email,
          is_admin: data.is_admin === true,
          role: data.role === 'friend' ? 'friend' : 'owner',
          divers: Array.isArray(data.divers) ? data.divers : [],
        })
      } else {
        clearLibraryCache()
        setUser(null)
      }
    } catch {
      clearLibraryCache()
      setUser(null)
    } finally {
      setChecking(false)
    }
  }

  const signOut = async () => {
    clearIntentData()
    clearLibraryCache()
    try {
      await fetch('/api/v1/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
      })
    } catch {
      // Cookie is HttpOnly; a network failure still means dropping local state.
    } finally {
      clearLibraryCache()
      setUser(null)
    }
  }

  useEffect(() => {
    refresh()
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
