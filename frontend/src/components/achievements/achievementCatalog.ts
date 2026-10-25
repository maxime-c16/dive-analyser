import {
  AtSign, BadgeCheck, Camera, FileText, Gavel, Heart, Megaphone, MessageCircle, MessagesSquare,
  Reply, Scale, Send, Share2, Sparkles, Tag, Trophy, Users, type LucideIcon,
} from 'lucide-react'
import type { AchievementCategory } from '../../services/achievementsApi'

export const ACHIEVEMENT_CATEGORIES: AchievementCategory[] = ['profile', 'community', 'jury', 'dives']

const ICONS: Record<string, LucideIcon> = {
  profile_photo: Camera,
  profile_handle: Tag,
  profile_bio: FileText,
  profile_complete: BadgeCheck,
  first_like: Heart,
  likes_25: Trophy,
  first_comment: MessageCircle,
  first_reply: Reply,
  comments_10: Megaphone,
  first_mention: AtSign,
  first_message: Send,
  first_like_received: Sparkles,
  first_comment_received: MessagesSquare,
  first_rating: Gavel,
  ratings_10: Scale,
  first_evaluation_request: Users,
  first_share: Share2,
}

export const achievementIcon = (key: string): LucideIcon => ICONS[key] ?? Trophy

export const isKnownAchievement = (key: string): boolean => key in ICONS

/**
 * Studio render of the achievement's trophy (tools/trophies/achievements.json,
 * ~12 KB WebP in public/achievements). Never precached: only fetched when shown.
 */
export const achievementArt = (key: string): string | null => isKnownAchievement(key) ? `/achievements/${key}.webp` : null
