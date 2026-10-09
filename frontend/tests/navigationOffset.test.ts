import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

it('defaults the shared bottom reservation to zero outside mobile navigation', () => {
  expect(readFileSync('src/index.css', 'utf8')).toMatch(/:root\s*\{\s*--mobile-nav-offset:\s*0px;/)
  for (const file of ['WhatsNew', 'SyncNotifications', 'SyncErrorHandler']) {
    expect(readFileSync(`src/components/${file}.tsx`, 'utf8')).toContain('var(--mobile-nav-offset,0px)')
  }
  expect(readFileSync('src/pages/AdminAccount.css', 'utf8')).toContain('var(--mobile-nav-offset, 0px)')
})
