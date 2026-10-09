import { StrictMode, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import { hasOpenOverlay, useModalOverlay, useOverlayCount } from './overlays'

function Modal({ name, close, layer = 50, children }: { name: string; close: () => void; layer?: number; children?: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useModalOverlay(ref, { onClose: close, layer })
  return <div ref={ref} tabIndex={-1} role="dialog" aria-label={name}><button>{name} first</button>{children}<button>{name} last</button><span style={{ display: 'none' }}><button>hidden</button></span><fieldset disabled><button>disabled by fieldset</button></fieldset></div>
}
function Harness({ portal = false }: { portal?: boolean }) {
  const [parent, setParent] = useState(false), [child, setChild] = useState(false)
  const count = useOverlayCount()
  const nested = <Modal name="child" layer={70} close={() => setChild(false)} />
  return <><output data-testid="count">{count}</output><button onClick={() => setParent(true)}>open</button>
    {parent && <Modal name="parent" close={() => setParent(false)}><button onClick={() => setChild(true)}>nested</button>{child && !portal && nested}</Modal>}
    {child && portal && createPortal(nested, document.body)}
  </>
}
afterEach(() => { cleanup(); document.body.style.removeProperty('overflow'); document.documentElement.style.removeProperty('overflow') })

it.each([false, true])('isolates nested overlays including body portals (%s), closes only the top, and restores parent and trigger focus', async portal => {
  render(<Harness portal={portal} />)
  const open = screen.getByText('open'); open.focus(); fireEvent.click(open)
  expect(screen.getByRole('dialog', { name: 'parent' })).toHaveFocus()
  expect(open.closest('[inert]')).not.toBeNull()
  const nested = screen.getByText('nested'); nested.focus(); fireEvent.click(nested)
  const child = screen.getByRole('dialog', { name: 'child' })
  expect(child).toHaveFocus()
  expect(child.closest('[inert]')).toBeNull()
  expect(nested.closest('[inert]')).not.toBeNull()
  expect(screen.getByTestId('count')).toHaveTextContent('2')
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: 'child' })).toBeNull()
  await waitFor(() => expect(nested).toHaveFocus())
  expect(nested.closest('[inert]')).toBeNull()
  expect(document.body.style.overflow).toBe('hidden')
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(open).toHaveFocus())
  expect(open.closest('[inert]')).toBeNull()
  expect(hasOpenOverlay()).toBe(false)
})

it('traps both Tab directions, excludes hidden/disabled controls and redirects focus escaping the modal', () => {
  render(<Harness />); fireEvent.click(screen.getByText('open'))
  const modal = screen.getByRole('dialog')
  fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
  expect(screen.getByText('parent last')).toHaveFocus()
  fireEvent.keyDown(document, { key: 'Tab' })
  expect(screen.getByText('parent first')).toHaveFocus()
  screen.getByText('open').focus()
  expect(modal).toHaveFocus()
})

it('preserves preexisting inert values and exact scroll styles while nested locks are released', () => {
  document.body.style.setProperty('overflow', 'scroll', 'important')
  document.documentElement.style.overflow = 'auto'
  const untouched = document.createElement('aside'); untouched.setAttribute('inert', 'existing'); document.body.append(untouched)
  const view = render(<Harness portal />)
  const open = screen.getByText('open'); open.focus(); fireEvent.click(open)
  const nested = screen.getByText('nested'); nested.focus(); fireEvent.click(nested)
  // A separate parent may disappear before a body portal; keep child mounted.
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(document.body.style.overflow).toBe('hidden')
  expect(untouched.getAttribute('inert')).toBe('')
  view.unmount()
  expect(untouched.getAttribute('inert')).toBe('existing')
  expect(document.body.style.overflow).toBe('scroll')
  expect(document.body.style.getPropertyPriority('overflow')).toBe('important')
  expect(document.documentElement.style.overflow).toBe('auto')
  untouched.remove()
})

it('keeps a surviving portal active when its parent unmounts first, then returns to the original page', async () => {
  const parentClose = vi.fn(), childClose = vi.fn()
  const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
  const view = render(<Modal name="parent" close={parentClose} />)
  screen.getByText('parent first').focus()
  const portal = render(createPortal(<Modal name="child" close={childClose} layer={70} />, document.body))
  view.unmount()
  expect(screen.getByRole('dialog', { name: 'child' }).closest('[inert]')).toBeNull()
  expect(document.body.style.overflow).toBe('hidden')
  fireEvent.keyDown(document, { key: 'Escape' }); expect(childClose).toHaveBeenCalledTimes(1); expect(parentClose).not.toHaveBeenCalled()
  portal.unmount()
  await waitFor(() => expect(trigger).toHaveFocus()); expect(trigger).not.toHaveAttribute('inert'); trigger.remove()
})

it('handles StrictMode, callback changes, newly mounted background siblings and cleanup', async () => {
  const oldClose = vi.fn(), newClose = vi.fn()
  const view = render(<StrictMode><Modal name="parent" close={oldClose} /></StrictMode>)
  view.rerender(<StrictMode><Modal name="parent" close={newClose} /></StrictMode>)
  const sibling = document.createElement('button')
  await act(async () => { document.body.append(sibling) })
  expect(sibling).toHaveAttribute('inert')
  fireEvent.keyDown(document, { key: 'Escape' }); expect(newClose).toHaveBeenCalledTimes(1); expect(oldClose).not.toHaveBeenCalled()
  view.unmount(); expect(sibling).not.toHaveAttribute('inert'); expect(hasOpenOverlay()).toBe(false); sibling.remove()
})

it('lets local popovers consume Escape before closing the modal', () => {
  const close = vi.fn()
  render(<Modal name="parent" close={close}><input aria-label="mention" onKeyDown={event => event.preventDefault()} /><button onKeyDown={event => event.stopPropagation()}>popover</button></Modal>)
  fireEvent.keyDown(screen.getByLabelText('mention'), { key: 'Escape' })
  fireEvent.keyDown(screen.getByText('popover'), { key: 'Escape' })
  expect(close).not.toHaveBeenCalled()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(1)
})
