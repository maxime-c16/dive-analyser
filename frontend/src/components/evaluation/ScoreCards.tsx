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
      <span className="eval-card-number">{whole ?? ''}</span>
      <span className="eval-card-spiral" aria-hidden="true" />
      <span className="eval-card-half" aria-hidden={!isHalf}>{isHalf ? '½' : ''}</span>
    </div>
  )
}

export const INTRO_MS = 3200
const INTRO_TEST_MS = 500 // tests: choreography compressed, still exercised

/** Absolute, named timeline in milliseconds (offsets are derived as ms/3200 —
 * no mutable arithmetic): a pile of backs (0–300), the deal with overshoot
 * (300–1300), successive true 3D flips 1300 + i·110 for ~250ms each (every
 * front readable by ~1880, held through 2200), merge 2200–2600, exit travel
 * 2600–3200 fading only at the very end.
 *
 * Frame-rate contract (120Hz / VRR displays included): every visual step of
 * the choreography is a WAAPI animation of transform/opacity only — the
 * compositor interpolates at the display's native cadence and continuously
 * adapts to variable refresh. No rAF stepping, no per-frame JS, no
 * layout-touching animation; the only timers here are lifecycle ones
 * (finish/cancel). */
const T = {
  total: 3200,
  pileEnd: 300,
  dealEnd: 1300,
  dealOvershootMs: 300 + (1300 - 300) * 0.55,
  flipStart: 1300,
  flipStep: 110,
  flipDur: 250,
  flipAllReadable: 1880,
  mergeStart: 2200,
  mergeEnd: 2600,
  exitStart: 2600,
  exitFadeStart: 2900,
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
  const timeScale = playMs / T.total

  const cancelAll = useCallback(() => {
    for (const animation of animsRef.current) animation?.cancel()
    for (const timer of timersRef.current) window.clearTimeout(timer)
    animsRef.current = []
    timersRef.current = []
  }, [])

  const finish = useCallback(() => {
    if (finishedRef.current) return
    finishedRef.current = true
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
    return cancelAll
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
  // common exit target. Keyframe offsets are (ms / total) with absolute times.
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

    // Common measured HUD target — the DOCK score card when judging is open
    // (doc order would match the header first, hence the explicit saat query),
    // header fallback otherwise.
    const hud = document.querySelector('.eval-judging .eval-score-card') || document.querySelector('.eval-stage-head')
    const hudRect = hud?.getBoundingClientRect()
    const targetX = hudRect ? hudRect.left + hudRect.width / 2 - stackCenterX : 0
    const targetY = hudRect ? hudRect.top + hudRect.height / 2 - stackCenterY : 0

    // Whole four-card fan (INCLUDING the 1.18 deal overshoot and each card's
    // rotated extent) must stay inside the stage: derive the centre gap.
    // maxRotation is the OUTERmost card's settle rotation; the overshoot adds
    // a bounded swing on top — the extent covers 17deg.
    const maxRotation = 11 // deg at settle for the outermost card
    const maxFanRotation = maxRotation
    const overshootSwing = 7 // deg, added on the outermost card mid-deal
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
      const fanRotation = (i - 1.5) * maxFanRotation
      const exitStack = (i - 1.5) * 8

      const swing = (i - 1.5) * overshootSwing
      const keyframes: Array<Keyframe> = [
        { transform: `translateX(${stackOffset}px) translateY(0px) rotate(0deg) scale(0.97)`, opacity: 0.92, offset: 0 },
        { transform: `translateX(${stackOffset}px) translateY(0px) rotate(${(i - 1.5) * 2}deg) scale(0.99)`, opacity: 1, offset: T.pileEnd / T.total },
        // Deal with an overshoot past the fan, then settle (damped).
        { transform: `translateX(${(offset * 1.18).toFixed(1)}px) translateY(${(-12 + i * 4).toFixed(1)}px) rotate(${fanRotation + swing}deg) scale(1.02)`, offset: T.dealOvershootMs / T.total },
        { transform: `translateX(${offset.toFixed(1)}px) translateY(0px) rotate(${fanRotation}deg) scale(1)`, offset: T.dealEnd / T.total },
        // Short readable fan hold with a tiny breathing lift.
        { transform: `translateX(${offset.toFixed(1)}px) translateY(-3px) rotate(${fanRotation}deg) scale(1)`, offset: T.flipAllReadable / T.total },
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
        const flipStart = T.flipStart + i * T.flipStep
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
      <button
        type="button"
        className="eval-intro-skip"
        onClick={() => {
          finishedRef.current = true
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
