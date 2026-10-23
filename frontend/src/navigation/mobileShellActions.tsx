import { createContext, useContext, useLayoutEffect, type ReactNode } from 'react'

type MobileShell = { actions: ReactNode; claim: () => () => void }

export const MobileShellContext = createContext<MobileShell | null>(null)

/**
 * Notifications + account trigger, placed by a page in its title row on
 * mobile (iOS large-title pattern). While one is mounted the shell drops its
 * own top bar, so nothing interactive sits under the status bar blur.
 */
export function MobileShellActions() {
  const shell = useContext(MobileShellContext)
  const claim = shell?.claim
  useLayoutEffect(() => claim?.(), [claim])
  if (!shell) return null
  return <div className="mobile-shell-actions flex shrink-0 items-center gap-2 lg:hidden">{shell.actions}</div>
}
