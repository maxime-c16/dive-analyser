import { afterEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ScoreChart, { type ChartPoint } from './ScoreChart'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
it('keeps curves and usual bands inside resolved segments on a mobile chart', () => {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(320)
  vi.stubGlobal('matchMedia', () => ({ matches: true }))
  const points: ChartPoint[] = [0, 1, 2, 3].map(i => ({ key: i, segment: i < 2 ? 1 : 2, highlight: i >= 2, occurredAt: i * 1000 + 1000, month: '2026-01', monthLabel: 'Jan', value: i < 2 ? 7 : 0, band: i < 2 ? 'G' : 'F', curveMedian: i < 2 ? 7 : 0, curveQ1: i < 2 ? 6 : 0, curveQ3: i < 2 ? 8 : 1 }))
  const select = vi.fn()
  const { container } = render(<ScoreChart points={points} smoothing={3} selected={0} onSelect={select} label="Technique ratings" boundary={{ start: 0, end: 5000, uncertainUntil: 500 }} markers={[{ at: 2000 }, { at: 3000 }]} />)
  expect(container.querySelector('.ca-medline')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
  expect(container.querySelector('.ca-band')?.getAttribute('d')?.match(/M/g)).toHaveLength(2)
  expect(container.querySelector('pattern')).toBeInTheDocument()
  expect(container.querySelector('rect[fill-opacity=".08"]')).toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('group', { name: /Technique ratings/ }), { key: 'ArrowRight' })
  expect(select).toHaveBeenCalledWith(1)
})
