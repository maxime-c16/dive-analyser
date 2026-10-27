import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Check, Copy, Crown, Link2, Play, Timer, Volume2 } from "lucide-react";
import MemberAvatar from "../components/MemberAvatar";
import { ScoreCard } from "../components/evaluation/ScoreCards";
import EvaluationPlayer from "../components/evaluation/EvaluationPlayer";
import "../components/evaluation/evaluations.css";
import useRoomPreload from "../components/judge-room/useRoomPreload";
import {
  AUDIO_PRIMER,
  unlockRoomAudio,
} from "../components/judge-room/audioUnlock";
import ScoreInput from "../components/evaluation/ScoreInput";
import { MobileShellActions } from "../navigation/mobileShellActions";
import { useAuth } from "../contexts/AuthContext";
import { roomRequest, type Room, type Player } from "../services/judgeRoomApi";
import "../components/code-analysis/codeAnalysis.css";
import "../components/community/community.css";
import "../components/evaluation/evaluationA.css";
import "../components/judge-room/judgeRoom.css";

function Seat({ player, size = 44 }: { player: Player; size?: number }) {
  return player.user_id ? (
    <MemberAvatar member={{ display_name: player.name }} size={size} />
  ) : (
    <span
      className="gm-ghost"
      style={{ width: size, height: size, fontSize: size * 0.5 }}
    >
      {player.emoji ?? player.name.slice(0, 1)}
    </span>
  );
}

type Invite = {
  host: string;
  count: number;
  mode: string;
  dives: number;
  posters: string[];
};

