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
}: {
  open: boolean
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
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    restoreFocusRef.current = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    containerRef.current?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
      restoreFocusRef.current?.focus?.()
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const nodes = Array.from(
        containerRef.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), video, a[href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
      if (!nodes.length) return
      const first = nodes[0]
      const last = nodes[nodes.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <div
      className="eval-stage-root"
      role="dialog"
      aria-modal="true"
      aria-label={t('evaluations.juryArea')}
      ref={containerRef}
      tabIndex={-1}
    >
      {/* The video IS the stage: full viewport layer under every overlay. */}
      <div className="eval-stage-video">{video}</div>
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
