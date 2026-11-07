import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { formatDistanceToNowStrict, parseISO } from 'date-fns'
import { ChevronRight, Search, User } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { searchMembers, getMemberDirectory, type MemberSummary, type MemberTotals } from '../services/communityApi'
import { appLocale } from '../utils/dateLocale'
import MemberAvatar from '../components/MemberAvatar'
import PageLoading from '../components/PageLoading'
import Leaderboard from '../components/community/Leaderboard'
import { MobileShellActions } from '../navigation/mobileShellActions'
import '../components/code-analysis/codeAnalysis.css'
import '../components/community/community.css'

const RECENT_DAYS = 30
const DAY_MS = 86_400_000

export default function Community() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [directory, setDirectory] = useState<MemberSummary[] | null>(null)
  const [directoryMore, setDirectoryMore] = useState<{ after: number | null; hasMore: boolean } | null>(null)
  const [totals, setTotals] = useState<MemberTotals | null>(null)
  const [directoryLoadingMore, setDirectoryLoadingMore] = useState(false)
  const [results, setResults] = useState<MemberSummary[] | null>(null)
  const [searchAfter, setSearchAfter] = useState<number | null>(null)
  const [searchingMore, setSearchingMore] = useState(false)
  const [error, setError] = useState(false)
  const [retry, setRetry] = useState(0)
  const [showAll, setShowAll] = useState(false)
  const generation = useRef(0)

  const directoryGeneration = useRef(0)
  useEffect(() => {
    const controller = new AbortController()
    directoryGeneration.current += 1
    setError(false)
    // THIS generation owns the async control state: a stale continuation's
    // fenced `finally` can never clear `directoryLoadingMore` after the
    // generation changed, so the fresh pass clears it here (finding
    // 736422cd — a retry would otherwise strand its button disabled).
    setDirectoryLoadingMore(false)
    // One bounded page replaces the former up-to-20-request sequential load
    // (discovery 2026-11-01, profil 6). Continuation stays explicit.
    getMemberDirectory(undefined, controller.signal).then(page => {
      if (controller.signal.aborted) return
      setDirectory(page.items)
      setDirectoryMore({ after: page.next_after ?? null, hasMore: Boolean(page.has_more && page.next_after != null) })
      setTotals(page.totals ?? null)
    }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => { controller.abort(); setDirectoryMore(null) }
  }, [retry])

  async function moreDirectory() {
    if (!directoryMore?.after || directoryLoadingMore) return
    // A retry builds a fresh first page while this continuation is in
    // flight; only the owner of the current generation may write.
    const token = directoryGeneration.current
    setDirectoryLoadingMore(true); setError(false)
    try {
      const page = await getMemberDirectory(directoryMore.after)
      if (token !== directoryGeneration.current) return
      if (page.items.length) setDirectory(previous => [...(previous ?? []), ...page.items])
      setDirectoryMore({ after: page.next_after ?? null, hasMore: Boolean(page.has_more && page.next_after != null) })
      // An explicitly served `totals: null` means the aggregate is
      // UNAVAILABLE right now: the numbers previously displayed are stale,
      // not current — clear them so the banners fall back to count-free
      // (the old `?? totals` kept the stale counts). An omitted field
      // (older payload shape) leaves the displayed totals in place.
      if ('totals' in page) setTotals(page.totals ?? null)
    } catch { if (token === directoryGeneration.current) setError(true) }
    finally { if (token === directoryGeneration.current) setDirectoryLoadingMore(false) }
  }

  useEffect(() => {
    if (!q) { setResults(null); setSearchAfter(null); return }
    const current = ++generation.current
    const controller = new AbortController()
    setResults(null); setSearchAfter(null); setSearchingMore(false)
    const timer = window.setTimeout(() => {
      searchMembers(q, undefined, controller.signal).then(page => { if (current === generation.current) { setResults(page.items); setSearchAfter(page.next_after) } })
        .catch(() => { if (!controller.signal.aborted) setError(true) })
    }, 220)
    return () => { controller.abort(); window.clearTimeout(timer) }
  }, [q, retry])

  async function moreResults() {
    if (!q || searchAfter == null || searchingMore) return
    const current = generation.current
    setSearchingMore(true); setError(false)
    try {
      const page = await searchMembers(q, searchAfter)
      if (current !== generation.current) return
      setResults(previous => [...(previous ?? []), ...page.items])
      setSearchAfter(page.next_after)
    } catch { if (current === generation.current) setError(true) }
    finally { if (current === generation.current) setSearchingMore(false) }
  }

  const me = user?.user_id
  // Peers only: never you, never accounts bound to your own diver.
  const peers = useMemo(() => (directory ?? []).filter(member => member.user_id !== me && !member.linked), [directory, me])
  const excluded = useMemo(() => new Set((directory ?? []).filter(member => member.linked && member.user_id !== me).map(member => member.user_id)), [directory, me])
  const now = Date.now()
  const lastAt = (member: MemberSummary) => member.latest_dive_at ? Date.parse(member.latest_dive_at) : 0
  const divers = peers.filter(member => (member.accessible_dive_count ?? 0) > 0).sort((a, b) => lastAt(b) - lastAt(a))
  const recent = divers.filter(member => now - lastAt(member) <= RECENT_DAYS * DAY_MS)
  const others = peers.filter(member => !(member.accessible_dive_count ?? 0)).sort((a, b) => a.display_name.localeCompare(b.display_name))
  const ago = (iso: string) => formatDistanceToNowStrict(parseISO(iso), { addSuffix: true, locale: appLocale() })
  // Section banners stay the complete-directory count even while the page
  // continues explicitly: the server total, never a silently truncated slice.
  const diversTotal = totals?.divers ?? divers.length
  const othersTotal = totals?.others ?? others.length
  // Same totals rule for Recently active: the complete-directory window,
  // never the loaded page's slice.
  const recentTotal = totals?.recent ?? recent.length
  // Unavailable totals (aggregate failure → null) are NOT complete counts:
  // the banners drop the number instead of presenting page counts as the
  // full picture, and the continuation uses a count-free label.
  const totalsKnown = totals !== null

  const row = (member: MemberSummary, index: number) => <Link key={member.user_id} to={`/users/${member.user_id}`} className="cm-row ca-pop" style={{ '--i': Math.min(index, 12) } as CSSProperties}>
    <MemberAvatar member={member} size={48} />
    <span className="cm-row-main">
      <b>{member.display_name}{member.handle && <small> @{member.handle}</small>}</b>
      {/* Name and facts are separate lines: an unseen comma keeps the link's
          computed name from welding them ("Louis2 shared dives"). */}
      <span className="sr-only">{', '}</span>
      <span>{(member.accessible_dive_count ?? 0) > 0
        ? <>{t('community.sharedDives', { count: member.accessible_dive_count })}{member.latest_dive_at && <> · {ago(member.latest_dive_at)}</>}</>
        : t('community.noSharedDives')}</span>
    </span>
    <ChevronRight size={18} className="cm-row-go" aria-hidden="true" />
  </Link>

  return <div className="ca cm-page">
    <header className="cm-head">
      <h1>{t('community.title')}</h1>
      {user && <Link className="ca-pill cm-me-pill" to={`/users/${user.user_id}`}><User size={16} aria-hidden="true" />{t('community.myProfile')}</Link>}
      <MobileShellActions />
    </header>
    <label className="cm-search">
      <Search size={16} aria-hidden="true" />
      <span className="sr-only">{t('community.search')}</span>
      <input type="search" maxLength={120} value={q} onChange={event => setParams(event.target.value ? { q: event.target.value } : {}, { replace: true })} placeholder={t('community.searchPlaceholder')} />
    </label>
    {error && <p role="alert" className="cm-alert">{t('community.error')} <button type="button" onClick={() => setRetry(value => value + 1)}>{t('common.retry')}</button></p>}

    {q ? <section className="cm-list" aria-label={t('community.results')}>
      {results === null ? <PageLoading /> : results.length ? <>{results.map(row)}
        {searchAfter != null && <button type="button" onClick={() => void moreResults()} disabled={searchingMore} className="ca-pill cm-more">{searchingMore ? t('common.loading') : t('community.more')}</button>}</>
        : <p className="cm-empty">{t('community.empty')}</p>}
    </section> : directory === null ? <PageLoading /> : <>
      {(totalsKnown ? (totals!.recent > 0 || recent.length > 0) : recent.length > 0) && <section className="cm-section ca-arrive" aria-labelledby="cm-recent">
        <h2 id="cm-recent" className="cm-h2">{t('community.recentlyActive')}{totalsKnown && <span>{recentTotal}</span>}</h2>
        <div className="cm-stories">{recent.map((member, index) => <Link key={member.user_id} to={`/users/${member.user_id}`} className="cm-story ca-pop" style={{ '--i': index } as CSSProperties}>
          <span className={`cm-story-ring${now - lastAt(member) <= 7 * DAY_MS ? ' is-hot' : ''}`}><MemberAvatar member={member} size={36} /></span>
          <b>{member.display_name}</b>
          <span className="sr-only">{', '}</span>
          <small>{member.latest_dive_at && formatDistanceToNowStrict(parseISO(member.latest_dive_at), { locale: appLocale() })}</small>
        </Link>)}</div>
      </section>}

      <Leaderboard excluded={excluded} me={me} />

      {/* Section banners come from the directory totals: a category that
          lives entirely on a later page still gets its banner (empty of
          cards until the continuation carries it in), instead of the first
          page deciding which sections exist. */}
      {/* Section banners come from the directory totals: a category that
          lives entirely on a later page still gets its banner (empty of
          cards until the continuation carries it in), instead of the first
          page deciding which sections exist. When the totals are
          UNAVAILABLE (aggregate failure → null) the banners drop their
          count: a loaded page's slice is never presented as the full
          picture. */}
      {(totalsKnown ? (totals!.divers > 0 || divers.length > 0) : divers.length > 0) && <section className="cm-section" aria-labelledby="cm-divers">
        <h2 id="cm-divers" className="cm-h2">{t('community.divers')}{totalsKnown && <span>{diversTotal}</span>}</h2>
        <div className="cm-list">{divers.map(row)}</div>
      </section>}

      {(totalsKnown ? (totals!.others > 0 || others.length > 0) : others.length > 0) && <section className="cm-section" aria-labelledby="cm-others">
        <h2 id="cm-others" className="cm-h2">{t('community.otherMembers')}{totalsKnown && <span>{othersTotal}</span>}</h2>
        <div className="cm-chips">{(showAll ? others : others.slice(0, 8)).map((member, index) => <Link key={member.user_id} to={`/users/${member.user_id}`} className="cm-chip ca-pop" style={{ '--i': index } as CSSProperties}>
          <MemberAvatar member={member} size={30} />{member.display_name}
        </Link>)}
          {others.length > 8 && !showAll && <button type="button" className="cm-chip cm-chip-more" onClick={() => setShowAll(true)}>+{others.length - 8}</button>}
        </div>
      </section>}

      {directoryMore?.hasMore && <button type="button" className="ca-pill cm-more" onClick={() => void moreDirectory()} disabled={directoryLoadingMore}>
        {directoryLoadingMore ? t('common.loading')
          // Unavailable totals: a count-free label — "remaining 0" would be
          // a fabricated number.
          : totalsKnown ? t('community.remaining', { count: Math.max((totals?.members ?? 0) - peers.length, 0) }) : t('community.more')}
      </button>}
    </>}
  </div>
}
