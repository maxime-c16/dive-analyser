import { expect, it } from 'vitest'
import i18n from '../i18n'
import { notificationText } from './notificationText'
const fr = i18n.getFixedT('fr')
it('localizes known automatic titles while retaining dive identity', () => {
  expect(notificationText({ type:'new_video', title:'New video synced', body:'101B · 1m' }, fr)).toEqual({ title:'Nouvelle vidéo synchronisée', body:'101B · 1m' })
  expect(notificationText({ type:'new_video', title:'New videos synced', body:'2 new clips synced' }, fr).body).toBe('2 nouveaux extraits synchronisés')
})
it('localizes a known message template while preserving the sender name', () => {
  expect(notificationText({ type:'direct_message', title:'New message', body:'Sasa & Loïs sent you a message.' }, fr)).toEqual({ title:'Nouveau message', body:'Sasa & Loïs vous a envoyé un message.' })
})
it('keeps custom and unknown payload text intact', () => {
  const custom = { type:'new_video' as const, title:'My special caption', body:'New video synced' }
  expect(notificationText(custom, fr)).toEqual({ title:custom.title, body:custom.body })
  expect(notificationText({ type:'direct_message', title:'New message', body:'Custom message excerpt' }, fr).body).toBe('Custom message excerpt')
})
