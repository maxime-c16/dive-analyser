import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useSeriesMedia } from './useSeriesMedia'
import type { SeriesClip } from '../../services/seriesApi'
import { diveCodeName } from '../../i18n/diveNames'
import { useModalOverlay } from '../../utils/overlays'

export interface SeriesPlaybackEntry { code: string; clip: SeriesClip | null; poster?: string; playbackUrl?: string }

export default function SeriesPlayer({ entries, height, title, initialIndex, onClose }: {
  entries: SeriesPlaybackEntry[]; height: string; title: string; initialIndex?: number; onClose: () => void
}) {
  const { i18n } = useTranslation()
  const fr = i18n.language.startsWith('fr')
  const text = (a: string, b: string) => fr ? a : b
  const playable = entries.map((entry, index) => entry.clip ? index : -1).filter(i => i >= 0)
  const [current, setCurrent] = useState(initialIndex ?? playable[0] ?? 0)
  const [frames, setFrames] = useState<Record<number, boolean>>({})
  const [slow, setSlow] = useState(false)
  const [retry, setRetry] = useState(0)
  const [media, setMedia] = useSeriesMedia(entries, initialIndex, retry)
  const [playing, setPlaying] = useState(false)
  const [finished, setFinished] = useState(false)
  const [buffering, setBuffering] = useState(false)
  const [autoplayBlocked, setAutoplayBlocked] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const videos = useRef<Record<number, HTMLVideoElement | null>>({})
  const videoRefs = useRef<Record<number, (el: HTMLVideoElement | null) => void>>({})
  const videoRef = (index: number) => {
    if (!videoRefs.current[index]) videoRefs.current[index] = el => {
      const previous = videos.current[index]
      if (!el && previous) { previous.pause(); previous.removeAttribute('src'); previous.load() }
      videos.current[index] = el
      if (el) setFrames(old => old[index] ? { ...old, [index]: false } : old)
    }
    return videoRefs.current[index]
  }
  const currentRef = useRef(current)
  currentRef.current = current
  useModalOverlay(container, { onClose, initialFocus: () => closeButton.current, layer: 70 })


  const entry = entries[current]
  const state = entry?.clip ? media[entry.clip.video_uuid] : undefined
  const next = playable.find(i => i > current)
  const previous = [...playable].reverse().find(i => i < current)
  const frameReady = !!entry?.clip && !!frames[current]
  const waitingForVideo = !!entry?.clip && state?.state !== 'error' && (!frameReady || buffering)
  useEffect(() => {
    setSlow(false)
    if (!waitingForVideo) return
    const timer = window.setTimeout(() => setSlow(true), 10000)
    return () => window.clearTimeout(timer)
  }, [current, waitingForVideo, retry])
  const retryCurrent = () => {
    if (!entry?.clip) return
    const uuid = entry.clip.video_uuid
    setPlaying(false); setBuffering(false)
    setFrames(old => ({ ...old, [current]: false }))
    setMedia(old => { const value = { ...old, [uuid]: { state: 'loading' as const, poster: old[uuid]?.poster } }; return value })
    setRetry(r => r + 1)
  }
  const go = (index: number, continuePlaying = playing) => {
    videos.current[current]?.pause()
    const target = videos.current[index]
    if (target && target.readyState >= 1) target.currentTime = 0
    setCurrent(index); setFinished(false); setAutoplayBlocked(false)
    setBuffering(false); setPlaying(continuePlaying)
  }
  useEffect(() => {
    if (state?.state === 'error') {
      setPlaying(false); setBuffering(false)
      return
    }
    const video = videos.current[current]
    if (!video) return
    if (playing && state?.state === 'ready') {
      setBuffering(video.readyState < 3)
      void video.play().catch(() => {
        if (currentRef.current === current) { setAutoplayBlocked(true); setPlaying(false); setBuffering(false) }
      })
    } else video.pause()
  }, [current, playing, state?.url, state?.state])


  const start = () => {
    if (finished || !entry?.clip) go(playable[0], true)
    else {
      setAutoplayBlocked(false); setFinished(false)
      const video = videos.current[current]
      if (video?.ended) video.currentTime = 0
      setPlaying(true)
    }
  }
  return createPortal(<div className="series-player-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div ref={container} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="series-player-title" className="series-player">
      <header className="series-player-heading"><div><p>{height}</p><h2 id="series-player-title">{title}</h2></div><button ref={closeButton} onClick={onClose}>{text('Fermer', 'Close')} ×</button></header>
      {playable.length < entries.length && <p className="series-player-missing" role="status">{text(
        `${entries.length - playable.length} passage${entries.length - playable.length > 1 ? 's' : ''} sans clip · ${playable.length} vidéos`,
        `${entries.length - playable.length} slot(s) without a clip · ${playable.length} videos`)}</p>}
      <div className="series-player-stage" aria-busy={waitingForVideo}>
        {waitingForVideo && !frameReady && (state?.poster || entry?.poster) && <img className="series-player-poster" src={state?.poster || entry.poster} alt="" />}

        {entries.map((e, index) => {
          if (!e.clip || (index !== current && index !== next)) return null
          const item = media[e.clip.video_uuid]
          if (!item?.url) return null
          return <video key={index} ref={videoRef(index)} src={item.url} poster={item.poster}
            className={index === current ? 'is-current' : 'is-preloading'} aria-hidden={index !== current}
            aria-label={text(`Vidéo du passage ${index + 1}`, `Video for dive ${index + 1}`)}
            controls={index === current} playsInline preload="auto" muted={index !== current}
            onPlay={() => { if (index === currentRef.current) { setPlaying(true); setFinished(false) } }}
            onPause={e => { if (index === currentRef.current && !e.currentTarget.ended) setPlaying(false) }}
            onWaiting={() => { if (index === currentRef.current) setBuffering(true) }}
            onLoadedData={() => { setFrames(old => ({ ...old, [index]: true })) }}
            onCanPlay={() => { setFrames(old => ({ ...old, [index]: true })); if (index === currentRef.current) setBuffering(false) }}
            onPlaying={() => { if (index === currentRef.current) setBuffering(false) }}
            onError={() => {
              setMedia(old => ({ ...old, [e.clip!.video_uuid]: { state: 'error', poster: old[e.clip!.video_uuid]?.poster } }))
              if (index === currentRef.current) { setPlaying(false); setBuffering(false) }
            }}
            onEnded={() => {
              if (index !== currentRef.current) return
              if (next !== undefined) go(next, true)
              else { setPlaying(false); setFinished(true); setBuffering(false) }
            }} />
        })}
        {!entry?.clip ? <p>{text('Aucun clip pour ce passage.', 'No clip for this slot.')}</p>
          : state?.state === 'error' ? <div role="alert"><p>{state.forbidden ? text('Ce clip n’est plus accessible.', 'This clip is no longer accessible.') : text('Cette vidéo ne peut pas être lue pour le moment.', 'This video cannot be played right now.')}</p>
            {!state.forbidden && <button onClick={retryCurrent}>{text('Réessayer', 'Retry')}</button>}
          </div>
          : waitingForVideo && <div className="series-player-loading" role="status">
            <span className="series-loading-spinner" aria-hidden="true" />
            <strong>{state?.state === 'preparing' ? text('Préparation de la vidéo…', 'Preparing video…') : text('Chargement de la vidéo…', 'Loading video…')}</strong>
            {slow && <><p>{text('Cette vidéo prend plus de temps que prévu.', 'This video is taking longer than expected.')}</p><button onClick={retryCurrent}>{text('Réessayer', 'Retry')}</button></>}
          </div>}

        {finished && <div className="series-player-finished"><p>{text('Fin de la série', 'End of series')}</p><button onClick={() => go(playable[0], true)}>{text('Revoir la série', 'Replay series')}</button></div>}
      </div>
      <div className="series-player-controls"><button disabled={previous === undefined} onClick={() => previous !== undefined && go(previous)}>{text('Précédent', 'Previous')}</button>
        <button className="series-primary" disabled={!playable.length || state?.state === 'error'} onClick={() => playing ? setPlaying(false) : start()}>{playing ? (!frameReady ? text('Annuler', 'Cancel') : text('Pause', 'Pause')) : finished ? text('Revoir', 'Replay') : text('Lire la série', 'Play series')}</button>
        <span>{text('Passage', 'Dive')} {current + 1}/{entries.length} · {entry?.code || '—'}</span>
        <button disabled={next === undefined} onClick={() => next !== undefined && go(next)}>{state?.state === 'error' ? text('Passer ce clip', 'Skip this clip') : text('Suivant', 'Next')}</button>
      </div>
      {autoplayBlocked && <p className="series-player-resume" role="status">{text('Appuie sur Lire pour reprendre la lecture.', 'Press Play to resume playback.')}</p>}
      {entry?.code && <p className="series-player-dive-name">{diveCodeName(entry.code, fr ? 'fr' : 'en', { extended: true })}</p>}
      <ol className="series-player-timeline">{entries.map((e, index) => <li key={index}><button aria-current={index === current ? 'step' : undefined} onClick={() => go(index, false)}>
        <span className="series-player-position">{index + 1}</span><span className="series-player-code">{e.code || '—'}</span><span className="series-player-entry-name">{e.code ? diveCodeName(e.code, fr ? 'fr' : 'en', { extended: true }) : ''}</span><small>{!e.clip ? text('Sans clip', 'No clip') : media[e.clip.video_uuid]?.state === 'error' ? text('Indisponible', 'Unavailable') : media[e.clip.video_uuid]?.state === 'ready' ? '' : media[e.clip.video_uuid]?.state === 'preparing' ? text('Préparation…', 'Preparing…') : text('Vérification…', 'Checking…')}</small>
      </button></li>)}</ol>
    </div>
  </div>, document.body)
}
