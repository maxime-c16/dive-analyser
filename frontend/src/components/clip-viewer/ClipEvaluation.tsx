import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Attempt } from '../../utils/attemptPresentation'
import {
  EVALUATION_COMMENT_MAX,
  getDiveEvaluation,
  rateDive,
  type DiveEvaluation,
  type JuryResults,
} from '../../services/evaluationApi'
import { ScoreCard } from '../evaluation/ScoreCards'
import { scoreNumber } from '../evaluation/scoreFormatting'
import EvaluationRequestControl from './EvaluationRequestControl'
import PageLoading from '../PageLoading'
import '../evaluation/evaluationA.css'

/** The player's evaluation state for one dive, reloaded when the dive changes. */
export function useDiveEvaluation(diveId: number, enabled: boolean) {
  const [data, setData] = useState<DiveEvaluation | null>(null)
  const [error, setError] = useState(false)
  const live = useRef(diveId)
  const load = useCallback(() => {
    if (!enabled) return
    live.current = diveId
    setError(false)
    getDiveEvaluation(diveId)
      .then((value) => { if (live.current === diveId) setData(value) })
      .catch(() => { if (live.current === diveId) setError(true) })
  }, [diveId, enabled])
  useEffect(() => {
    setData(null)
    load()
  }, [load])
  return { data, setData, error, reload: load }
}

function JuryPanel({ results, mine }: { results: JuryResults; mine: number | null }) {
  const { t, i18n } = useTranslation()
  const myId = results.my_rating?.id
  const peers = results.ratings.filter((row) => row.id !== myId)
  const remarks = peers.filter((row) => row.comment)
  if (!results.rating_count) return <p className="clip-eval-fine">{t('clipEvaluation.noVotes')}</p>
  return (
    <div className="clip-eval-jury">
      <p className="clip-eval-mean">
        <strong>{scoreNumber(results.mean_score, i18n.language)}</strong>
        <span>{t('clipEvaluation.mean', { count: results.rating_count })}</span>
      </p>
      <ul className="clip-eval-peers" aria-label={t('clipEvaluation.juryAria')}>
        {mine !== null && (
          <li data-mine="true">
            <ScoreCard scoreHalfSteps={mine} ariaLabel={t('evaluations.myCardAria', { score: scoreNumber(mine / 2, i18n.language) })} />
            <span>{t('evaluations.you')}</span>
          </li>
        )}
        {peers.map((row) => (
          <li key={row.id}>
            <ScoreCard scoreHalfSteps={row.score_half_steps} ariaLabel={t('evaluations.cardAria', { score: scoreNumber(row.score_half_steps / 2, i18n.language) })} />
            <span>{row.author ?? '—'}</span>
          </li>
        ))}
      </ul>
      {remarks.length > 0 && (
        <ul className="clip-eval-remarks">
          {remarks.map((row) => <li key={row.id}><strong>{row.author ?? '—'}</strong> — {row.comment}</li>)}
        </ul>
      )}
    </div>
  )
}

/**
 * Evaluation tab of the clip player. The server decides the circuit (an
 * active request first, else the public community score); the member votes
 * once, and peer votes stay hidden until that vote is stored.
 */
