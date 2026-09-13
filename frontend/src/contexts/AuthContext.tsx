import React, { createContext, useContext, useEffect, useState } from 'react'

export interface AuthUser {
  user_id: number
  email: string
}

interface AuthState {
  user: AuthUser | null
  checking: boolean
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState>({
  user: null,
  checking: true,
  refresh: async () => {},
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [checking, setChecking] = useState(true)

  const refresh = async () => {
    try {
      const res = await fetch('/api/v1/auth/me', { credentials: 'same-origin' })
      if (res.ok) {
        const data = await res.json()
        setUser({ user_id: data.user_id, email: data.email })
      } else {
        setUser(null)
      }
    } catch {
      setUser(null)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  return (
    <AuthContext.Provider value={{ user, checking, refresh }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
