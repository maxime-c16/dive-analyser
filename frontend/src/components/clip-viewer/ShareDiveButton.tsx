import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next'
import { Share2, X } from 'lucide-react';
import { api } from '../../services/api';

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

export default function ShareDiveButton({ id }: { id: number }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [mode, setMode] = useState<ShareMode>('idle');
  const [hasShares, setHasShares] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const shareButton = useRef<HTMLButtonElement>(null);
  const pending = useRef(false);
  const mutationVersion = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const version = mutationVersion.current;
    api.get<{ active_count: number }>(`/api/v1/dives/${id}/shares`)
      .then(({ data }) => { if (mounted.current && mutationVersion.current === version) setHasShares(data.active_count > 0); })
      .catch(() => { /* Sharing remains usable if the status lookup fails. */ });
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!AUTO_CLEAR_MODES.includes(mode)) return;
    const timer = setTimeout(() => setMode('idle'), 3000);
    return () => clearTimeout(timer);
  }, [mode]);
  const dismiss = () => {
    setMode('idle');
    setMenuOpen(false);
    shareButton.current?.focus();
  };
  // Parent keys this component by dive ID, so each dive has its own link.
  const share = async () => {
    if (pending.current) return;
    pending.current = true;
    mutationVersion.current += 1;
    setBusy(true);
    setMode('idle');
    setMenuOpen(false);
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
    <button ref={shareButton} type="button" aria-label={t('clipViewer.shareDive')} aria-expanded={menuOpen} disabled={busy} onClick={() => {
      if (hasShares) { setMode('idle'); setMenuOpen(value => !value); }
      else void share();
    }}>
      <Share2 size={25} /><span>{busy ? t('clipViewer.sharing') : t('clipViewer.share')}</span>
    </button>
    {(message || menuOpen) && <div className="clip-share-result" role="group" aria-label={t('clipViewer.videoSharing')}>
      <div className="clip-share-result-heading">
        <p role="status">{menuOpen ? t('clipViewer.shareVideo') : message}</p>
        <button type="button" className="clip-share-close" aria-label={t('clipViewer.dismissSharing')} onClick={dismiss}><X size={18} /></button>
      </div>
      {url && mode === 'manual' && <input aria-label={t('clipViewer.shareLink')} value={url} readOnly onFocus={event => event.target.select()} />}
      {menuOpen && <div className="clip-share-menu">
        <button type="button" disabled={busy} onClick={() => void share()}>{t('clipViewer.copyLink')}</button>
        {hasShares && <button type="button" disabled={busy} onClick={async () => {
          if (pending.current) return;
          pending.current = true;
          mutationVersion.current += 1;
          setBusy(true);
          try {
            await api.delete(`/api/v1/dives/${id}/shares`);
            if (mounted.current) { setUrl(''); setHasShares(false); setMenuOpen(false); setMode('revoked'); shareButton.current?.focus(); }
          } catch { if (mounted.current) { setMenuOpen(false); setMode('revokeError'); } }
          finally { pending.current = false; if (mounted.current) setBusy(false); }
        }}>{t('clipViewer.revokeLinks')}</button>}
      </div>}
    </div>}
  </>;
}
