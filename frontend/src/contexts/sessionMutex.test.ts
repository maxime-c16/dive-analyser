import { expect, it } from 'vitest'
import { runSessionMutation } from './sessionMutex'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

/**
 * Logout and login responses race at the browser: whichever Set-Cookie the
 * browser applies last wins. Serialization guarantees a login POST is never
 * in flight while a logout POST is, so a logout response can never clear a
 * newer session's cookie (and vice versa).
 */
it('never overlaps session mutations: a login waits for a pending logout', async () => {
  const logout = deferred<string>()
  const order: string[] = []
  const logoutTask = runSessionMutation(async () => {
    order.push('logout-start')
    const result = await logout.promise
    order.push('logout-end')
    return result
  })
  let loginStarted = false
  const loginTask = runSessionMutation(async () => {
    loginStarted = true
    order.push('login')
    return 'fresh-cookie'
  })
  // Let the microtask queue run: the login must not start while logout holds
  // the lock, i.e. no login request is issued before logout settles.
  await Promise.resolve()
  await Promise.resolve()
  expect(loginStarted).toBe(false)
  logout.resolve('cleared')
  expect(await logoutTask).toBe('cleared')
  expect(await loginTask).toBe('fresh-cookie')
  expect(order).toEqual(['logout-start', 'logout-end', 'login'])
})

it('keeps the queue usable after a failing mutation', async () => {
  await expect(runSessionMutation(async () => { throw new Error('offline') })).rejects.toThrow('offline')
  expect(await runSessionMutation(async () => 'next')).toBe('next')
})
