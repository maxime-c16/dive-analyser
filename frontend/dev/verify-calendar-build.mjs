// Run after npm run build. The calendar ships flag-gated (server CALENDAR_ENABLED,
// default off) and must never ship prototype fixtures, the removed local
// private-data adapter, or private schedule/source identifiers.
import fs from 'node:fs'
import assert from 'node:assert/strict'
const assets = new URL('../dist/assets/', import.meta.url)
const files = fs.readdirSync(assets)
assert(!files.some(file => /CalendarPrototype|calendarPrototype/.test(file)), 'prototype chunk shipped')
const code = files.filter(file => file.endsWith('.js')).map(file => fs.readFileSync(new URL(file, assets), 'utf8')).join('\n')
for (const marker of ['__calendar_local', 'kcpm:2026-2027', 'Prototype controls', 'calendar-prototype-tabs', 'import-bundle', 'chat.whatsapp.com'])
  assert(!code.includes(marker), `Forbidden marker shipped: ${marker}`)
assert(code.includes('/api/v1/calendar'), 'calendar client missing from the build')
assert(code.includes('calendar-five-tabs'), 'flag-gated five-tab navigation missing')
console.log('PASS: build has the flag-gated calendar client and no prototype, private adapter, schedule IDs or private links')
