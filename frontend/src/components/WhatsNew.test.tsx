import React from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { WhatsNewProvider, WhatsNewButton, parseManifest } from './WhatsNew'

vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { user_id: 42 } }) }))
const key = 'dive-analyser:updates:v1:42'
const note = { id: 'first', date: '2026-10-05', title: 'First improvement', body: 'The first description.' }
const second = { ...note, id: 'second', title: 'Second improvement' }
const manifest = (notes = [note]) => ({ schema: 1, version: '', frontend_sha: 'a'.repeat(40), notes })
let current = manifest()
function mount() { return render(<WhatsNewProvider><WhatsNewButton /><button>Workspace action</button></WhatsNewProvider>) }

beforeEach(() => {
  const values = new Map<string, string>()
  vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value) }, clear: () => values.clear() })
  current = manifest()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => current })))
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async (_: string, callback: () => unknown) => callback() } })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('update hints', () => {
  it('groups updates and persists dismissal across reloads and redeploys', async () => {
    current = manifest([note, second])
    const view = mount()
    await screen.findByRole('status')
    expect(screen.getAllByRole('status')).toHaveLength(1)
    expect(screen.getByText('2 improvements are ready to explore.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss update notification' }))
    expect(JSON.parse(localStorage.getItem(key)!).seen).toEqual(['first', 'second'])
    view.unmount(); mount()
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: "What's new" }))
    expect(screen.getByRole('dialog')).toHaveTextContent(note.body)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('does not spam successive deployments and freezes the open history', async () => {
    mount(); await screen.findByRole('status')
    fireEvent.click(screen.getByRole('button', { name: "See what's new →" }))
    expect(screen.getByRole('dialog')).toHaveTextContent(note.title)
    current = manifest([second, note])
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(screen.getByRole('dialog')).not.toHaveTextContent(second.title)
    fireEvent.click(screen.getByRole('button', { name: 'Close update details' }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem(key)!).seen).toEqual(['first'])
    expect(screen.getByLabelText('Unread updates')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: "What's new" }))
    expect(screen.getByRole('dialog')).toHaveTextContent(second.title)
  })

  it('synchronizes dismissal from another tab', async () => {
    mount(); await screen.findByRole('status')
    localStorage.setItem(key, JSON.stringify({ seen: ['first'], lastShown: Date.now() }))
    fireEvent(window, new StorageEvent('storage', { key }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows only newly arrived notes after the cooldown expires', async () => {
    localStorage.setItem(key, JSON.stringify({ seen: ['first'], lastShown: Date.now() - 86_400_001 }))
    current = manifest([second, note])
    mount(); await screen.findByRole('status')
    expect(screen.getByRole('status')).toHaveTextContent(second.title)
    expect(screen.getByRole('status')).not.toHaveTextContent(note.title)
  })

  it('removes an ineligible hint on rollback without resetting the cooldown', async () => {
    mount(); await screen.findByRole('status')
    const claimed = localStorage.getItem(key)
    current = manifest([])
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(localStorage.getItem(key)).toEqual(claimed)
    current = manifest()
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('keeps manual history when storage is unavailable', async () => {
    vi.spyOn(localStorage, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    mount(); await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: "What's new" }))
    expect(screen.getByRole('dialog')).toHaveTextContent(note.title)
  })

  it('suppresses hints during video playback', async () => {
    const video = document.createElement('video')
    Object.defineProperty(video, 'paused', { value: false })
    document.body.append(video)
    mount(); await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    video.remove()
  })

  it('rejects malformed and duplicate notes', () => {
    expect(parseManifest(manifest([note, note]))).toBeNull()
    expect(parseManifest({ schema: 2, notes: [] })).toBeNull()
    expect(parseManifest(manifest([{ ...note, body: 'x'.repeat(601) }]))).toBeNull()
  })

  it('shows the release version in the panel header', async () => {
    current = { ...manifest(), version: 'v1.2.3' }
    mount(); await screen.findByRole('status')
    fireEvent.click(screen.getByRole('button', { name: "What's new" }))
    expect(screen.getByRole('dialog')).toHaveTextContent('Version v1.2.3')
  })
})
