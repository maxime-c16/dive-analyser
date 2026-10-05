import { useEffect, useRef, useState } from 'react';
import { Share2 } from 'lucide-react';
import { api } from '../../services/api';

export default function ShareDiveButton({ id }: { id: number }) {
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [message, setMessage] = useState('');
  const [hasShares, setHasShares] = useState(false);
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
  // Parent keys this component by dive ID, so each dive has its own link.
  const share = async () => {
    if (pending.current) return;
    pending.current = true;
    mutationVersion.current += 1;
    setBusy(true);
    setMessage('');
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
        if (mounted.current) setMessage('Copy this link to share the video:');
      } catch { if (mounted.current) setMessage('Could not create a link. Try again.'); }
    } finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  return <>
    <button type="button" aria-label="Share dive" disabled={busy} onClick={() => void share()}>
      <Share2 size={25} /><span>{busy ? 'Sharing…' : 'Share'}</span>
    </button>
    {(message || hasShares) && <div className="clip-share-result" role="status">
      <p>{message || 'Shared links active'}</p>
      {url && message !== 'Link copied' && <input aria-label="Share link" value={url} readOnly onFocus={event => event.target.select()} />}
      {hasShares && <button type="button" disabled={busy} onClick={async () => {
        if (pending.current) return;
        pending.current = true;
    mutationVersion.current += 1;
        setBusy(true);
        try {
          await api.delete(`/api/v1/dives/${id}/shares`);
          if (mounted.current) { setUrl(''); setHasShares(false); setMessage('Shared links revoked'); }
        } catch { if (mounted.current) setMessage('Could not revoke links. Try again.'); }
        finally { pending.current = false; if (mounted.current) setBusy(false); }
      }}>Revoke shared links</button>}
    </div>}
  </>;
}
