/**
 * The Judge tab once the stage is closed: today's carnets laid on the
 * judges' table next to the rest of the panel, the member's judging style,
 * the daily streak and a pool pace clock counting down to the next hand.
 * Everything comes from the server overview — nothing here is a local tally.
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Pause } from 'lucide-react'
import { ScoreCard } from './ScoreCards'
import type { EvaluationOverview, PanelVote } from '../../services/evaluationApi'

import { DEFAULT_DRAW_SIZE, MAX_DRAW_SIZE } from '../../hooks/useEvaluationDrawSize'
import { points } from './scoreFormatting'
export { points } from './scoreFormatting'

export default function JudgeTable({ overview, onResume, onDeal, onRequests, onHistory, drawSize = DEFAULT_DRAW_SIZE, onDrawSizeChange }: {
  drawSize?: number
  onDrawSizeChange?: (size: number) => void
  overview: EvaluationOverview
  onResume: () => void
  onDeal: () => void
  onRequests: () => void
  onHistory: () => void
}) {
  const { t } = useTranslation()
  const { today, judge } = overview
  const resume = today.resume
  const emptyPool = !resume && today.daily?.total === 0 && today.votes.length === 0
  return (
    <div className="eval-table">
      {resume ? (
        <section className="eval-paused" aria-labelledby="eval-paused-title">
          <p id="eval-paused-title"><Pause aria-hidden size={16} /> {t('evaluations.pausedTitle', { count: resume.remaining })}</p>
          <button type="button" className="eval-start" onClick={onResume}>{t('evaluations.pausedResume')}</button>
        </section>
      ) : (
        <header className="eval-table-head">
          <h2>{emptyPool ? t('evaluations.emptyPoolTitle') : t('evaluations.ripTitle')}</h2>
          <p>{emptyPool ? t('evaluations.emptyPoolNote') : t('evaluations.ripNote', { count: today.judged_today })}</p>
        </header>
      )}
      {judge.streak > 0 && <p className="eval-streak" title={t('evaluations.streakHint')}><span aria-hidden>🔥</span> {t('evaluations.streak', { count: judge.streak })}</p>}
      {today.votes.length > 0 && (
        <ul className="eval-table-cards" aria-label={t('evaluations.tableAria')}>
          {today.votes.map((vote, index) => <TableCard key={vote.dive_id} vote={vote} index={index} />)}
        </ul>
      )}
      <JudgeMeter bias={judge.bias} compared={judge.compared} />
      {onDrawSizeChange && (
        <section className="eval-draw-settings" aria-label={t('evaluations.drawSize')}>
          <label htmlFor="eval-draw-size">{t('evaluations.drawSize')}</label>
          <select id="eval-draw-size" value={drawSize} onChange={event => onDrawSizeChange(Number(event.target.value))}>
            {Array.from({ length: MAX_DRAW_SIZE }, (_, index) => index + 1).map(size => <option key={size} value={size}>{size}</option>)}
          </select>
          <p className="eval-note">{t('evaluations.drawSizeHint')}</p>
          <p className="eval-note">{t('evaluations.automaticNote', { count: drawSize })}</p>
        </section>
      )}
      {!resume && (
        <div className="eval-table-next">
          <PaceClock until={today.resets_at} />
          {!emptyPool && (
            <button type="button" className="eval-deal" onClick={onDeal}>
              <span className="eval-deal-backs" aria-hidden><i /><i /><i /></span>
              {t('evaluations.todayMore', { count: drawSize })}
            </button>
          )}
        </div>
      )}
      {overview.requests_pending > 0 && (
        <section className="eval-hub-card" aria-labelledby="eval-requests-title">
          <h2 id="eval-requests-title">{t('evaluations.requestsTitle')}</h2>
          <p>{t('evaluations.requestsPending', { count: overview.requests_pending })}</p>
          <button type="button" className="eval-pass" onClick={onRequests}>{t('evaluations.requestsCta')}</button>
        </section>
      )}
      {overview.judged_total > 0 && (
        <button type="button" className="eval-hub-link" onClick={onHistory}>
          {t('evaluations.judgedTotal', { count: overview.judged_total })} →
        </button>
      )}
    </div>
  )
}

function TableCard({ vote, index }: { vote: PanelVote; index: number }) {
  const { t, i18n } = useTranslation()
  const mine = vote.score_half_steps / 2
  const delta = vote.panel_mean === null ? null : Math.round((mine - vote.panel_mean) * 10) / 10
  return (
    <li className="eval-table-card" style={{ '--i': index } as CSSProperties}>
      <ScoreCard scoreHalfSteps={vote.score_half_steps} className="eval-card-raised" staggerMs={120 + index * 110}
        ariaLabel={t('evaluations.myCardAria', { score: points(mine, i18n.language) })} />
      <span className="eval-panel-chip">
        {vote.panel_mean === null ? t('evaluations.firstJudge') : t('evaluations.panelChip', { mean: points(vote.panel_mean, i18n.language) })}
      </span>
      {delta !== null && <span className="eval-delta" data-sign={delta > 0 ? 'up' : delta < 0 ? 'down' : 'even'}>{points(delta, i18n.language, true)}</span>}
      <strong>{vote.diver ?? t('evaluations.unknownOwner')}</strong>
      <span>{vote.dive_code} · {vote.height}</span>
    </li>
  )
}

const PERSONAS = [
  { max: -1.5, key: 'ice' },
  { max: -0.5, key: 'hard' },
  { max: 0.5, key: 'spot' },
  { max: 1.5, key: 'generous' },
  { max: Infinity, key: 'santa' },
] as const
const METER_RANGE = 3

/** Harsh ◀── spot-on ──▶ generous, from my scores minus the other judges'. */
export function JudgeMeter({ bias, compared }: { bias: number | null; compared: number }) {
  const { t, i18n } = useTranslation()
  const known = bias !== null && compared >= 3
  const persona = known ? PERSONAS.find(item => bias < item.max)!.key : null
  const position = known ? 50 + (Math.max(-METER_RANGE, Math.min(METER_RANGE, bias)) / METER_RANGE) * 50 : 50
  return (
    <section className="eval-meter" aria-labelledby="eval-meter-title">
      <h2 id="eval-meter-title">{persona ? t(`evaluations.persona.${persona}`) : t('evaluations.persona.unknown')}</h2>
      <div className="eval-meter-track" role="img" aria-label={known ? t('evaluations.meterAria', { bias: points(bias, i18n.language, true) }) : t('evaluations.persona.unknown')}>
        <span className="eval-meter-zone" aria-hidden />
        <span className="eval-meter-needle" data-known={known ? 'true' : undefined} style={{ '--pos': `${position}%` } as CSSProperties} aria-hidden>{known ? '' : '?'}</span>
      </div>
      <div className="eval-meter-ends" aria-hidden><span>{t('evaluations.meterHarsh')}</span><span>{t('evaluations.meterGenerous')}</span></div>
      <p className="eval-note">
        {known
          ? t(bias >= 0 ? 'evaluations.meterAbove' : 'evaluations.meterBelow', { delta: points(Math.abs(bias), i18n.language), count: compared })
          : t('evaluations.meterLearning', { count: Math.max(1, 3 - compared) })}
      </p>
    </section>
  )
}

/** A pool pace clock: the sweep hand runs, the digits count to the next hand. */
export function PaceClock({ until }: { until: string }) {
  const { t, i18n } = useTranslation()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const left = Math.max(0, Math.floor((new Date(until).getTime() - now) / 1000))
  const pad = (value: number) => String(value).padStart(2, '0')
  const digits = `${pad(Math.floor(left / 3600))}:${pad(Math.floor(left / 60) % 60)}:${pad(left % 60)}`
  return (
    <div className="eval-pace">
      <span className="eval-pace-face" aria-hidden><span className="eval-pace-hand" /></span>
      <span>
        <small>{t('evaluations.nextHand')}</small>
        <strong className="eval-pace-digits" role="timer" aria-label={t('evaluations.nextHandAria', { time: new Date(until).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' }) })}>{digits}</strong>
      </span>
    </div>
  )
}
