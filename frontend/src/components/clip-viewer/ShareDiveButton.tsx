import { useEffect, useRef, useState } from 'react';
import { Share2 } from 'lucide-react';
import { api } from '../../services/api';

export default function ShareDiveButton({ id }: { id: number }) {
  const [busy, setBusy] = useState(false);
  const [url, setUrl] = useState('');
  const [message, setMessage] = useState('');
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  // Parent keys this component by dive ID, so each dive has its own link.
  const share = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setMessage('');
    const link = url ? Promise.resolve(url) : api
      .post<{ path: string }>(`/api/v1/dives/${id}/shares`)
      .then(({ data }) => {
        const value = new URL(data.path, window.location.origin).href;
        if (mounted.current) setUrl(value);
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
    {message && <div className="clip-share-result" role="status">
      <p>{message}</p>
      {url && message !== 'Link copied' && <input aria-label="Share link" value={url} readOnly onFocus={event => event.target.select()} />}
      {url && <button type="button" onClick={async () => {
        try {
          await api.delete(`/api/v1/dives/${id}/shares`);
          setUrl(''); setMessage('Shared links revoked');
        } catch { setMessage('Could not revoke links. Try again.'); }
      }}>Revoke shared links</button>}
    </div>}
  </>;
}
