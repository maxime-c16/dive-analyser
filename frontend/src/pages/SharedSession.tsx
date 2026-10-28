import { useEffect, useState } from 'react'
import { useLocation, useParams, Link, useNavigate } from 'react-router-dom'
import PageLoading from '../components/PageLoading'
import SessionGallery from '../components/session-video/SessionGallery'
import { visitSharedSession, type SharedSessionVideo } from '../services/sessionVideosApi'
import { api } from '../services/api'
import { useAuth } from '../contexts/AuthContext'

type Group={id:number;name:string;club_id:number;club:string}
export default function SharedSession() {
  const {shareId}=useParams(); const {hash,pathname}=useLocation(); const navigate=useNavigate()
  const {user,refresh}=useAuth()
  const [session,setSession]=useState<SharedSessionVideo|null>(null)
  const [error,setError]=useState(''); const [signup,setSignup]=useState(false)
  const [groups,setGroups]=useState<Group[]>([]); const [club,setClub]=useState(''); const [group,setGroup]=useState('')
  const [emailEnabled,setEmail]=useState(true); const [done,setDone]=useState(''); const [busy,setBusy]=useState(false)
  useEffect(()=>{let alive=true;setSession(null);setError('')
    if(!/^\d+$/.test(shareId??'') || !/^[A-Za-z0-9_-]{43}$/.test(hash.slice(1))){setError('Lien invalide');return}
    visitSharedSession(shareId!,hash.slice(1)).then(d=>{if(alive){setSession(d);if(user)navigate(`/sessions/shared/${d.session_id}`,{replace:true})}})
      .catch(()=>{if(alive)setError('Séance indisponible')});return()=>{alive=false}
  },[shareId,hash,user,navigate])
  useEffect(()=>{if(!signup)return;let alive=true;api.get<Group[]>(`/api/v1/shared-dives/sessions/${shareId}/groups`).then(r=>{if(alive)setGroups(r.data)}).catch(()=>setError('Groupes indisponibles'));return()=>{alive=false}},[signup,shareId])
  if(done)return <main className="session-onboarding"><h1>Compte créé</h1><p>Vous recevrez un e-mail pour les prochaines séances de votre groupe.</p>
    <label><input type="checkbox" checked={emailEnabled} onChange={async e=>{const enabled=e.target.checked;await api.put('/api/v1/session-preferences',{enabled});setEmail(enabled)}}/>E-mails de mon groupe</label>
    <button onClick={async()=>{await refresh();navigate(done)}}>Ouvrir la séance</button></main>
  if(error && !session)return <main><p role="alert">{error}</p></main>
  if(!session)return <PageLoading/>
  if(signup)return <main className="session-onboarding"><h1>Créer mon compte</h1>
    <Link to={`/login?next=${encodeURIComponent(pathname+hash)}`}>Se connecter</Link>
    <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');const form=new FormData(e.currentTarget)
      try {const r=await api.post(`/api/v1/shared-dives/sessions/${shareId}/signup`,{display_name:form.get('name'),email:form.get('email'),password:form.get('password'),group_id:Number(group),email_enabled:emailEnabled});setDone(r.data.path)}
      catch {setError('Inscription impossible. Vérifiez vos informations ou connectez-vous.')}finally{setBusy(false)}
    }}>
      <input name="name" aria-label="Nom" placeholder="Nom" autoComplete="name" required maxLength={100}/>
      <input name="email" aria-label="E-mail" placeholder="E-mail" autoComplete="email" type="email" required/>
      <input name="password" aria-label="Mot de passe" placeholder="Mot de passe" autoComplete="new-password" type="password" minLength={10} required/>
      <select aria-label="Club" required value={club} onChange={e=>{setClub(e.target.value);setGroup('')}}><option value="">Club</option>{[...new Map(groups.map(g=>[g.club_id,g.club])).entries()].map(([id,name])=><option key={id} value={id}>{name}</option>)}</select>
      <select aria-label="Groupe" required value={group} onChange={e=>setGroup(e.target.value)}><option value="">Groupe</option>{groups.filter(g=>String(g.club_id)===club).map(g=><option key={g.id} value={g.id}>{g.name}</option>)}</select>
      <label><input type="checkbox" checked={emailEnabled} onChange={e=>setEmail(e.target.checked)}/>E-mails de mon groupe</label>
      {error && <p role="alert">{error}</p>}<button disabled={busy}>Créer mon compte</button>
    </form><button onClick={()=>setSignup(false)}>Retour</button></main>
  return <div className="shared-session"><SessionGallery session={session} guest guestBase={`/api/v1/shared-dives/sessions/${shareId}`} onSignup={()=>setSignup(true)}/><Link className="session-login" to={`/login?next=${encodeURIComponent(pathname+hash)}`}>Se connecter</Link></div>
}
