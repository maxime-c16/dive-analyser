import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { useBottomAction, useMobileNavPolicy, useMobileViewport } from './useMobileNavigation'
import { useModalOverlay } from '../utils/overlays'
import { useRef } from 'react'
function State({ dirty = false, modal = false }: { dirty?: boolean; modal?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  useBottomAction(dirty)
  useModalOverlay(ref,{ enabled:modal,onClose:()=>{} })
  return <><output>{useMobileNavPolicy()}</output><input aria-label="Search" /><input type="checkbox" aria-label="Check" />{modal && <div ref={ref} tabIndex={-1}>Overlay</div>}</>
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('transitions visible → replaced → hidden and retains hidden until all modal surfaces close', () => {
  vi.stubGlobal('innerWidth',390)
  const view = render(<MemoryRouter><State /></MemoryRouter>)
  expect(screen.getByRole('status')).toHaveTextContent('visible')
  view.rerender(<MemoryRouter><State dirty /></MemoryRouter>); expect(screen.getByRole('status')).toHaveTextContent('replaced')
  view.rerender(<MemoryRouter><State dirty modal /></MemoryRouter>); expect(screen.getByRole('status')).toHaveTextContent('hidden')
  view.rerender(<MemoryRouter><State /></MemoryRouter>); expect(screen.getByRole('status')).toHaveTextContent('visible')
})
it('coarse-pointer editing is conservative, ignores checkboxes, and delays blur across fields', () => {
  vi.useFakeTimers(); vi.stubGlobal('innerWidth',390)
  vi.stubGlobal('matchMedia', () => ({ matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn() }))
  render(<MemoryRouter><State /></MemoryRouter>)
  act(() => screen.getByLabelText('Check').focus()); expect(screen.getByRole('status')).toHaveTextContent('visible')
  act(() => screen.getByLabelText('Search').focus()); expect(screen.getByRole('status')).toHaveTextContent('hidden')
  act(() => screen.getByLabelText('Search').blur()); expect(screen.getByRole('status')).toHaveTextContent('hidden')
  act(() => vi.advanceTimersByTime(150)); expect(screen.getByRole('status')).toHaveTextContent('visible')
})
it('fine-pointer focus remains visible', () => {
  vi.stubGlobal('innerWidth',390); vi.stubGlobal('innerHeight',844)
  vi.stubGlobal('matchMedia', () => ({ matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn() }))
  render(<MemoryRouter><State /></MemoryRouter>)
  act(() => screen.getByLabelText('Search').focus()); expect(screen.getByRole('status')).toHaveTextContent('visible')
})
it('tracks available viewport height independently of keyboard claims', () => {
  const viewport = new EventTarget() as EventTarget & { height:number;scale:number }
  viewport.height=500;viewport.scale=1
  vi.stubGlobal('visualViewport',viewport)
  function View() { return <output>{useMobileViewport().height}</output> }
  render(<View />);expect(screen.getByRole('status')).toHaveTextContent('500')
  act(() => { viewport.height=700;viewport.dispatchEvent(new Event('resize')) });expect(screen.getByRole('status')).toHaveTextContent('700')
})

it('coarse viewport shrink hides without focus but pinch zoom is excluded', () => {
  const viewport = new EventTarget() as EventTarget & { height:number;scale:number }
  viewport.height=844;viewport.scale=1
  vi.stubGlobal('innerWidth',390);vi.stubGlobal('innerHeight',844);vi.stubGlobal('visualViewport',viewport)
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}))
  render(<MemoryRouter><State /></MemoryRouter>)
  act(()=>{viewport.height=500;viewport.dispatchEvent(new Event('resize'))});expect(screen.getByRole('status')).toHaveTextContent('hidden')
  act(()=>{viewport.scale=1.5;viewport.dispatchEvent(new Event('resize'))});expect(screen.getByRole('status')).toHaveTextContent('visible')
  act(()=>{viewport.scale=1;viewport.height=844;viewport.dispatchEvent(new Event('resize'))});expect(screen.getByRole('status')).toHaveTextContent('visible')
})
