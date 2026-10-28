import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Download, Lock, Settings, X } from 'lucide-react'
import DiveThumbnail from '../DiveThumbnail'
import type { Attempt } from '../../utils/attemptPresentation'
import SessionVideoPlayer from './SessionVideoPlayer'
import ShareDiveButton from '../clip-viewer/ShareDiveButton'
import { api } from '../../services/api'
import { formatBytes, formatDuration, sessionVideoPaths, type SharedTrainingSession, type SessionVideoInfo } from '../../services/sessionVideosApi'
import './sessionVideo.css'
import '../clip-viewer/clipViewer.css'

export function SessionPoster({video}: {video: SessionVideoInfo}) {
  return <DiveThumbnail compact dive={{id: video.id, thumb_url: video.poster_url, animated_url: video.animated_url} as Attempt} />
}
export default function SessionGallery({session, guest=false, onSignup, reload, guestBase}: {session: SharedTrainingSession; guest?: boolean; onSignup?:()=>void; reload?:()=>void; guestBase?:string}) {
  const root = useRef<HTMLElement>(null)
  useLayoutEffect(()=>{
    const resize=()=>{const node=root.current;if(!node)return;const nav=document.querySelector('.mobile-tab-bar')?.getBoundingClientRect();const bottom=nav && nav.height>0 ? nav.top-32 : window.innerHeight-(guest?52:16);node.style.setProperty('--session-height',`${Math.max(220,bottom-node.getBoundingClientRect().top)}px`)}
    resize();window.addEventListener('resize',resize);window.visualViewport?.addEventListener('resize',resize);return()=>{window.removeEventListener('resize',resize);window.visualViewport?.removeEventListener('resize',resize)}
  },[guest])
  const [selected, select] = useState<number | null>(null)
  const [settings, showSettings] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [moveDate, setMoveDate] = useState('')
  const [videos,setVideos] = useState(session.videos)
  const [next,setNext] = useState(session.next_video_id)
  useEffect(()=>{setVideos(session.videos);setNext(session.next_video_id)},[session])
  const pageUrl=guest ? `${guestBase}/recordings` : `/api/v1/shared-sessions/${session.session_id}`
  async function more() {const {data}=await api.get<SharedTrainingSession>(pageUrl,{params:{after:next}});setVideos(v=>[...v,...data.videos]);setNext(data.next_video_id)}
  const video = videos.find(v=>v.id===selected)
  const owner = videos.find(v=>v.can_share)
  const canManage = session.can_manage || Boolean(owner)
  const date = new Intl.DateTimeFormat('fr', {weekday:'long', day:'numeric', month:'long'}).format(new Date(session.date+'T12:00:00'))
  async function edit(id:number, payload:object) {
    setBusy(true); setError('')
    try { await api.patch(`/api/v1/session-videos/${id}`, payload); select(null); reload?.() }
    catch { setError('Modification impossible') } finally {setBusy(false)}
  }
  async function downloadAll() {
    if (guest) {onSignup?.(); return}
    setBusy(true)
    try {
      let remaining=videos, cursor=next
      do {
      for (const v of remaining.filter(v=>!v.hidden)) {
        const a=document.createElement('a'); a.href=sessionVideoPaths(v.id).download; a.download=v.filename
        a.target='_blank'; a.rel='noopener'; document.body.append(a); a.click(); a.remove()
        await new Promise(resolve=>setTimeout(resolve, 1000))
      }
      if(!cursor)break
      const {data}=await api.get<SharedTrainingSession>(pageUrl,{params:{after:cursor}})
      remaining=data.videos;cursor=data.next_video_id
      } while(remaining.length)
    } catch {setError('Téléchargement impossible')} finally {setBusy(false)}
  }
  return <main ref={root} className="session-gallery">
    <header><h1>{session.title || date}</h1><span>{session.video_count} {session.video_count === 1 ? 'vidéo' : 'vidéos'} · {formatDuration(session.total_duration)}</span>
      {canManage && <div className="session-video-actions"><ShareDiveButton id={session.session_id} sharesPath={`/api/v1/shared-sessions/${session.session_id}/shares`} label="Partager" /><button aria-label="Réglages" onClick={()=>showSettings(!settings)}><Settings size={20}/></button></div>}
    </header>
    {video && <section className="session-selected"><button aria-label="Fermer le lecteur" onClick={()=>select(null)}><X size={20}/></button>
      <SessionVideoPlayer key={video.id} info={video} playUrl={guest ? (video as SessionVideoInfo & {video_url:string}).video_url : sessionVideoPaths(video.id).play}
        downloadUrl={guest ? '' : sessionVideoPaths(video.id).download} onDownload={guest ? onSignup : undefined} reportUrl={guest ? `${guestBase}/videos/${video.id}/playback-issues` : sessionVideoPaths(video.id).report}/>
      <button className="session-video-download" onClick={()=>guest ? onSignup?.() : window.open(sessionVideoPaths(video.id).download, '_blank', 'noopener')}>
        {guest ? <Lock size={16}/> : <Download size={16}/>}Télécharger · {formatBytes(video.size_bytes,'fr')}</button>
    </section>}
    <div className={`session-strip ${video ? 'session-strip-small' : ''}`}>
      {videos.map(v=><div key={v.id} className="session-tile"><button aria-label={`Lire ${v.filename}`} aria-pressed={v.id===selected} onClick={()=>select(v.id)}>
        <div className="session-poster"><SessionPoster video={v}/></div>
        <span>{v.recorded_at ? new Date(v.recorded_at).toLocaleTimeString('fr',{hour:'2-digit',minute:'2-digit'}) : ''} · {formatDuration(v.duration_seconds)}{v.hidden ? ' · Masquée' : ''}</span>
      </button>
      {settings && v.can_share && <div className="session-settings">
        <button disabled={busy} onClick={()=>edit(v.id,{hidden:!v.hidden})}>{v.hidden?'Afficher':'Masquer'}</button>
        <button disabled={busy} onClick={()=>edit(v.id,{delete:true})}>Supprimer</button>
        <input aria-label="Date de destination" type="date" value={moveDate} onChange={e=>setMoveDate(e.target.value)}/>
        <button disabled={busy || !moveDate} onClick={()=>edit(v.id,{date:moveDate})}>Déplacer</button>
      </div>}
      </div>)}
      {next && <button onClick={()=>more().catch(()=>setError('Chargement impossible'))}>Autres vidéos</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    <button className="session-download-all" disabled={busy} onClick={downloadAll}>{guest ? <Lock size={18}/> : <Download size={18}/>}Tout télécharger · {formatBytes(session.total_bytes,'fr')}</button>
  </main>
}
