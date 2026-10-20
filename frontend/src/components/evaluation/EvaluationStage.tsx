/**
 * Immersive evaluation stage (issue #68), v2: a true theater stage mounted as
 * a React portal OUTSIDE the app Layout — full-viewport, borderless, no
 * reserved rows. The VIDEO is the stage: one absolute video layer fills the
 * viewport (`object-fit: contain` inside the element, never cover, no
 * proxy upsampling); the top/bottom HUDs are translucent overlays. Honest
 * letterbox bands of a landscape source host the overlays without ever
 * shrinking the source frame.
 *
 * - top HUD: 44px quit, diver + code/height, judged counter, prompt fold;
 * - the stage traps keyboard focus, closes on Escape (quit keeps submitted
 *   votes), restores focus to the trigger on exit, locks body scroll;
 * - content stays reachable at high zoom: dock overlays never clip (they
 *   scroll instead).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useModalOverlay } from '../../utils/overlays'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X, MessageSquare } from 'lucide-react'

export default function EvaluationStage({
  open,
  onClose,
  head,
  prompt,
  video,
  overlays,
  children,
  hideChrome = false,
  phase,
  preparing = false,
}: {
  open: boolean
  preparing?: boolean
  phase?: string
  hideChrome?: boolean
  onClose: () => void
  /** Compact top row: diver name + code/height + judged counter. */
  head: ReactNode
  /** Folded jury prompt, readable on demand without covering live action. */
  prompt: string | null
  /** The evaluation-scoped player; rendered in the absolute video layer. */
  video: ReactNode
  /** Renders above the video (intro choreography), below the chrome. */
  overlays?: ReactNode
  /** Bottom overlay dock: judging controls / reveal / stage states. */
  children: ReactNode
}) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const [promptOpen, setPromptOpen] = useState(false)
  const [chromeRevealed, setChromeRevealed] = useState(false)
  const chromeTimer = useRef<number | null>(null)
  const revealChrome = (keyboard = false) => {
    if (!hideChrome) return
    setChromeRevealed(true)
    if (chromeTimer.current) window.clearTimeout(chromeTimer.current)
    chromeTimer.current = window.setTimeout(() => {
      if (!keyboard || !document.activeElement?.closest('.eval-stage-head, .eval-player-controls')) setChromeRevealed(false)
    }, 2200)
  }
  useEffect(() => {
    setChromeRevealed(false)
    setPromptOpen(false)
    return () => { if (chromeTimer.current) window.clearTimeout(chromeTimer.current) }
  }, [hideChrome])

  useEffect(() => {
    if (!open) return
    const update = () => {
      const vv = window.visualViewport
      const root = containerRef.current
      root?.style.setProperty('--eval-visible-height', `${vv?.height ?? window.innerHeight}px`)
      root?.style.setProperty('--eval-visible-top', `${vv?.offsetTop ?? 0}px`)
      root?.classList.toggle('eval-keyboard-open', (vv?.height ?? window.innerHeight) < window.innerHeight - 120)
    }
    update()
    window.addEventListener('resize', update)
    window.visualViewport?.addEventListener('resize', update)
    window.visualViewport?.addEventListener('scroll', update)
    return () => {
      window.removeEventListener('resize', update)
      window.visualViewport?.removeEventListener('resize', update)
      window.visualViewport?.removeEventListener('scroll', update)
    }
  }, [open])

  useModalOverlay(containerRef, { enabled: open, layer: 80, onClose,
    fallbackFocus: () => document.querySelector<HTMLElement>('.eval-start, .eval-summary .eval-pass'),
  })

  if (!open) return null
  return createPortal(
    <div
      className="eval-stage-root"
      role="dialog"
      aria-modal="true"
      aria-label={t('evaluations.juryArea')}
      ref={containerRef}
      tabIndex={-1}
      data-phase={phase}
      data-preparing={preparing ? 'true' : undefined}
      data-watching={hideChrome ? 'true' : undefined}
      data-chrome-revealed={chromeRevealed ? 'true' : undefined}
      onPointerDown={() => revealChrome(false)}
      onKeyDown={() => revealChrome(true)}
    >
      {/* The video IS the stage: full viewport layer under every overlay. */}
      <div className="eval-stage-video" aria-hidden={preparing || undefined} {...(preparing ? { inert: '' } : {})}>{video}</div>
      {overlays}
      <header className="eval-stage-head">
        <button type="button" className="eval-quit" onClick={onClose} aria-label={t('evaluations.quit')}>
          <X size={20} />
        </button>
        <div className="eval-stage-head-center">{head}</div>
        {prompt !== null && (
          <button
            type="button"
            className={`eval-prompt-toggle ${promptOpen ? 'is-open' : ''}`}
            aria-expanded={promptOpen}
            aria-label={t('evaluations.promptFold')}
            onClick={() => setPromptOpen((value: boolean) => !value)}
          >
            <MessageSquare size={18} />
          </button>
        )}
      </header>
      {promptOpen && prompt !== null && (
        <div className="eval-prompt-sheet" role="status">{prompt}</div>
      )}
      <div className="eval-stage-dock">{children}</div>
    </div>,
    document.body,
  )
}
