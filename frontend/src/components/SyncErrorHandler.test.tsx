import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import i18n from '../i18n'
import SyncErrorHandler from './SyncErrorHandler'

const status = {
  currentSync: { status: 'error' },
  lastEvent: { type: 'sync_error', timestamp: '2026-10-06T10:00:00Z', sync_id: 'sync-1', data: {} },
}
vi.mock('../hooks/useSyncStatus', () => ({ useSyncStatus: () => status }))

describe('SyncErrorHandler', () => {
  afterEach(async () => { await i18n.changeLanguage('en') })

  it('does not add a duplicate alert or lose the message when the language changes', async () => {
    render(<SyncErrorHandler />)
    expect(screen.getAllByText('Unknown error occurred').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Sync Error')).toHaveLength(1)

    await act(async () => { await i18n.changeLanguage('fr') })
    expect(screen.getAllByText(i18n.t('sync.error'))).toHaveLength(1)
    expect(screen.getAllByText(i18n.t('sync.unknownError')).length).toBeGreaterThan(0)
  })
})
