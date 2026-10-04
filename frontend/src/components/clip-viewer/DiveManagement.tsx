import { useState } from 'react'
import api from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

export default function DiveManagement({ attempt, onUpdate, onDelete }: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
  onDelete: () => void
}) {
  const [performance, setPerformance] = useState(attempt.performance)
  const [notes, setNotes] = useState(attempt.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [message, setMessage] = useState('')

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setMessage('')
    try {
      const { data } = await api.put(`/api/v1/dives/${attempt.id}`, {
        performance, performance_numeric: ['F', 'B', 'M', 'G', 'P'].indexOf(performance), notes,
      })
      onUpdate(data)
      setMessage('Dive saved.')
    } catch {
      setMessage('The dive could not be saved. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setMessage('')
    try {
      await api.delete(`/api/v1/dives/${attempt.id}`)
      onDelete()
    } catch {
      setMessage('The dive could not be deleted. Please try again.')
      setBusy(false)
    }
  }

  return <form onSubmit={save} className="mt-3 max-h-[32vh] max-w-lg space-y-2 overflow-y-auto border border-app bg-app-panel p-3">
    <h3 className="text-sm font-semibold">Edit dive</h3>
    <label className="block text-sm">Performance
      <select aria-label="Dive performance" value={performance} onChange={e => setPerformance(e.target.value)} disabled={busy} className="mt-1 block w-full border border-app bg-app-panel-elevated p-2">
        {['F', 'B', 'M', 'G', 'P'].map(value => <option key={value}>{value}</option>)}
      </select>
    </label>
    <label className="block text-sm">Personal notes
      <textarea aria-label="Personal notes" value={notes} onChange={e => setNotes(e.target.value)} disabled={busy} rows={2} className="mt-1 block w-full border border-app bg-app-panel-elevated p-2" />
    </label>
    <div className="flex flex-wrap gap-2">
      <button disabled={busy} className="touch-target border border-app-accent px-3 text-sm">{busy ? 'Working…' : 'Save changes'}</button>
      <button type="button" disabled={busy} onClick={() => setConfirmDelete(true)} className="touch-target border border-app px-3 text-sm text-red-300">Delete dive</button>
    </div>
    {confirmDelete && <div className="space-y-2" role="alert">
      <p className="text-sm">Delete this dive record? This cannot be undone. The original video is retained.</p>
      <button type="button" disabled={busy} onClick={remove} className="touch-target border border-red-300 px-3 text-sm text-red-300">Confirm deletion</button>{' '}
      <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)} className="touch-target border border-app px-3 text-sm">Cancel</button>
    </div>}
    {message && <p role="status" className="text-sm">{message}</p>}
  </form>
}
