import { useState } from 'react'

export const DEFAULT_DRAW_SIZE = 5
export const MAX_DRAW_SIZE = 20

/** Browser preference isolated by account; storage failure leaves it usable. */
export function useEvaluationDrawSize(userId?: number): [number, (size: number) => void] {
  const key = userId === undefined ? null : `dive:eval-draw-size:${userId}`
  const [size, setSize] = useState(() => {
    try {
      const stored = key ? Number(localStorage.getItem(key)) : NaN
      if (Number.isInteger(stored) && stored >= 1 && stored <= MAX_DRAW_SIZE) return stored
    } catch { /* Use the default when storage is unavailable. */ }
    return DEFAULT_DRAW_SIZE
  })
  return [size, next => {
    if (!Number.isInteger(next) || next < 1 || next > MAX_DRAW_SIZE) return
    setSize(next)
    try {
      if (key) localStorage.setItem(key, String(next))
    } catch { /* The preference still works for this visit. */ }
  }]
}
