/** Searchable, paginated owner library with community results kept on each video. */
import { Info, Search, SlidersHorizontal } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import DiveThumbnail from '../DiveThumbnail'
import { OwnedPanelLink } from './EvaluationSpaces'
import { scoreNumber } from './scoreFormatting'
import { getAutomaticScores, setAutomaticExclusion, type AutomaticScore, type AutomaticScoreFilters } from '../../services/evaluationApi'

export default function AutomaticScores() {
  const { t, i18n } = useTranslation()
  const [items, setItems] = useState<AutomaticScore[]>([])
  const [total, setTotal] = useState(0)
  const [params, setParams] = useSearchParams()
  const signature = JSON.stringify(['divePage','diveSearch','diveHeight','diveSince','diveScores','diveSort'].map(key => params.get(key)))
  const query = useMemo(() => readQuery(params), [signature])
  const [search, setSearch] = useState(query.search || '')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [error, setError] = useState<'load' | 'unsupported' | 'mutation' | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<number | null>(null)
  const [retry, setRetry] = useState(0)
  const firstLink = useRef<HTMLAnchorElement>(null)
  const root = useRef<HTMLElement>(null)
  const focusPage = useRef(false)
  const restored = useRef(false)
  function update(patch:Partial<typeof query>) {
    const next = { ...query, ...patch }
    // No new query means no new effect. Keep the settled result visible
    // instead of entering a loading state that nothing can resolve.
    if (Object.keys(next).every(key => next[key as keyof typeof next] === query[key as keyof typeof query])) return
    setLoading(true)
    setParams(previous => {
      const result = new URLSearchParams(previous)
      result.delete('diveFocus')
      for (const [key,value] of Object.entries({ divePage:next.offset ? String(next.offset/20+1) : '', diveSearch:next.search, diveHeight:next.height, diveSince:next.date_from, diveScores:next.score_state === 'all' ? '' : next.score_state, diveSort:next.sort === 'recent' ? '' : next.sort })) {
        if (value) result.set(key,value); else result.delete(key)
      }
      return result
    })
  }
  function filter(patch: AutomaticScoreFilters) { update({ ...patch, offset:0 }) }
  function page(offset:number) { focusPage.current = true; update({ offset }) }
  useEffect(() => { setSearch(query.search || '') }, [query.search])
  useEffect(() => {
    let live = true
    setLoading(true); setError(null)
    const { offset, ...filters } = query
    getAutomaticScores(offset, filters).then(data => { if (live) { setItems(data.items); setTotal(data.total) } })
      .catch(reason => { if (live) { setError(reason?.code === 'AUTOMATIC_FILTERS_UNAVAILABLE' ? 'unsupported' : 'load'); setItems([]); setTotal(0) } }).finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [query, retry])
  useEffect(() => {
    if (!loading && !error && focusPage.current && firstLink.current) {
      focusPage.current = false
      firstLink.current.focus({ preventScroll:true })
      firstLink.current.scrollIntoView?.({ block:'nearest' })
    }
  }, [loading, error, items])
  useEffect(() => {
    if (loading || error || restored.current) return
    const id = params.get('diveFocus')
    const link = id && root.current?.querySelector<HTMLAnchorElement>(`a[data-dive-id="${/^\d+$/.test(id) ? id : ''}"]`)
    if (link) { restored.current = true; link.focus({ preventScroll:true }); link.scrollIntoView?.({ block:'center' }) }
  }, [loading, error, items, params])
  async function toggle(item:AutomaticScore) {
    setBusy(item.dive_id); setError(null)
    try {
      await setAutomaticExclusion(item.dive_id, !item.excluded)
      setItems(rows => rows.map(row => row.dive_id === item.dive_id ? { ...row, excluded:!item.excluded } : row))
    } catch { setError('mutation') } finally { setBusy(null) }
  }
  const pages = Math.max(1, Math.ceil(total / 20))
  const activeFilters = [query.height, query.date_from, query.score_state !== 'all', query.sort !== 'recent'].filter(Boolean).length
  return <section ref={root} className="eval-owned eval-board eval-library" aria-busy={loading}>
    <header className="eval-board-head">
      <div className="eval-board-title"><h2>{t('evaluations.tabCommunity')}</h2>
        <details className="eval-rules"><summary aria-label={t('evaluations.rulesSummary')} title={t('evaluations.rulesSummary')}><Info size={16} aria-hidden="true" /></summary><p>{t('evaluations.communityNote')}</p></details>
      </div>
      <span className="eval-library-count" role="status">{!loading && !error && t('evaluations.browser.count', { count:total })}</span>
    </header>
    <form className="eval-library-filters" data-open={filtersOpen} onSubmit={event => { event.preventDefault(); filter({ search:search.trim() }) }}>
      <label className="eval-library-search"><span className="sr-only">{t('evaluations.browser.search')}</span><Search size={16} aria-hidden="true" />
        <input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder={t('evaluations.browser.searchPlaceholder')} />
        <button type="submit" aria-label={t('evaluations.browser.submit')}><Search size={18} aria-hidden="true" /></button>
      </label>
      <button className="eval-library-filter-toggle" type="button" data-active={activeFilters > 0} aria-label={activeFilters ? t('evaluations.browser.activeFilters', { count:activeFilters }) : t('evaluations.browser.filters')} aria-expanded={filtersOpen} aria-controls="eval-library-options" onClick={() => setFiltersOpen(open => !open)}><SlidersHorizontal size={18} aria-hidden="true" />{activeFilters > 0 && <b>{activeFilters}</b>}</button>
      <div className="eval-library-options" id="eval-library-options">
      <select aria-label={t('evaluations.browser.height')} value={query.height || ''} onChange={event => filter({ height:event.target.value })}>
        <option value="">{t('evaluations.browser.heightPlaceholder')}</option>{['1m','3m','5m','7m','7.5m','10m'].map(height => <option key={height}>{height}</option>)}
      </select>
      <select aria-label={t('evaluations.browser.scoreState')} value={query.score_state} onChange={event => filter({ score_state:event.target.value as AutomaticScoreFilters['score_state'] })}>
        <option value="all">{t('evaluations.browser.all')}</option><option value="scored">{t('evaluations.browser.scored')}</option><option value="awaiting">{t('evaluations.browser.awaiting')}</option>
      </select>
      <label className="eval-library-date"><span>{t('evaluations.browser.since')}</span><input type="date" lang={i18n.language} value={query.date_from?.slice(0,10) || ''} onChange={event => filter({ date_from:event.target.value ? `${event.target.value}T00:00:00` : '' })} /></label>
      <select aria-label={t('evaluations.sortAria')} value={query.sort} onChange={event => filter({ sort:event.target.value as AutomaticScoreFilters['sort'] })}>
        {(['recent','top','votes'] as const).map(sort => <option key={sort} value={sort}>{t(`evaluations.sort.${sort}`)}</option>)}
      </select>
      </div>
    </form>
    {error && <div role="alert"><p>{t(error === 'unsupported' ? 'evaluations.browser.searchUnavailable' : 'evaluations.loadError')}</p>{error !== 'unsupported' && <button className="eval-pass" onClick={() => setRetry(n => n + 1)}>{t('evaluations.retry')}</button>}{error !== 'mutation' && <button className="eval-pass" onClick={() => filter({ search:'', height:'', date_from:'', score_state:'all', sort:'recent' })}>{t('evaluations.browser.reset')}</button>}</div>}
    {loading ? <div className="eval-board-loading" role="status">{t('common.loading')}</div> : <>
      {!items.length && !error && <p>{t('evaluations.browser.empty')}</p>}
      <ul className="eval-library-grid">{items.map((item, index) => <li key={item.dive_id} className="eval-library-card">
        <Link ref={index === 0 ? firstLink : undefined} data-dive-id={item.dive_id} className="eval-library-dive" to={`/dives?clip=${item.dive_id}&scope=all`} onClick={event => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) setParams(previous => { const next = new URLSearchParams(previous); next.set('diveFocus',String(item.dive_id)); return next }, { replace:true }) }}>
          {item.video_uuid && <div className="eval-library-thumb" aria-hidden="true"><DiveThumbnail dive={item} compact /></div>}
          <div className="eval-library-identity"><strong>{item.dive_code}<span>{item.height}</span></strong>
            {item.dive_datetime ? <time dateTime={item.dive_datetime}>{new Date(item.dive_datetime).toLocaleString(i18n.language, { day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit' })}</time> : <small>{t('evaluations.attemptId', { id:item.dive_id })}</small>}
          </div>
        </Link>
        <div className="eval-library-result">{item.mean_score == null ? <span className="eval-score-empty">{t('evaluations.awaitingScores')}</span> : <strong>{scoreNumber(item.mean_score, i18n.language)}<small> / 10 · {t('evaluations.requestVotes', { count:item.rating_count })}</small></strong>}
          {item.rating_count > 0 && <OwnedPanelLink requestId={item.dive_id} automatic />}
        </div>
        <label className="eval-library-selection eval-switch"><small>{t(item.excluded ? 'evaluations.excludedFromSelections' : 'evaluations.inSelections')}</small>
          <input type="checkbox" role="switch" checked={!item.excluded} disabled={busy !== null} onChange={() => void toggle(item)} aria-label={t(item.excluded ? 'evaluations.includeAutomatic' : 'evaluations.excludeAutomatic')} /><span aria-hidden="true" />
        </label>
      </li>)}</ul>
      {!error && total > 20 && <nav className="eval-library-pager" aria-label={t('evaluations.browser.pages')}>
        <button className="eval-pass" disabled={query.offset === 0} onClick={() => page(Math.max(0,query.offset-20))}>{t('evaluations.previousPage')}</button>
        <span>{t('evaluations.pagePosition', { current:Math.floor(query.offset/20)+1, total:pages })}</span>
        <button className="eval-pass" disabled={query.offset+items.length >= total} onClick={() => page(query.offset+20)}>{t('evaluations.nextPage')}</button>
      </nav>}
    </>}
  </section>
}

function readQuery(params:URLSearchParams):AutomaticScoreFilters & { offset:number } {
  const page = params.get('divePage') || '1'
  const score = params.get('diveScores'), sort = params.get('diveSort'), since = params.get('diveSince') || ''
  return { offset:(/^\d{1,6}$/.test(page) && Number(page) > 0 ? Number(page)-1 : 0)*20,
    search:(params.get('diveSearch') || '').slice(0,100), height:params.get('diveHeight') || '',
    date_from:/^\d{4}-\d{2}-\d{2}T00:00:00$/.test(since) && Number.isFinite(Date.parse(since)) ? since : '',
    score_state:score === 'scored' || score === 'awaiting' ? score : 'all', sort:sort === 'top' || sort === 'votes' ? sort : 'recent' }
}
