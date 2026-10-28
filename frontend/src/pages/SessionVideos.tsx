import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import SessionGallery from '../components/session-video/SessionGallery'
import {getSessionVideo, getTrainingSession, trainingSessions, type SharedTrainingSession} from '../services/sessionVideosApi'

export function SessionVideoList() {
  const [items,setItems]=useState<SharedTrainingSession[]>([])
  useEffect(()=>{let alive=true; trainingSessions().then(d=>{if(alive)setItems(d.items)}).catch(()=>{});return()=>{alive=false}},[])
  return <main>{items.map(s=><Link className="block touch-target" key={s.session_id} to={`/sessions/shared/${s.session_id}`}>{s.date} · {s.video_count} vidéos</Link>)}</main>
}
export default function SessionVideoPage() {
  const {sessionId,videoId}=useParams()
  const [session,setSession]=useState<SharedTrainingSession|null>(null)
  const [error,setError]=useState(false)
  const [epoch,reload]=useState(0)
  useEffect(()=>{
    let alive=true; setSession(null);setError(false)
    const load=async()=>{const id=sessionId ? Number(sessionId) : (await getSessionVideo(Number(videoId))).session_id; return getTrainingSession(id!)}
    load().then(d=>{if(alive)setSession(d)}).catch(()=>{if(alive)setError(true)})
    return()=>{alive=false}
  },[sessionId,videoId,epoch])
  if(error)return <p role="alert">Séance indisponible</p>
  if(!session)return <PageLoading/>
  return <SessionGallery key={session.session_id} session={session} reload={()=>reload(v=>v+1)}/>
}
