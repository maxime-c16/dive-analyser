import { useEffect, useRef, useState } from "react";
import { Trash2, Send } from "lucide-react";
import { api } from "../../services/api";
import { useAuth } from "../../contexts/AuthContext";
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
  const { user } = useAuth();
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
        setError("Could not load comments.");
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
              setError("Could not post your comment. Your text is saved here.");
          } finally {
            if (mounted.current) setBusy(false);
          }
        }}
      >
        <label htmlFor="clip-comment">Join the discussion</label>
        <div className="clip-composer">
          <textarea
            id="clip-comment"
            placeholder="Add a comment…"
            maxLength={2000}
            rows={2}
            value={body}
            onChange={(event) => setBody(event.target.value)}
            disabled={busy}
          />
          <button aria-label="Post comment" disabled={busy || !body.trim()}>
            <Send size={18} />
          </button>
        </div>
      </form>
      {error && (
        <p role="alert">
          {error} <button onClick={() => void load()}>Retry</button>
        </p>
      )}
      {loading && <p role="status">Loading comments…</p>}
      {!loading && !error && !comments.length && (
        <div className="clip-empty-comments">
          <p>No comments yet.</p>
          <span>Be the first to share a thought on this dive.</span>
        </div>
      )}
      {comments.map((comment) => (
        <article key={comment.id} className="clip-comment">
          <div className="clip-avatar">
            {comment.author.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <strong>{comment.author}</strong>
            <time dateTime={comment.created_at}>
              {new Date(comment.created_at).toLocaleDateString()}
            </time>
            <p>{comment.body}</p>
          </div>
          {(guestId !== undefined ? comment.guest_id === guestId : (comment.user_id === user?.user_id || user?.is_admin)) && (
            <button
              type="button"
              aria-label={`Delete comment by ${comment.author}`}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await api.delete(
                    `${basePath}/comments/${comment.id}`,
                  );
                  if (!mounted.current || activeId.current !== id) return;
                  pendingMutations.current.set(comment.id, null);
                  setComments((previous) =>
                    previous.filter((item) => item.id !== comment.id),
                  );
                  onCountChange(-1);
                } catch {
                  if (mounted.current)
                    setError("Could not delete your comment.");
                } finally {
                  if (mounted.current) setBusy(false);
                }
              }}
            >
              <Trash2 size={16} />
            </button>
          )}
        </article>
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
