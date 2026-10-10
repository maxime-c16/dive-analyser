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
import { DEFAULT_DRAW_SIZE } from '../../hooks/useEvaluationDrawSize'
import { scoreNumber } from './scoreFormatting'
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, MessageSquare, SendHorizontal } from 'lucide-react'
import { ScoreCard } from './ScoreCards'
import EvaluationPlayer from './EvaluationPlayer'
import EvaluationStage from './EvaluationStage'
import ScoreInput from './ScoreInput'
import ResultsBoard from './ResultsBoard'
import { useModalOverlay } from '../../utils/overlays'
import {
  EVALUATION_CLOSED,
  createSession,
  createAutomaticStack,
  getAutomaticQueue,
  skipAutomaticDive,
  getQueue,
  skipRequest,
  submitRating,
  type JuryResults,
  type QueueItem,
} from '../../services/evaluationApi'

/* Results stay open until the juror explicitly advances. */
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
  automatic = false,
  autoStart = false,
  daily = true,
  drawSize = DEFAULT_DRAW_SIZE,
  resumeStackId,
  doneBefore = 0,
  onDone,
}: {
  automatic?: boolean
  onCountChange?: (judged: number) => void
  /** Tells the page chrome to compact itself while a dive is on stage. */
  onStageChange?: (judging: boolean) => void
  /** Skip the landing: the caller's button already was the start. */
  autoStart?: boolean
  /** Automatic only: today's selection (true) or one more on demand. */
  daily?: boolean
  drawSize?: number
  /** Automatic only: reopen this existing selection instead of allocating. */
  resumeStackId?: number
  /** Dives of the resumed selection already handled before this mount. */
  doneBefore?: number
  /** Leaves the finished/quit session (the hub refreshes its own state). */
  onDone?: () => void
}) {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<Phase>({ kind: 'landing' })
  const [watching, setWatching] = useState(true)
  const [quitRequested, setQuitRequested] = useState(false)
  const [replayCount, setReplayCount] = useState(0)
  const [sessionExpired, setSessionExpired] = useState(false)
  const [judgedCount, setJudgedCount] = useState(0)
  const [score, setScore] = useState<number | null>(null)
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [rated, setRated] = useState<RatedEntry[]>([])
  const [passed, setPassed] = useState<PassedEntry[]>([])
  const [commentOpen, setCommentOpen] = useState(false)
  const dailyRef = useRef(daily)
  const drawSizeRef = useRef(drawSize)
  const resumeRef = useRef(resumeStackId)
  const offsetRef = useRef(doneBefore)
  const startKeyRef = useRef<string | null>(null)
  const selectionSizeRef = useRef(0)
  const automaticLoadedRef = useRef(false)
  const sessionIdRef = useRef<number | null>(null)
  const batchRef = useRef<QueueItem[]>([])
  const batchIdRef = useRef<string | null>(null)
  const committedBatches = useRef(new Set<string>())
  const submittingRef = useRef(false)
  // Set by quit(): any in-flight vote/pass response or opened timer then
  // arrives too late and must not resurrect the stage after the summary.
  const supersededRef = useRef(false)
  const aliveRef = useRef(true)

  useEffect(() => {
    aliveRef.current = true
    return () => {
      aliveRef.current = false
    }
  }, [])

  const autoStarted = useRef(false)
  useEffect(() => {
    if (!autoStart || autoStarted.current) return
    autoStarted.current = true
    void start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart])

  // Inside the hub, the hub's own table is the recap: hand control straight back.
  useEffect(() => {
    if (phase.kind === 'summary' && onDone) onDone()
  }, [phase.kind, onDone])

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
    if (automatic && automaticLoadedRef.current) return false
    if (batchIdRef.current && committedBatches.current.has(batchIdRef.current)) {
      // That batch was delivered and fully consumed: a fresh id for the next.
      batchIdRef.current = null
    }
    for (let attempt = 0; attempt < MAX_BATCH_ROTATIONS; attempt++) {
      const batchId = batchIdRef.current || (batchIdRef.current = clientId())
      // Lost response (or transport error) AFTER possible server-side
      // allocation: rethrow untouched, keeping the SAME id so the retry
      // returns the same batch instead of orphaning it.
      const payload = await (automatic ? getAutomaticQueue(sid) : getQueue(sid, batchId))
      if (automatic) automaticLoadedRef.current = true
      committedBatches.current.add(batchId)
      const usable = payload.items.filter(
        (item): item is QueueItem =>
          !(item as { unavailable?: boolean }).unavailable && 'media' in item,
      )
      if (automatic) selectionSizeRef.current = usable.length
      batchRef.current.push(...usable)
      if (usable.length) return true
      // All-unavailable batch: keep going while the server says there is more.
      if (!payload.has_more) return false
      // Rotate: this batch produced nothing usable (its confirmed items stay
      // marked unavailable server-side, so they can never be re-served).
      batchIdRef.current = null
    }
    return batchRef.current.length > 0
  }, [automatic])

  /** Next reviewable item: local queue first, then a fresh server batch. */
  const advance = useCallback(async () => {
    if (!aliveRef.current) return
    setScore(null)
    setComment('')
    setCommentOpen(false)
    setError('')
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
    setWatching(true)
    setReplayCount(0)
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
    setScore(null); setComment(''); setCommentOpen(false); setQuitRequested(false)
    setError('')
    setSessionExpired(false)
    setJudgedCount(0)
    setRated([])
    setPassed([])
    supersededRef.current = false
    setPhase({ kind: 'loading' })
    try {
      const key = startKeyRef.current || (startKeyRef.current = clientId())
      const resume = resumeRef.current
      resumeRef.current = undefined
      if (resume === undefined) offsetRef.current = 0
      const session = resume !== undefined
        ? { session_id: resume }
        : await (automatic ? createAutomaticStack(key, dailyRef.current, drawSizeRef.current) : createSession(key))
      if (!aliveRef.current) return
      automaticLoadedRef.current = false
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
    if (current.kind !== 'reviewing' || watching || score === null) return
    if (submittingRef.current || supersededRef.current) return
    submittingRef.current = true
    const nextCount = judgedCount + 1
    setPhase({ kind: 'submitting', item: current.item, score, comment })
    try {
      const response = await submitRating(current.item.request_id, score, comment.trim() || undefined, automatic, current.item.dive.video_uuid)
      if (!aliveRef.current || supersededRef.current) return
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
          setPhase({ kind: 'reveal', item: current.item, score, comment, results: response.results })
    } catch (err: unknown) {
      if (!aliveRef.current || supersededRef.current) return
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
      if (sessionIdRef.current !== null) await (automatic ? skipAutomaticDive(sessionIdRef.current, current.item.request_id) : skipRequest(sessionIdRef.current, current.item.request_id))
    } catch {
      // A failed pass is not fatal: the request stays proposed in this
      // session and returns in the next one; the UI still moves forward.
    } finally {
      submittingRef.current = false
    }
    if (supersededRef.current || !aliveRef.current) return
    await advance()
  }

  function quit() {
    // In-flight votes land as persisted rows server-side; the UI here just
    // stays retired: no reveal resurrect, and pass() stops advancing too.
    supersededRef.current = true
    setPhase({ kind: 'summary' })
  }

  const replayDive = () => { setCommentOpen(false); setWatching(true); setReplayCount(value => value + 1) }

  const inStage = phase.kind === 'reviewing' || phase.kind === 'submitting' || phase.kind === 'reveal' || phase.kind === 'media-unavailable' || phase.kind === 'closed'
  const stageItem = inStage ? (phase as { item: QueueItem }).item : null

  return (
    <section className="eval-session" aria-label={t('evaluations.juryArea')}>
      {phase.kind === 'landing' && (
        <div className="eval-landing">
          {judgedCount > 0 && <p className="eval-count" role="status">{t('evaluations.counted', { count: judgedCount })}</p>}
          <button type="button" className="eval-start" onClick={() => void start()}>{t(automatic ? 'evaluations.dailyStart' : 'evaluations.start')}</button>
          <p className="eval-note">{t(automatic ? 'evaluations.automaticNote' : 'evaluations.startNote', { count: drawSize })}</p>
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
          onClose={() => { if (phase.kind === 'reviewing' && (score !== null || comment.trim())) setQuitRequested(true); else quit() }}
          hideChrome={watching && (phase.kind === 'reviewing' || phase.kind === 'reveal')}
          phase={watching && (phase.kind === 'reviewing' || phase.kind === 'reveal') ? 'watching' : phase.kind}
          head={
            <>
              <strong className="eval-head-owner">{stageItem.dive.owner_display_name ?? t('evaluations.unknownOwner')}</strong>
              <span className="eval-meta">{stageItem.dive.dive_code} · {stageItem.dive.height}</span>
              <span className="eval-count" role="status" aria-label={t('evaluations.counted', { count: judgedCount })} title={t('evaluations.counted', { count: judgedCount })}>
                {automatic ? `${offsetRef.current + judgedCount + passed.length + (phase.kind === 'reveal' ? 0 : 1)} / ${offsetRef.current + selectionSizeRef.current}` : judgedCount}
              </span>
            </>
          }
          prompt={stageItem.prompt}
          video={
            <EvaluationPlayer
              key={`eval-video-${stageItem.request_id}-${replayCount}`}
              requestId={stageItem.request_id}
              automatic={automatic}
              watching={watching && (phase.kind === 'reviewing' || phase.kind === 'reveal')}
              onEnded={() => setWatching(false)}
              onReplay={phase.kind === 'reviewing' || phase.kind === 'reveal' ? replayDive : undefined}
              onFailure={() => { setWatching(false); setPhase({ kind: 'media-unavailable', item: stageItem, reason: 'missing' }) }}
              paused={!watching || (phase.kind !== 'reviewing' && phase.kind !== 'reveal')}
            />
          }
        >
          {quitRequested && <QuitQuestion onStay={() => setQuitRequested(false)} onQuit={() => { setQuitRequested(false); quit() }} />}
          {phase.kind === 'reviewing' && !watching && (
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
              onReplay={replayDive}
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
          {phase.kind === 'reveal' && !watching && (
            <RevealPanel
              score={phase.score}
              results={phase.results}
              automatic={automatic}
              onReplay={replayDive}
              onNext={() => void advance()}
            />
          )}
          {phase.kind === 'media-unavailable' && (
            <div className="eval-state" role="alert">
              <p>{phase.reason === 'closed' ? t('evaluations.mediaClosed') : t('evaluations.mediaMissing')}</p>
              <button type="button" className="eval-start" onClick={() => { const item = phase.item; replayDive(); setPhase({ kind: 'reviewing', item }) }}>{t('evaluations.retry')}</button>
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
      {phase.kind === 'summary' && !onDone && (
        <SessionSummary
          judgedCount={judgedCount}
          rated={rated}
          passed={passed}
          automatic={automatic}
          onResume={automatic ? () => { batchRef.current = []; void start() } : undefined}
          onAgain={() => { dailyRef.current = false; startKeyRef.current = null; void start(); setSessionExpired(false) }}
        />
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* Judging dock: score keypad + one row of actions. The comment opens  */
/* as a chat-style composer that REPLACES the keypad (nothing overlaps)*/
/* and whose send button is the confirmation: Enter sends, as in any   */
/* messaging app; the arrow goes back to the keypad keeping the draft. */
/* ------------------------------------------------------------------ */
function JudgingDock({
  score, comment, commentOpen, saving, error,
  onScore, onComment, onCommentOpen, onConfirm, onPass, onReplay,
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
  onReplay?: () => void
}) {
  const { t, i18n } = useTranslation()
  const scoreText = score === null ? null : scoreNumber(score / 2, i18n.language)
  if (commentOpen && !saving) {
    return (
      <div className="eval-judging eval-composing" role="group" aria-label={t('evaluations.judgeAria')}>
        <header className="eval-composer-head">
          <button type="button" className="eval-composer-back" onClick={() => onCommentOpen(false)} aria-label={t('evaluations.backToScore')}>
            <ArrowLeft size={18} aria-hidden />
          </button>
          <ScoreCard scoreHalfSteps={score} ariaLabel={score === null ? t('evaluations.chooseScore') : t('evaluations.ariaScoreOf', { score: scoreText })} />
          <span>{score === null ? t('evaluations.composerNeedScore') : t('evaluations.composerFor', { score: scoreText })}</span>
        </header>
        <div className="eval-composer" id="eval-comment-field">
          <textarea
            aria-label={t('evaluations.commentAria')}
            maxLength={2000}
            rows={2}
            value={comment}
            enterKeyHint="send"
            placeholder={t('evaluations.commentPlaceholder')}
            onChange={(event) => onComment(event.target.value)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
              event.preventDefault()
              if (score === null) return
              event.currentTarget.blur()
              onConfirm()
            }}
            autoFocus
          />
          <button type="button" className="eval-send" disabled={score === null} onClick={(event) => { event.currentTarget.blur(); onConfirm() }}
            aria-label={score === null ? t('evaluations.composerNeedScore') : t('evaluations.sendAria', { score: scoreText })}>
            <SendHorizontal size={20} aria-hidden />
          </button>
        </div>
        {error && <p role="alert" className="eval-error">{error}</p>}
      </div>
    )
  }
  const confirmLabel = saving ? t('evaluations.saving') : t('evaluations.confirm')
  return (
    <div className="eval-judging" role="group" aria-label={t('evaluations.judgeAria')}>
      <ScoreInput score={score} disabled={saving} onScore={onScore} />
      <div className="eval-judge-actions">
        {onReplay && <button type="button" className="eval-pass eval-icon-action" onClick={onReplay} aria-label={t('evaluations.replayAria')}>↺</button>}
        <button
          type="button"
          className="eval-pass eval-icon-action eval-comment-toggle"
          aria-expanded={false}
          aria-controls="eval-comment-field"
          aria-label={comment ? t('evaluations.commentEdit') : t('evaluations.commentAdd')}
          data-filled={comment ? 'true' : undefined}
          disabled={saving}
          onClick={() => onCommentOpen(true)}
        >
          <MessageSquare size={18} aria-hidden />
        </button>
        <button type="button" className="eval-pass" disabled={saving} onClick={onPass}>{t('evaluations.pass')}</button>
        <button
          type="button"
          className="eval-confirm"
          data-saving={saving ? 'true' : undefined}
          disabled={saving || score === null}
          onClick={() => { (document.activeElement as HTMLElement | null)?.blur(); onConfirm() }}
        >
          {confirmLabel}
        </button>
      </div>
      {error && <p role="alert" className="eval-error">{error}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Reveal: peers flip first (staggered), then MY card arrives once.    */
/* my_rating already sits in results.ratings — never duplicated.       */
/* ------------------------------------------------------------------ */
function RevealPanel({ score, results, automatic, onNext, onReplay }: {
  score: number; results: JuryResults; automatic: boolean; onNext: () => void; onReplay: () => void
}) {
  const { t } = useTranslation()
  return <div className="eval-reveal">
    <ResultsBoard results={results} score={score} automatic={automatic} />
    <div className="eval-judge-actions">
      <button type="button" className="eval-pass eval-replay" onClick={onReplay} aria-label={t('evaluations.replayAria')}>↺</button>
      <button type="button" className="eval-confirm" onClick={onNext}>{t('evaluations.next')}</button>
    </div>
  </div>
}

/* ------------------------------------------------------------------ */
/* Session summary: real recap of this session + the invitation CTAs.  */
/* ------------------------------------------------------------------ */
function SessionSummary({
  judgedCount, rated, passed, onAgain, automatic, onResume,
}: {
  judgedCount: number
  rated: RatedEntry[]
  passed: PassedEntry[]
  onAgain: () => void
  automatic?: boolean
  onResume?: () => void
}) {
  const { t, i18n } = useTranslation()
  return (
    <div className="eval-summary">
      <p className="eval-count" role="status">{t('evaluations.summaryJudged', { count: judgedCount })}</p>
      {rated.length > 0 && (
        <ul className="eval-recap-list">
          {rated.map((entry) => (
            <li key={entry.request_id}>
              <ScoreCard scoreHalfSteps={entry.score_half_steps} ariaLabel={scoreNumber(entry.score_half_steps / 2, i18n.language)} />
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
      <p>{t(automatic ? 'evaluations.automaticFinished' : 'evaluations.exhausted')}</p>
      <div className="eval-judge-actions">
        <button type="button" className="eval-pass" onClick={onAgain}>{t(automatic ? 'evaluations.anotherStack' : 'evaluations.evaluateAgain')}</button>
        {onResume && <button type="button" className="eval-pass" onClick={onResume}>{t('evaluations.resumeStack')}</button>}
        <Link className="eval-confirm eval-link" to="/dives">{t('evaluations.requestDive')}</Link>
      </div>
      <p className="eval-note">{t('evaluations.requestDiveHint')}</p>
    </div>
  )
}

function QuitQuestion({ onStay, onQuit }: { onStay: () => void; onQuit: () => void }) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement>(null)
  useModalOverlay(ref, { layer: 85, onClose: onStay })
  return <div ref={ref} className="eval-quit-question" role="alertdialog" aria-modal="true" aria-label={t('evaluations.discardTitle')}>
    <p>{t('evaluations.discardDraft')}</p>
    <button type="button" onClick={onStay}>{t('evaluations.stay')}</button>
    <button type="button" onClick={onQuit}>{t('evaluations.quit')}</button>
  </div>
}
