import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import MemberAvatar, { AVATAR_HUDS, type AvatarHud } from '../src/components/MemberAvatar'
import './avatar-lab.css'

const portrait = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#294c52"/><stop offset="1" stop-color="#111e29"/></linearGradient></defs><path fill="url(#bg)" d="M0 0h256v256H0z"/><circle cx="202" cy="40" r="80" fill="#63948b" opacity=".15"/><path d="M36 256c0-64 34-85 92-85s92 21 92 85" fill="#192b37"/><path d="M102 145h52v46c-18 19-36 19-52 0" fill="#be8c6c"/><ellipse cx="128" cy="105" rx="48" ry="62" fill="#d5a17e"/><path d="M79 107c-15-50 7-85 47-85 49 0 62 35 51 77-8-30-15-27-31-42-12 21-36 29-67 31" fill="#28272b"/><path d="M91 125c7 38 25 46 37 46 21 0 36-17 42-43-23 22-52 22-79-3" fill="#353032"/><path d="M98 101h14M145 101h14" stroke="#332f2c" stroke-width="5" stroke-linecap="round"/><path d="M115 134q13 9 27 0" stroke="#eee0d1" stroke-width="3" fill="none"/><path d="M104 188l24 26 24-26" fill="none" stroke="#49766e" stroke-width="3"/></svg>`
const example = `data:image/svg+xml,${encodeURIComponent(portrait)}`
const descriptions = { orbit: 'A quiet circular signature. The photo stays in focus.', reticle: 'Camera brackets and a fine targeting ring. Closest to the analysis HUD.', depth: 'An angular instrument frame with subtle depth ticks.' }
function Lab() {
  const [hud, setHud] = useState<AvatarHud>('reticle')
  const [photo, setPhoto] = useState(example)
  const [light, setLight] = useState(false)
  useEffect(() => () => { if (photo.startsWith('blob:')) URL.revokeObjectURL(photo) }, [photo])
  const member = { display_name: 'Maxime Cauchy', avatar_url: photo, avatar_hud: hud }
  return <main className={light ? 'lab light' : 'lab'}>
    <header><div className="brand"><span className="brand-mark">≋</span>DIVE ANALYSER <span>/ IDENTITY LAB</span></div><button onClick={() => setLight(!light)}>{light ? 'Dark' : 'Light'} appearance</button></header>
    <section className="intro"><div><p className="eyebrow">ONE PHOTO. YOUR SIGNATURE.</p><h1>A familiar face.<br/><span>A Dive Analyser feel.</span></h1><p>Three HUD explorations using the same shared avatar.<br/>Compare the profile view and the small details in conversation.</p></div><div className="hero-avatar"><MemberAvatar member={member} size={164}/><span>{hud.toUpperCase()} / PROFILE</span></div></section>
    <div className="lab-toolbar"><label className="upload">Try your own photo<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => { const file = e.target.files?.[0]; if (file) setPhoto(URL.createObjectURL(file)); e.target.value = '' }}/></label><button onClick={() => setPhoto(example)}>Example illustration</button><button onClick={() => setPhoto('')}>Initials fallback</button><small>Local visual preview · no account changes</small></div>
    <section className="variants" aria-label="HUD versions">{AVATAR_HUDS.map((variant, index) => <button className="variant" aria-pressed={variant === hud} key={variant} onClick={() => setHud(variant)}><div className="variant-top"><span>0{index + 1} / {variant.toUpperCase()}</span><span>{variant === hud ? 'SELECTED' : 'TRY FRAME'}</span></div><MemberAvatar member={member} hud={variant} size={116}/><h2>{variant[0].toUpperCase() + variant.slice(1)}</h2><p>{descriptions[variant]}</p><div className="scale"><MemberAvatar member={member} hud={variant} size={48}/><MemberAvatar member={member} hud={variant} size={36}/><MemberAvatar member={member} hud={variant} size={28}/><span>48 / 36 / 28 px</span></div></button>)}</section>
    <section className="contexts"><article><p className="eyebrow">MEMBER PROFILE</p><div className="identity"><MemberAvatar member={member} size={80}/><div><h3>Maxime Cauchy</h3><p>@maxime_dive</p><small>Training, sharing, improving.</small></div></div></article><article><p className="eyebrow">COMMENTS & ACTIVITY</p><div className="identity"><MemberAvatar member={member} size={36}/><div><h3>Maxime Cauchy <time>14:32</time></h3><p>Much cleaner entry on this one.</p></div></div><div className="identity activity"><MemberAvatar member={member} size={28}/><p><strong>Maxime</strong> liked your dive <span>· 2 min ago</span></p></div></article><article><p className="eyebrow">FUTURE DM · VISUAL EXAMPLE</p><div className="identity"><MemberAvatar member={member} size={40}/><div><h3>Maxime Cauchy</h3><p>See you at the next session!</p></div><span className="dm-unread">1</span></div></article></section>
    <footer>Decorative frames only. The HUD does not represent presence, rank or a live score.</footer>
  </main>
}
createRoot(document.getElementById('root')!).render(<Lab/> )
