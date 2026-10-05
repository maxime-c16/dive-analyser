import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

export default function DiveVisibilityControl({ attempt, onUpdate }: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  async function change(visibility: 'public' | 'private') {
    setBusy(true)
    setError(false)
    try {
      const { data } = await api.put(`/api/v1/dives/${attempt.id}`, { visibility })
      onUpdate(data)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return <span className="inline-flex items-center gap-2">
    <select aria-label={t('clipViewer.visibility')} title={t('clipViewer.visibilityHint')}
      value={attempt.visibility ?? 'public'} disabled={busy}
      onChange={event => void change(event.target.value as 'public' | 'private')}
      className="h-8 w-auto rounded border border-app bg-app-panel px-2 text-xs text-app-text">
      <option value="public">{t('clipViewer.public')}</option>
      <option value="private">{t('clipViewer.private')}</option>
    </select>
    {error && <span role="status" className="text-xs text-red-300">{t('clipViewer.couldNotSave')}</span>}
  </span>
}
