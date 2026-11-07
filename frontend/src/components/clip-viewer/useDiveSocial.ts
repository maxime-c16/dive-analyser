import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import type { AvatarHud } from '../MemberAvatar'
import { useTranslation } from "react-i18next";
export type Social = {
  liked: boolean;
  like_count: number;
  comment_count: number;
};
export type Comment = {
  id: number;
  body: string;
  mentions?: import('../mentions/mentionValue').Mention[];
  author: string;
  avatar_url?: string | null;
  avatar_hud?: AvatarHud;
  user_id: number | null;
  guest_id?: number | null;
  created_at: string;
  parent_id?: number | null;
  liked?: boolean;
  like_count?: number;
  reply_count?: number;
};

export function useDiveSocial(id: number, basePath = `/api/v1/dives/${id}`) {
  const { t } = useTranslation();
  const [social, setSocial] = useState<Social | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const activeId = useRef(id);
  activeId.current = id;
  const pending = useRef(false);
  const [epoch, setEpoch] = useState(0);
  useEffect(() => {
    let alive = true;
    setSocial(null);
    setError("");
    api
      .get<Social>(`${basePath}/social`)
      .then(({ data }) => {
        if (alive) setSocial(data);
      })
      .catch(() => {
        if (alive) setError(t("clipViewer.reactionsUnavailable"));
      });
    return () => {
      alive = false;
    };
  }, [id, basePath, epoch, t]);
  const like = useCallback(
    async (liked: boolean) => {
      if (!social || pending.current || social.liked === liked) return;
      pending.current = true;
      setBusy(true);
      setError("");
      try {
        const { data } = await api.put<Social>(`${basePath}/like`, {
          liked,
        });
        if (activeId.current === id) setSocial(data);
      } catch {
        if (activeId.current === id)
          setError(t("clipViewer.likeFailed"));
      } finally {
        pending.current = false;
        setBusy(false);
      }
    },
    [id, basePath, social, t],
  );
  return {
    social,
    setSocial,
    like,
    error,
    busy,
    retry: () => setEpoch((value) => value + 1),
  };
}
