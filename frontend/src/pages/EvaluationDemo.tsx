/**
 * Visual review page for the Évaluations UI (issue #68) — DEMO ONLY.
 * Fixture-driven (no backend calls, no auth): renders the jury session
 * experience in three variants chosen with ?variant=a|b|c. All cards are
 * decorative and none of the data is real. Used for design review; not
 * linked from the main navigation.
 */
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import EvaluationIntro, { ScoreCard } from '../components/evaluation/ScoreCards'
import '../components/evaluation/evaluations.css'
import './evaluationsDemo.css'

type DemoItem = {
  request_id: number
  dive: { dive_code: string; height: string; platform_type: string; owner_display_name: string }
  prompt: string | null
  mean: number | null
  votes: number
}

const ITEMS: DemoItem[] = [
  {
    request_id: 11,
    dive: { dive_code: '107B', height: '3m', platform_type: 'springboard', owner_display_name: 'Claire' },
    prompt: 'Jugez l’entrée et l’ouverture.',
    mean: 6.5,
    votes: 3,
  },
  {
    request_id: 12,
    dive: { dive_code: '105C', height: '10m', platform_type: 'platform', owner_display_name: 'Marc' },
    prompt: null,
    mean: null,
    votes: 0,
  },
  {
    request_id: 13,
    dive: { dive_code: '203B', height: '1m', platform_type: 'springboard', owner_display_name: 'Sofia' },
    prompt: 'Premier plongeon en compétition.',
    mean: 7.0,
    votes: 2,
  },
]

const PANEL = [
  { id: 5, score_half_steps: 10, author: 'Bob', comment: 'Solide', created_at: 'x' },
  { id: 6, score_half_steps: 8, author: 'Zoé', comment: null, created_at: 'y' },
]

export default function EvaluationDemo() {
  const [params, setParams] = useSearchParams()
  const { t } = useTranslation()
  const variant = (params.get('variant') ?? 'a') as 'a' | 'b' | 'c'
  const [stage, setStage] = useState<'intro' | 'judging' | 'reveal' | 'summary'>('intro')
  const [index, setIndex] = useState(0)
  const [score, setScore] = useState<number | null>(null)
  const [comment, setComment] = useState('')

  useEffect(() => {
    document.title = `Démo Évaluations ${variant.toUpperCase()} · Dive Analyser`
  }, [variant])

  const item = ITEMS[index % ITEMS.length]

  function next() {
    setStage((current) => (current === 'intro' ? 'judging' : current === 'reveal' ? 'judging' : current))
    setScore(null)
    setComment('')
    if (stage !== 'intro') setIndex((value) => value + 1)
  }

  return (
    <div className="eval-demo" data-variant={variant}>
      <header className="eval-demo-banner">
        <strong>Maquette {variant.toUpperCase()}</strong>
        <span>Données fictives — aucun score réel. Naviguez : /evaluations-demo?variant=a · b · c</span>
        <nav>
          {(['a', 'b', 'c'] as const).map((key) => (
            <button key={key} type="button" onClick={() => setParams({ variant: key })} disabled={key === variant}>
              {key.toUpperCase()}
            </button>
          ))}
        </nav>
      </header>

      <div className="eval-demo-stage" data-stage={stage}>
        {stage === 'intro' && (
          <EvaluationIntro onDone={next} onSkip={next} />
        )}
        <main className="eval-demo-main">
          <div className="eval-demo-player" aria-label="Emplacement du lecteur vidéo">
            <span>{item.dive.dive_code}</span>
            <small>lecteur vidéo (maquette)</small>
          </div>
          {stage !== 'intro' && (
            <>
              <p className="eval-owner">
                {item.dive.owner_display_name}
                {item.prompt ? ` — ${item.prompt}` : ''}
              </p>
              {stage === 'judging' && (
                <div className="eval-judging" role="group">
                  <div className="eval-score-row">
                    <input
                      type="range"
                      aria-label="Note de 0 à 10 par demi-point"
                      min={0}
                      max={20}
                      step={1}
                      value={score ?? 10}
                      onChange={(event) => setScore(Number(event.target.value))}
                    />
                    <ScoreCard scoreHalfSteps={score} ariaLabel={score === null ? '—' : `${(score / 2).toFixed(1)}`} />
                    <p className="eval-score-hint">0 à 10 par demi-point</p>
                  </div>
                  <textarea
                    aria-label="Commentaire facultatif"
                    rows={2}
                    maxLength={2000}
                    value={comment}
                    placeholder="Commentaire facultatif pour le plongeur…"
                    onChange={(event) => setComment(event.target.value)}
                  />
                  <div className="eval-judge-actions">
                    <button type="button" onClick={next}>Passer</button>
                    <button
                      type="button"
                      className="eval-confirm"
                      disabled={score === null}
                      onClick={() => setStage('reveal')}
                    >
                      Confirmer la note
                    </button>
                  </div>
                </div>
              )}
              {stage === 'reveal' && (
                <div className="eval-reveal">
                  <div className="eval-reveal-panel">
                    {PANEL.map((rating, i) => (
                      <ScoreCard
                        key={rating.id}
                        scoreHalfSteps={rating.score_half_steps}
                        rotation={((i % 5) - 2) * 2}
                        ariaLabel={`${(rating.score_half_steps / 2).toFixed(1)}`}
                      />
                    ))}
                    <ScoreCard
                      scoreHalfSteps={score}
                      rotation={4}
                      className="eval-card-mine"
                      ariaLabel={`Votre carton ${(score ?? 0) / 2}`}
                    />
                  </div>
                  <div className="eval-reveal-meta">
                    <p>
                      {item.votes} vote(s) · moyenne communautaire {item.mean !== null ? item.mean.toFixed(1) : '—'}
                    </p>
                    <div className="eval-judge-actions">
                      <button type="button" onClick={() => setStage('judging')}>Garder les résultats ouverts</button>
                      <button type="button" className="eval-confirm" onClick={next}>Plongeon suivant</button>
                    </div>
                    <button type="button" className="eval-demo-end" onClick={() => setStage('summary')}>
                      Terminer la série (récapitulatif)
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
        {stage === 'summary' && (
          <div className="eval-summary">
            <p className="eval-count">3 plongeon(s) évalué(s)</p>
            <p>Plus rien à juger pour l’instant.</p>
            <button type="button" className="eval-start" onClick={() => { setStage('intro'); setIndex(0) }}>
              Réévaluer
            </button>
          </div>
        )}
        <aside className="eval-demo-side">
          <h2>Maquette — variante {variant.toUpperCase()}</h2>
          <ul>
            <li>Cartons blancs, très grands chiffres noirs, spirale et ½ en partie basse.</li>
            <li>Intro 3 s en éventail, passable, absente en reduced-motion.</li>
            <li>Révélation animée après confirmation (données fictives ici).</li>
          </ul>
          <p>{t('evaluations.footerHint')}</p>
        </aside>
      </div>
    </div>
  )
}
