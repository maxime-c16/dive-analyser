/**
 * Decorative jury score cards (issue #68): white flip cards with very large
 * black upright condensed numerals, a small spiral separator mid/lower and
 * the ½ visible under it — explicit HTML/CSS only, no bitmap asset. The four
 * intro cards and any pre-vote display card are DECORATIVE: they never carry
 * real jury data. The introduction is a light, passable overlay: the
 * decorative fan is aria-hidden and pointer-events none; the accessible
 * Skip button sits outside it and never blocks the stage underneath.
 */
import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'

const FAN_ROTATIONS = [-7, -3, 3, 7] as const

/** One judge card face. `scoreHalfSteps` 0–20 renders value/2; a `null`
 * score renders a blank card. Purely presentational. */
export function ScoreCard({
  scoreHalfSteps,
  className = '',
  rotation = 0,
  ariaLabel,
  staggerMs,
}: {
  scoreHalfSteps: number | null
  className?: string
  rotation?: number
  ariaLabel?: string
  staggerMs?: number
}) {
  const whole = scoreHalfSteps === null ? null : Math.floor(scoreHalfSteps / 2)
  const isHalf = scoreHalfSteps !== null && scoreHalfSteps % 2 === 1
  const style: CSSProperties & Record<string, string | number> = {}
  if (rotation) style['--rot'] = `${rotation}deg`
  if (staggerMs !== undefined) style['--stagger'] = `${staggerMs}ms`
  return (
    <div
      className={`eval-card ${className}`}
      style={style}
      role="img"
      aria-label={ariaLabel}
    >
      <span className="eval-card-number">{whole ?? ''}</span>
      <span className="eval-card-spiral" aria-hidden="true" />
      <span className="eval-card-half" aria-hidden={!isHalf}>{isHalf ? '½' : ''}</span>
    </div>
  )
}

export const INTRO_MS = 3000

/**
 * 3-second non-blocking introduction: four cards dealt in a fanned overlap
 * with a slight rotation and a flip. Skippable at any moment; reduced-motion
 * ends it immediately. Decorative layer never intercepts the page.
 */
export default function EvaluationIntro({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const { t } = useTranslation()
  const [leaving, setLeaving] = useState(false)
  const dealTimer = useRef<number | null>(null)
  const leaveTimer = useRef<number | null>(null)

  useEffect(() => {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      onDone()
      return
    }
    dealTimer.current = window.setTimeout(() => {
      setLeaving(true)
      leaveTimer.current = window.setTimeout(onDone, 320)
    }, INTRO_MS)
    return () => {
      if (dealTimer.current) window.clearTimeout(dealTimer.current)
      if (leaveTimer.current) window.clearTimeout(leaveTimer.current)
    }
    // The overlay runs once per mount; onDone/onSkip stay first-call stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const rotations = useMemo(() => FAN_ROTATIONS, [])

  function finish() {
    if (dealTimer.current) window.clearTimeout(dealTimer.current)
    if (leaveTimer.current) window.clearTimeout(leaveTimer.current)
    onSkip()
  }

  return (
    <div className="eval-intro" data-leaving={leaving || undefined}>
      {/* Decorative only: hidden to AT and click-transparent. */}
      <div className="eval-intro-cards" aria-hidden="true" role="presentation">
        {rotations.map((rotation, index) => (
          <ScoreCard
            key={index}
            scoreHalfSteps={index === 0 ? 15 : index === 1 ? 16 : index === 2 ? 13 : 14}
            rotation={rotation}
            staggerMs={index * 110}
            className="eval-intro-card"
          />
        ))}
      </div>
      <button type="button" className="eval-intro-skip" onClick={finish}>
        {t('evaluations.introSkip')}
      </button>
    </div>
  )
}
