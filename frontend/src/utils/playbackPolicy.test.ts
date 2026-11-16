import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { NOMINAL_MBPS, canAffordHq, canAffordRate, recordResourceTiming, resetPlaybackPolicy, sampleBuffering, throughputEstimate } from './playbackPolicy'

const timing = (over: Partial<PerformanceResourceTiming>) => ({
  name: 'https://app.example/api/v1/media/cache/42/play',
  transferSize: 1_786_287,
  encodedBodySize: 1_785_987,
  responseStart: 100,
  responseEnd: 1100,
  ...over,
})

beforeEach(() => resetPlaybackPolicy())
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('measures finished same-origin proxy downloads exactly, skipping cache hits and tiny files', () => {
  expect(recordResourceTiming(timing({ transferSize: 0 }))).toBe(false) // HTTP cache
  expect(recordResourceTiming(timing({ encodedBodySize: 50_000 }))).toBe(false) // latency-bound
  expect(recordResourceTiming(timing({ name: 'https://app.example/api/v1/dives/library' }))).toBe(false)
  expect(throughputEstimate()).toBeNull()
  expect(recordResourceTiming(timing({}))).toBe(true)
  expect(throughputEstimate()).toBeCloseTo((1_785_987 * 8) / 1 / 1e6) // ~14.3 Mbps
})

it('the browser downlink hint can unlock Light but never HQ on its own', () => {
  vi.stubGlobal('navigator', { ...navigator, connection: { downlink: 10, effectiveType: '4g' } })
  expect(canAffordRate(2.7)).toBe(true)
  expect(canAffordRate(6.4)).toBe(true) // 10 ≥ 9.6
  expect(canAffordHq()).toBe(false) // Chrome caps downlink at 10 Mbps
  expect(throughputEstimate()).toBeNull()
})

it('samples a background download from buffered media time', () => {
  const video = document.createElement('video')
  const now = vi.spyOn(performance, 'now').mockReturnValue(0)
  const stop = sampleBuffering(video, NOMINAL_MBPS.light)
  Object.defineProperty(video, 'duration', { configurable: true, value: 12 })
  Object.defineProperty(video, 'buffered', { configurable: true, value: { length: 1, end: () => 12, start: () => 0 } })
  now.mockReturnValue(2000) // 12 s of media in 2 s
  video.dispatchEvent(new Event('progress'))
  expect(throughputEstimate()).toBeCloseTo(6 * NOMINAL_MBPS.light)
  stop()
})
