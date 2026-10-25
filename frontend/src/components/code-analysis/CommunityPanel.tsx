import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'
import { ArrowLeft, Play } from 'lucide-react'
import MemberAvatar, { type AvatarIdentity } from '../MemberAvatar'
import DiveThumbnail from '../DiveThumbnail'
import type { CommunityMember } from '../../services/codeCommunityApi'
import { attemptScore } from '../../utils/attemptPresentation'
import { appLocale } from '../../utils/dateLocale'
import { fmtScore, scoreBand } from '../../utils/codeStats'

export type CommunityRow = {
  key: string; name: string; avatar: AvatarIdentity; count: number
  median: number; q1: number; q3: number; series: number[]
  member?: CommunityMember
}

function useMedia(query: string) {
  const get = () => typeof window !== 'undefined' && Boolean(window.matchMedia?.(query).matches)
  const [matches, setMatches] = useState(get)
  useEffect(() => {
    const list = window.matchMedia?.(query)
    if (!list) return
    const sync = () => setMatches(list.matches)
    sync()
    list.addEventListener?.('change', sync)
    return () => list.removeEventListener?.('change', sync)
  }, [query])
  return matches
}
export { useMedia }

const pct = (value: number) => `${Math.max(0, Math.min(10, value)) * 10}%`
// Diver records are often stored in capitals ("FANNY"); accounts keep their own spelling.
export const diverName = (member: CommunityMember) => member.account?.display_name
  ?? (member.name === member.name.toUpperCase() ? member.name.toLowerCase().replace(/(^|[\s'-])\p{L}/gu, letter => letter.toUpperCase()) : member.name)

/**
 * Where you stand on this code among divers with public attempts. Phone: the
 * ranking, and a tapped row turns the card into the comparison chart (back
 * returns to the ranking). Tablet/desktop: both side by side.
 */
export default function CommunityPanel({ me, members, hidden, height, onWatch, onAnalysis }: {
  me: CommunityRow
  height: string
  members: CommunityMember[]
  hidden: number
  onWatch: (member: CommunityMember, attemptId: number) => void
  onAnalysis: (member: CommunityMember) => void
}) {
  const { t } = useTranslation()
  const wide = useMedia('(min-width: 700px)')
  const panel = useRef<HTMLElement>(null)
  const others = useMemo<CommunityRow[]>(() => members.map(member => ({
    key: String(member.diver_id), name: diverName(member),
    avatar: member.account ?? { display_name: diverName(member) }, count: member.scored_count,
    median: member.median, q1: member.q1, q3: member.q3, series: member.series, member,
  })), [members])
  const rows = useMemo(() => [...others, me].sort((a, b) => b.median - a.median || b.count - a.count), [others, me])
  const [chosen, setChosen] = useState<string | null>(null)
  // Wide screens always show a comparison, so they start on the closest rival above you.
  const fallback = wide ? (rows.slice(0, rows.indexOf(me)).reverse()[0] ?? others[0])?.key ?? null : null
  const pickedKey = chosen ?? fallback
  const picked = others.find(row => row.key === pickedKey) ?? null
  const [direction, setDirection] = useState<'in' | 'out'>('in')

  const choose = (key: string | null) => {
    setDirection(key ? 'in' : 'out')
    setChosen(key)
    // The card changes height on phones: keep its top on screen.
    if (!wide) requestAnimationFrame(() => {
      const top = panel.current?.getBoundingClientRect().top ?? 0
      if (top < 0) panel.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
    })
  }

  const date = (value: string, pattern: string) => format(parseISO(value), pattern, { locale: appLocale() })
  const ago = (value: string) => formatDistanceToNowStrict(parseISO(value), { addSuffix: true, locale: appLocale() })
  const showRank = wide || !picked
  const showCompare = wide || Boolean(picked)

  const ranking = <div className={`ca-comm-rank${!wide ? ` ca-comm-swap is-${direction}` : ''}`} key="rank">
    <div className="ca-comm-axis" aria-hidden="true"><span /><span className="ca-comm-ticks"><i>0</i><i>5</i><i>10</i></span><span /></div>
    {rows.map((row, index) => {
      const isMe = row === me
      const content = <>
        <MemberAvatar member={row.avatar} size={36} />
        <span className="ca-comm-who"><b>{isMe ? t('codeAnalysis.community.you') : row.name}</b><small>{t('codeAnalysis.attemptsShort', { count: row.count })}</small></span>
        <span className="ca-comm-track" aria-hidden="true">
          <i className="ca-comm-mine" style={{ left: pct(me.median) }} />
          <i className="ca-comm-iqr" style={{ left: pct(row.q1), width: `${Math.max(1.5, (row.q3 - row.q1) * 10)}%`, '--i': index } as React.CSSProperties} />
          <i className={`ca-comm-dot ca-r-${scoreBand(row.median)}`} style={{ left: pct(row.median), '--i': index } as React.CSSProperties} />
        </span>
        <b className={`ca-comm-val ca-t-${scoreBand(row.median)}`}>{fmtScore(row.median)}</b>
      </>
      return isMe
        ? <div key={row.key} className="ca-comm-row is-me ca-pop" style={{ '--i': index } as React.CSSProperties}>{content}</div>
        : <button key={row.key} type="button" className="ca-comm-row ca-pop" style={{ '--i': index } as React.CSSProperties}
            aria-pressed={wide ? picked?.key === row.key : undefined} onClick={() => choose(row.key)}
            aria-label={t('codeAnalysis.community.compareWith', { name: row.name, median: fmtScore(row.median) })}>{content}</button>
    })}
    {hidden > 0 && <p className="ca-sample">{t('codeAnalysis.community.hidden', { count: hidden })}</p>}
  </div>

  const best = picked?.member?.best ?? null
  const comparison = picked && <div className={`ca-comm-compare${!wide ? ` ca-comm-swap is-${direction}` : ''}`} key="compare">
    {!wide && <button type="button" className="ca-back ca-comm-back" onClick={() => choose(null)}><ArrowLeft className="h-4 w-4" aria-hidden="true" />{t('codeAnalysis.community.ranking')}</button>}
    <div className="ca-comm-picked" key={picked.key}>
      <MemberAvatar member={picked.avatar} size={44} />
      <span className="ca-comm-who"><b>{picked.name}</b><small>{t('codeAnalysis.attemptsShort', { count: picked.count })} · {ago(picked.member!.last_attempt_at)}</small></span>
      <span className="ca-comm-vs"><b className={`ca-t-${scoreBand(picked.median)}`}>{fmtScore(picked.median)}</b><small>{t('codeAnalysis.community.vsYou', { score: fmtScore(me.median) })}</small></span>
    </div>
    {!wide && others.length > 1 && <div className="ca-comm-strip" role="group" aria-label={t('codeAnalysis.community.title')}>
      {rows.filter(row => row !== me).map(row => <button key={row.key} type="button" aria-pressed={row.key === picked.key} onClick={() => { setChosen(row.key) }} aria-label={row.name}>
        <MemberAvatar member={row.avatar} size={38} />
      </button>)}
    </div>}
    <CompareChart others={others} me={me} picked={picked.key} onPick={key => setChosen(key)} label={t('codeAnalysis.community.chartLabel', { name: picked.name })} />
    <div className="ca-legend">
      <span><i />{t('codeAnalysis.community.you')}</span>
      <span><i className="ca-comm-legend-picked" />{picked.name}</span>
      {others.length > 1 && <span><i className="ca-comm-legend-other" />{t('codeAnalysis.community.others')}</span>}
    </div>
    {best && <div className="ca-preview" key={`best-${best.id}`}>
      <span className="ca-thumb"><DiveThumbnail dive={best} compact /></span>
      <div style={{ minWidth: 0 }}>
        <div><span className={`ca-preview-score ca-t-${best.performance}`}>{fmtScore(attemptScore(best))}</span> </div>
        <div className="ca-preview-sub">{t('codeAnalysis.community.best')} · {date(best.dive_datetime, 'd MMM yy')} · {best.height}</div>
      </div>
      <button type="button" className="ca-btn" onClick={() => onWatch(picked.member!, best.id)}><Play className="h-4 w-4" aria-hidden="true" />{t('codeAnalysis.watch')}</button>
    </div>}
    <div className="ca-comm-actions">
      <button type="button" className="ca-pill" onClick={() => onAnalysis(picked.member!)}>{t('codeAnalysis.community.fullAnalysis')}</button>
      {picked.member!.account && <Link className="ca-pill" to={`/users/${picked.member!.account.user_id}`}>{t('codeAnalysis.community.profile')}</Link>}
    </div>
  </div>

  return <section ref={panel} className="ca-panel ca-comm">
    <div className="ca-panel-h"><h2>{t('codeAnalysis.community.title')}</h2><span>{height ? `${height} · ` : ''}{t('codeAnalysis.community.legend')}</span></div>
    <div className={`ca-comm-body${wide ? ' is-wide' : ''}`}>
      {showRank && ranking}
      {showCompare && comparison}
    </div>
  </section>
}

/**
 * Everyone's rolling median on one 0–10 scale over their last 40 graded
 * attempts, aligned on the newest. Pixel-sized viewBox so labels never stretch; the more
 * divers, the thinner and fainter the background lines. Lines draw in on
 * mount; picking someone re-mounts (and re-draws) only their line.
 */
function CompareChart({ others, me, picked, onPick, label }: {
  others: CommunityRow[]; me: CommunityRow; picked: string; onPick: (key: string) => void; label: string
}) {
  const host = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const element = host.current
    if (!element) return
    const measure = () => setWidth(element.clientWidth)
    measure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    observer?.observe(element)
    return () => observer?.disconnect()
  }, [])

  // G: a right gutter for the end values, so they never sit on the lines.
  const W = Math.max(260, width), H = W < 500 ? 190 : 220, L = 22, R = 4, G = 40, T = 14, B = 20
  const right = W - R - G
  // One step per attempt, newest on the right: a short history stays short.
  const slots = Math.max(2, me.series.length, ...others.map(row => row.series.length))
  const x = (index: number, count: number) => L + (slots - count + index) * (right - L) / (slots - 1)
  const y = (value: number) => T + (10 - value) * (H - T - B) / 10
  const path = (series: number[]) => series.map((value, index) => `${index ? 'L' : 'M'}${x(index, series.length).toFixed(1)},${y(value).toFixed(1)}`).join('')
  const crowd = others.length
  const pickedRow = others.find(row => row.key === picked)
  // Background lines are context: fainter and thinner as the crowd grows.
  const faint = Math.max(0.12, Math.min(0.3, 0.4 - crowd * 0.03))
  const thin = crowd > 6 ? 1 : 1.25
  // Lines draw in once; afterwards picking someone only restyles: their grey
  // line fades out, the highlight swaps in place, and the end markers stay put.
  const [intro, setIntro] = useState(true)
  const firstPick = useRef(picked)
  useEffect(() => { if (!width) return; const timer = window.setTimeout(() => setIntro(false), 1400); return () => window.clearTimeout(timer) }, [width > 0])

  const meLast = me.series[me.series.length - 1] ?? me.median
  const pickedLast = pickedRow?.series[pickedRow.series.length - 1] ?? meLast
  // End values sit in the gutter, pushed apart when the two lines finish close together.
  let meY = y(meLast), pickedY = y(pickedLast)
  if (pickedRow && Math.abs(meY - pickedY) < 18) {
    const mid = (meY + pickedY) / 2, meAbove = meLast > pickedLast || (meLast === pickedLast)
    meY = mid + (meAbove ? -9 : 9); pickedY = mid + (meAbove ? 9 : -9)
  }
  const motion = intro ? ' is-intro' : ''

  return <div ref={host} className="ca-chart ca-comm-chart" role="img" aria-label={label}>
    {width > 0 && <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} aria-hidden="true">
      {[0, 5, 10].map(value => <g key={value}>
        <line className="ca-grid" x1={L} x2={right} y1={y(value)} y2={y(value)} />
        <text className="ca-axis" x={L - 6} y={y(value) + 3} textAnchor="end">{value}</text>
      </g>)}
      {others.map((row, index) => <g key={row.key} className="ca-comm-other" onPointerDown={() => onPick(row.key)}>
        <path className="ca-comm-hit" d={path(row.series)} />
        <path className={`ca-comm-line${motion}`} pathLength={1} d={path(row.series)}
          style={{ strokeOpacity: row.key === picked ? 0 : faint, strokeWidth: thin, '--d': `${index * 60}ms` } as React.CSSProperties} />
      </g>)}
      {/* A halo in the panel colour separates the two highlighted lines where they cross the crowd. */}
      <path className="ca-comm-halo" d={path(me.series)} />
      <path className={`ca-comm-line ca-comm-me${motion}`} pathLength={1} d={path(me.series)} />
      {pickedRow && <path key={`halo-${pickedRow.key}`} className={`ca-comm-halo${pickedRow.key !== firstPick.current ? ' is-swap' : ''}`} d={path(pickedRow.series)} />}
      {pickedRow && <path key={pickedRow.key} className={`ca-comm-line ca-comm-picked-line${pickedRow.key !== firstPick.current ? ' is-swap' : motion}`} pathLength={1} d={path(pickedRow.series)} style={{ '--d': '120ms' } as React.CSSProperties} />}
      {me.series.length > 0 && <circle className={`ca-comm-tip is-me${motion}`} cx={right} cy={y(meLast)} r="3.5" />}
      {pickedRow && <circle className={`ca-comm-tip${motion}`} cx={right} cy={y(pickedLast)} r="3.5" />}
      {me.series.length > 0 && <text className={`ca-comm-end is-me${motion}`} x={right + 9} y={meY + 4}>{fmtScore(meLast)}</text>}
      {pickedRow && <text className={`ca-comm-end${motion}`} x={right + 9} y={pickedY + 4}>{fmtScore(pickedLast)}</text>}
    </svg>}
  </div>
}
