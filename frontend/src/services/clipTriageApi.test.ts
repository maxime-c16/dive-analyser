import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api } from './api'
import { downloadVideoGroundTruth } from './clipTriageApi'

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => { vi.restoreAllMocks() })

it('follows GT export cursors and saves each bounded page as its own file', async () => {
  const pages = [
    '{"counts":{"positives":1},"items":[],"has_more":true,"next_cursor":"c2"}',
    '{"items":[],"has_more":true,"next_cursor":"c3"}',
    '{"items":[],"has_more":false,"next_cursor":null}',
  ]
  const get = vi.spyOn(api, 'get').mockImplementation(async () => ({ data: new Blob([pages.shift()!]) }))
  const names: string[] = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download) })

  expect(await downloadVideoGroundTruth(9, 'IMG_1.MOV')).toBe(3)
  expect(get.mock.calls.map(call => (call[1] as { params?: { cursor?: string } }).params?.cursor)).toEqual([undefined, 'c2', 'c3'])
  expect(names).toEqual(['gt-IMG_1-v9.json', 'gt-IMG_1-v9.part2.json', 'gt-IMG_1-v9.part3.json'])
})

it('stops when the cursor does not advance', async () => {
  vi.spyOn(api, 'get').mockImplementation(async () => ({ data: new Blob(['{"next_cursor":"same"}']) }))
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  await expect(downloadVideoGroundTruth(9, 'a.mov')).rejects.toThrow('did not advance')
})
