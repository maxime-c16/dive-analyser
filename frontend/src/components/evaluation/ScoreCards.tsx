/**
 * Decorative jury score cards (issue #68): white flip cards with very large
 * black upright condensed numerals, a small spiral separator mid/lower and
 * the ½ visible under it — explicit HTML/CSS only, no bitmap asset. Cards are
 * DECORATIVE: they never carry real jury data and never join the panel.
 */
import { useCallback, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { CSSProperties } from 'react'

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
      <span className={`eval-card-number${whole === 10 ? ' is-two' : ''}`}>{whole ?? ''}</span>
      <svg className="eval-card-spiral" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <line x1="0" y1="50" x2="100" y2="50" />
        {Array.from({ length: 14 }, (_, i) => <ellipse key={i} cx={(i + .5) * 100 / 14} cy="50" rx={.42 * 100 / 14} ry="46" />)}
      </svg>
      <span className="eval-card-half" aria-hidden={!isHalf}>{isHalf ? '½' : ''}</span>
    </div>
  )
}

export const INTRO_MS = 3200
const INTRO_TEST_MS = 500 // tests: choreography compressed, still exercised

/** Absolute, named timeline in milliseconds (offsets are ms/total — no
 * mutable arithmetic). A COMPACT pile of backs (0–280), a STAGGERED deal —
 * card i leaves the pile at 280 + i·100 and settles in its fan slot by 1420 —
 * clear successive true-3D flips 1460 + i·130 (every front readable by ~2110,
 * held to 2260), merge 2260–2560, exit travel 2600–3130 fading at the very
 * end. Rotations stay small and deliberate: ±8° settle, +5° overshoot, no
 * per-frame floating.
 *
 * Frame-rate contract (120Hz / VRR displays included): every visual step of
 * the choreography is a WAAPI animation of transform/opacity only — the
 * compositor interpolates at the display's native cadence and continuously
 * adapts to variable refresh. No rAF stepping, no per-frame JS, no
 * layout-touching animation; the only timers here are lifecycle ones
 * (finish/cancel). */
const T = {
  total: 3200,
  pileEnd: 280,
  dealStagger: 100,
  dealEnd: 1420,
  overshootRatio: 0.55,
  flipStart: 1460,
  flipStep: 130,
  flipDur: 260,
  flipAllReadable: 2110,
  mergeStart: 2260,
  mergeEnd: 2560,
  exitStart: 2600,
  exitFadeStart: 2960,
} as const

const cardHalfRotatedExtent = (cardW: number, cardH: number, maxRotDeg: number) => {
  const rad = (maxRotDeg * Math.PI) / 180
  return (cardW * Math.abs(Math.cos(rad)) + cardH * Math.abs(Math.sin(rad))) / 2
}

/** Tiny pile offset so the stacked backs read as a hand of cards. */
const stackOffsetsInPx = [-6, 8, 4, -3]
const stackLeft = (index: number) => stackOffsetsInPx[index] ?? 0

