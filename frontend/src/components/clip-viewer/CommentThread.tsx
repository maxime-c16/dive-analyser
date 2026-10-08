import { useEffect, useRef, useState } from "react";
import { useTranslation } from 'react-i18next'
import { Heart, Send, Trash2 } from "lucide-react";
import { api } from "../../services/api";
import { useAuth } from "../../contexts/AuthContext";
import { appLanguage } from "../../utils/dateLocale";
import MemberLink from "../activity/MemberLink";
import MemberAvatar from '../MemberAvatar'
import type { Comment } from "./useDiveSocial";

export default function CommentThread({ comment, diveId, basePath = `/api/v1/dives/${diveId}`, guestId, onDelete, onCountChange, onChange, onReply, nested = false }: {
  comment: Comment;
  diveId: number;
  basePath?: string;
  guestId?: number;
  onDelete: () => Promise<void>;
  onCountChange: (delta: number) => void;
  onChange: (comment: Comment) => void;
  nested?: boolean;
  onReply?: (author: string) => void;
}) {
  const { t } = useTranslation()
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [replies, setReplies] = useState<Comment[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const alive = useRef(true);
  const latestComment = useRef(comment);
  latestComment.current = comment;
  const replyMutations = useRef(new Map<number, Comment | null>());
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);
  const input = useRef<HTMLTextAreaElement>(null);
  const load = async (cursor?: number) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    replyMutations.current.clear();
    try {
      const { data } = await api.get<{ items: Comment[]; next_before: number | null }>(`${basePath}/comments`, { params: { parent_id: comment.id, before: cursor } });
      if (!alive.current) return;
      const mutations = new Map(replyMutations.current);
      setReplies(previous => {
        const rows = new Map((cursor ? [...previous, ...data.items] : data.items).map(row => [row.id, row]));
        for (const [replyId, reply] of mutations) {
          if (reply) rows.set(replyId, reply);
          else rows.delete(replyId);
        }
        return [...rows.values()].sort((a, b) => b.id - a.id);
      });
      setBefore(data.next_before);
    } catch { setError(t('comments.errorLoadReplies')); }
    finally { pending.current = false; setBusy(false); }
  };
  const mutate = async (action: () => Promise<void>) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    try { await action(); }
    catch { setError(t('comments.errorSaveReply')); }
    finally { pending.current = false; setBusy(false); }
  };
  return <div className="clip-thread">
    <article className="clip-comment">
      <MemberAvatar member={user && comment.user_id === user.user_id ? { ...user, display_name: user.display_name || comment.author } : { display_name: comment.author, avatar_url: comment.avatar_url, avatar_hud: comment.avatar_hud }} size={36} />
      <div>
        {comment.user_id ? (
          <MemberLink userId={comment.user_id} className="comment-author-link" ariaLabel={t('comments.viewProfileBy', { author: comment.author })}>
            <strong>{comment.author}</strong>
          </MemberLink>
        ) : (
          <strong>{comment.author}</strong>
        )}
        <time dateTime={comment.created_at}>{new Date(comment.created_at).toLocaleDateString(appLanguage())}</time>
        <p>{comment.body}</p>
        <div className="clip-comment-actions">
          <button type="button" aria-label={t('comments.likeBy', { author: comment.author })} aria-pressed={comment.liked ?? false} disabled={busy} onClick={() => void mutate(async () => {
            const { data } = await api.put<Comment>(`${basePath}/comments/${comment.id}/like`, { liked: !comment.liked });
            if (alive.current) onChange({ ...latestComment.current, liked: data.liked, like_count: data.like_count });
          })}><Heart size={16} fill={comment.liked ? "currentColor" : "none"} />{comment.like_count ?? 0}</button>
          <button type="button" disabled={busy} aria-expanded={nested ? undefined : open} onClick={() => {
            if (nested) { onReply?.(comment.author); return; }
            setOpen(true);
            if (!open) void load();
            requestAnimationFrame(() => input.current?.focus());
          }}>{t('comments.reply')}</button>
        </div>
      </div>
      {(guestId !== undefined ? comment.guest_id === guestId : (comment.user_id === user?.user_id || user?.is_admin)) && <button type="button" aria-label={t('comments.deleteBy', { author: comment.author })} disabled={busy} onClick={() => void mutate(onDelete)}><Trash2 size={16} /></button>}
    </article>
    {error && <p role="alert">{error} {open && <button onClick={() => void load()}>{t('comments.retryReplies')}</button>}</p>}
    {!nested && <>
      {!!comment.reply_count && <button className="clip-thread-toggle" type="button" disabled={busy} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void load(); }}>{open ? t('comments.hideReplies') : t('comments.viewReplies', { count: comment.reply_count })}</button>}
      {open && <div className="clip-thread-replies">
        {replies.map(reply => <CommentThread key={reply.id} comment={reply} diveId={diveId} basePath={basePath} guestId={guestId} nested onReply={author => { setBody(previous => previous || `@${author} `); input.current?.focus(); }} onCountChange={onCountChange} onChange={updated => {
          replyMutations.current.set(updated.id, updated);
          setReplies(rows => rows.map(row => row.id === updated.id ? updated : row));
        }} onDelete={async () => {
          await api.delete(`${basePath}/comments/${reply.id}`);
          if (!alive.current) return;
          replyMutations.current.set(reply.id, null);
          setReplies(rows => rows.filter(row => row.id !== reply.id));
          onChange({ ...latestComment.current, reply_count: Math.max(0, (latestComment.current.reply_count ?? 0) - 1) });
          onCountChange(-1);
        }} />)}
        {busy && <p role="status">{t('comments.savingReplies')}</p>}
        {before && <button type="button" className="clip-load-more" disabled={busy} onClick={() => void load(before)}>{t('comments.olderReplies')}</button>}
        <form onSubmit={event => {
          event.preventDefault();
          if (!body.trim()) return;
          void mutate(async () => {
            const { data } = await api.post<Comment>(`${basePath}/comments`, { body: body.trim(), parent_id: comment.id });
            if (!alive.current) return;
            replyMutations.current.set(data.id, data);
            setReplies(rows => [data, ...rows]);
            setBody("");
            onChange({ ...latestComment.current, reply_count: (latestComment.current.reply_count ?? 0) + 1 });
            onCountChange(1);
          });
        }}>
          <label htmlFor={`reply-${comment.id}`}>{t('comments.replyTo')} {comment.author}</label>
          <div className="clip-composer">
            <textarea ref={input} id={`reply-${comment.id}`} placeholder={t('comments.replyPlaceholder')} rows={2} maxLength={2000} value={body} onChange={event => setBody(event.target.value)} disabled={busy} />
            <button type="submit" aria-label={t('comments.postReplyTo', { author: comment.author })} disabled={busy || !body.trim()}><Send size={18} /></button>
          </div>
        </form>
      </div>}
    </>}
  </div>;
}
