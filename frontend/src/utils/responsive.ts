/**
 * Responsive design utilities and hooks
 */

import { useEffect, useState } from 'react'

export type Breakpoint = 'xs' | 'sm' | 'md' | 'lg' | 'xl' | '2xl'

const breakpoints: Record<Breakpoint, number> = {
  xs: 0,
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
}

/**
 * Hook to track current breakpoint
 */
export const useBreakpoint = (): Breakpoint => {
  const [breakpoint, setBreakpoint] = useState<Breakpoint>('md')

  useEffect(() => {
    const updateBreakpoint = () => {
      const width = window.innerWidth

      if (width < breakpoints.sm) {
        setBreakpoint('xs')
      } else if (width < breakpoints.md) {
        setBreakpoint('sm')
      } else if (width < breakpoints.lg) {
        setBreakpoint('md')
      } else if (width < breakpoints.xl) {
        setBreakpoint('lg')
      } else if (width < breakpoints['2xl']) {
        setBreakpoint('xl')
      } else {
        setBreakpoint('2xl')
      }
    }

    // Initial check
    updateBreakpoint()

    // Listen for resize
    window.addEventListener('resize', updateBreakpoint)
    return () => window.removeEventListener('resize', updateBreakpoint)
  }, [])

  return breakpoint
}

/**
 * Check if current breakpoint matches
 */
export const useIsBreakpoint = (target: Breakpoint | Breakpoint[]): boolean => {
  const current = useBreakpoint()
  const targets = Array.isArray(target) ? target : [target]
  return targets.includes(current)
}

/**
 * Get responsive class names
 */
export const getResponsiveClass = (
  classes: Record<Breakpoint, string>,
  current: Breakpoint
): string => {
  // Return classes for current breakpoint and all smaller breakpoints
  const sortedBreakpoints = Object.keys(breakpoints).sort(
    (a, b) => breakpoints[a as Breakpoint] - breakpoints[b as Breakpoint]
  )

  const currentIndex = sortedBreakpoints.indexOf(current)
  const applicableClasses = sortedBreakpoints
    .slice(0, currentIndex + 1)
    .map((bp) => classes[bp as Breakpoint])
    .filter(Boolean)

  return applicableClasses.join(' ')
}
