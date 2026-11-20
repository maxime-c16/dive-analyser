import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import CorrectionScores from './CorrectionScores'
import type { Attempt } from '../../utils/attemptPresentation'
import '../../i18n'

const correction = (id: number, date: string, end: string | null = null) =>
  ({ id, label: `Correction ${id}`, start_at: date, start_id: 0, end_at: end, end_id: 0, uncertain_until: null })

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('uses the immutable dive date and the exclusive saved end, including after an edit', () => {
  const attempts = [
    { id: 1, performance: 'G', history_occurred_at: '2026-01-01T10:00:00', dive_datetime: '2026-04-01T10:00:00' },
    { id: 2, performance: 'F', history_occurred_at: '2026-01-02T10:00:00', dive_datetime: '2026-01-02T10:00:00' },
  ] as Attempt[]
  const active = correction(1, '2026-01-01T10:00:00', '2026-01-02T10:00:00')
  const view = render(<CorrectionScores attempts={attempts} corrections={[active]} />)
  expect(screen.getByText('1 rated dive on the chart · score 7.0')).toBeInTheDocument()
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  view.rerender(<CorrectionScores attempts={attempts} corrections={[{ ...active, end_at: '2026-01-03T10:00:00' }]} />)
  expect(screen.getByText('2 rated dives on the chart · median of these dives 3.5')).toBeInTheDocument()
})

it('compares microseconds before dive IDs at an anchored start and end', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  const at = (value: string) => `2026-01-01T10:00:${value}`
  const attempts = [
    { id: 11, performance: 'F', dive_datetime: at('00.123400') },
    { id: 9, performance: 'F', dive_datetime: at('00.123900') },
    { id: 10, performance: 'G', dive_datetime: at('00.1239') },
    { id: 22, performance: 'M', dive_datetime: at('01.123400') },
    { id: 19, performance: 'P', dive_datetime: at('01.123500+00:00') },
    { id: 20, performance: 'F', dive_datetime: at('01.123500Z') },
    { id: 18, performance: 'F', dive_datetime: at('01.123900') },
  ] as Attempt[]
  const active = { ...correction(1, at('00.123900'), at('01.123500')), start_id: 10, end_id: 20 }
  const { container } = render(<CorrectionScores attempts={attempts} corrections={[active]} />)
  expect(screen.getByText('3 rated dives on the chart · median of these dives 7.0')).toBeInTheDocument()
  expect([...container.querySelectorAll('.ca-score-point')].map(point => point.getAttribute('fill-opacity')))
    .toEqual(['0.55', '0.55', '0.9', '0.9', '0.9', '0.55', '0.55'])
})

it('keeps 36 overlapping corrections operable in a shared-date group on mobile', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  const corrections = Array.from({ length: 36 }, (_, index) => correction(index + 1, '2026-01-01T10:00:00'))
  render(<CorrectionScores attempts={[]} corrections={corrections} />)
  const lane = screen.getByRole('group', { name: 'Correction starts' })
  expect(within(lane).getAllByRole('button')).toHaveLength(1)
  const group = within(lane).getByRole('button', { name: /Correction 36 of 36/ })
  expect(group).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(group)
  expect(group).toHaveAccessibleName(/Correction 1 of 36/)
  expect(screen.getByRole('combobox')).toHaveValue('1')
  fireEvent.change(screen.getByRole('combobox'), { target: { value: '20' } })
  expect(screen.getByRole('img', { name: /Correction 20/ })).toBeInTheDocument()
  expect(screen.getByText('Correction 20', { selector: 'strong' })).toBeInTheDocument()
  fireEvent.click(group)
  expect(screen.getByRole('combobox')).toHaveValue('21')
})
