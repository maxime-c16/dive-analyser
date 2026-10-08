import MemberLink from '../activity/MemberLink'
import type { Mention } from './mentionValue'

export default function MentionText({ body, mentions = [] }: { body: string; mentions?: Mention[] }) {
  const chars = Array.from(body)
  const parts = []
  let end = 0
  for (const mention of [...mentions].sort((a, b) => a.start - b.start)) {
    if (mention.start < end || mention.end > chars.length || mention.end <= mention.start) continue
    parts.push(chars.slice(end, mention.start).join(''))
    parts.push(<MemberLink key={`${mention.start}-${mention.user_id}`} userId={mention.user_id} className="mention-link">{chars.slice(mention.start, mention.end).join('')}</MemberLink>)
    end = mention.end
  }
  parts.push(chars.slice(end).join(''))
  return <>{parts}</>
}
