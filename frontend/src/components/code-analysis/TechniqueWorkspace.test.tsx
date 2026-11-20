import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../services/api'
import TechniqueWorkspace from './TechniqueWorkspace'
import '../../i18n'

vi.mock('./TechniqueAdjustments', () => ({
  default: ({ diver, context, contextPicker }: { diver: number; context: { height: string }; contextPicker?: import('react').ReactNode }) =>
    <>{contextPicker}<div>Technique history for diver {diver} at {context.height}</div></>,
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
  expect(await screen.findByText('Technique history for diver 1 at 1m')).toBeInTheDocument()
})

it('defaults to the most recorded 201C group and respects manual and page height selections', async () => {
  const context = { diver_id: 1, diver_name: 'Demo', code: '201C', position: 'C', sync: false }
  const items = [
    { ...context, apparatus: 'platform', height: '5m', eligible: 4 },
    { ...context, apparatus: 'springboard', height: '1m', eligible: 276 },
    { ...context, apparatus: 'springboard', height: '3m', eligible: 113 },
  ]
  const load = vi.fn(async config => ({
    data: {
      items: config.params.after ? items.slice(0, 1) : items.filter(item => !config.params.height || item.height === config.params.height),
      next: config.params.after || config.params.height ? null : 'next-page',
    },
    status: 200, statusText: 'OK', headers: {}, config,
  }))
  api.defaults.adapter = load

  const { rerender } = render(<TechniqueWorkspace viewer={1} code="201C" height={null} />)
  expect(await screen.findByText('Technique history for diver 1 at 1m')).toBeInTheDocument()
  const picker = screen.getByRole('combobox', { name: 'Dives to view' })
  const platform = screen.getByRole<HTMLOptionElement>('option', { name: /5m.*4 dives/ })
  fireEvent.change(picker, { target: { value: platform.value } })
  expect(screen.getByText('Technique history for diver 1 at 5m')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'More dive contexts' }))
  expect(await screen.findByText('Technique history for diver 1 at 5m')).toBeInTheDocument()
  expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ params: expect.objectContaining({ after: 'next-page' }) }))

  rerender(<TechniqueWorkspace viewer={1} code="201C" height="3m" />)
  expect(await screen.findByText('Technique history for diver 1 at 3m')).toBeInTheDocument()
  expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ params: { code: '201C', order: 'volume', height: '3m', after: '' } }))
})
