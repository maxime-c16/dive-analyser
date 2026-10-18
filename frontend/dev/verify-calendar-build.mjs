// Run after npm run build. Calendar code and private adapter must never ship.
import fs from 'node:fs'
import assert from 'node:assert/strict'
const assets = new URL('../dist/assets/', import.meta.url)
const files = fs.readdirSync(assets)
assert(!files.some(file => /CalendarPrototype|calendarPrototype/.test(file)))
const code = files.filter(file => file.endsWith('.js')).map(file => fs.readFileSync(new URL(file, assets), 'utf8')).join('\n')
for (const marker of ['__calendar_local', 'kcpm:2026-2027', 'Prototype controls · local only', 'calendar-prototype-tabs']) assert(!code.includes(marker), `Prototype marker shipped: ${marker}`)
console.log('PASS: production build excludes calendar chunk, adapter, training IDs, controls and five-tab class')
