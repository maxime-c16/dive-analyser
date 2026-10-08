import { useState } from 'react'
import type { MemberIdentity } from '../services/communityApi'

export default function MemberAvatar({ member, large = false }: { member: MemberIdentity; large?: boolean }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  return <span aria-hidden className={`flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-app-panel-elevated font-semibold text-app-accent ring-1 ring-app ${large ? 'h-20 w-20 text-2xl sm:h-24 sm:w-24' : 'h-12 w-12 text-lg'}`}>
    {member.avatar_url && failedUrl !== member.avatar_url
      ? <img src={member.avatar_url} alt="" className="h-full w-full object-cover" onError={() => setFailedUrl(member.avatar_url)} />
      : member.display_name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('').toUpperCase() || '?'}
  </span>
}
