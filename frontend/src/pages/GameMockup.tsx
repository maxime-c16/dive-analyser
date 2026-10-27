// TEMPORARY design mockup for the Judge Room game. Not shipped.
import { useEffect, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, Copy, Crown, Link2, Play, Share2, Timer, UserPlus } from 'lucide-react'
import MemberAvatar from '../components/MemberAvatar'
import { ScoreCard } from '../components/evaluation/ScoreCards'
import ScoreInput from '../components/evaluation/ScoreInput'
import { MobileShellActions } from '../navigation/mobileShellActions'
import { getProfileDives, searchMembers, type MemberSummary, type ProfileDive } from '../services/communityApi'
import { useAuth } from '../contexts/AuthContext'
import '../components/code-analysis/codeAnalysis.css'
import '../components/community/community.css'
import '../components/evaluation/evaluationA.css'
import './gameMockup.css'

type Judge = { key: string; name: string; human?: MemberSummary; ghost?: string; kind: string; score: number; line?: string }

const GHOSTS = { mum: '🥰', coach: '🧊', echo: '👻', olympian: '🏅', maxime: '🌑' }

function Seat({ judge, size = 44 }: { judge: Judge; size?: number }) {
  if (judge.human) return <MemberAvatar member={judge.human} size={size} />
  return <span className="gm-ghost" style={{ width: size, height: size, fontSize: size * .5 }}>{judge.ghost}</span>
}

