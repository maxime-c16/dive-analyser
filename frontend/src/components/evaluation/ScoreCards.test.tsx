import { fireEvent, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import EvaluationIntro from './ScoreCards'
afterEach(() => vi.restoreAllMocks())
it('hides the intro before cancelling the filled animations on completion', () => {
  const states: string[] = []
  vi.spyOn(HTMLElement.prototype, 'offsetParent', 'get').mockImplementation(function (this: HTMLElement) { return this.parentElement })
  Object.defineProperty(Element.prototype, 'animate', { configurable: true, writable: true, value: vi.fn(function (this: Element) {
    return { cancel: () => states.push((this.closest('.eval-intro') as HTMLElement)?.style.visibility) } as unknown as Animation
  }) })
  const onDone = vi.fn()
  const { container } = render(<EvaluationIntro onDone={onDone} onSkip={vi.fn()} />)
  fireEvent(window, new Event('resize'))
  expect(onDone).toHaveBeenCalledOnce()
  expect(states.length).toBeGreaterThan(0)
  expect(states.every(state => state === 'hidden')).toBe(true)
  expect((container.querySelector('.eval-intro') as HTMLElement).style.visibility).toBe('hidden')
})