export default function EvaluationIntro({
  onDone,
  onSkip,
  interrupt,
}: {
  onDone: () => void
  onSkip: () => void
  /** Judging started (score chosen/confirm): drop the decoration NOW. */
  interrupt?: boolean
}) {
  const { t } = useTranslation()
  const rootRef = useRef<HTMLDivElement>(null)
  const slotsRef = useRef<Array<HTMLDivElement | null>>([])
  const facesRef = useRef<Array<HTMLDivElement | null>>([])
  const animsRef = useRef<Animation[]>([])
  const timersRef = useRef<number[]>([])
  const finishedRef = useRef(false)
  // Vitest sets NODE_ENV=test; compress the choreography so unit tests still
  // exercise the real timeline without paying 3.2s.
  const playMs = import.meta.env.MODE === 'test' ? INTRO_TEST_MS : INTRO_MS

  const cancelAll = useCallback(() => {
    for (const animation of animsRef.current) animation?.cancel()
    for (const timer of timersRef.current) window.clearTimeout(timer)
    animsRef.current = []
    timersRef.current = []
  }, [])

  const finish = useCallback(() => {
    if (finishedRef.current) return
    finishedRef.current = true
    if (rootRef.current) rootRef.current.style.visibility = 'hidden'
    cancelAll()
    onDone()
  }, [cancelAll, onDone])

  useEffect(() => {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      onDone()
      return
    }
    timersRef.current.push(window.setTimeout(finish, playMs + 340))
    // Viewport relayout (rotation, desktop resize): the measured geometry is
    // stale — leave gracefully instead of persisting misplaced visuals.
    const onResize = () => finish()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      cancelAll()
    }
    // Choreography runs once; finish/onDone stay first-call stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (interrupt) {
      // Judging began: leave immediately, no decorative residue.
      for (const slot of slotsRef.current) if (slot) slot.style.opacity = '0'
      finish()
    }
  }, [interrupt, finish])

  // One WAAPI timeline per card. All geometry is MEASURED from the live DOM:
  // slot size (not presumed), stage box, and the HUD score-card centre as the
  // common exit target. Each card has its own deal start (staggered deal) and
  // its own flip start (staggered flips).
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const stageRect = root.getBoundingClientRect()
    const firstSlot = slotsRef.current[0]
    if (!firstSlot || typeof firstSlot.animate !== 'function') return
    // Slot size from COMPUTED style: getBoundingClientRect would include the
    // pile transform/margins and corrupt every downstream prediction.
    const slotStyle = getComputedStyle(firstSlot)
    const cardW = parseFloat(slotStyle.width)
    const cardH = parseFloat(slotStyle.height)

    // All positions are computed in the SLOT OFFSET PARENT's coordinate
    // space (whatever CSS ends up anchoring the overlay), so the fan stacks
    // on the overlay centre and the measured HUD target converts exactly.
    const parentRect = firstSlot.offsetParent?.getBoundingClientRect()
    if (!parentRect) return
    const stackCenterX = parentRect.left + parentRect.width / 2
    const stackCenterY = parentRect.top + parentRect.height * 0.4

    // Common measured HUD target — the PERSONAL score-card zone of the
    // responsive judging dock (manifested here as the actual dock element,
    // portrait bottom or landscape column) when judging is open; the stage
    // head otherwise. Demo numbers never stand in for a vote.
    const hud = document.querySelector('.eval-judging .eval-score-card') || document.querySelector('.eval-stage-head')
    const hudRect = hud?.getBoundingClientRect()
    const targetX = hudRect ? hudRect.left + hudRect.width / 2 - stackCenterX : 0
    const targetY = hudRect ? hudRect.top + hudRect.height / 2 - stackCenterY : 0

    // Whole four-card fan (INCLUDING the deal overshoot and each card's
    // rotated extent) must stay inside the stage: derive the centre gap.
    const maxRotation = 8 // deg at settle for the outermost card (calm fan)
    const overshootSwing = 5 // deg, added mid-deal, then damped
    const extent = cardHalfRotatedExtent(cardW, cardH, maxRotation + overshootSwing)
    const inset = Math.min(16, stageRect.width * 0.05)
    const availableHalf = (stageRect.width - inset * 2) / 2
    const gap = Math.max(
      24,
      Math.min(
        stageRect.width >= 900 ? 120 : stageRect.width >= 560 ? 86 : 64,
        (availableHalf - extent) / (1.18 * 1.5),
      ),
    )

    const card = (i: number) => {
      const slot = slotsRef.current[i]
      const face = facesRef.current[i]
      if (!slot) return
      // Centre the slot on the pile in OFFSET-PARENT coordinates (no guesses).
      slot.style.left = `${stackCenterX - parentRect.left - cardW / 2}px`
      slot.style.top = `${stackCenterY - parentRect.top - cardH / 2}px`
      slot.style.transform = 'none'
      slot.style.margin = '0'
      const offset = (i - 1.5) * gap // centre-to-centre fan offsets
      const stackOffset = stackLeft(i) // small pile offset (see helper below)
      const fanRotation = (i - 1.5) * maxRotation
      const exitStack = (i - 1.5) * 8
      const dealStart = T.pileEnd + i * T.dealStagger // staggered deal
      const dealOvershoot = dealStart + (T.dealEnd - dealStart) * T.overshootRatio

      const swing = (i - 1.5) * overshootSwing
      const pileFrame = `translateX(${stackOffset}px) translateY(0px) rotate(0deg) scale(0.97)`
      const keyframes: Array<Keyframe> = [
        { transform: pileFrame, opacity: 0.92, offset: 0 },
        // Compact pile hold while the cards before this one deal off it.
        { transform: pileFrame, opacity: 1, offset: dealStart / T.total },
        // Deal with a small overshoot past the fan slot, then settle.
        { transform: `translateX(${(offset * 1.18).toFixed(1)}px) translateY(${(-10 + i * 3).toFixed(1)}px) rotate(${fanRotation + swing}deg) scale(1.02)`, offset: dealOvershoot / T.total },
        { transform: `translateX(${offset.toFixed(1)}px) translateY(0px) rotate(${fanRotation}deg) scale(1)`, offset: T.dealEnd / T.total },
        // Short readable fan hold with NO floating.
        { transform: `translateX(${offset.toFixed(1)}px) translateY(0px) rotate(${fanRotation}deg) scale(1)`, offset: T.flipAllReadable / T.total },
        // Merge/tighten the fan once every front has been readable.
        { transform: `translateX(${(offset * 0.35).toFixed(1)}px) translateY(2px) rotate(${fanRotation * 0.4}deg) scale(0.9)`, offset: T.mergeStart / T.total },
        { transform: `translateX(${(offset * 0.35).toFixed(1)}px) translateY(2px) rotate(${fanRotation * 0.4}deg) scale(0.9)`, offset: T.mergeEnd / T.total },
        // Travel INTO the measured HUD zone: every card goes to the SAME
        // centre delta, with only a small intentional stack offset.
        { transform: `translateX(${(targetX + exitStack).toFixed(1)}px) translateY(${targetY.toFixed(1)}px) rotate(${fanRotation * 0.2}deg) scale(0.62)`, opacity: 1, offset: T.exitStart / T.total + ((T.exitFadeStart - T.exitStart) / T.total) * 0.9 },
        { transform: `translateX(${(targetX + exitStack).toFixed(1)}px) translateY(${targetY.toFixed(1)}px) rotate(0deg) scale(0.6)`, opacity: 0, offset: 1 },
      ]
      const anim = slot.animate(keyframes, { duration: playMs, fill: 'both', easing: 'ease-out' })
      animsRef.current.push(anim)
      if (face) {
        const flipStart = T.flipStart + i * T.flipStep // staggered flips
        const flipEnd = flipStart + T.flipDur
        const anim2 = face.animate(
          [
            { transform: 'rotateY(0deg)', offset: 0 },
            { transform: 'rotateY(0deg)', offset: flipStart / T.total },
            { transform: 'rotateY(180deg)', offset: flipEnd / T.total },
            { transform: 'rotateY(180deg)', offset: 1 },
          ],
          { duration: playMs, fill: 'both', easing: 'cubic-bezier(.4,.9,.35,1.05)' },
        )
        animsRef.current.push(anim2)
      }
    }
    for (let i = 0; i < 4; i++) card(i)

    return () => { for (const animation of animsRef.current) animation?.cancel(); animsRef.current = [] }
  }, [playMs])

  const decorative = [15, 16, 13, 14]

  return (
    <div className="eval-intro" data-choreo="true" ref={rootRef}>
      {/* Decorative only: hidden to AT and click-transparent. */}
      <div className="eval-intro-cards" aria-hidden="true" role="presentation">
        {decorative.map((half, i) => (
          <div
            key={i}
            className="eval-intro-slot"
            ref={(node) => {
              slotsRef.current[i] = node
            }}
          >
            <div
              className="eval-flip"
              ref={(node) => {
                facesRef.current[i] = node
              }}
            >
              <div className="eval-card-back" data-pile={i} />
              <div className="eval-card-front">
                <ScoreCard scoreHalfSteps={half} staggerMs={i * 110} />
              </div>
            </div>
          </div>
        ))}
      </div>
      {/* Unambiguously illustrative: demo cards are NOT real votes and never
          reach the panel. aria-hidden as with the rest of the decoration. */}
      <span className="eval-intro-demo" aria-hidden="true">{t('evaluations.introDemo')}</span>
      <button
        type="button"
        className="eval-intro-skip"
        onClick={() => {
          finishedRef.current = true
          if (rootRef.current) rootRef.current.style.visibility = 'hidden'
          cancelAll()
          onSkip()
        }}
      >
        {t('evaluations.introSkip')}
      </button>
    </div>
  )
}

/** Tiny pile offset so the stacked backs read as a hand of cards. */
