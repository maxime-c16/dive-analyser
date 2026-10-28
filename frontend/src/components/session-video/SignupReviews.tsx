import {useEffect,useState} from 'react'
import {Link} from 'react-router-dom'
import {api} from '../../services/api'
type Review={id:number;user_id:number;name:string;email:string;candidate_name:string}
export default function SignupReviews(){
 const [rows,setRows]=useState<Review[]>([]);const [error,setError]=useState('')
 useEffect(()=>{let live=true;(async()=>{const all:Review[]=[];let after=0;for(;;){const r=await api.get('/api/v1/session-signup-reviews',{params:{after}});all.push(...r.data.items);if(!r.data.next_after)break;after=r.data.next_after}if(live)setRows(all)})().catch(()=>{});return()=>{live=false}},[])
 if(!rows.length)return null
 return <section className="border border-app p-4"><h2>Profils à rattacher</h2>{rows.map(r=><div key={r.id} className="flex flex-wrap items-center gap-3 py-2"><Link to={`/admin/users/${r.user_id}`}>{r.name} · {r.email}</Link><span>→ {r.candidate_name}</span><button className="touch-target border border-app px-3" onClick={async()=>{try{await api.post(`/api/v1/session-signup-reviews/${r.id}/accept`);setRows(rows=>rows.filter(row=>row.id!==r.id))}catch{setError('Rattachement impossible')}}}>Valider</button></div>)}{error&&<p role="alert">{error}</p>}</section>
}
