import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next'
import { Copy, Send, Check, Share2, X } from 'lucide-react';
import { api } from '../../services/api';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import MemberPicker from '../messages/MemberPicker';
import { sendMessage, startConversation } from '../../services/messagesApi';
import { useModalOverlay } from '../../utils/overlays';

/**
 * Share outcome states are semantic (`mode`), never compared against
 * translated strings: display text is looked up per mode at render time so
 * a language change cannot break the manual-copy input visibility.
 */
type ShareMode = 'idle' | 'copied' | 'manual' | 'revoked' | 'createError' | 'revokeError';

const AUTO_CLEAR_MODES: ShareMode[] = ['copied', 'revoked'];

export function modeMessage(t: (key: string) => string, mode: ShareMode): string {
  switch (mode) {
    case 'copied': return t('clipViewer.linkCopied');
    case 'manual': return t('clipViewer.copyLinkToShare');
    case 'revoked': return t('clipViewer.linksRevoked');
    case 'createError': return t('clipViewer.createLinkError');
    case 'revokeError': return t('clipViewer.revokeError');
    default: return '';
  }
}

export default function ShareDiveButton({ id, allowLink = true, allowDm = false }: { id: number; allowLink?: boolean; allowDm?: boolean }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [mode, setMode] = useState<ShareMode>('idle');
  const [hasShares, setHasShares] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const shareButton = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const sendPending = useRef(false);
  const keys = useRef(new Map<number, string>());
  const pending = useRef(false);
  const mutationVersion = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    if (!allowLink) return () => { mounted.current = false; };
    const version = mutationVersion.current;
    api.get<{ active_count: number }>(`/api/v1/dives/${id}/shares`)
      .then(({ data }) => { if (mounted.current && mutationVersion.current === version) setHasShares(data.active_count > 0); })
      .catch(() => { /* Sharing remains usable if the status lookup fails. */ });
    return () => { mounted.current = false; };
  }, [id, allowLink]);
  useEffect(() => {
    if (!AUTO_CLEAR_MODES.includes(mode)) return;
    const timer = setTimeout(() => setMode('idle'), 3000);
    return () => clearTimeout(timer);
  }, [mode]);
  const dismiss = () => {
    setMode('idle');
    setMenuOpen(false);
  };
  useModalOverlay(sheet, { enabled: menuOpen, layer: 70, extraRef: backdrop, onClose: dismiss, returnFocus: () => shareButton.current });
  // Parent keys this component by dive ID, so each dive has its own link.
  const share = async () => {
    if (pending.current) return;
    pending.current = true;
    mutationVersion.current += 1;
    setBusy(true);
    setMode('idle');
    const link = url ? Promise.resolve(url) : api
      .post<{ path: string }>(`/api/v1/dives/${id}/shares`)
      .then(({ data }) => {
        const value = new URL(data.path, window.location.origin).href;
        if (mounted.current) { setUrl(value); setHasShares(true); }
        return value;
      });
    try {
      // Request permission during the click; Safari needs user activation.
      if (navigator.clipboard?.write && typeof ClipboardItem !== 'undefined') {
        await navigator.clipboard.write([new ClipboardItem({
          'text/plain': link.then(value => new Blob([value], { type: 'text/plain' })),
        })]);
      } else {
        const value = await link;
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(value);
      }
      if (mounted.current) setMode('copied');
    } catch {
      try {
        await link;
        if (mounted.current) setMode('manual');
      } catch { if (mounted.current) setMode('createError'); }
    } finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  const message = modeMessage(t, mode);
  return <>
    <button ref={shareButton} type="button" aria-label={t('clipViewer.shareDive')} aria-expanded={menuOpen} aria-haspopup="dialog" onClick={() => {
      setMenuOpen(true); setMode('idle'); setSendError(false); setSent(null);
    }}>
      <Share2 size={25} /><span>{t('clipViewer.share')}</span>
    </button>
    {menuOpen && createPortal(<div ref={backdrop} className="clip-share-backdrop" onClick={event => { if (event.target === event.currentTarget) dismiss(); }}>
      <div ref={sheet} className="clip-share-sheet" role="dialog" aria-modal="true" aria-label={t('clipViewer.videoSharing')} tabIndex={-1}>
        <div className="clip-share-sheet-handle" aria-hidden="true" />
        <header className="clip-share-sheet-heading">
          <div><h2>{t('clipViewer.shareVideo')}</h2><p>{t('clipViewer.shareChoose')}</p></div>
          <button type="button" className="clip-share-close" aria-label={t('clipViewer.dismissSharing')} onClick={dismiss}><X size={20} /></button>
        </header>
        {allowLink && <section className="clip-share-link-section" aria-label={t('clipViewer.shareLink')}>
          <button type="button" className="clip-share-copy" aria-label={t('clipViewer.copyLink')} disabled={busy} onClick={() => void share()}>
            <span className="clip-share-action-icon">{mode === 'copied' ? <Check size={22} /> : <Copy size={22} />}</span>
            <span><strong>{busy ? t('clipViewer.sharing') : t('clipViewer.copyLink')}</strong><small>{t('clipViewer.shareLinkHint')}</small></span>
          </button>
          {message && <p className="clip-share-feedback" role={mode === 'createError' || mode === 'revokeError' ? 'alert' : 'status'}>{message}</p>}
          {url && mode === 'manual' && <input aria-label={t('clipViewer.shareLink')} value={url} readOnly onFocus={event => event.target.select()} />}
          {hasShares && <button type="button" className="clip-share-revoke" disabled={busy} onClick={async () => {
            if (pending.current) return;
            pending.current = true;
            mutationVersion.current += 1;
            setBusy(true);
            try {
              await api.delete(`/api/v1/dives/${id}/shares`);
              if (mounted.current) { setUrl(''); setHasShares(false); setMode('revoked'); }
            } catch { if (mounted.current) setMode('revokeError'); }
            finally { pending.current = false; if (mounted.current) setBusy(false); }
          }}>{t('clipViewer.revokeLinks')}</button>}
        </section>}
        {allowDm && <section className="clip-share-dm-section" aria-label={t('messages.sendDive')}>
          <h3><Send size={17} />{t('clipViewer.shareDm')}</h3>
          <p className="clip-share-dm-hint">{t('clipViewer.shareDmHint')}</p>
          {sent ? <div className="clip-share-sent" role="status"><Check size={20} /><span>{t('messages.diveSent')}</span><Link to={`/messages/${sent}`}>{t('messages.open')}</Link></div> : <MemberPicker disabled={sending} onSelect={async member => {
            if (sendPending.current) return;
            sendPending.current = true;
            setSending(true); setSendError(false);
            if (!keys.current.has(member.user_id)) keys.current.set(member.user_id, crypto.randomUUID());
            try {
              const conversation = await startConversation(member.user_id);
              await sendMessage(conversation.id, { client_id: keys.current.get(member.user_id)!, dive_id: id });
              keys.current.delete(member.user_id);
              if (mounted.current) setSent(conversation.id);
            } catch { if (mounted.current) setSendError(true); }
            finally { sendPending.current = false; if (mounted.current) setSending(false); }
          }} />}
          {sending && <p role="status" className="clip-share-feedback">{t('clipViewer.sharing')}</p>}
          {sendError && <p role="alert" className="clip-share-feedback">{t('messages.sendDiveError')}</p>}
        </section>}
      </div>
    </div>, document.body)}
  </>;
}
