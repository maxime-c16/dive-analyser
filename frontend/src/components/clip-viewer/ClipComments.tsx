import { useEffect, useRef, useState } from "react";
import { useTranslation } from 'react-i18next'
import { Send } from "lucide-react";
import { api } from "../../services/api";
import CommentThread from "./CommentThread";
import type { Comment } from "./useDiveSocial";

export default function ClipComments({
  id,
  onCountChange,
  basePath = `/api/v1/dives/${id}`,
  guestId,
}: {
  id: number;
  onCountChange: (delta: number) => void;
  basePath?: string;
  guestId?: number;
}) {
  const { t } = useTranslation()
  const [comments, setComments] = useState<Comment[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const activeId = useRef(id);
  activeId.current = id;
  const latestLoad = useRef(0);
  // Changes made after a read starts must win over that read's snapshot.
  const pendingMutations = useRef(new Map<number, Comment | null>());
  const load = async (cursor?: number) => {
    const request = ++latestLoad.current;
    pendingMutations.current.clear();
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get<{
        items: Comment[];
        next_before: number | null;
      }>(`${basePath}/comments`, {
        params: cursor ? { before: cursor } : {},
      });
      if (!mounted.current || request !== latestLoad.current) return;
      const mutations = new Map(pendingMutations.current);
      setComments((previous) => {
        const rows = new Map(
          (cursor ? [...previous, ...data.items] : data.items).map((item) => [
            item.id,
            item,
          ]),
        );
        for (const [commentId, comment] of mutations) {
          if (comment) rows.set(commentId, comment);
          else rows.delete(commentId);
        }
        return [...rows.values()].sort((a, b) => b.id - a.id);
      });
      setBefore(data.next_before);
    } catch {
      if (mounted.current && request === latestLoad.current)
        setError(t('comments.errorLoad'));
    } finally {
      if (mounted.current && request === latestLoad.current) setLoading(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      latestLoad.current += 1;
    };
  }, [id, basePath]);
  return (
    <div className="clip-comments">
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!body.trim() || busy) return;
          setBusy(true);
          setError("");
          try {
            const { data } = await api.post<Comment>(
              `${basePath}/comments`,
              { body: body.trim() },
            );
            if (!mounted.current || activeId.current !== id) return;
            pendingMutations.current.set(data.id, data);
            setComments((previous) => [
              data,
              ...previous.filter((item) => item.id !== data.id),
            ]);
            setBody("");
            onCountChange(1);
          } catch {
            if (mounted.current)
              setError(t('comments.errorPost'));
          } finally {
            if (mounted.current) setBusy(false);
          }
        }}
      >
        <label htmlFor="clip-comment">{t('comments.join')}</label>
        <div className="clip-composer">
          <textarea
            id="clip-comment"
            placeholder={t('comments.placeholder')}
            maxLength={2000}
            rows={2}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            disabled={busy}
          />
          <button aria-label={t('comments.post')} disabled={busy || !body.trim()}>
            <Send size={18} />
          </button>
        </div>
      </form>
      {error && (
        <p role="alert">
          {error} <button onClick={() => void load()}>{t('common.retry')}</button>
        </p>
      )}
      {loading && <p role="status">{t('comments.loading')}</p>}
      {!loading && !error && !comments.length && (
        <div className="clip-empty-comments">
          <p>{t('comments.noComments')}</p>
          <span>{t('comments.beFirst')}</span>
        </div>
      )}
      {comments.map((comment) => (
        <CommentThread key={comment.id} comment={comment} diveId={id} basePath={basePath} guestId={guestId}
          onCountChange={onCountChange}
          onChange={updated => {
            pendingMutations.current.set(updated.id, updated);
            setComments(rows => rows.map(row => row.id === updated.id ? updated : row));
          }}
          onDelete={async () => {
            await api.delete(`${basePath}/comments/${comment.id}`);
            if (!mounted.current || activeId.current !== id) return;
            pendingMutations.current.set(comment.id, null);
            setComments(rows => rows.filter(row => row.id !== comment.id));
            onCountChange(-1 - (comment.reply_count ?? 0));
          }}
        />

      ))}
      {before && (
        <button
          disabled={loading}
          className="clip-load-more"
          onClick={() => void load(before)}
        >
          Older comments
        </button>
      )}
    </div>
  );
}
