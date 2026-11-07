import type { AppNotification } from '../services/notificationsApi'

/** Translate only exact templates emitted by our producers; preserve custom text. */
export function notificationText(item: Pick<AppNotification, 'type' | 'title' | 'body'>, t: (key:string, values?:Record<string, unknown>) => string) {
  let { title, body } = item
  if (item.type === 'new_video' && ['New video synced', 'New videos synced'].includes(title)) {
    title = t(title === 'New videos synced' ? 'notifications.generated.videosSynced' : 'notifications.generated.videoSynced')
    const batch = body?.match(/^(\d+) new clips synced$/)
    if (batch) body = t('notifications.generated.clipsSynced', { count:Number(batch[1]) })
    else if (body?.endsWith(' synced')) body = t('notifications.generated.clipSynced', { label:body.slice(0, -7) })
  }
  if (item.type === 'direct_message' && title === 'New message') {
    title = t('notifications.generated.message')
    const sender = body?.match(/^(.+) sent you a message\.$/)
    if (sender) body = t('notifications.generated.messageFrom', { name:sender[1] })
  }
  return { title, body }
}
