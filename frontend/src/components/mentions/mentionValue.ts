export type Mention = { user_id: number; start: number; end: number }
/** Composer spans use textarea UTF-16 offsets. API spans use Unicode code points. */
export type MentionValue = { body: string; mentions: Mention[] }
export const emptyMentionValue = (): MentionValue => ({ body: '', mentions: [] })

export function editMentionValue(value: MentionValue, body: string): MentionValue {
  let start = 0
  while (start < value.body.length && start < body.length && value.body[start] === body[start]) start++
  let oldEnd = value.body.length, newEnd = body.length
  while (oldEnd > start && newEnd > start && value.body[oldEnd - 1] === body[newEnd - 1]) { oldEnd--; newEnd-- }
  const delta = newEnd - oldEnd
  return { body, mentions: value.mentions.flatMap(m => {
    if (m.end <= start) return [m]
    if (m.start >= oldEnd) return [{ ...m, start: m.start + delta, end: m.end + delta }]
    return [] // Editing a label removes its identity rather than linking the wrong text.
  }) }
}

export function mentionPayload(value: MentionValue) {
  return { body: value.body, mentions: value.mentions.map(m => ({ ...m,
    start: Array.from(value.body.slice(0, m.start)).length,
    end: Array.from(value.body.slice(0, m.end)).length,
  })) }
}
