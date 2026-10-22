import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { seriesApi, seriesClipScore, type SeriesChoice, type SeriesClip, type SeriesClipPolicy } from '../../services/seriesApi'
import { api } from '../../services/api'
import { diveCodeName } from '../../i18n/diveNames'
import { useModalOverlay } from '../../utils/overlays'
import { useSeriesMobileLayout } from './SeriesPanel'
import { useSeriesMedia } from './useSeriesMedia'

type Preview = { poster_url?: string; playback_url?: string }
export default function SeriesComparison({ main, alternative, height, policy, previews, onClose, onUse }: {
  main: SeriesChoice; alternative: SeriesChoice; height: string; policy: SeriesClipPolicy
  previews: Record<string, Preview>; onClose: () => void; onUse: (main: SeriesChoice, alternative: SeriesChoice) => void
}) {
  const { i18n } = useTranslation()
  const fr = i18n.language.startsWith('fr')
  const text = (a: string, b: string) => fr ? a : b
  const mobile = useSeriesMobileLayout()
  const root = useRef<HTMLDivElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const videos = useRef<Array<HTMLVideoElement | null>>([])
  const videoRefs = useRef<Record<number, (el: HTMLVideoElement | null) => void>>({})
  const videoRef = (side: number) => {
    if (!videoRefs.current[side]) videoRefs.current[side] = el => {
      const previous = videos.current[side]
      if (previous && previous !== el) { previous.pause(); previous.removeAttribute('src'); previous.load() }
      videos.current[side] = el
      if (el) setDecoded(old => old[el.dataset.clipKey!] ? { ...old, [el.dataset.clipKey!]: false } : old)
    }
    return videoRefs.current[side]
  }
  const [choices, setChoices] = useState([main, alternative])
  const [candidates, setCandidates] = useState<SeriesClip[][]>([[], []])
  const [clipError, setClipError] = useState(false)
  const [tab, setTab] = useState(0)
  const [retry, setRetry] = useState(0)
  const [slow, setSlow] = useState(false)
  const [decoded, setDecoded] = useState<Record<string, boolean>>({})
  useModalOverlay(root, { onClose, initialFocus: () => close.current, layer: 75 })
  useEffect(() => {
    let live = true
    const controller = new AbortController()
    ;[main, alternative].forEach((choice, side) => {
      if (choice.dd === undefined) api.get<{ dd_value: number }>(`/api/v1/dd/lookup/${choice.code}/${height}`, { signal: controller.signal, timeout: 12000 })
        .then(response => { if (live) setChoices(old => old.map((c, i) => i === side ? { ...c, dd: response.data.dd_value } : c)) })
        .catch(() => { if (live) setChoices(old => old.map((c, i) => i === side ? { ...c, dd: null } : c)) })
      seriesApi.clips(choice.code, height, policy).then(rows => {
        if (live) {
          setCandidates(old => old.map((list, i) => i === side ? rows : list))
          if (rows.length) setChoices(old => old.map((c, i) => i === side && !c.clip && !c.clip_id ? { ...c, clip: rows[0] } : c))
        }
      }).catch(() => { if (live) setClipError(true) })
    })
    return () => {
      live = false
      controller.abort()
    }
  }, [main, alternative, height, policy])
  const entries = useMemo(() => choices.map(choice => {
    const preview = choice.clip ? previews[choice.clip.video_uuid] : undefined
    return { clip: choice.clip ?? null, poster: preview?.poster_url, playbackUrl: preview?.playback_url }
  }), [choices, previews])
  const [media, setMedia] = useSeriesMedia(entries, 0, retry)
  const select = (side: number, id: number) => {
    videos.current[side]?.pause()
    const clip = candidates[side].find(c => c.id === id)
    if (clip) setChoices(old => old.map((choice, i) => i === side ? { ...choice, clip_id: clip.id, clip } : choice))
  }
  const waitingKeys = choices.flatMap((choice, side) => choice.clip && media[choice.clip.video_uuid]?.state !== 'error' && !decoded[`${side}:${choice.clip.video_uuid}`] ? [`${side}:${choice.clip.video_uuid}`] : []).join(',')
  useEffect(() => {
    setSlow(false)
    if (!waitingKeys) return
    const timer = window.setTimeout(() => setSlow(true), 10000)
    return () => window.clearTimeout(timer)
  }, [waitingKeys, retry])
  const retrySide = (side: number) => {
    const uuid = choices[side].clip?.video_uuid
    if (!uuid) return
    setDecoded(old => ({ ...old, [`${side}:${uuid}`]: false }))
    setMedia(old => ({ ...old, [uuid]: { state: 'loading', poster: old[uuid]?.poster } }))
    setRetry(value => value + 1)
  }
  const switchTab = (side: number) => { videos.current.forEach(v => v?.pause()); setTab(side) }
  const score = (side: number) => choices[side].clip ? seriesClipScore(choices[side].clip!) : null
  const points = (side: number) => score(side) != null && choices[side].dd != null ? score(side)! * choices[side].dd! * 3 : null
  const number = (value: number | null | undefined, digits = 1) => value == null ? '—' : value.toLocaleString(fr ? 'fr' : 'en', { maximumFractionDigits: digits })
  const difference = (a: number | null | undefined, b: number | null | undefined) => a == null || b == null ? '—' : `${b - a > 0 ? '+' : ''}${number(b - a, 2)}`
  return createPortal(<div className="series-compare-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div ref={root} role="dialog" aria-modal="true" aria-labelledby="series-compare-title" tabIndex={-1} className="series-workspace series-compare">
      <header className="series-compare-heading"><h2 id="series-compare-title">{main.code} / {alternative.code} · {height}</h2><button ref={close} onClick={onClose}>{text('Fermer', 'Close')} ×</button></header>
      {mobile && <div className="series-compare-tabs" role="tablist" aria-label={text('Plongeon à regarder', 'Dive to watch')}>
        {choices.map((choice, side) => <button key={side} role="tab" id={`series-compare-tab-${side}`} aria-controls={`series-compare-side-${side}`} aria-selected={tab === side} tabIndex={tab === side ? 0 : -1}
          onKeyDown={e => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); switchTab(1 - side); document.getElementById(`series-compare-tab-${1 - side}`)?.focus() } }}
          onClick={() => switchTab(side)}>{side === 0 ? text('Ma série', 'My series') : text('Alternative', 'Alternative')} · {choice.code}</button>)}
      </div>}
      <div className="series-compare-videos">{choices.map((choice, side) => {
        const item = choice.clip ? media[choice.clip.video_uuid] : undefined
        const poster = item?.poster || entries[side].poster
        const clipKey = `${side}:${choice.clip?.video_uuid}`
        const waiting = !!choice.clip && item?.state !== 'error' && !decoded[clipKey]
        return <section key={side} id={`series-compare-side-${side}`} hidden={mobile && tab !== side} role={mobile ? 'tabpanel' : undefined} aria-labelledby={mobile ? `series-compare-tab-${side}` : undefined}>
          {!mobile && <h3>{side === 0 ? text('Ma série', 'My series') : text('Alternative', 'Alternative')} · {choice.code}</h3>}
          <div className="series-compare-video" aria-busy={waiting}>
            {poster && waiting && <img src={poster} alt="" />}
            {item?.url && <video key={choice.clip!.video_uuid} ref={videoRef(side)} data-clip-key={clipKey} src={item.url} poster={poster} controls playsInline preload="auto"
              aria-label={text(`Vidéo ${choice.code}`, `${choice.code} video`)}
              onPlay={() => videos.current[1 - side]?.pause()}
              onLoadedData={() => setDecoded(old => ({ ...old, [clipKey]: true }))}
              onError={() => setMedia(old => ({ ...old, [choice.clip!.video_uuid]: { state: 'error', poster } }))} />}
            {!choice.clip ? <p>{text('Aucun clip', 'No clip')}</p> : item?.state === 'error' ? <div role="alert"><p>{text('Vidéo indisponible', 'Video unavailable')}</p>{!item.forbidden && <button onClick={() => retrySide(side)}>{text('Réessayer', 'Retry')}</button>}</div>
              : waiting && <div className="series-compare-loading" role="status"><span className="series-loading-spinner" aria-hidden="true" />{item?.state === 'preparing' ? text('Préparation…', 'Preparing…') : text('Chargement…', 'Loading…')}{slow && <button onClick={() => retrySide(side)}>{text('Réessayer', 'Retry')}</button>}</div>}
          </div>
          <div className="series-compare-caption"><span>{diveCodeName(choice.code, fr ? 'fr' : 'en', { extended: true })}</span>
            {choice.clip && <select aria-label={text(`Clip ${choice.code}`, `${choice.code} clip`)} value={choice.clip.id} onChange={e => select(side, Number(e.target.value))}>
              {[choice.clip, ...candidates[side].filter(c => c.id !== choice.clip!.id)].map(clip => <option key={clip.id} value={clip.id}>{new Date(clip.date).toLocaleDateString(fr ? 'fr' : 'en')} · {seriesClipScore(clip) == null ? text('Sans note', 'Unrated') : `${number(seriesClipScore(clip), 2)}/10`}</option>)}
            </select>}
          </div>
        </section>
      })}</div>
      <div className="series-compare-decision">
        <table><thead><tr><th scope="col" /><th scope="col">{main.code}</th><th scope="col">{alternative.code}</th><th scope="col">{text('Écart', 'Difference')}</th></tr></thead>
          <tbody>{[[text('DD', 'DD'), choices[0].dd, choices[1].dd], [text('Note /10', 'Score /10'), score(0), score(1)], [text('Points estimés', 'Estimated points'), points(0), points(1)]].map(([label, a, b]) => <tr key={String(label)}><th scope="row">{label}</th><td>{number(a as number | null, 2)}</td><td>{number(b as number | null, 2)}</td><td>{difference(a as number | null, b as number | null)}</td></tr>)}</tbody>
        </table>
        <footer><small>{text('Estimation : note × DD × 3', 'Estimate: score × DD × 3')}</small><button className="series-primary" onClick={() => onUse(choices[0], choices[1])}>{text(`Utiliser ${alternative.code}`, `Use ${alternative.code}`)}</button></footer>
        {clipError && <p role="status">{text('Les autres clips n’ont pas pu être chargés.', 'Other clips could not be loaded.')}</p>}
      </div>
    </div>
  </div>, document.body)
}
