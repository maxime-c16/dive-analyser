// Isolated design review with synthetic data; no backend or account writes.
import React from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Series from '../../src/pages/Series'
import { api } from '../../src/services/api'
import type { SeriesSheet, SeriesChoice, SeriesClip } from '../../src/services/seriesApi'
import i18n from '../../src/i18n'
import ddCatalog from './series-dd.generated.json'
import '../../src/index.css'
if (!import.meta.env.DEV) throw new Error('Review fixture is development-only')
const params = new URLSearchParams(location.search)
void i18n.changeLanguage(params.get('lang') === 'en' ? 'en' : 'fr')
// Generated directly from the same versioned Python formula as the real API.
const ddByHeight: Record<string, Record<string, number>> = ddCatalog.by_height
const fixtureHeight = ['1m', '3m', '5m', '7.5m', '10m'].includes(params.get('height') ?? '') ? params.get('height')! : '3m'
const ddAt = (code: string, height: string) => ddByHeight[height]?.[code] ?? null
const demoMedia = new Map<string, { playback_url: string; preview_url: string; poster_url: string }>()
function demoClips(code: string, height: string): SeriesClip[] {
  if (params.has('noclips') || ddAt(code, height) === null) return []
  const base = Number.parseInt(code, 10) * 100 + ['1m', '3m', '5m', '7.5m', '10m'].indexOf(height) * 10 + code.charCodeAt(code.length - 1)
  const clip = (recent: boolean): SeriesClip => {
    const uuid = `series-review-${height}-${code}-${recent ? 'recent' : 'best'}`
    demoMedia.set(uuid, { playback_url: '/series-review-demo.mp4', preview_url: '/series-review-demo.mp4', poster_url: '/series-review-demo.jpg' })
    return { id: base + Number(recent), video_uuid: uuid, date: recent ? '2026-10-22T12:00:00Z' : '2026-10-18T12:00:00Z', mean_score: recent ? null : 7.5, rating_count: recent ? 0 : 3, url: '/series-review-demo.mp4' }
  }
  return code.startsWith('2') ? [clip(true)] : [clip(false), clip(true)]
}
const enrich = (c: SeriesChoice, height: string) => {
  const clips = demoClips(c.code, height)
  return { ...c, dd: ddAt(c.code, height), clip: c.clip_id ? clips.find(v => v.id === c.clip_id) ?? null : clips[0] ?? null }
}
let sheet: SeriesSheet = { id: 1, title: 'Ma série de printemps', height: fixtureHeight, event_id: null, version: 1, can_edit: true,
  updated_at: '2026-10-22', slot_count: 4, shared_with: [], dd_reference: ddCatalog.reference_label,
  slots: Array.from({ length: 6 }, (_, i) => ({ code: params.has('empty') ? '' : ['101B', '201B', '301B', '401B', '', ''][i], clip_id: null, dd: params.has('empty') ? null : ddAt(['101B', '201B', '301B', '401B', '', ''][i], fixtureHeight), clip: demoClips(params.has('empty') ? '' : ['101B', '201B', '301B', '401B', '', ''][i], fixtureHeight)[0] ?? null,
    alternatives: i === 2 && !params.has('empty') ? [{ code: '203B', clip_id: null, dd: ddAt('203B', fixtureHeight), clip: demoClips('203B', fixtureHeight)[0] ?? null }] : [] })) }
api.defaults.adapter = async config => {
  let data: unknown = {}
  if (config.url?.startsWith('/api/v1/dd/lookup/')) {
    const [, , , , , code, height] = config.url.split('/')
    const value = ddAt(code, height)
    if (value === null) throw Object.assign(new Error('DD not defined by the reference'), { response: { status: 404 } })
    data = { dd_value: value, reference_id: ddCatalog.reference_id }
  } else if (config.url === '/api/v1/media/status/batch') {
    const body = JSON.parse(config.data)
    data = Object.fromEntries(body.video_uuids.map((uuid: string) => [uuid, { status: 'ready', ...demoMedia.get(uuid) }]))
  } else if (/^\/api\/v1\/media\/[^/]+\/(status|request)$/.test(config.url ?? '')) {
    const uuid = decodeURIComponent(config.url!.split('/')[4])
    const media = demoMedia.get(uuid)
    if (!media) throw Object.assign(new Error('Missing demo clip'), { response: { status: 404 } })
    data = { video_uuid: uuid, status: 'ready', can_request: false, available_renditions: ['proxy_720p'], ...media }
  } else if (config.url === '/api/v1/series/clips') data = demoClips(config.params.code, config.params.height)
  else if (config.method === 'put' || config.method === 'post') {
    const input = JSON.parse(config.data)
    sheet = { ...sheet, ...input, slots: input.slots ? input.slots.map((s: SeriesSheet['slots'][number]) => ({ ...enrich(s, input.height ?? sheet.height), alternatives: s.alternatives.map(c => enrich(c, input.height ?? sheet.height)) })) : sheet.slots, version: sheet.version + 1 }
    sheet.slot_count = sheet.slots.filter(s => s.code).length
    sheet.total_slots = sheet.slots.length
    data = sheet
  } else if (config.url === '/api/v1/series') data = [sheet]
  else data = sheet
  return { data, status: 200, statusText: 'OK', headers: {}, config }
}
const path = params.get('list') === '1' ? '/series' : '/series/1'
createRoot(document.getElementById('root')!).render(<div style={{ padding: 20 }}><p style={{ color: '#98a2aa', marginBottom: 20, fontSize: 12 }}>Démo</p><MemoryRouter initialEntries={[path]}><Routes><Route path="/series" element={<Series />} /><Route path="/series/:seriesId" element={<Series />} /></Routes></MemoryRouter></div>)
