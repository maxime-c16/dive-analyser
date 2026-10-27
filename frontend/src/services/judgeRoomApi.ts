export type Player = {
  id: string;
  user_id?: number;
  avatar_url?: string | null;
  name: string;
  emoji?: string;
  points: number;
  accurate?: number;
  low?: number;
  streak?: number;
};
export type Dive = {
  id: number;
  diver_name: string;
  choices: string[];
  dive_code: string | null;
  height: string;
  dd: number | null;
  duration: number;
  poster_url: string;
  playback_url: string;
};
export type Room = {
  code: string;
  host: string;
  me: string;
  phase: string;
  mode: string;
  source: string;
  players: Player[];
  playlist: Dive[];
  index: number;
  game_id: string;
  ready: string[];
  scoring_starts: number;
  starts: number;
  closes: number;
  server_time: number;
  voted: string[];
  my_answer: string | null;
  has_ballot: boolean;
  skipped: string[];
  my_score: number | null;
  is_mole: boolean;
  mole: string | null;
  result: null | {
    correct_code?: string;
    answers?: Record<string, string>;
    shadow_comment?: string | null;
    scores: Record<string, number>;
    cuts: Record<string, string>;
    jury: number | null;
    target: number | null;
    gains: Record<string, number>;
  };
};
export async function roomRequest<T = Room>(
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api/v1/rooms" + path, {
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    method: body ? "POST" : "GET",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}