export default function JudgeRoom() {
  const { code } = useParams();
  const { user, checking } = useAuth();
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const videoA = useRef<HTMLVideoElement>(null);
  const videoB = useRef<HTMLVideoElement>(null);
  const [soundBlocked, setSoundBlocked] = useState(false);
  const unlock = () => {
    void unlockRoomAudio([videoA.current, videoB.current]);
  };
  const [room, setRoom] = useState<Room | null>(null);
  const preloaded = useRoomPreload(code, room?.playlist ?? []);
  const [invite, setInvite] = useState<Invite | null>(null);
  const [shadow, setShadow] = useState(false);
  useEffect(() => {
    if (user)
      roomRequest<{ enabled: boolean }>("/preferences/shadow")
        .then((r) => setShadow(r.enabled))
        .catch(() => {});
  }, [user]);
  const [nick, setNick] = useState("");
  const [joinCode, setJoinCode] = useState("");
  const [filter, setFilter] = useState("");
  const [score, setScore] = useState<number | null>(null);
  const [suspect, setSuspect] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [clock, setClock] = useState(Date.now() / 1000);
  const offset = useRef(0);
  const channel = useRef<WebSocket | null>(null);
  const sentReady = useRef("");
  const current = useRef<Room | null>(null);
  const readyDives = useRef(new Set<number>());
  const [endedDive, setEndedDive] = useState<string | null>(null);
  const signal = useCallback((type: "ready" | "ended") => {
    const state = current.current;
    if (!state || channel.current?.readyState !== WebSocket.OPEN) return;
    if (type === "ready") {
      const round = `${state.game_id}:${state.index}`;
      if (state.phase !== "loading" || sentReady.current === round) return;
      sentReady.current = round;
    }
    channel.current.send(
      JSON.stringify({ type, index: state.index, game_id: state.game_id }),
    );
  }, []);
  const accept = (next: Room) => {
    offset.current = next.server_time - Date.now() / 1000;
    if (current.current?.game_id !== next.game_id) readyDives.current.clear();
    current.current = next;
    setRoom(next);
    if (
      next.phase === "loading" &&
      readyDives.current.has(next.playlist[next.index]?.id)
    )
      signal("ready");
    setError(false);
  };
  useEffect(() => {
    setRoom(null);
    if (!code) return;
    let active = true;
    roomRequest("/" + code)
      .then((r) => {
        if (active) accept(r);
      })
      .catch(() =>
        roomRequest<Invite>("/" + code + "/invite")
          .then((r) => {
            if (active) setInvite(r);
          })
          .catch(() => {
            if (active) setError(true);
          }),
      );
    return () => {
      active = false;
    };
  }, [code]);
  const joined = Boolean(room);
  useEffect(() => {
    if (!code || !joined) return;
    let active = true,
      socket: WebSocket,
      retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/rooms/${code}/live`,
      );
      sentReady.current = "";
      channel.current = socket;
      socket.onmessage = (e) => {
        if (active) accept(JSON.parse(e.data));
      };
      socket.onclose = () => {
        if (active) retry = setTimeout(connect, 1500);
      };
    };
    connect();
    return () => {
      active = false;
      clearTimeout(retry);
      channel.current = null;
      socket?.close();
    };
  }, [code, joined]);
  useEffect(() => {
    const timer = setInterval(
      () => setClock(Date.now() / 1000 + offset.current),
      100,
    );
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    setScore(null);
    setSuspect(null);
  }, [room?.index, room?.phase]);
  const dive = room?.playlist[Math.min(room.index, room.playlist.length - 1)];
  const roundKey = room ? `${room.game_id}:${room.index}` : "";
  const scoring = room?.phase === "judge" && endedDive === roundKey;
  const watching =
    room && ["loading", "watching", "judge"].includes(room.phase) && !scoring;
  const mediaActive =
    room && ["loading", "watching", "judge", "reveal"].includes(room.phase);
  const action = async (payload: unknown) => {
    if (busy) return;
    setBusy(true);
    try {
      accept(await roomRequest("/" + code + "/actions", payload));
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };
  const join = async () => {
    unlock();
    setBusy(true);
    try {
      accept(
        await roomRequest("/" + code + "/join", {
          nickname: nick || user?.display_name || "Guest",
        }),
      );
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(location.origin + "/room/" + code);
      setCopied(true);
    } catch {
      setError(true);
    }
  };
  const number = (value: number | null | undefined) =>
    value == null
      ? "—"
      : (value / 2).toLocaleString(i18n.language, { maximumFractionDigits: 1 });
  const host = room?.host === room?.me;
  const configure = (mode: string, source: string) =>
    void action({ action: "configure", mode, source, code: filter });
  if (checking) return <div className="ca gm-page">{t("common.loading")}</div>;
  if (!code)
    return (
      <div className="ca gm-page gm-home">
        <header className="cm-head">
          <h1>{t("room.title")}</h1>
          <MobileShellActions />
        </header>
        <section className="ca-panel gm-hero ca-arrive">
          <ul className="gm-hero-seats" aria-hidden="true">
            {user && (
              <li className="is-me">
                <MemberAvatar member={user} size={64} />
              </li>
            )}
            {["🥰", "🧊", "👻", "🏅"].map((emoji, i) => (
              <li key={emoji} className="ca-pop" style={{ "--i": i } as CSSProperties}>
                <span className="gm-ghost">{emoji}</span>
              </li>
            ))}
          </ul>
          <div className="gm-hero-modes" aria-hidden="true">
            <span className="ca-fact">{t("room.classic")}</span>
            <span className="ca-fact">{t("room.mole")}</span>
            <span className="ca-fact">{t("room.guessCode")}</span>
          </div>
          <button
            className="gm-cta"
            disabled={busy || !user}
            onClick={async () => {
              setBusy(true);
              try {
                const r = await roomRequest("", {});
                navigate("/room/" + r.code);
              } catch {
                setError(true);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Play size={18} />
            {t("room.create")}
          </button>
        </section>
        <form
          className="gm-join-code"
          onSubmit={(e) => {
            e.preventDefault();
            const value = joinCode.trim().toUpperCase();
            if (value) navigate("/room/" + value);
          }}
        >
          <label className="cm-search">
            <Link2 size={18} aria-hidden="true" />
            <input
              aria-label={t("room.joinCode")}
              placeholder={t("room.joinCode")}
              value={joinCode}
              maxLength={8}
              autoCapitalize="characters"
              onChange={(e) => setJoinCode(e.target.value)}
            />
          </label>
          <button className="ca-btn" disabled={!joinCode.trim()}>
            {t("room.joinGo")}
          </button>
        </form>
        {user && (
          <label className="ca-panel gm-switch-row">
            <span className="gm-ghost">🌑</span>
            <b>{t("room.shadow")}</b>
            <input
              type="checkbox"
              role="switch"
              className="gm-toggle"
              checked={shadow}
              onChange={async (e) => {
                try {
                  const r = await roomRequest<{ enabled: boolean }>(
                    "/preferences/shadow",
                    { enabled: e.target.checked },
                  );
                  setShadow(r.enabled);
                } catch {
                  setError(true);
                }
              }}
            />
          </label>
        )}
        {error && <p role="alert" className="cm-alert">{t("room.error")}</p>}
      </div>
    );
  return (
    <div
      className={`ca gm-page gm-phase-${room?.phase ?? "join"}${watching ? " gm-watching" : ""}${scoring ? " gm-scoring" : ""}`}
    >
      {error && (
        <p role="alert" className="eval-error">
          {t("room.error")}
        </p>
      )}
      <div className="gm-video-deck">
        {[0, 1].map((slot) => {
          const index = room
            ? Math.min(room.index, Math.max(0, room.playlist.length - 1))
            : 0;
          const assigned = slot === index % 2 ? index : index + 1;
          const clip = room?.playlist[assigned];
          const active = assigned === index;
          const source = clip && preloaded[clip.id];
          const visible = Boolean(active && watching);
          return (
            <figure
              key={slot}
              className={`gm-video${visible ? " is-visible" : ""}`}
              aria-hidden={!visible}
            >
              <EvaluationPlayer
                roomVideoRef={slot === 0 ? videoA : videoB}
                roomMedia={{
                  src: source || AUDIO_PRIMER,
                  poster: clip?.poster_url ?? "",
                  startsAt: source && active && mediaActive ? room!.starts : 0,
                  serverOffset: offset.current,
                  playToken: `${room?.game_id}:${assigned}`,
                }}
                onRoomReady={() => {
                  if (clip && source) {
                    readyDives.current.add(clip.id);
                    if (active) signal("ready");
                  }
                }}
                onEnded={() => {
                  if (
                    active &&
                    source &&
                    current.current &&
                    ["watching", "judge"].includes(current.current.phase)
                  ) {
                    setEndedDive(roundKey);
                    signal("ended");
                  }
                }}
                onSoundBlocked={() => setSoundBlocked(true)}
                onFailure={() => {
                  if (active && source) setError(true);
                }}
              />
              {clip && (
                <span className="gm-diver">
                  <MemberAvatar
                    member={{ display_name: clip.diver_name }}
                    size={26}
                  />
                  <b>{clip.diver_name}</b>
                </span>
              )}
              {visible && room?.phase === "loading" && (
                <span className="gm-loading" role="status">
                  {t("common.loading")}
                </span>
              )}
              {visible && soundBlocked && (
                <button
                  className="gm-sound"
                  onClick={() => {
                    const activeVideo =
                      slot === 0 ? videoA.current : videoB.current;
                    void unlockRoomAudio(
                      [videoA.current, videoB.current],
                      activeVideo ?? undefined,
                    ).then((results) => {
                      if (results[slot]) setSoundBlocked(false);
                    });
                  }}
                >
                  <Volume2 size={16} />
                  {t("room.soundOn")}
                </button>
              )}
            </figure>
          );
        })}
      </div>
      {!room && (
        <section className="gm-join ca-arrive">
          <div className="gm-join-posters">
            {invite?.posters.map((url, i) => (
              <img
                key={url}
                src={url}
                alt=""
                style={{ "--i": i } as CSSProperties}
              />
            ))}
          </div>
          <MemberAvatar
            member={{ display_name: invite?.host ?? code }}
            size={64}
          />
          <h1>{t("room.invite", { name: invite?.host ?? code })}</h1>
          <div className="gm-facts">
            <span className="ca-fact">
              {t("room.diveCount", { count: invite?.dives ?? 0 })}
            </span>
            <span className="ca-fact">
              {t("room." + (invite?.mode ?? "classic"))}
            </span>
            <span className="ca-fact">
              {t("room.playerCount", { count: invite?.count ?? 0 })}
            </span>
          </div>
          {!user && (
            <label className="cm-search gm-nick">
              <input
                aria-label={t("room.nickname")}
                placeholder={t("room.nickname")}
                value={nick}
                maxLength={40}
                onChange={(e) => setNick(e.target.value)}
              />
            </label>
          )}
          <button
            className="gm-cta"
            disabled={busy || !invite || (!user && !nick.trim())}
            onClick={() => void join()}
          >
            {t("room.join")}
          </button>
          <Link
            className="gm-link"
            to="/login"
            state={{ from: "/room/" + code }}
          >
            {t("room.account")}
          </Link>
        </section>
      )}
      {room?.phase === "lobby" && (
        <>
          <header className="cm-head">
            <h1>{t("room.room", { code })}</h1>
            <MobileShellActions />
          </header>
          <button className="gm-invite ca-pop" onClick={() => void copy()}>
            <Link2 size={18} />
            <span>
              {location.host}/room/{code}
            </span>
            <b>
              <Copy size={15} />
              {t(copied ? "room.copied" : "room.copy")}
            </b>
          </button>
          <section className="ca-panel ca-arrive">
            <div className="ca-panel-h">
              <h2>{t("room.jury")}</h2>
              <span>
                {t("room.playerCount", {
                  count: room.players.filter((p) => !p.emoji).length,
                })}{" "}
                ·{" "}
                {t("room.ghostCount", {
                  count: room.players.filter((p) => p.emoji).length,
                })}
              </span>
            </div>
            <ul className="gm-seats">
              {room.players.map((p) => (
                <li key={p.id} className={p.emoji ? "" : "is-human"}>
                  <Seat player={p} size={52} />
                  <b>{p.name}</b>
                  <small>
                    {t(
                      p.id === room.host
                        ? "room.host"
                        : p.emoji
                          ? "room.ghost"
                          : "room.player",
                    )}
                  </small>
                </li>
              ))}
            </ul>
          </section>
          <section className="cm-section">
            <h2 className="cm-h2">{t("room.mode")}</h2>
            <div className="ca-scroll">
              {["classic", "mole", "code"].map((m) => (
                <button
                  key={m}
                  className="ca-pill"
                  aria-pressed={room.mode === m}
                  disabled={!host || busy}
                  onClick={() => configure(m, room.source)}
                >
                  {t(m === "code" ? "room.guessCode" : "room." + m)}
                </button>
              ))}
            </div>
          </section>
          <section className="cm-section">
            <h2 className="cm-h2">
              {t("room.dives")}
              <span>{room.playlist.length}</span>
            </h2>
            <div className="ca-scroll">
              {["latest", "community", "code"].map((s) => (
                <button
                  key={s}
                  className="ca-pill"
                  aria-pressed={room.source === s}
                  disabled={!host || busy}
                  onClick={() => configure(room.mode, s)}
                >
                  {t("room." + s)}
                </button>
              ))}
            </div>
            {host && room.source === "code" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  configure(room.mode, "code");
                }}
              >
                <input
                  aria-label={t("room.code")}
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <button className="ca-btn">{t("room.apply")}</button>
              </form>
            )}
            <div className="gm-posters">
              {room.playlist.map((d) => (
                <figure key={d.id}>
                  <img src={d.poster_url} alt="" />
                  <figcaption>{d.dive_code}</figcaption>
                </figure>
              ))}
            </div>
            {!room.playlist.length && <p>{t("room.empty")}</p>}
          </section>
          {host && (
            <button
              className="gm-cta"
              disabled={busy || !room.playlist.length}
              onClick={() => {
                unlock();
                void action({ action: "start" });
              }}
            >
              <Play size={18} />
              {t("room.start")}
            </button>
          )}
        </>
      )}
      {room &&
        ["loading", "watching", "judge", "reveal"].includes(room.phase) &&
        dive && (
          <>
            {!watching && (
              <div className="gm-bar">
                <span className="ca-fact">
                  {room.index + 1} / {room.playlist.length}
                </span>
                <span className="gm-dots">
                  {room.playlist.map((d, i) => (
                    <i
                      key={d.id}
                      className={
                        i < room.index
                          ? "is-done"
                          : i === room.index
                            ? "is-now"
                            : ""
                      }
                    />
                  ))}
                </span>
                <span className="gm-timer">
                  <Timer size={14} />
                  {Math.max(0, Math.ceil(room.closes - clock))}
                </span>
              </div>
            )}
            {room.is_mole && <p className="gm-roast">{t("room.secret")}</p>}
            {scoring && (
              <>
                <ul className="gm-status">
                  {room.players.map((p) => (
                    <li
                      key={p.id}
                      className={room.voted.includes(p.id) ? "is-in" : ""}
                    >
                      <Seat player={p} size={34} />
                      {room.voted.includes(p.id) && <Check size={12} />}
                    </li>
                  ))}
                </ul>
                {room.mode === "code" ? (
                  <div className="gm-choices">
                    {dive.choices.map((c) => (
                      <button
                        key={c}
                        disabled={
                          busy ||
                          room.my_answer !== null ||
                          clock < room.starts ||
                          clock >= room.closes
                        }
                        aria-pressed={room.my_answer === c}
                        onClick={() =>
                          void action({ action: "answer", choice: c })
                        }
                      >
                        {c}
                      </button>
                    ))}
                  </div>
                ) : (
                  <>
                    <ScoreInput
                      score={room.my_score ?? score}
                      disabled={
                        busy ||
                        room.my_score !== null ||
                        clock < room.starts ||
                        clock >= room.closes
                      }
                      onScore={setScore}
                    />
                    <button
                      className="gm-cta"
                      disabled={
                        busy ||
                        score === null ||
                        room.my_score !== null ||
                        clock < room.starts ||
                        clock >= room.closes
                      }
                      onClick={() => void action({ action: "score", score })}
                    >
                      {t(
                        room.my_score !== null
                          ? "room.submitted"
                          : "room.submit",
                      )}
                    </button>
                  </>
                )}
              </>
            )}
            {room.phase === "reveal" && room.result && (
              <>
                {room.mode === "code" ? (
                  <>
                    <div className="gm-choices">
                      {dive.choices.map((c) => (
                        <button
                          key={c}
                          disabled
                          className={
                            room.result?.correct_code === c
                              ? "is-right"
                              : room.result?.answers?.[room.me] === c
                                ? "is-wrong"
                                : ""
                          }
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                    <p className="gm-roast">
                      +{room.result.gains[room.me] ?? 0} {t("room.points")}
                    </p>
                  </>
                ) : (
                  <>
                    <ul className="gm-reveal">
                      {room.players.map((p, i) => (
                        <li
                          key={p.id}
                          className={room.result!.cuts[p.id] ? "is-cut" : ""}
                        >
                          {room.result!.cuts[p.id] && (
                            <span className="gm-cut">
                              {t("room." + room.result!.cuts[p.id])}
                            </span>
                          )}
                          <ScoreCard
                            scoreHalfSteps={room.result!.scores[p.id] ?? null}
                            rotation={(i - 2) * 3}
                            staggerMs={i * 130}
                          />
                          <Seat player={p} size={30} />
                          <b>{p.name}</b>
                          {p.emoji && (
                            <q>
                              {p.id === "shadow" && room.result?.shadow_comment
                                ? room.result.shadow_comment
                                : t("room.line." + p.id)}
                            </q>
                          )}
                        </li>
                      ))}
                    </ul>
                    <section className="gm-verdict ca-arrive">
                      <div>
                        <small>{t("room.juryScore")}</small>
                        <b>{number(room.result.jury)}</b>
                      </div>
                      <div>
                        <small>{t("room.yourScore")}</small>
                        <b>{number(room.result.scores[room.me])}</b>
                      </div>
                      <div className="is-gain">
                        <small>{t("room.points")}</small>
                        <b>+{room.result.gains[room.me] ?? 0}</b>
                      </div>
                    </section>
                    <p className="gm-roast">{t("room.roast")}</p>
                  </>
                )}
                <button
                  className="gm-cta gm-next"
                  disabled={busy || room.skipped.includes(room.me)}
                  onClick={() => void action({ action: "next" })}
                >
                  {room.skipped.includes(room.me)
                    ? t("room.waiting")
                    : room.index + 1 >= room.playlist.length
                      ? t("room.toResults")
                      : t("room.next")}
                </button>
              </>
            )}
          </>
        )}
      {room?.phase === "mole" && (
        <>
          <header className="cm-head">
            <h1>{t("room.findMole")}</h1>
          </header>
          <ul className="gm-suspects">
            {room.players
              .filter((p) => p.id !== room.me)
              .map((p) => (
                <li key={p.id}>
                  <button
                    aria-pressed={suspect === p.id}
                    onClick={() => setSuspect(p.id)}
                  >
                    <Seat player={p} />
                    <b>{p.name}</b>
                  </button>
                </li>
              ))}
            <li>
              <button
                aria-pressed={suspect === null}
                onClick={() => setSuspect(null)}
              >
                {t("room.nobody")}
              </button>
            </li>
          </ul>
          <button
            className="gm-cta"
            disabled={busy || room.has_ballot}
            onClick={() => void action({ action: "vote", suspect })}
          >
            {t("room.vote")}
          </button>
        </>
      )}
      {room?.phase === "results" && (
        <>
          <header className="cm-head">
            <h1>{t("room.finished")}</h1>
          </header>
          {room.mode === "mole" && (
            <section className="gm-mole-out">
              <span>🕵️</span>
              <b>
                {t("room.moleWas", {
                  name:
                    room.players.find((p) => p.id === room.mole)?.name ??
                    t("room.nobody"),
                })}
              </b>
            </section>
          )}
          <section className="ca-panel">
            <ol className="cm-podium">
              {[...room.players]
                .sort((a, b) => b.points - a.points)
                .slice(0, 3)
                .map((p, i) => (
                  <li key={p.id} className={"cm-step is-" + (i + 1)}>
                    <span className="cm-step-who">
                      {i === 0 && <Crown size={20} />}
                      <Seat player={p} size={i === 0 ? 64 : 48} />
                      <b>{p.name}</b>
                      <span className="cm-step-value">{p.points}</span>
                    </span>
                    <span className="cm-step-block">{i + 1}</span>
                  </li>
                ))}
            </ol>
          </section>
          <ol className="gm-ranking" start={4}>
            {[...room.players]
              .sort((a, b) => b.points - a.points)
              .slice(3)
              .map((p) => (
                <li key={p.id}>
                  <Seat player={p} size={30} />
                  <b>{p.name}</b>
                  <span>{p.points}</span>
                </li>
              ))}
          </ol>
          <section className="gm-awards">
            <div className="ca-panel">
              <span>🎯</span>
              <b>{t("room.sharp")}</b>
              <small>
                {
                  [...room.players]
                    .filter((p) => !p.emoji)
                    .sort((a, b) => (b.accurate ?? 0) - (a.accurate ?? 0))[0]
                    ?.name
                }
              </small>
            </div>
            <div className="ca-panel">
              <span>🔥</span>
              <b>{t("room.harsh")}</b>
              <small>
                {
                  [...room.players]
                    .filter((p) => !p.emoji)
                    .sort((a, b) => (b.low ?? 0) - (a.low ?? 0))[0]?.name
                }
              </small>
            </div>
          </section>
          <div className="gm-row">
            <button
              className="ca-btn"
              disabled={busy}
              onClick={async () => {
                if (!user) {
                  navigate("/login");
                  return;
                }
                setBusy(true);
                try {
                  const next = await roomRequest("", {});
                  navigate("/room/" + next.code);
                } catch {
                  setError(true);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t("room.challenge")}
            </button>
            {host && (
              <button
                className="gm-cta"
                disabled={busy}
                onClick={() => void action({ action: "replay" })}
              >
                {t("room.replay")}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
