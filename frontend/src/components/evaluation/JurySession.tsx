/**
 * Jury session state machine (issue #68).
 *
 * landing → loading → reviewing → submitting → reveal → reviewing(next) | summary
 * Plus visible failure states: loading-error, media-unavailable, closed, empty —
 * each with its own retry/pass affordance. Confirmed votes are the only source
 * of results: nothing is shown before the server answers, late responses never
 * touch the next dive, and an unsent draft is never presented as saved.
 *
 * Batch loading contract: each load uses ONE client batch id; a failed load
 * retries the same id (the server returns the same batch, marking consumed
 * items unavailable); once a batch is fully consumed the NEXT load rotates to
 * a fresh id. An all-unavailable batch with has_more keeps loading instead of
 * reporting exhaustion.
 */
import React, { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import EvaluationIntro, { ScoreCard } from './ScoreCards'
import EvaluationPlayer from './EvaluationPlayer'
import EvaluationStage from './EvaluationStage'
import {
  EVALUATION_CLOSED,
  createSession,
  getQueue,
  skipRequest,
  submitRating,
  type JuryResults,
  type QueueItem,
  type RatingRecord,
} from '../../services/evaluationApi'

const REVEAL_HOLD_MS = 1500
const REVEAL_ANIMATION_MS = 750
const MAX_BATCH_ROTATIONS = 10

type Phase =
  | { kind: 'landing' }
  | { kind: 'loading' }
  | { kind: 'loading-error' }
  | { kind: 'reviewing'; item: QueueItem }
  | { kind: 'submitting'; item: QueueItem; score: number; comment: string }
  | { kind: 'reveal'; item: QueueItem; score: number; comment: string; results: JuryResults }
  | { kind: 'media-unavailable'; item: QueueItem; reason: 'closed' | 'missing' }
  | { kind: 'closed'; item: QueueItem }
  | { kind: 'summary' }

type RatedEntry = { request_id: number; dive_code: string; height: string; score_half_steps: number; comment: string | null }
type PassedEntry = { request_id: number; dive_code: string; height: string }

function clientId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export default function JurySession({
  onCountChange,
  onStageChange,
}: {
  onCountChange?: (judged: number) => void
  /** Tells the page chrome to compact itself while a dive is on stage. */
  onStageChange?: (judging: boolean) => void
}) {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<Phase>({ kind: 'landing' })
  const [introDone, setIntroDone] = useState(false)
  const [sessionExpired, setSessionExpired] = useState(false)
  const [judgedCount, setJudgedCount] = useState(0)
  const [score, setScore] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [rated, setRated] = useState<RatedEntry[]>([])
  const [passed, setPassed] = useState<PassedEntry[]>([])
  const [commentOpen, setCommentOpen] = useState(false)
  const sessionIdRef = useRef<number | null>(null)
  const batchRef = useRef<QueueItem[]>([])
  const batchIdRef = useRef<string | null>(null)
  const committedBatches = useRef(new Set<string>())
  const hoverRef = useRef(false)
  const keptOpenRef = useRef(false)
  const submittingRef = useRef(false)
  const revealTimerRef = useRef<number | null>(null)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
      if (revealTimerRef.current) window.clearTimeout(revealTimerRef.current)
    }
  }, [])

  useEffect(() => {
    onStageChange?.(phase.kind === 'reviewing' || phase.kind === 'submitting' || phase.kind === 'reveal')
  }, [phase.kind, onStageChange])

  /**
   * One server batch load. Batch ids survive lost responses: a batch whose
   * CONFIRMED response was fully consumed rotates for the next load, but an
   * id with a failed/unconfirmed fetch is reused so an already-committed
   * allocation is returned on retry instead of being orphaned until the next
   * session. All-unavailable batches with has_more keep loading.
   */
  const loadBatch = useCallback(async (sid: number): Promise<boolean> => {
    if (batchIdRef.current && committedBatches.current.has(batchIdRef.current)) {
      // That batch was delivered and fully consumed: a fresh id for the next.
      batchIdRef.current = null
    }
    for (let attempt = 0; attempt < MAX_BATCH_ROTATIONS; attempt++) {
      const batchId = batchIdRef.current || (batchIdRef.current = clientId())
      // Lost response (or transport error) AFTER possible server-side
      // allocation: rethrow untouched, keeping the SAME id so the retry
      // returns the same batch instead of orphaning it.
      const payload = await getQueue(sid, batchId)
      committedBatches.current.add(batchId)
      const usable = payload.items.filter(
        (item): item is QueueItem =>
          !(item as { unavailable?: boolean }).unavailable && 'media' in item,
      )
      batchRef.current.push(...usable)
      if (usable.length) return true
      // All-unavailable batch: keep going while the server says there is more.
      if (!payload.has_more) return false
      // Rotate: this batch produced nothing usable (its confirmed items stay
      // marked unavailable server-side, so they can never be re-served).
      batchIdRef.current = null
    }
    return batchRef.current.length > 0
  }, [])

  /** Next reviewable item: local queue first, then a fresh server batch. */
  const advance = useCallback(async () => {
    if (!aliveRef.current) return
    setScore(null)
    setComment('')
    setError('')
    hoverRef.current = false
    keptOpenRef.current = false
    if (batchRef.current.length) {
      serveNext()
      return
    }
    const sid = sessionIdRef.current
    if (sid === null) {
      setPhase({ kind: 'landing' })
      return
    }
    setPhase({ kind: 'loading' })
    try {
      const any = await loadBatch(sid)
      if (!aliveRef.current) return
      if (any) serveNext()
      else setPhase({ kind: 'summary' })
    } catch (err: unknown) {
      if (!aliveRef.current) return
      handleLoadError(err)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadBatch])

  function serveNext() {
    const next = batchRef.current.shift()!
    if (next.media.status === 'ready' && next.media.playback_url) {
      setPhase({ kind: 'reviewing', item: next })
    } else {
      setPhase({
        kind: 'media-unavailable',
        item: next,
        reason: next.media.status === 'missing' ? 'missing' : 'closed',
      })
    }
  }

  function handleLoadError(err: unknown) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 410) {
      setSessionExpired(true)
      setPhase({ kind: 'summary' })
      return
    }
    setPhase({ kind: 'loading-error' })
  }

  async function start() {
    setError('')
    setSessionExpired(false)
    setPhase({ kind: 'loading' })
    try {
      const session = await createSession(clientId())
      if (!aliveRef.current) return
      sessionIdRef.current = session.session_id
      batchRef.current = []
      batchIdRef.current = null
      committedBatches.current = new Set()
      const any = await loadBatch(session.session_id)
      if (!aliveRef.current) return
      if (any) serveNext()
      else setPhase({ kind: 'summary' })
    } catch (err: unknown) {
      if (!aliveRef.current) return
      handleLoadError(err)
    }
  }

  async function confirm() {
    const current = phase
    if (current.kind !== 'reviewing' || score === null) return
    if (submittingRef.current) return
    submittingRef.current = true
    const nextCount = judgedCount + 1
    setPhase({ kind: 'submitting', item: current.item, score, comment })
    try {
      const response = await submitRating(current.item.request_id, score, comment.trim() || undefined)
      if (!aliveRef.current) return
      setJudgedCount(nextCount)
      onCountChange?.(nextCount)
      setRated((list) => [
        ...list,
        {
          request_id: current.item.request_id,
          dive_code: current.item.dive.dive_code,
          height: current.item.dive.height,
          score_half_steps: response.results.my_rating?.score_half_steps ?? score,
          comment: response.results.my_rating?.comment ?? null,
        },
      ])
      // Leave the confirmed dive exactly once.
      batchRef.current = batchRef.current.filter((entry) => entry.request_id !== current.item.request_id)
      hoverRef.current = false
      keptOpenRef.current = false
      setPhase({ kind: 'reveal', item: current.item, score, comment, results: response.results })
      // Readable hold AFTER the arrival animation; parked results pause it.
      revealTimerRef.current = window.setTimeout(() => {
        if (aliveRef.current && !hoverRef.current && !keptOpenRef.current) void advance()
      }, REVEAL_ANIMATION_MS + REVEAL_HOLD_MS)
    } catch (err: unknown) {
      if (!aliveRef.current) return
      const axios = err as { response?: { status?: number; data?: { detail?: unknown } } }
      // Business codes are authoritative; older string details stay decodable.
      const rawDetail = axios.response?.data?.detail
      const detailCode = typeof rawDetail === 'string'
        ? (rawDetail.includes('immutable') ? 'RATING_ALREADY_SUBMITTED' : EVALUATION_CLOSED)
        : ((rawDetail as { code?: string } | undefined)?.code ?? '')
      if (axios.response?.status === 409 && detailCode === 'RATING_ALREADY_SUBMITTED') {
        // The juror's own immutable vote exists: back to the same dive.
        setError(t('evaluations.voteAlready'))
        setPhase({ kind: 'reviewing', item: current.item })
      } else if (axios.response?.status === 409) {
        // EVALUATION_CLOSED: no further vote attempts; next from the closed screen.
        setError(t('evaluations.voteClosed'))
        setPhase({ kind: 'closed', item: current.item })
        return
      } else if (axios.response?.status === 403) {
        setError(t('evaluations.voteSelf'))
        setPhase({ kind: 'reviewing', item: current.item })
      } else {
        // Network/5xx: keep the chosen score, comment and dive for a retry.
        setError(t('evaluations.voteError'))
        setPhase({ kind: 'reviewing', item: current.item })
      }
    } finally {
      submittingRef.current = false
    }
  }

  async function pass() {
    const current = phase
    if (current.kind !== 'reviewing' && current.kind !== 'media-unavailable') return
    if (submittingRef.current) return
    submittingRef.current = true
    setPassed((list) => [
      ...list.filter((entry) => entry.request_id !== current.item.request_id),
      { request_id: current.item.request_id, dive_code: current.item.dive.dive_code, height: current.item.dive.height },
    ])
    try {
      if (sessionIdRef.current !== null) await skipRequest(sessionIdRef.current, current.item.request_id)
    } catch {
      // A failed pass is not fatal: the request stays proposed in this
      // session and returns in the next one; the UI still moves forward.
    } finally {
      submittingRef.current = false
    }
    await advance()
  }

  function quit() {
    if (revealTimerRef.current) window.clearTimeout(revealTimerRef.current)
    keptOpenRef.current = true // freeze any in-flight auto-advance
    setPhase({ kind: 'summary' })
  }

  const inStage = phase.kind === 'reviewing' || phase.kind === 'submitting' || phase.kind === 'reveal' || phase.kind === 'media-unavailable' || phase.kind === 'closed'
  const stageItem = inStage ? (phase as { item: QueueItem }).item : null

  return (
    <section className="eval-session" aria-label={t('evaluations.juryArea')}>
      {phase.kind === 'landing' && (
        <div className="eval-landing">
          <p className="eval-count" role="status">{t('evaluations.counted', { count: judgedCount })}</p>
          <button type="button" className="eval-start" onClick={() => void start()}>{t('evaluations.start')}</button>
          <p className="eval-note">{t('evaluations.startNote')}</p>
          {sessionExpired && <p className="eval-note" role="status">{t('evaluations.sessionNew')}</p>}
        </div>
      )}
      {phase.kind === 'loading' && <p className="eval-status" role="status">{t('common.loading')}</p>}
      {phase.kind === 'loading-error' && (
        <div className="eval-state" role="alert">
          <p>{t('evaluations.loadError')}</p>
          <button type="button" className="eval-start" onClick={() => (sessionIdRef.current ? void advance() : void start())}>
            {t('evaluations.retry')}
          </button>
        </div>
      )}
      {inStage && stageItem !== null && (
        <EvaluationStage
          open
          onClose={quit}
          head={
            <>
              <strong className="eval-head-owner">{stageItem.dive.owner_display_name ?? t('evaluations.unknownOwner')}</strong>
              <span className="eval-meta">{stageItem.dive.dive_code} · {stageItem.dive.height}</span>
              <span className="eval-count" role="status" aria-label={t('evaluations.counted', { count: judgedCount })} title={t('evaluations.counted', { count: judgedCount })}>
                {judgedCount}
              </span>
            </>
          }
          prompt={stageItem.prompt}
          video={
            <EvaluationPlayer
              requestId={stageItem.request_id}
              paused={
              phase.kind === 'submitting' ||
              phase.kind === 'reveal' ||
              (phase.kind === 'reviewing' && (score !== null || commentOpen))
            }
            />
          }
          overlays={
            !introDone && (
              <EvaluationIntro onDone={() => setIntroDone(true)} onSkip={() => setIntroDone(true)} interrupt={score !== null} />
            )
          }
        >
          {phase.kind === 'reviewing' && (
            <JudgingDock
              score={score}
              comment={comment}
              commentOpen={commentOpen}
              saving={false}
              error={error}
              onScore={setScore}
              onComment={setComment}
              onCommentOpen={setCommentOpen}
              onConfirm={() => void confirm()}
              onPass={() => void pass()}
            />
          )}
          {phase.kind === 'submitting' && (
            <JudgingDock
              score={phase.score}
              comment={phase.comment}
              commentOpen={false}
              saving
              error={error}
              onScore={() => {}}
              onComment={() => {}}
              onCommentOpen={() => {}}
              onConfirm={() => {}}
              onPass={() => {}}
            />
          )}
          {phase.kind === 'reveal' && (
            <RevealPanel
              score={phase.score}
              results={phase.results}
              onKeepOpen={() => { keptOpenRef.current = true; if (revealTimerRef.current) window.clearTimeout(revealTimerRef.current) }}
              onNext={() => { if (revealTimerRef.current) window.clearTimeout(revealTimerRef.current); void advance() }}
              onHover={open => { hoverRef.current = open }}
            />
          )}
          {phase.kind === 'media-unavailable' && (
            <div className="eval-state" role="alert">
              <p>{phase.reason === 'closed' ? t('evaluations.mediaClosed') : t('evaluations.mediaMissing')}</p>
              <button type="button" onClick={() => void pass()}>{t('evaluations.pass')}</button>
            </div>
          )}
          {phase.kind === 'closed' && (
            <div className="eval-state" role="alert">
              <p>{t('evaluations.voteClosed')}</p>
              <button type="button" className="eval-start" onClick={() => void advance()}>{t('evaluations.next')}</button>
            </div>
          )}
        </EvaluationStage>
      )}
      {phase.kind === 'summary' && (
        <SessionSummary
          judgedCount={judgedCount}
          rated={rated}
          passed={passed}
          onAgain={() => { setPhase({ kind: 'landing' }); setIntroDone(false); setSessionExpired(false) }}
        />
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Judging dock: persistent compact score + Confirm + Pass; the        */
/* optional comment stays collapsed behind an explicit toggle.         */
/* ------------------------------------------------------------------ */
function JudgingDock({
  score, comment, commentOpen, saving, error,
  onScore, onComment, onCommentOpen, onConfirm, onPass,
}: {
  score: number | null
  comment: string
  commentOpen: boolean
  saving: boolean
  error: string
  onScore: (value: number) => void
  onComment: (value: string) => void
  onCommentOpen: (open: boolean) => void
  onConfirm: () => void
  onPass: () => void
}) {
  const { t } = useTranslation()
  const step = (delta: number) => {
    onScore(Math.max(0, Math.min(20, (score ?? 10) + delta)))
  }
  const selectVisible = (event: { currentTarget: HTMLInputElement }) => {
    onScore(Number(event.currentTarget.value))
  }
  const ariaText = score === null ? t('evaluations.noScore') : t('evaluations.ariaScoreOf', { score: (score / 2).toFixed(1) })
  const confirmLabel = saving ? t('evaluations.saving') : t('evaluations.confirm')
  return (
    <div className="eval-judging" role="group" aria-label={t('evaluations.judgeAria')}>
      <div className="eval-score-row">
        <div className="eval-stepper" role="group" aria-label={t('evaluations.scoreAria')}>
          <button type="button" onClick={() => step(-1)} disabled={saving || score === null} aria-label={t('evaluations.stepDownAria')}>−</button>
          <input
            type="range"
            aria-label={t('evaluations.scoreAria')}
            aria-valuetext={ariaText}
            min={0}
            max={20}
            step={1}
            // Controlled so +/- stay in sync; touch/mouse on the SAME value
            // (e.g. tapping the middle) still selects it explicitly.
            value={score ?? 10}
            disabled={saving}
            onChange={(event) => onScore(Number(event.target.value))}
            onMouseUp={selectVisible}
            onTouchEnd={selectVisible}
          />
          <button type="button" onClick={() => step(1)} disabled={saving || (score ?? 10) >= 20} aria-label={t('evaluations.stepUpAria')}>+</button>
        </div>
        <div className="eval-score-card">
          {score === null ? (
            <p className="eval-score-placeholder">{t('evaluations.chooseScore')}</p>
          ) : (
            <ScoreCard scoreHalfSteps={score} ariaLabel={ariaText} />
          )}
        </div>
      </div>
      {!commentOpen && (
        <button type="button" className="eval-comment-toggle" onClick={() => onCommentOpen(true)}>
          {comment ? t('evaluations.commentEdit') : t('evaluations.commentAdd')}
        </button>
      )}
      <div className="eval-judge-actions">
        <button type="button" className="eval-pass" disabled={saving} onClick={onPass}>{t('evaluations.pass')}</button>
        <button
          type="button"
          className="eval-confirm"
          data-saving={saving ? 'true' : undefined}
          disabled={saving || score === null}
          onClick={onConfirm}
        >
          {confirmLabel}
        </button>
      </div>
      {error && <p role="alert" className="eval-error">{error}</p>}
      {commentOpen && (
        <div className="eval-comment-sheet" role="dialog" aria-label={t('evaluations.commentEdit')}>
          <header>
            <span>{t('evaluations.commentAria')}</span>
            <button type="button" aria-label={t('common.close')} onClick={() => onCommentOpen(false)}>
              {String.fromCodePoint(0x2715)}
            </button>
          </header>
          <textarea
            aria-label={t('evaluations.commentAria')}
            maxLength={2000}
            rows={3}
            value={comment}
            placeholder={t('evaluations.commentPlaceholder')}
            onChange={(event) => onComment(event.target.value)}
            autoFocus
          />
          <p className="eval-note">{t('evaluations.commentSavedOnConfirm')}</p>
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Reveal: peers flip first (staggered), then MY card arrives once.    */
/* my_rating already sits in results.ratings — never duplicated.       */
/* ------------------------------------------------------------------ */
function RevealPanel({
  score, results, onKeepOpen, onNext, onHover,
}: {
  score: number
  results: JuryResults
  onKeepOpen: () => void
  onNext: () => void
  onHover: (open: boolean) => void
}) {
  const { t } = useTranslation()
  const [commentsOpen, setCommentsOpen] = useState(false)
  const myId = results.my_rating?.id ?? null
  const peers = results.ratings.filter((rating) => rating.id !== myId)
  const myRating: RatingRecord | undefined = results.my_rating ?? undefined
  return (
    <div
      className="eval-reveal"
      aria-live="polite"
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
    >
      <div className="eval-reveal-panel">
        {peers.map((rating, index) => (
          <figure className="eval-card-figure" key={rating.id} style={{ '--stagger': `${index * 120}ms` } as CSSProperties}>
            <ScoreCard
              scoreHalfSteps={rating.score_half_steps}
              rotation={((index % 5) - 2) * 2}
              ariaLabel={t('evaluations.cardAria', { score: (rating.score_half_steps / 2).toFixed(1) })}
            />
            <figcaption>{rating.author ?? '—'}</figcaption>
          </figure>
        ))}
        <figure className="eval-card-figure eval-card-mine-figure" style={{ '--stagger': `${peers.length * 120 + 240}ms` } as CSSProperties}>
          <ScoreCard
            scoreHalfSteps={myRating?.score_half_steps ?? score}
            rotation={4}
            className="eval-card-mine"
            ariaLabel={t('evaluations.myCardAria', { score: ((myRating?.score_half_steps ?? score) / 2).toFixed(1) })}
          />
          <figcaption>{t('evaluations.you')}</figcaption>
        </figure>
      </div>
      <div className="eval-reveal-meta">
        <p>
          {t('evaluations.panelSummary', {
            count: results.rating_count,
            mean: results.mean_score !== null ? results.mean_score.toFixed(1) : '—',
          })}
        </p>
        <div className="eval-reveal-actions">
          <button type="button" className="eval-chip" onClick={() => { setCommentsOpen(open => !open); onKeepOpen() }} aria-expanded={commentsOpen}>
            {t('evaluations.commentsToggle')}
          </button>
          <button type="button" className="eval-chip" onClick={onKeepOpen} aria-label={t('evaluations.keepOpen')}>
            {t('evaluations.keepOpenShort')}
          </button>
          <button type="button" className="eval-confirm" onClick={onNext}>{t('evaluations.next')}</button>
        </div>
        {commentsOpen && (
          <ul className="eval-panel-list">
            {results.ratings.map((rating) => (
              <li key={rating.id}>
                <strong>{(rating.score_half_steps / 2).toFixed(1)}</strong> — {rating.author ?? '—'}
                {rating.comment ? <p className="eval-panel-comment">{rating.comment}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Session summary: real recap of this session + the invitation CTAs.  */
/* ------------------------------------------------------------------ */
function SessionSummary({
  judgedCount, rated, passed, onAgain,
}: {
  judgedCount: number
  rated: RatedEntry[]
  passed: PassedEntry[]
  onAgain: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="eval-summary">
      <p className="eval-count" role="status">{t('evaluations.summaryJudged', { count: judgedCount })}</p>
      {rated.length > 0 && (
        <ul className="eval-recap-list">
          {rated.map((entry) => (
            <li key={entry.request_id}>
              <ScoreCard scoreHalfSteps={entry.score_half_steps} ariaLabel={(entry.score_half_steps / 2).toFixed(1)} />
              <span className="eval-recap-label">
                <strong>{entry.dive_code}</strong> · {entry.height}
                {entry.comment && <p className="eval-panel-comment">{entry.comment}</p>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {passed.length > 0 && (
        <div className="eval-recap-passed">
          <p>{t('evaluations.summarySkipped')}</p>
          <ul>
            {passed.map((entry) => (
              <li key={entry.request_id}>{entry.dive_code} · {entry.height}</li>
            ))}
          </ul>
        </div>
      )}
      <p>{t('evaluations.exhausted')}</p>
      <div className="eval-judge-actions">
        <button type="button" className="eval-pass" onClick={onAgain}>{t('evaluations.evaluateAgain')}</button>
        <Link className="eval-confirm eval-link" to="/dives">{t('evaluations.requestDive')}</Link>
      </div>
      <p className="eval-note">{t('evaluations.requestDiveHint')}</p>
    </div>
  )
}
