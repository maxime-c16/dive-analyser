import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next'
import { useLocation, useParams } from 'react-router-dom';
import { Heart, MessageCircle } from 'lucide-react';
import { api } from '../services/api';
import ClipComments from '../components/clip-viewer/ClipComments';
import { useDiveSocial } from '../components/clip-viewer/useDiveSocial';
import '../components/clip-viewer/clipViewer.css';

type SharedVideo = {
  dive_id: number; dive_code: string; height: string;
  guest_id: number; guest_name: string; video_url: string;
};
// StrictMode replays effects. Share the in-flight exchange so two visits cannot
// race to install different guest cookies/identities in the same page.
const pendingVisits = new Map<string, Promise<SharedVideo>>();
function visitSharedVideo(basePath: string, token: string) {
  const key = `${basePath}#${token}`;
  const existing = pendingVisits.get(key);
  if (existing) return existing;
  const request = api.post<SharedVideo>(`${basePath}/visit`, null, { headers: { 'X-Dive-Share': token } })
    .then(({ data }) => data)
    .finally(() => pendingVisits.delete(key));
  pendingVisits.set(key, request);
  return request;
}

function SharedVideoPlayer({ video, basePath }: { video: SharedVideo; basePath: string }) {
  const { t } = useTranslation()
  const { social, setSocial, like, error, busy, retry } = useDiveSocial(video.dive_id, basePath);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [videoEpoch, setVideoEpoch] = useState(0);
  return <main className="shared-dive">
    <header><span className="clip-eyebrow">{t('sharedDive.eyebrow')}</span><h1>{video.dive_code} · {video.height}</h1></header>
    <div className="shared-dive-layout">
      <section aria-label={t('sharedDive.videoAria')} className="shared-dive-video">
        <video key={videoEpoch} src={video.video_url} controls playsInline preload="metadata" onError={() => setVideoError(true)} />
        {videoError && <p role="alert">{t('sharedDive.videoUnavailable')} <button onClick={() => { setVideoError(false); setVideoEpoch(value => value + 1); }}>{t('sharedDive.retryVideo')}</button></p>}
        <div className="shared-dive-actions">
          <button type="button" aria-label={t('clipViewer.likeDive')} aria-pressed={social?.liked ?? false} disabled={!social || busy} onClick={() => void like(!social?.liked)}>
            <Heart size={24} fill={social?.liked ? 'currentColor' : 'none'} /><span>{social?.like_count ?? t('sharedDive.like')}</span>
          </button>
          <button type="button" aria-label={t('clipViewer.comments')} aria-expanded={commentsOpen} aria-controls="shared-comments" onClick={() => setCommentsOpen(value => !value)}>
            <MessageCircle size={24} /><span>{social?.comment_count ?? t('sharedDive.commentsLabel')}</span>
          </button>
        </div>
        {error && <p role="alert">{error} <button onClick={retry}>{t("common.retry")}</button></p>}
      </section>
      <section className="shared-dive-discussion" aria-label={t('sharedDive.discussionAria')}>
        <p>{t('sharedDive.commentingAs')} <strong>{video.guest_name}</strong>.</p>
        {commentsOpen && <div id="shared-comments"><ClipComments id={video.dive_id} basePath={basePath} guestId={video.guest_id} onCountChange={delta => setSocial(value => value ? { ...value, comment_count: Math.max(0, value.comment_count + delta) } : value)} /></div>}
      </section>
    </div>
  </main>;
}
export default function SharedDive() {
  const { t } = useTranslation()
  const { shareId } = useParams();
  const { hash } = useLocation();
  const [video, setVideo] = useState<SharedVideo | null>(null);
  const [error, setError] = useState('');
  const [epoch, setEpoch] = useState(0);
  const basePath = `/api/v1/shared-dives/${shareId}`;
  useEffect(() => {
    let alive = true;
    setVideo(null); setError('');
    const token = hash.slice(1);
    if (!/^\d+$/.test(shareId ?? '') || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
      setError('invalid');
      return;
    }
    visitSharedVideo(basePath, token)
      .then(data => { if (alive) setVideo(data); })
      .catch(() => { if (alive) setError('unavailable'); });
    return () => { alive = false; };
  }, [shareId, hash, basePath, epoch]);
  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'referrer'; meta.content = 'no-referrer';
    document.head.appendChild(meta);
    return () => { meta.remove(); };
  }, []);
  if (error) return <main className="shared-dive"><p role="alert">{t(error === 'invalid' ? 'sharedDive.errorInvalid' : 'sharedDive.errorUnavailable')}</p><button onClick={() => setEpoch(value => value + 1)}>{t("common.retry")}</button></main>;
  if (!video) return <main className="shared-dive"><p role="status">{t("sharedDive.loadingShared")}</p></main>;
  return <SharedVideoPlayer key={`${basePath}-${video.guest_id}`} video={video} basePath={basePath} />;
}
