"""Single-worker, server authoritative rooms. No bot score enters consensus."""

from dataclasses import dataclass, field
import hashlib
import random
import secrets
import time
from statistics import mean

GHOSTS = [
    ("mum", "La Maman", "🥰", 3),
    ("coach", "Le Coach", "🧊", -2),
    ("copy", "Le Copieur", "👻", 0),
    ("olympian", "L’Ex-Olympien", "🏅", 0),
]


def truth(stored, humans, exclude=None):
    values = [score for key, score in stored if key != exclude] + list(humans)
    return mean(values) if values else None


def points(score, target, streak=0):
    if target is None:
        return 0
    return round(
        20 * max(0, min(1, (6 - abs(score - target)) / 5)) * (1 + min(streak, 5) * 0.2)
    )


def seeded(code, round_number=0):
    return random.Random(hashlib.sha256(f"{code}:{round_number}".encode()).digest())


def ghost_scores(code, index, target, count, previous=None):
    rng = seeded(code, index)
    return [
        max(
            0,
            min(
                20,
                round(
                    (previous if key == "copy" and previous is not None else target)
                    + bias
                    + rng.gauss(0, 0.3 if key == "olympian" else 1)
                ),
            ),
        )
        for key, _, _, bias in GHOSTS[:count]
    ]


