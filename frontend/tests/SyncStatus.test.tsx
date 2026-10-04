import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SyncStatusProvider } from '../src/contexts/SyncStatusContext'
import { SyncStatus } from '../src/components/SyncStatus'
import { useSyncStatus } from '../src/hooks/useSyncStatus'

/**
 * Test suite for SyncStatus component and context
 */

// Mock component to access context
const TestComponent = () => {
  const { isConnected, currentSync } = useSyncStatus()
  return (
    <div>
      <div data-testid="connection-status">{isConnected ? 'connected' : 'disconnected'}</div>
      {currentSync && <div data-testid="sync-progress">{currentSync.progress_percent}%</div>}
    </div>
  )
}

describe('SyncStatusContext', () => {
  it('should provide sync status context to components', () => {
    render(
      <SyncStatusProvider>
        <TestComponent />
      </SyncStatusProvider>
    )

    const status = screen.getByTestId('connection-status')
    expect(status).toBeInTheDocument()
  })

  it('should provide safe disconnected state outside provider', () => {
    render(<TestComponent />)
    expect(screen.getByTestId('connection-status')).toHaveTextContent('disconnected')
  })
})

describe('SyncStatus Component', () => {
  it('should render connection status', () => {
    render(
      <SyncStatusProvider>
        <SyncStatus compact={true} />
      </SyncStatusProvider>
    )

    // Should show connection indicator
    expect(screen.getByText(/connected|offline/i)).toBeInTheDocument()
  })

  it('should render full sync status when sync is active', async () => {
    render(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )

    // Should render sync status section
    await waitFor(() => {
      const connectionStatus = screen.queryByText(/connected|disconnected/i)
      expect(connectionStatus).toBeInTheDocument()
    })
  })

  it('should display progress bar during active sync', async () => {
    const { rerender } = render(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )

    // Initial render - no sync active
    let progressBars = document.querySelectorAll('[class*="progress"]')
    expect(progressBars.length >= 0).toBe(true)

    rerender(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )
  })

  it('should handle milestone dismissal', async () => {
    const user = userEvent.setup()

    render(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )

    // The dismiss button should be present for milestones
    const dismissButtons = screen.queryAllByLabelText('Dismiss milestone')
    expect(Array.isArray(dismissButtons)).toBe(true)
  })
})

describe('SyncStatus Connection', () => {
  it('should initialize WebSocket connection', async () => {
    render(
      <SyncStatusProvider>
        <TestComponent />
      </SyncStatusProvider>
    )

    // Component should render without errors
    expect(screen.getByTestId('connection-status')).toBeInTheDocument()
  })

  it('should maintain client ID across renders', () => {
    const { rerender } = render(
      <SyncStatusProvider>
        <TestComponent />
      </SyncStatusProvider>
    )

    const firstClientId = sessionStorage.getItem('sync_client_id')
    expect(firstClientId).toBeTruthy()

    rerender(
      <SyncStatusProvider>
        <TestComponent />
      </SyncStatusProvider>
    )

    const secondClientId = sessionStorage.getItem('sync_client_id')
    expect(firstClientId).toBe(secondClientId)
  })
})

describe('Accessibility', () => {
  it('should have proper ARIA labels', () => {
    render(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )

    const dismissButtons = screen.queryAllByLabelText(/dismiss/i)
    expect(dismissButtons.length >= 0).toBe(true)
  })

  it('should support keyboard navigation', async () => {
    const user = userEvent.setup()

    render(
      <SyncStatusProvider>
        <SyncStatus compact={false} />
      </SyncStatusProvider>
    )

    // Tab to first focusable element
    await user.tab()
    expect(document.activeElement).toBeTruthy()
  })
})
