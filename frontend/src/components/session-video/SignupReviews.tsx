import {useEffect,useRef,useState} from 'react'
import {Link} from 'react-router-dom'
import {api} from '../../services/api'
type Review={id:number;user_id:number;name:string;email:string;candidate_name:string}
type Page={items:Review[];next_after:number|null}
export default function SignupReviews(){
 const [rows,setRows]=useState<Review[]>([]);const [next,setNext]=useState<number|null>(null);const [busy,setBusy]=useState(false);const [error,setError]=useState('')
 const pending=useRef<AbortController|null>(null)
 const load=async(after:number|null,append:boolean)=>{
   pending.current?.abort()
   const ctrl=new AbortController();pending.current=ctrl;setBusy(true)
   try{
     const {data}=await api.get<Page>('/api/v1/session-signup-reviews',{params:{after:after??0},signal:ctrl.signal})
     setRows(current=>append?[...current,...data.items]:data.items);setNext(data.next_after)
   }catch(event){if(!ctrl.signal.aborted)setError('File inaccessible')}
   finally{if(pending.current===ctrl){pending.current=null;setBusy(false)}}
 }
 useEffect(()=>{void load(null,false);return()=>pending.current?.abort()},[])
 if(!rows.length&&!busy)return null
 return <section className="border border-app p-4"><h2>Profils à rattacher</h2>{rows.map(r=><div key={r.id} className="flex flex-wrap items-center gap-3 py-2"><Link to={`/admin/users/${r.user_id}`}>{r.name} · {r.email}</Link><span>→ {r.candidate_name}</span><button className="touch-target border border-app px-3" onClick={async()=>{try{await api.post(`/api/v1/session-signup-reviews/${r.id}/accept`);setRows(rows=>rows.filter(row=>row.id!==r.id))}catch{setError('Rattachement impossible')}}}>Valider</button></div>)}{next!==null&&<button className="touch-target border border-app px-3" disabled={busy} onClick={()=>void load(next,true)}>Afficher plus</button>}{error&&<p role="alert">{error}</p>}</section>
}