@dataclass
class Room:
    code: str
    host: str
    players: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    playlist: list = field(default_factory=list)
    mode: str = "classic"
    source: str = "community"
    phase: str = "lobby"
    index: int = 0
    starts: float = 0
    closes: float = 0
    votes: dict = field(default_factory=dict)
    ballots: dict = field(default_factory=dict)
    answer_times: dict = field(default_factory=dict)
    results: list = field(default_factory=list)
    ghosts: list = field(default_factory=list)
    persisted: bool = False
    mole: str | None = None
    touched: float = field(default_factory=time.time)
    game_id: str = field(default_factory=lambda: secrets.token_hex(16))

    def panel(self):
        return (
            list(self.players.values())
            + (
                self.ghosts
                or [dict(id=k, name=n, emoji=e, points=0) for k, n, e, _ in GHOSTS]
            )[: max(0, 5 - len(self.players))]
        )

    def start(self, now):
        self.phase = "judge"
        self.starts = now + 3
        self.closes = self.starts + self.playlist[self.index]["duration"] + 5
        self.votes = {}
        self.answer_times = {}

    def assign_mole(self):
        rng = seeded(self.code)
        self.mole = (
            rng.choice([p["id"] for p in self.panel()])
            if self.mode == "mole" and rng.random() < 0.5
            else None
        )

    def reveal(self, now):
        dive = self.playlist[self.index]
        if self.mode == "code":
            correct = dive["dive_code"]
            gains = {
                key: (
                    max(
                        10,
                        round(
                            30
                            - 20
                            * min(
                                1,
                                self.answer_times[key]
                                / max(1, self.closes - self.starts),
                            )
                        ),
                    )
                    if answer == correct
                    else 0
                )
                for key, answer in self.votes.items()
            }
            for key, gain in gains.items():
                self.players[key]["points"] += gain
                self.players[key]["accurate"] = self.players[key].get(
                    "accurate", 0
                ) + int(gain > 0)
            self.results.append(
                dict(
                    correct_code=correct,
                    answers=dict(self.votes),
                    gains=gains,
                    scores={},
                    cuts={},
                    jury=None,
                    target=None,
                    winner_score=None,
                )
            )
            self.phase = "reveal"
            self.closes = now + 9
            return
        target = truth(dive["stored"], self.votes.values())
        ghosts = dict(
            zip(
                [g[0] for g in GHOSTS],
                ghost_scores(
                    self.code,
                    self.index,
                    target if target is not None else 12,
                    4,
                    self.results[-1]["winner_score"] if self.results else None,
                ),
            )
        )
        scores = dict(self.votes)
        for i, judge in enumerate(self.panel()[len(self.players) :]):
            score = (
                dive.get("shadow_score")
                if judge["id"] == "shadow"
                else ghosts[judge["id"]]
            )
            if score is None:
                score = max(
                    0,
                    min(
                        20,
                        round(
                            (target if target is not None else 12)
                            + dive.get("shadow_offset", 0)
                            + seeded(self.code, self.index).gauss(0, 0.6)
                        ),
                    ),
                )
            if judge["id"] == "mum" and dive.get("host_owned"):
                score = min(20, score + 1)
            scores[judge["id"]] = (
                min(20, score + 4) if judge["id"] == self.mole else score
            )
        ordered = sorted(scores, key=lambda k: (scores[k], k))
        cuts = {ordered[0]: "low", ordered[-1]: "high"} if len(ordered) >= 3 else {}
        kept = [s for k, s in scores.items() if k not in cuts]
        gains = {}
        for key, score in self.votes.items():
            player = self.players[key]
            gain = points(score, target, player["streak"])
            player["streak"] = (
                player["streak"] + 1
                if target is not None and abs(score - target) <= 1
                else 0
            )
            player["accurate"] = player.get("accurate", 0) + int(
                target is not None and abs(score - target) <= 1
            )
            player["low"] = player.get("low", 0) + int(cuts.get(key) == "low")
            player["points"] += gain
            gains[key] = gain
        winner = max(self.votes, key=lambda k: gains[k], default=None)
        self.results.append(
            dict(
                scores=scores,
                cuts=cuts,
                target=target,
                jury=mean(kept) if kept else None,
                gains=gains,
                winner_score=self.votes.get(winner),
                shadow_comment=dive.get("shadow_comment"),
            )
        )
        self.phase = "reveal"
        self.closes = now + 9

    def advance(self, now):
        if self.phase == "judge" and now >= self.closes:
            self.reveal(now)
        elif self.phase == "reveal" and now >= self.closes:
            self.index += 1
            if self.index < len(self.playlist):
                self.start(now)
            else:
                self.phase = "mole" if self.mode == "mole" else "results"
                self.closes = now + 20
        elif self.phase == "mole" and (
            now >= self.closes or len(self.ballots) == len(self.players)
        ):
            for key, player in self.players.items():
                player["points"] += (
                    30 if self.ballots.get(key, "missing") == self.mole else 0
                )
                if key == self.mole:
                    player["points"] += 15 * sum(
                        v != key for k, v in self.ballots.items() if k != key
                    )
            self.phase = "results"

    def snapshot(self, key, now):
        self.touched = now
        dive = (
            self.playlist[min(self.index, len(self.playlist) - 1)]
            if self.playlist
            else None
        )
        return dict(
            code=self.code,
            host=self.host,
            me=key,
            phase=self.phase,
            mode=self.mode,
            source=self.source,
            players=self.panel(),
            playlist=[
                {
                    k: (None if self.mode == "code" and k in ("dive_code", "dd") else v)
                    for k, v in d.items()
                    if k
                    not in (
                        "stored",
                        "shadow_score",
                        "shadow_offset",
                        "shadow_comment",
                        "host_owned",
                    )
                }
                for d in self.playlist
            ],
            index=self.index,
            starts=self.starts,
            closes=self.closes,
            server_time=now,
            voted=list(self.votes)
            + [
                p["id"]
                for i, p in enumerate(self.panel()[len(self.players) :])
                if now > self.starts + 2 + i
            ],
            my_score=self.votes.get(key) if self.mode != "code" else None,
            my_answer=self.votes.get(key) if self.mode == "code" else None,
            has_ballot=key in self.ballots,
            is_mole=key == self.mole and self.phase not in ("lobby", "results"),
            result=self.results[-1] if self.results and self.phase != "judge" else None,
            mole=self.mole if self.phase == "results" else None,
        )


rooms = {}
