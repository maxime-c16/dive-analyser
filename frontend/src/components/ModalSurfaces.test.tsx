import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import EvaluationStage from './evaluation/EvaluationStage'
import { AccountActionDialog } from './AccountSecurity'

it('isolates the body-portal jury stage and falls back to the new page action when its Start unmounts', async () => {
  function Page() {
    const [open, setOpen] = useState(false)
    return <><button className={open ? '' : 'eval-start'} onClick={() => setOpen(true)}>{open ? 'page' : 'start'}</button>
      <EvaluationStage open={open} onClose={() => setOpen(false)} head="Jury" prompt={null} video={<div>video</div>}><button>Vote</button></EvaluationStage></>
  }
  render(<Page />)
  document.body.focus(); fireEvent.click(screen.getByText('start'))
  const dialog = screen.getByRole('dialog')
  expect(dialog.parentElement).toBe(document.body)
  expect(dialog).toHaveFocus()
  expect(screen.getByText('page').closest('[inert]')).not.toBeNull()
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.getByText('start')).toHaveFocus())
  expect(document.documentElement.style.overflow).toBe('')
})

it('keeps a busy security confirmation open and focuses Cancel before idle confirmation', () => {
  const cancel = vi.fn(), confirm = vi.fn()
  const view = render(<AccountActionDialog title="Sign out?" busy={false} onCancel={cancel} onConfirm={confirm}><p>Security action</p></AccountActionDialog>)
  expect(screen.getByText('Cancel')).toHaveFocus()
  view.rerender(<AccountActionDialog title="Sign out?" busy onCancel={cancel} onConfirm={confirm}><p>Security action</p></AccountActionDialog>)
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(cancel).not.toHaveBeenCalled()
  expect(screen.getByRole('dialog')).toBeInTheDocument()
  expect(document.body.style.overflow).toBe('hidden')
  view.rerender(<AccountActionDialog title="Sign out?" busy={false} onCancel={cancel} onConfirm={confirm}><p>Security action</p></AccountActionDialog>)
  fireEvent.keyDown(document, { key: 'Escape', repeat: true }); expect(cancel).not.toHaveBeenCalled()
  fireEvent.keyDown(document, { key: 'Escape' }); expect(cancel).toHaveBeenCalledTimes(1)
})
