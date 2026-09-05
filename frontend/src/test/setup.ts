import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => cleanup())

Object.defineProperty(HTMLMediaElement.prototype, 'load', { configurable: true, value: () => undefined })
Object.defineProperty(HTMLMediaElement.prototype, 'play', { configurable: true, value: async () => undefined })
Object.defineProperty(HTMLMediaElement.prototype, 'pause', { configurable: true, value: () => undefined })
