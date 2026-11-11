import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../services/api'
import TechniqueWorkspace from './TechniqueWorkspace'
import '../../i18n'

vi.mock('./TechniqueHistory', () => ({
  default: ({ diver }: { diver: number }) => <div>Technique history for diver {diver}</div>,
}))

const originalAdapter = api.defaults.adapter
afterEach(() => { api.defaults.adapter = originalAdapter })

it('loads contexts through the versioned API instead of the SPA fallback', async () => {
  api.defaults.adapter = async config => {
    if (config.url !== '/api/v1/technique-history/contexts') {
      return { data: '<!doctype html><html></html>', status: 200, statusText: 'OK', headers: {}, config }
    }
    expect(config.params.code).toBe('5132D')
    return {
      data: { items: [{ diver_id: 1, diver_name: 'Demo', code: '5132D', apparatus: 'springboard', height: '1m', position: 'D', sync: false, eligible: 108 }], next: null },
      status: 200, statusText: 'OK', headers: {}, config,
    }
  }
  render(<TechniqueWorkspace viewer={1} code="5132D" height={null} />)
  expect(await screen.findByText('Technique history for diver 1')).toBeInTheDocument()
})