export default function ClipEvaluation({
  attempt,
  evaluation,
  error,
  onReload,
  onRated,
  onUpdate,
}: {
  attempt: Attempt
  evaluation: DiveEvaluation | null
  error: boolean
  onReload: () => void
  onRated: (value: DiveEvaluation) => void
  onUpdate?: (attempt: Attempt) => void
}) {
  const { t, i18n } = useTranslation()
  const [score, setScore] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [submitError, setSubmitError] = useState(false)
  useEffect(() => {
    setScore(null)
    setComment('')
    setSubmitError(false)
  }, [attempt.id])

  if (error) {
    return (
      <div className="clip-eval" role="alert">
        <p>{t('clipEvaluation.loadError')}</p>
        <button type="button" className="clip-eval-link" onClick={onReload}>{t('common.retry')}</button>
      </div>
    )
  }
  if (!evaluation) return <PageLoading />

  const circuitLabel = evaluation.circuit === 'request'
    ? t('clipEvaluation.circuitRequest')
    : evaluation.circuit === 'automatic' ? t('clipEvaluation.circuitCommunity') : null
  const prompt = evaluation.circuit === 'request' && evaluation.prompt
    ? <p className="clip-eval-prompt">{t('clipEvaluation.prompt')} <strong>« {evaluation.prompt} »</strong></p>
    : null

  if (evaluation.state === 'owner') {
    return (
      <div className="clip-eval">
        <div className="clip-eval-head">
          <h4>{t('clipEvaluation.ownerTitle')}</h4>
          {circuitLabel && <span>{circuitLabel}</span>}
        </div>
        {evaluation.results ? <JuryPanel results={evaluation.results} mine={null} /> : <p className="clip-eval-fine">{t('clipEvaluation.ownerPrivate')}</p>}
        {evaluation.automatic_excluded && <p className="clip-eval-fine">{t('clipEvaluation.excluded')}</p>}
        {attempt.can_manage && onUpdate && attempt.video_uuid && attempt.diver_id != null && (
          <EvaluationRequestControl
            key={`evaluation-${attempt.id}`}
            attempt={attempt}
            onUpdate={(next) => { onUpdate(next); onReload() }}
          />
        )}
        <p className="clip-eval-fine">{t('clipEvaluation.ownerCannotRate')}</p>
      </div>
    )
  }

  if (evaluation.state === 'closed') {
    return <div className="clip-eval"><p className="clip-eval-fine">{t('clipEvaluation.closed')}</p></div>
  }

  if (evaluation.state === 'rated' && evaluation.my_rating) {
    const mine = evaluation.my_rating.score_half_steps
    return (
      <div className="clip-eval">
        <div className="clip-eval-head">
          <h4>{t('clipEvaluation.yourScore')}</h4>
          {circuitLabel && <span>{circuitLabel}</span>}
        </div>
        <div className="clip-eval-pick">
          <ScoreCard scoreHalfSteps={mine} ariaLabel={t('evaluations.myCardAria', { score: scoreNumber(mine / 2, i18n.language) })} />
          <div>
            <p className="clip-eval-readout">{scoreNumber(mine / 2, i18n.language)} <small>/ 10</small></p>
            {evaluation.my_rating.comment && <p className="clip-eval-fine">« {evaluation.my_rating.comment} »</p>}
          </div>
        </div>
        {evaluation.results && <JuryPanel results={evaluation.results} mine={mine} />}
      </div>
    )
  }

  const whole = score === null ? null : Math.floor(score / 2)
  const half = score !== null && score % 2 === 1
  const submit = async () => {
    if (score === null || busy) return
    setBusy(true)
    setSubmitError(false)
    try {
      const out = await rateDive(attempt.id, score, comment.trim() || null)
      onRated({ ...evaluation, state: 'rated', circuit: out.circuit, results: out.results, my_rating: out.rating })
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 409 || status === 403) onReload()
      else setSubmitError(true)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="clip-eval">
      <div className="clip-eval-head">
        <h4>{t('clipEvaluation.yourScore')}</h4>
        {circuitLabel && <span>{circuitLabel}</span>}
      </div>
      {prompt}
      <div className="clip-eval-pick">
        <ScoreCard
          scoreHalfSteps={score}
          ariaLabel={score === null ? t('evaluations.chooseScore') : t('evaluations.ariaScoreOf', { score: scoreNumber(score / 2, i18n.language) })}
        />
        <p className="clip-eval-readout" aria-live="polite">
          {score === null ? <span>{t('evaluations.chooseScore')}</span> : <>{scoreNumber(score / 2, i18n.language)} <small>/ 10</small></>}
        </p>
      </div>
      <div className="clip-eval-pad" role="group" aria-label={t('evaluations.scoreAria')}>
        {Array.from({ length: 11 }, (_, value) => (
          <button
            key={value}
            type="button"
            disabled={busy}
            aria-pressed={whole === value}
            aria-label={t('evaluations.ariaScoreOf', { score: value })}
            onClick={() => setScore(value * 2 + (value < 10 && half ? 1 : 0))}
          >
            {value}
          </button>
        ))}
        <button
          type="button"
          aria-pressed={half}
          disabled={busy || whole === null || whole === 10}
          onClick={() => setScore((value) => (value === null ? value : value + (half ? -1 : 1)))}
        >
          + ½
        </button>
      </div>
      <textarea
        value={comment}
        maxLength={EVALUATION_COMMENT_MAX}
        onChange={(event) => setComment(event.target.value)}
        placeholder={t('clipEvaluation.commentPlaceholder')}
        aria-label={t('clipEvaluation.commentPlaceholder')}
      />
      <button type="button" className="clip-eval-confirm" disabled={score === null || busy} onClick={() => void submit()}>
        {score === null ? t('clipEvaluation.confirm') : t('clipEvaluation.confirmScore', { score: scoreNumber(score / 2, i18n.language) })}
      </button>
      {submitError && <p className="clip-eval-error" role="alert">{t('clipEvaluation.submitError')}</p>}
      <p className="clip-eval-fine">{t('clipEvaluation.once')}</p>
    </div>
  )
}
