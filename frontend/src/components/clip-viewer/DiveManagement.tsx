import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import api from '../../services/api'
import { attemptScore, performanceLabel, PERFORMANCE, type Attempt } from '../../utils/attemptPresentation'
import { performanceScore10 } from '../../utils/performanceScoring'
import { scoreNumber } from '../evaluation/scoreFormatting'

type Letter = (typeof PERFORMANCE)[number]
const LETTERS: Letter[] = ['F', 'B', 'M', 'G', 'P']

function LetterPicker({ label, value, onChange, disabled, hideLabel = false }: {
  label: string
  hideLabel?: boolean
  value: string | null
  onChange: (value: Letter) => void
  disabled: boolean
}) {
  return (
    <div className="clip-letter-row" role="group" aria-label={label}>
      <span className={hideLabel ? 'sr-only' : undefined}>{label}</span>
      <div className="clip-letters">
        {LETTERS.map((letter) => (
          <button
            key={letter}
            type="button"
            className={`is-${letter}`}
            aria-pressed={value === letter}
            aria-label={`${label} : ${performanceLabel(letter)}`}
            title={performanceLabel(letter)}
            disabled={disabled}
            onClick={() => onChange(letter)}
          >
            {letter}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * Owner editing for one dive: the rating (one note or the two phases the
 * caption may carry), personal notes, and deletion behind a confirmation.
 * The server derives the composite letter from the phases.
 */
export default function DiveManagement({ attempt, onUpdate, onDelete }: {
  attempt: Attempt
  onUpdate: (attempt: Attempt) => void
  onDelete: () => void
}) {
  const { t, i18n } = useTranslation()
  const initialPhased = Boolean(attempt.phase1_performance && attempt.phase2_performance)
  const [phased, setPhased] = useState(initialPhased)
  const [performance, setPerformance] = useState(attempt.performance)
  const [phase1, setPhase1] = useState<string | null>(attempt.phase1_performance ?? null)
  const [phase2, setPhase2] = useState<string | null>(attempt.phase2_performance ?? null)
  const [notes, setNotes] = useState(attempt.notes ?? '')
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => { setMessage('') }, [performance, phase1, phase2, notes, phased])

  const ready = phased ? Boolean(phase1 && phase2) : Boolean(performance)
  const dirty = phased !== initialPhased
    || (phased ? phase1 !== (attempt.phase1_performance ?? null) || phase2 !== (attempt.phase2_performance ?? null) : performance !== attempt.performance)
    || notes !== (attempt.notes ?? '')
  const preview = phased
    ? (phase1 && phase2 ? performanceScore10(null, phase1, phase2) : null)
    : performanceScore10(performance)

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!ready || !dirty) return
    setBusy(true)
    setMessage('')
    try {
      const rating = phased
        ? { phase1_performance: phase1, phase2_performance: phase2 }
        : { performance, phase1_performance: null, phase2_performance: null }
      const { data } = await api.put(`/api/v1/dives/${attempt.id}`, { ...rating, notes })
      onUpdate(data)
      setMessage(t('diveManagement.saved'))
    } catch {
      setMessage(t('diveManagement.errorSave'))
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
      setMessage(t('diveManagement.errorDelete'))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={save} className="clip-editor">
      <div className="clip-editor-head">
        <span className="clip-eyebrow">{t('diveManagement.rating')}</span>
        <div className="clip-segmented" role="group" aria-label={t('diveManagement.ratingMode')}>
          <button type="button" aria-pressed={!phased} disabled={busy} onClick={() => setPhased(false)}>{t('diveManagement.single')}</button>
          <button
            type="button"
            aria-pressed={phased}
            disabled={busy}
            onClick={() => {
              setPhased(true)
              // Start both phases from the current note so one tap adjusts them.
              setPhase1((value) => value ?? performance)
              setPhase2((value) => value ?? performance)
            }}
          >
            {t('diveManagement.phases')}
          </button>
        </div>
      </div>
      {phased ? (
        <>
          <LetterPicker label={t('diveManagement.phase1')} value={phase1} onChange={setPhase1} disabled={busy} />
          <LetterPicker label={t('diveManagement.phase2')} value={phase2} onChange={setPhase2} disabled={busy} />
        </>
      ) : (
        <LetterPicker label={t('diveManagement.performance')} value={performance} onChange={setPerformance} disabled={busy} hideLabel />
      )}
      <p className="clip-editor-score" aria-live="polite">
        <strong>{preview == null ? '—' : scoreNumber(preview, i18n.language)}</strong> / 10
        {dirty && preview != null && preview !== attemptScore(attempt) && (
          <span>{t('diveManagement.was', { score: scoreNumber(attemptScore(attempt), i18n.language) })}</span>
        )}
      </p>
      <label className="clip-field">
        <span className="clip-field-label">{t('diveManagement.personalNotes')}</span>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} disabled={busy} rows={2} />
      </label>
      <button type="submit" className="clip-primary" disabled={busy || !ready || !dirty}>
        {busy ? t('diveManagement.working') : t('diveManagement.saveChanges')}
      </button>
      {message && <p role="status" className="clip-editor-message">{message}</p>}
      <div className="clip-editor-danger">
        {confirmDelete ? (
          <div role="alert">
            <p>{t('diveManagement.deleteConfirm')}</p>
            <div>
              <button type="button" className="clip-danger" disabled={busy} onClick={remove}>{t('diveManagement.confirmDelete')}</button>
              <button type="button" className="clip-quiet" disabled={busy} onClick={() => setConfirmDelete(false)}>{t('common.cancel')}</button>
            </div>
          </div>
        ) : (
          <button type="button" className="clip-quiet is-danger" disabled={busy} onClick={() => setConfirmDelete(true)}>{t('diveManagement.delete')}</button>
        )}
      </div>
    </form>
  )
}
