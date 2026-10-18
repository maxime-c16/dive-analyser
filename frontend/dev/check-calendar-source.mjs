// Local-only evidence. Reads ignored inputs, prints no private source contents.
import fs from 'node:fs'
import assert from 'node:assert/strict'
const bundle = JSON.parse(fs.readFileSync(new URL('../../reports/calendar/kcpm-2026-2027/import-bundle.json', import.meta.url)))
const response = await fetch('http://127.0.0.1:5173/__calendar_local/training')
assert(response.ok)
assert.equal(response.headers.get('cache-control'), 'no-store')
const rows = await response.json()
const fields = ['source_key', 'local_date', 'start_local', 'end_local', 'timezone', 'venue_code', 'group_key']
assert.deepEqual(rows, bundle.training_occurrences.map(row => Object.fromEntries(fields.map(key => [key, row[key]]))))
assert.equal(rows.length, 116)
console.log('PASS: 116 exact occurrences; dates, times, timezone, venues and group IDs preserved; private resource fields excluded')
