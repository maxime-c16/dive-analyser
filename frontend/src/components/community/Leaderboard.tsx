import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Flame, Rocket, TrendingUp, Compass } from 'lucide-react'
import MemberAvatar from '../MemberAvatar'
import { CountUp, Segmented } from '../code-analysis/parts'
import { getLeaderboard, type Leaderboard as Board, type LeaderboardMember, type LeaderboardPeriod } from '../../services/communityApi'
import { fmtScore } from '../../utils/codeStats'

const CATEGORIES = [
  { key: 'active', icon: Rocket, value: (m: LeaderboardMember) => m.attempts, digits: 0 },
  { key: 'streak', icon: Flame, value: (m: LeaderboardMember) => m.streak_weeks, digits: 0 },
  { key: 'progress', icon: TrendingUp, value: (m: LeaderboardMember) => m.delta ?? 0, digits: 1 },
  { key: 'explorer', icon: Compass, value: (m: LeaderboardMember) => m.codes, digits: 0 },
] as const
type Category = (typeof CATEGORIES)[number]['key']

/**
 * Community rankings for the week or the month: a podium for the top three,
 * then everyone else with a bar. You are always shown, highlighted, even
 * outside the top. Accounts bound to your own diver are left out.
 */
export default function Leaderboard({ excluded, me }: { excluded: Set<number>; me?: number }) {
  const { t } = useTranslation()
  const [period, setPeriod] = useState<LeaderboardPeriod>('week')
  const [category, setCategory] = useState<Category>('active')
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    let live = true
    setError(false)
    getLeaderboard(period).then(data => {
      if (!live) return
      // An empty week opens on the month instead of an empty podium (first load only).
      if (!touched.current && period === 'week' && !data.members.some(member => member.attempts > 0 && !excluded.has(member.user_id))) { setPeriod('month'); return }
      setBoard(data)
    }).catch(() => { if (live) setError(true) })
    return () => { live = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period])
  const touched = useRef(false)

  const spec = CATEGORIES.find(item => item.key === category)!
  const ranked = useMemo(() => (board?.members ?? [])
    // The viewer stays visible (highlighted below the top 10) even with a zero score.
    .filter(member => !excluded.has(member.user_id) && (spec.value(member) > 0 || member.user_id === me))
    .sort((a, b) => spec.value(b) - spec.value(a) || b.attempts - a.attempts), [board, excluded, me, spec])
  const top = ranked.slice(0, 3)
  const rest = ranked.slice(3, 10)
  const mine = me != null ? ranked.findIndex(member => member.user_id === me) : -1
  const max = ranked.length ? spec.value(ranked[0]) : 1
  const label = (member: LeaderboardMember) => t(`community.board.unit.${category}`, { count: spec.value(member), value: category === 'progress' ? `+${fmtScore(spec.value(member))}` : spec.value(member) })
  const replay = `${period}-${category}-${board?.end ?? ''}`
  const Value = ({ member }: { member: LeaderboardMember }) => category === 'progress'
    ? <>+<CountUp value={spec.value(member)} /></>
    : <CountUp value={spec.value(member)} digits={0} />

  return <section className="ca-panel cm-board ca-arrive" aria-labelledby="cm-board">
    <div className="ca-panel-h">
      <h2 id="cm-board">{t('community.board.title')}</h2>
      <Segmented label={t('community.board.periodAria')} value={period} onChange={value => { touched.current = true; setPeriod(value) }}
        options={[['week', t('community.board.week')], ['month', t('community.board.month')]] as const} />
    </div>
    <div className="ca-scroll cm-board-tabs" role="tablist" aria-label={t('community.board.categoryAria')}>
      {CATEGORIES.map(({ key, icon: Icon }) => <button key={key} type="button" role="tab" aria-selected={category === key} className="ca-pill" aria-pressed={category === key} onClick={() => setCategory(key)}>
        <Icon size={15} aria-hidden="true" />{t(`community.board.${key}`)}
      </button>)}
    </div>
    {error ? <p className="cm-empty">{t('community.error')}</p>
      : !board ? <div className="ca-skeleton" style={{ height: 220 }} />
      : !ranked.length ? <p className="cm-empty">{t(`community.board.empty.${category}`)}</p>
      : <div key={replay}>
        <ol className="cm-podium" aria-label={t('community.board.podium')}>
          {[top[1], top[0], top[2]].map((member, slot) => member && <li key={member.user_id} className={`cm-step is-${[2, 1, 3][slot]}${member.user_id === me ? ' is-me' : ''}`} style={{ '--i': [1, 0, 2][slot] } as CSSProperties}>
            <Link to={`/users/${member.user_id}`} className="cm-step-who" aria-label={`${[2, 1, 3][slot]}. ${member.display_name} · ${label(member)}`}>
              <span className="cm-step-avatar"><MemberAvatar member={member} size={[2, 1, 3][slot] === 1 ? 64 : 52} />{[2, 1, 3][slot] === 1 && <span className="cm-crown" aria-hidden="true">👑</span>}</span>
              <b>{member.user_id === me ? t('community.you') : member.display_name}</b>
              <span className="cm-step-value"><Value member={member} /></span>
            </Link>
            <span className="cm-step-block" aria-hidden="true">{[2, 1, 3][slot]}</span>
          </li>)}
        </ol>
        {(rest.length > 0 || mine >= 10) && <ol className="cm-ranks" start={4}>
          {rest.map((member, index) => <RankRow key={member.user_id} rank={index + 4} member={member} me={me} share={spec.value(member) / max} label={label(member)} index={index} />)}
          {mine >= 10 && <RankRow rank={mine + 1} member={ranked[mine]} me={me} share={spec.value(ranked[mine]) / max} label={label(ranked[mine])} index={rest.length} gap />}
        </ol>}
      </div>}
  </section>
}

function RankRow({ rank, member, me, share, label, index, gap = false }: { rank: number; member: LeaderboardMember; me?: number; share: number; label: string; index: number; gap?: boolean }) {
  const { t } = useTranslation()
  return <li className={`cm-rank ca-pop${member.user_id === me ? ' is-me' : ''}${gap ? ' is-gap' : ''}`} style={{ '--i': index + 3 } as CSSProperties}>
    <Link to={`/users/${member.user_id}`}>
      <span className="cm-rank-n">{rank}</span>
      <MemberAvatar member={member} size={34} />
      <span className="cm-rank-name">{member.user_id === me ? t('community.you') : member.display_name}</span>
      <span className="cm-rank-bar" aria-hidden="true"><i style={{ width: `${Math.max(6, share * 100)}%` }} /></span>
      <span className="cm-rank-value">{label}</span>
    </Link>
  </li>
}
