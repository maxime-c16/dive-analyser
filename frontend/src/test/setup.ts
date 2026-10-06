import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
// i18next must be initialized before any component using useTranslation
// renders in tests (components render standalone, without I18nProvider).
// English is the baseline so existing assertions on UI text keep passing.
import '../i18n'

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

// jsdom does not implement window.scrollTo; the Library scroll-restoration
// effect calls it when the reader closes. Tests assert behavior elsewhere.
window.scrollTo = () => {}

// jsdom lacks ResizeObserver; recharts ResponsiveContainer needs it.
if (typeof (globalThis as { ResizeObserver?: unknown }).ResizeObserver === "undefined") {
  class ROStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = ROStub as unknown;
}
