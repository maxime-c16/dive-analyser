import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())

Object.defineProperty(HTMLMediaElement.prototype, 'load', { configurable: true, value: () => undefined })
Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: async () => undefined })
Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: () => undefined })

// jsdom lacks IntersectionObserver; DiveThumbnail lazy-loading needs a stub.
if (typeof (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver === "undefined") {
  class IOStub {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return [] }
  }
  (globalThis as { IntersectionObserver: unknown }).IntersectionObserver = IOStub as unknown;
}