export default function GameMockup() {
  const [params, setParams] = useSearchParams()
  const screen = params.get('s') ?? 'lobby'
  const { user } = useAuth()
  const [members, setMembers] = useState<MemberSummary[]>([])
  const [dives, setDives] = useState<ProfileDive[]>([])
  const [score, setScore] = useState<number | null>(13)

  useEffect(() => {
    searchMembers('').then(async page => {
      setMembers(page.items)
      const diver = page.items.find(m => (m.accessible_dive_count ?? 0) > 20) ?? page.items[0]
      if (diver) setDives((await getProfileDives(diver.user_id)).items.filter(d => d.poster_url).slice(0, 8))
    })
  }, [])

  const me: MemberSummary = members.find(m => m.user_id === user?.user_id) ?? { user_id: 0, display_name: user?.display_name ?? 'Moi' } as MemberSummary
  const friend = members.find(m => m.display_name === 'Louis') ?? members.find(m => m.avatar_url && m.user_id !== me.user_id) ?? members[1]
  const dive = dives[2] ?? dives[0]
  if (!friend || !dive) return <div className="ca gm-page"><p className="cm-empty">Chargement…</p></div>

  const judges: Judge[] = [
    { key: 'me', name: 'Vous', human: me, kind: 'joueur', score: 13 },
    { key: 'f', name: friend.display_name, human: friend, kind: 'joueur', score: 10 },
    { key: 'max', name: 'Fantôme de Maxime', ghost: GHOSTS.maxime, kind: 'ombre', score: 12, line: 'genoux pliés à l’entrée' },
    { key: 'mum', name: 'La Maman', ghost: GHOSTS.mum, kind: 'bot', score: 17, line: 'il fait tellement d’efforts' },
    { key: 'coach', name: 'Le Coach', ghost: GHOSTS.coach, kind: 'bot', score: 12, line: 'éclaboussure. encore.' },
  ]
  const nav = (s: string) => setParams({ s })

  return <div className="ca gm-page">
    <nav className="ca-scroll gm-switch" aria-label="Maquettes">
      {[['lobby', 'Salon'], ['judge', 'Notation'], ['reveal', 'Révélation'], ['mole', 'La taupe'], ['results', 'Résultats'], ['code', 'Devine le code'], ['join', 'Invitation']].map(([k, label]) =>
        <button key={k} type="button" className="ca-pill" aria-pressed={screen === k} onClick={() => nav(k)}>{label}</button>)}
    </nav>

    {screen === 'join' && <section className="gm-join ca-arrive">
      <div className="gm-join-posters">{dives.slice(0, 3).map((d, i) => <img key={d.id} src={d.poster_url!} alt="" style={{ '--i': i } as CSSProperties} />)}</div>
      <MemberAvatar member={me} size={64} />
      <h1>{me.display_name} vous invite à juger</h1>
      <div className="gm-facts"><span className="ca-fact">8 plongeons</span><span className="ca-fact">Mode taupe</span><span className="ca-fact">3 joueurs</span></div>
      <label className="cm-search gm-nick"><input defaultValue="" placeholder="Votre pseudo" /></label>
      <button type="button" className="gm-cta">Rejoindre la salle</button>
      <button type="button" className="gm-link">J’ai déjà un compte</button>
    </section>}

    {screen === 'lobby' && <>
      <header className="cm-head"><h1>Salle K7QX</h1><MobileShellActions /></header>
      <button type="button" className="gm-invite ca-pop"><Link2 size={18} aria-hidden="true" /><span>dive-analyser…/room/K7QX</span><b><Copy size={15} aria-hidden="true" />Copier</b></button>
      <section className="ca-panel ca-arrive">
        <div className="ca-panel-h"><h2>Jury</h2><span>2 joueurs · 3 fantômes</span></div>
        <ul className="gm-seats">
          {judges.map((j, i) => <li key={j.key} className={`ca-pop${j.human ? ' is-human' : ''}`} style={{ '--i': i } as CSSProperties}>
            <Seat judge={j} size={52} /><b>{j.name}</b><small>{j.key === 'me' ? 'hôte' : j.kind}</small>
          </li>)}
          <li className="gm-seat-add"><span><UserPlus size={20} aria-hidden="true" /></span><b>Inviter</b></li>
        </ul>
      </section>
      <section className="cm-section">
        <h2 className="cm-h2">Mode</h2>
        <div className="ca-scroll"><button type="button" className="ca-pill" aria-pressed="false">Classique</button><button type="button" className="ca-pill" aria-pressed="true">🕵️ La taupe</button><button type="button" className="ca-pill" aria-pressed="false">Devine le code</button></div>
      </section>
      <section className="cm-section">
        <h2 className="cm-h2">Plongeons<span>8</span></h2>
        <div className="ca-scroll"><button type="button" className="ca-pill" aria-pressed="true">Ma dernière séance</button><button type="button" className="ca-pill" aria-pressed="false">Communauté</button><button type="button" className="ca-pill" aria-pressed="false">Par code</button></div>
        <div className="gm-posters">{dives.map((d, i) => <figure key={d.id} className="ca-pop" style={{ '--i': i } as CSSProperties}><img src={d.poster_url!} alt="" /><figcaption>{d.dive_code}</figcaption></figure>)}</div>
      </section>
      <button type="button" className="gm-cta"><Play size={18} aria-hidden="true" />Lancer</button>
    </>}

    {screen === 'judge' && <>
      <div className="gm-bar"><span className="ca-fact">3 / 8</span><span className="gm-dots">{Array.from({ length: 8 }, (_, i) => <i key={i} className={i < 2 ? 'is-done' : i === 2 ? 'is-now' : ''} />)}</span><span className="gm-timer"><Timer size={14} aria-hidden="true" />4</span></div>
      <figure className="gm-video"><img src={dive.poster_url!} alt="" /><figcaption><b>{dive.dive_code}</b><span>{dive.height} · DD 2,8</span></figcaption></figure>
      <ul className="gm-status">{judges.map(j => <li key={j.key} className={j.key === 'f' ? '' : 'is-in'}><Seat judge={j} size={34} />{j.key !== 'f' && <Check size={12} aria-hidden="true" />}</li>)}</ul>
      <ScoreInput score={score} disabled={false} onScore={setScore} />
    </>}

    {screen === 'reveal' && <>
      <div className="gm-bar"><span className="ca-fact">3 / 8</span><span className="ca-fact">{dive.dive_code} · {dive.height}</span><span className="gm-streak">🔥 ×2</span></div>
      <ul className="gm-reveal">
        {judges.map((j, i) => {
          const cut = j.key === 'mum' ? 'Haute' : j.key === 'f' ? 'Basse' : null
          return <li key={j.key} className={cut ? 'is-cut' : ''}>
            {cut && <span className="gm-cut">{cut}</span>}
            <ScoreCard scoreHalfSteps={j.score} rotation={(i - 2) * 3} staggerMs={i * 130} />
            <Seat judge={j} size={30} /><b>{j.name}</b>
            {j.line && <q>{j.line}</q>}
          </li>
        })}
      </ul>
      <section className="gm-verdict ca-arrive">
        <div><small>Note du jury</small><b>6,2</b></div>
        <div><small>Votre note</small><b>6,5</b></div>
        <div className="is-gain"><small>Points</small><b>+18</b></div>
      </section>
      <p className="gm-roast">🌶️ {friend.display_name} a été éliminé(e) par le bas. Encore.</p>
    </>}

    {screen === 'mole' && <>
      <header className="cm-head"><h1>Y a-t-il une taupe ?</h1></header>
      <p className="gm-sub">Écart moyen avec le jury sur 8 plongeons</p>
      <ul className="gm-suspects">
        {judges.filter(j => j.key !== 'me').map((j, i) => <li key={j.key}><button type="button" aria-pressed={j.key === 'mum'} className="ca-pop" style={{ '--i': i } as CSSProperties}>
          <Seat judge={j} size={44} /><span className="gm-suspect-txt"><b>{j.name}</b><small>{j.kind}</small></span>
          <em className={j.key === 'mum' ? 'is-hot' : ''}>{({ f: '−0,9', max: '+0,2', mum: '+1,8', coach: '−0,6' } as Record<string, string>)[j.key]}</em>
        </button></li>)}
        <li><button type="button" aria-pressed="false" className="gm-nobody">Personne, le jury est honnête</button></li>
      </ul>
      <button type="button" className="gm-cta">Voter</button>
    </>}

    {screen === 'results' && <>
      <header className="cm-head"><h1>Partie terminée</h1><MobileShellActions /></header>
      <section className="gm-mole-out ca-arrive"><span>🕵️</span><p><b>La taupe était La Maman</b><small>Démasquée par 2 joueurs sur 2 · +30 chacun</small></p></section>
      <section className="ca-panel">
        <ol className="cm-podium">
          {[{ j: judges[2], v: 131, n: 2 }, { j: judges[0], v: 164, n: 1 }, { j: judges[1], v: 97, n: 3 }].map(({ j, v, n }, i) => <li key={j.key} className={`cm-step is-${n}${j.key === 'me' ? ' is-me' : ''}`} style={{ '--i': i } as CSSProperties}>
            <span className="cm-step-who"><span className="cm-step-avatar">{n === 1 && <Crown className="gm-crown" size={20} aria-hidden="true" />}<Seat judge={j} size={n === 1 ? 64 : 48} /></span><b>{j.name}</b><span className="cm-step-value">{v}</span></span>
            <span className="cm-step-block">{n}</span>
          </li>)}
        </ol>
      </section>
      <section className="gm-awards">
        <div className="ca-panel"><span>🎯</span><b>Œil de lynx</b><small>Vous · 5 notes à ±0,5</small></div>
        <div className="ca-panel"><span>🌶️</span><b>Le plus sévère</b><small>{friend.display_name} · éliminé 6 fois</small></div>
      </section>
      <div className="gm-row"><button type="button" className="ca-btn"><Share2 size={16} aria-hidden="true" />Défier d’autres amis</button><button type="button" className="gm-cta gm-cta-inline">Rejouer</button></div>
    </>}

    {screen === 'code' && <>
      <div className="gm-bar"><span className="ca-fact">5 / 10</span><span className="gm-dots">{Array.from({ length: 10 }, (_, i) => <i key={i} className={i < 4 ? 'is-done' : i === 4 ? 'is-now' : ''} />)}</span><span className="gm-timer"><Timer size={14} aria-hidden="true" />7</span></div>
      <figure className="gm-video"><img src={(dives[5] ?? dive).poster_url!} alt="" /><figcaption><b>???</b><span>{(dives[5] ?? dive).height}</span></figcaption></figure>
      <div className="gm-choices">{['103C', (dives[5] ?? dive).dive_code, '201C', '5132D'].map((c, i) => <button key={c + i} type="button" className={i === 1 ? 'is-right' : i === 0 ? 'is-wrong' : ''}>{c}{i === 1 && <span className="gm-who"><MemberAvatar member={friend} size={22} /></span>}</button>)}</div>
      <p className="gm-roast">⚡ {friend.display_name} a trouvé en 1,4 s</p>
    </>}
  </div>
}
