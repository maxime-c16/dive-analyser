import { useState, type CSSProperties } from 'react'
import './MemberAvatar.css'

export const AVATAR_HUDS = ['orbit', 'reticle', 'depth'] as const
export type AvatarHud = typeof AVATAR_HUDS[number]
export type AvatarIdentity = { display_name: string; avatar_url?: string | null; avatar_hud?: AvatarHud }

/** Decorative only: the HUD never implies presence, rank or a live score. */
export default function MemberAvatar({ member, large = false, size, hud }: {
  member: AvatarIdentity; large?: boolean; size?: number; hud?: AvatarHud
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const style = hud ?? member.avatar_hud ?? 'reticle'
  const words = (member.display_name ?? '').trim().split(/\s+/).filter(Boolean)
  const initials = (words.length > 1 ? words[0][0] + words[words.length - 1][0] : words[0]?.slice(0, 2))?.toUpperCase() || '?'
  return <span aria-hidden="true" className="member-avatar" data-hud={style} style={{ '--avatar-size': `${size ?? (large ? 96 : 48)}px` } as CSSProperties}>
    <span className="member-avatar-face">
      {member.avatar_url && failedUrl !== member.avatar_url
        ? <img src={member.avatar_url} alt="" decoding="async" onError={() => setFailedUrl(member.avatar_url ?? null)} />
        : initials}
    </span>
    <svg className="member-avatar-hud" viewBox="0 0 100 100" aria-hidden="true">
      {style === 'orbit' && <>
        <circle className="hud-muted" cx="50" cy="50" r="46" />
        <circle cx="50" cy="50" r="46" strokeDasharray="104 40 36 109" transform="rotate(-90 50 50)" />
        <path className="hud-bold" d="M47 4h6M47 96h6" />
      </>}
      {style === 'reticle' && <>
        <circle className="hud-muted" cx="50" cy="50" r="43" />
        <path d="M10 28V14h14M76 14h14v14M90 72v14H76M24 86H10V72" />
        <path className="hud-muted" d="M50 4v7M50 89v7M4 50h7M89 50h7" />
      </>}
      {style === 'depth' && <>
        <path className="hud-muted" d="M24 7h52l17 17v52L76 93H24L7 76V24Z" />
        <path d="M24 7H40M60 7h16l17 17M93 60v16L76 93H60M40 93H24L7 76M7 40V24L24 7" />
        <path d="M91 37h5M91 45h3M91 53h5M91 61h3M4 47h5M4 55h3" />
      </>}
    </svg>
  </span>
}
