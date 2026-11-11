import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../services/api'
import type { Attempt } from '../../utils/attemptPresentation'

/** Public/private as one two-option switch; saves on tap, reverts on failure. */
export default function DiveVisibilityControl({ attempt, onUpdate }: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
}) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const current = attempt.visibility ?? 'public'

  async function change(visibility: 'public' | 'private') {
    if (visibility === current) return
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

  return (
    <div className="clip-setting">
      <span>{t('clipViewer.visibility')}</span>
      <div className="clip-segmented" role="group" aria-label={t('clipViewer.visibility')} title={t('clipViewer.visibilityHint')}>
        {(['public', 'private'] as const).map((value) => (
          <button key={value} type="button" aria-pressed={current === value} disabled={busy} onClick={() => void change(value)}>
            {t(`clipViewer.${value}`)}
          </button>
        ))}
      </div>
      {error && <p role="status" className="clip-editor-message is-error">{t('clipViewer.couldNotSave')}</p>}
    </div>
  )
}
