import React from 'react'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { useSyncStatus } from './useSyncStatus'

function Consumer() { const value = useSyncStatus(); return <div>{value.isConnected ? 'connected' : 'disconnected'}</div> }
it('does not crash outside SyncStatusProvider', () => { render(<Consumer />); expect(screen.getByText('disconnected')).toBeInTheDocument() })
