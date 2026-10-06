import { Link, useInRouterContext } from 'react-router-dom'
import type { ReactNode } from 'react'

/**
 * Link to a member profile that degrades to plain content outside a Router
 * context (guest surfaces, isolated test renders).
 */
export default function MemberLink({ userId, className, children, ariaLabel }: {
  userId: number
  className?: string
  children: ReactNode
  ariaLabel?: string
}) {
  if (!useInRouterContext()) {
    return <span className={className}>{children}</span>
  }
  return (
    <Link to={`/users/${userId}`} className={className} aria-label={ariaLabel}>
      {children}
    </Link>
  )
}
