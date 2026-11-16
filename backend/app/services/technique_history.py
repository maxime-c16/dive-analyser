"""Pure attribution rules shared by history queries and mutation previews.

Callers must supply ownership-filtered records. This module never reads dives or
caption modifiers and never computes ratings from a paginated detail response.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

FAMILIES = frozenset({'1', '2', '3', '4', '51', '52', '53', '54'})
State = Literal['technique', 'mixed', 'unknown', 'unrecorded']


@dataclass(frozen=True, order=True)
class OrderKey:
    occurred_at: datetime
    attempt_id: int


@dataclass(frozen=True)
class Context:
    diver_id: int
    track_id: int
    code: str
    apparatus: str
    height: str
    position: str | None
    sync: bool


@dataclass(frozen=True)
class Episode:
    id: int
    context: Context
    scope: str
    start: OrderKey
    technique_id: int | None
    end: OrderKey | None = None
    uncertain_until: OrderKey | None = None
    gap: bool = False
    constrain_position: bool = False
    constrain_sync: bool = False


@dataclass(frozen=True)
class Attribution:
    state: State
    technique_id: int | None = None
    episode_id: int | None = None
    source: str = 'unrecorded'


def family(code: str) -> str | None:
    if code.startswith('5'):
        return code[:2] if code[:2] in FAMILIES else None
    return code[:1] if code[:1] in FAMILIES else None


def specificity(episode: Episode, context: Context) -> tuple[int, int] | None:
    ec = episode.context
    if (ec.diver_id, ec.track_id, ec.apparatus, ec.height) != (
        context.diver_id, context.track_id, context.apparatus, context.height
    ):
        return None
    exact = episode.scope == context.code
    if not exact and (episode.scope not in FAMILIES or episode.scope != family(context.code)):
        return None
    if episode.constrain_position and ec.position != context.position:
        return None
    if episode.constrain_sync and ec.sync != context.sync:
        return None
    return int(exact), int(episode.constrain_position) + int(episode.constrain_sync)


def resolve_context(context: Context, key: OrderKey, episodes: list[Episode]) -> Attribution:
    """Resolve one bounded preview; database readers implement the same ranking.

    Ambiguity fails closed. Unknown ranges and gaps block inherited context.
    Explicit ends permit family fallback. An episode's next boundary must have
    been supplied as its effective end by the query/preview producer.
    """
    candidates = [(specificity(e, context), e) for e in episodes
                  if e.start <= key and (e.end is None or key < e.end)]
    candidates = [(rank, e) for rank, e in candidates if rank is not None]
    if not candidates:
        return Attribution('unrecorded')
    rank = max(r for r, _ in candidates)
    winners = [e for r, e in candidates if r == rank]
    if len(winners) != 1:
        raise ValueError('Ambiguous equally specific episodes')
    e = winners[0]
    if e.gap or (e.uncertain_until is not None and key < e.uncertain_until):
        return Attribution('unknown', episode_id=e.id, source='gap' if e.gap else 'approximate')
    return Attribution('technique', e.technique_id, e.id, 'inferred')


def resolve_use(inferred: Attribution, explicit: Attribution | None = None,
                session: Attribution | None = None) -> Attribution:
    if explicit is not None:
        return explicit
    if session is not None:
        if session.state not in ('mixed', 'unknown'):
            raise ValueError('Session flags must be mixed or unknown')
        return session
    return inferred


def validate_pair(left: Context, right: Context) -> None:
    if left != right:
        raise ValueError('Comparison requires an identical exact context and track')


def recorded_side(key: OrderKey, technique_id: int | None, left: Episode,
                  right: Episode) -> int | None:
    """Union of resolved intervals, never the enclosing continuous date window."""
    validate_pair(left.context, right.context)
    if left.technique_id == right.technique_id:
        raise ValueError('Repeated identity requires recorded-by-episode comparison')
    in_window = any(e.start <= key and (e.end is None or key < e.end)
                    and (e.uncertain_until is None or e.uncertain_until <= key)
                    and not e.gap for e in (left, right))
    if not in_window or technique_id is None:
        return None
    if technique_id == left.technique_id:
        return 0
    if technique_id == right.technique_id:
        return 1
    return None
