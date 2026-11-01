import React from 'react'
import { MemoryRouter } from 'react-router-dom'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import RouteErrorBoundary from './RouteErrorBoundary'
import { chunkRecovery } from '../utils/chunkLoad'

function Broken(): React.ReactElement {
  throw new Error('Failed to fetch dynamically imported module: assets/MemberProfile-x.js')
}

function Probe(): React.ReactElement {
  return <p>Route is fine</p>
}

function renderBoundary(path: string, element: React.ReactElement) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <RouteErrorBoundary>{element}</RouteErrorBoundary>
    </MemoryRouter>,
  )
}

describe('RouteErrorBoundary', () => {
  it('renders a recovery panel instead of the raw router error screen', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    try {
      renderBoundary('/users/15', <Broken />)
      expect(screen.getByRole('alert')).toBeInTheDocument()
      expect(screen.getByText('This page could not open.')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
      expect(screen.getByRole('link', { name: 'Back to Library' })).toHaveAttribute('href', '/dives')
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('the Reload action triggers one full page reload', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const reload = vi.spyOn(chunkRecovery, 'reload').mockImplementation(() => undefined)
    try {
      renderBoundary('/community', <Broken />)
      fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
      expect(reload).toHaveBeenCalledTimes(1)
    } finally {
      vi.restoreAllMocks()
    }
  })

  it('a healthy route renders normally', () => {
    renderBoundary('/users/15', <Probe />)
    expect(screen.getByText('Route is fine')).toBeInTheDocument()
  })
})
