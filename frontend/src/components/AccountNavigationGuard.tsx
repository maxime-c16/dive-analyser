import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

/** Data-router blocker covers Back/Forward, Links and imperative navigation.
 * Query-only tab navigation stays available while the identity draft is dirty.
 */
export default function AccountNavigationGuard({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (window.confirm('Leave this account with unsaved changes?')) blocker.proceed()
    else blocker.reset()
  }, [blocker])
  return null
}
