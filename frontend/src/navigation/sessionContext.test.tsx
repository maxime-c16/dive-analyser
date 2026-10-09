import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../contexts/AuthContext'
function State() { const {user,checking,signOut}=useAuth();return <><output>{checking?'checking':user?'signed in':'signed out'}</output><button onClick={()=>void signOut()}>Logout</button></> }
beforeEach(()=>sessionStorage.clear())
afterEach(()=>{ vi.unstubAllGlobals() })
it('a confirmed expired session purges draft/navigation data from previous accounts',async()=>{
  sessionStorage.setItem('message-draft:v1:1:3','old');sessionStorage.setItem('mobile-nav:v1:2:dives','old')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:401}))
  render(<AuthProvider><State /></AuthProvider>)
  await screen.findByText('signed out');expect(sessionStorage.length).toBe(0)
})
it('a transient authentication transport error keeps recovery data',async()=>{
  sessionStorage.setItem('message-draft:v1:1:3','keep')
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')))
  render(<AuthProvider><State /></AuthProvider>)
  await screen.findByText('signed out');expect(sessionStorage.getItem('message-draft:v1:1:3')).toBe('keep')
})
it('logout clears only the current account recovery keys',async()=>{
  sessionStorage.setItem('message-draft:v1:1:3','old');sessionStorage.setItem('message-draft:v1:2:3','keep')
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:true,json:async()=>({user_id:1,email:'fixture@example.test',display_name:'Fixture',is_admin:false,divers:[]})}))
  render(<AuthProvider><State /></AuthProvider>);await screen.findByText('signed in');fireEvent.click(screen.getByRole('button',{name:'Logout'}))
  await waitFor(()=>expect(screen.getByRole('status')).toHaveTextContent('signed out'))
  expect(sessionStorage.getItem('message-draft:v1:1:3')).toBeNull();expect(sessionStorage.getItem('message-draft:v1:2:3')).toBe('keep')
})
