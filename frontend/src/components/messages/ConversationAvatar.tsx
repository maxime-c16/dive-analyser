import MemberAvatar from '../MemberAvatar'
import type { MemberIdentity } from '../../services/communityApi'

/** One member's avatar, or two overlapping ones for a group. */
export default function ConversationAvatar({ peers, size }: { peers: MemberIdentity[]; size: number }) {
  if (peers.length < 2) return peers[0] ? <MemberAvatar member={peers[0]} size={size} /> : null
  const small = Math.round(size * 0.72)
  return <span className="msg-group-avatar" style={{ width: size, height: size }} aria-hidden="true">
    <MemberAvatar member={peers[1]} size={small} />
    <MemberAvatar member={peers[0]} size={small} />
  </span>
}
