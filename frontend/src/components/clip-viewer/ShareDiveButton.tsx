import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next'
import { Share2, X } from 'lucide-react';
import { api } from '../../services/api';

export default function ShareDiveButton({ id }: { id: number }) {
  const { t } = useTranslation()
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [message, setMessage] = useState('');
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
    if (message !== 'Link copied' && message !== 'Shared links revoked') return;
    const timer = setTimeout(() => setMessage(''), 3000);
    return () => clearTimeout(timer);
  }, [message]);
  const dismiss = () => {
    setMessage('');
    setMenuOpen(false);
    shareButton.current?.focus();
  };
  // Parent keys this component by dive ID, so each dive has its own link.
  const share = async () => {
    if (pending.current) return;
    pending.current = true;
    mutationVersion.current += 1;
    setBusy(true);
    setMessage('');
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
      if (mounted.current) setMessage('Link copied');
    } catch {
      try {
        await link;
        if (mounted.current) setMessage(t('clipViewer.copyLinkToShare'));
      } catch { if (mounted.current) setMessage('Could not create a link. Try again.'); }
    } finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  return <>
    <button ref={shareButton} type="button" aria-label={t('clipViewer.shareDive')} aria-expanded={menuOpen} disabled={busy} onClick={() => {
      if (hasShares) { setMessage(''); setMenuOpen(value => !value); }
      else void share();
    }}>
      <Share2 size={25} /><span>{busy ? 'Sharing…' : 'Share'}</span>
    </button>
    {(message || menuOpen) && <div className="clip-share-result" role="group" aria-label="Video sharing">
      <div className="clip-share-result-heading">
        <p role="status">{menuOpen ? 'Share video' : message}</p>
        <button type="button" className="clip-share-close" aria-label="Dismiss sharing notification" onClick={dismiss}><X size={18} /></button>
      </div>
      {url && message === 'Copy this link to share the video:' && <input aria-label={t('clipViewer.shareLink')} value={url} readOnly onFocus={event => event.target.select()} />}
      {menuOpen && <div className="clip-share-menu">
        <button type="button" disabled={busy} onClick={() => void share()}>Copy link</button>
        {hasShares && <button type="button" disabled={busy} onClick={async () => {
          if (pending.current) return;
          pending.current = true;
          mutationVersion.current += 1;
          setBusy(true);
          try {
            await api.delete(`/api/v1/dives/${id}/shares`);
            if (mounted.current) { setUrl(''); setHasShares(false); setMenuOpen(false); setMessage('Shared links revoked'); shareButton.current?.focus(); }
          } catch { if (mounted.current) { setMenuOpen(false); setMessage('Could not revoke links. Try again.'); } }
          finally { pending.current = false; if (mounted.current) setBusy(false); }
        }}>Revoke shared links</button>}
      </div>}
    </div>}
  </>;
}
