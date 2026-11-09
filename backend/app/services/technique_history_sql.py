"""PostgreSQL attribution over the full eligible scope; no Python history scan.

Bounded details use LIMIT 51. Aggregates deliberately scan all eligible rows.
All parameters are bound and authorization is performed before this SQL runs.
"""
from app.services.performance_scoring import ATHLETE_SCORE_10


def _rating(column):
    return 'CASE ' + column + ' ' + ' '.join(f"WHEN '{key}' THEN {value}" for key,value in ATHLETE_SCORE_10.items()) + ' END'


RATING = f"CASE WHEN d.performance IS NULL THEN NULL WHEN d.phase1_performance IS NOT NULL AND d.phase2_performance IS NOT NULL THEN 0.45 * ({_rating('d.phase1_performance')}) + 0.55 * ({_rating('d.phase2_performance')}) ELSE ({_rating('d.performance')}) END"

RESOLVED = """
WITH eligible AS (
 SELECT d.*, """ + RATING + """ rating,
 coalesce((SELECT string_agg(m.modifier_code, ',' ORDER BY m.modifier_code)
 FROM dive_modifiers m WHERE m.dive_id=d.id),'') modifiers
 FROM dives d WHERE d.diver_id=:diver AND d.dive_code=:code
 AND d.platform_type=:apparatus AND d.height=:height
 AND coalesce(d.position,'')=:position AND coalesce(d.is_sync,false)=:sync
), resolved AS (
 SELECT d.*, (d.created_at>e.created_at AND d.history_occurred_at<e.created_at) late_import, e.id episode_id, e.scope intended_scope, e.technique_id intended_id, a.episode_id recorded_episode_id, coalesce(recorded_e.deleted,false) recorded_episode_deleted,
 CASE WHEN e.gap OR d.history_occurred_at < e.uncertain_until THEN true ELSE false END uncertain,
 coalesce(a.state,s.state,CASE WHEN e.id IS NULL THEN 'unrecorded'
 WHEN e.gap OR d.history_occurred_at < e.uncertain_until THEN 'unknown' ELSE 'technique' END) state,
 CASE WHEN a.id IS NOT NULL THEN a.technique_id WHEN s.id IS NOT NULL THEN NULL
 WHEN e.gap OR d.history_occurred_at < e.uncertain_until THEN NULL ELSE e.technique_id END use_id,
 CASE WHEN a.id IS NOT NULL THEN 'recorded' WHEN s.id IS NOT NULL THEN 'session'
 WHEN e.id IS NOT NULL THEN 'inferred' ELSE 'unrecorded' END source
 FROM eligible d
 LEFT JOIN LATERAL (
 SELECT e.* FROM technique_episodes e WHERE e.track_id=:track AND NOT e.deleted
 AND e.apparatus=d.platform_type AND e.height=d.height
 AND (e.scope=d.dive_code OR e.scope=CASE WHEN left(d.dive_code,1)='5' THEN left(d.dive_code,2)
 WHEN left(d.dive_code,1) IN ('1','2','3','4') THEN left(d.dive_code,1) ELSE NULL END)
 AND (e.position IS NULL OR e.position=d.position) AND (e.sync IS NULL OR e.sync=d.is_sync)
 AND (e.start_at,e.start_id)<=(d.history_occurred_at,d.id)
 AND (e.end_at IS NULL OR (d.history_occurred_at,d.id)<(e.end_at,e.end_id))
 ORDER BY (e.scope=d.dive_code) DESC,
 ((e.position IS NOT NULL)::int+(e.sync IS NOT NULL)::int) DESC LIMIT 1
 ) e ON true
 LEFT JOIN technique_assignments a ON a.track_id=:track AND a.dive_id=d.id
 AND a.diver_id=d.diver_id AND a.code=d.dive_code AND a.apparatus=d.platform_type
 AND a.height=d.height AND a.position IS NOT DISTINCT FROM d.position AND a.sync=d.is_sync
 LEFT JOIN technique_episodes recorded_e ON recorded_e.id=a.episode_id AND recorded_e.track_id=:track
 LEFT JOIN technique_session_states s ON s.track_id=:track AND s.session_id=d.session_id
 AND s.code=d.dive_code AND s.apparatus=d.platform_type AND s.height=d.height
 AND s.position=coalesce(d.position,'') AND s.sync=coalesce(d.is_sync,false)
)
"""


def comparison_sql(recorded=False, session_weight=False, same_identity=False):
    side = ('CASE WHEN episode_id=:left THEN 0 ELSE 1 END' if not recorded or same_identity
            else 'CASE WHEN use_id=:left_identity THEN 0 ELSE 1 END')
    membership = ('AND source=\'recorded\' AND state=\'technique\' AND use_id IN (:left_identity,:right_identity)' if recorded else '')
    return RESOLVED + f""", members AS (
 SELECT *, {side} side FROM resolved WHERE episode_id IN (:left,:right) AND NOT uncertain
 {membership} AND modifiers=:modifiers
 ), coverage AS (
 SELECT side,count(*) eligible,count(rating) scored,count(DISTINCT session_id) sessions,
 count(*) FILTER (WHERE source='recorded' AND use_id=intended_id) recorded_matching,
 count(*) FILTER (WHERE source='recorded' AND state='technique' AND use_id<>intended_id) recorded_conflicting,
 count(*) FILTER (WHERE source='inferred' AND state='technique') inferred_only,
 count(*) FILTER (WHERE state IN ('mixed','unknown','unrecorded')) mixed_unknown,count(*) FILTER(WHERE late_import) late_imports
 FROM members GROUP BY side
 ), observations AS (
 {"SELECT side,percentile_cont(0.5) WITHIN GROUP (ORDER BY rating) value FROM members WHERE rating IS NOT NULL GROUP BY side,session_id" if session_weight else "SELECT side,rating value FROM members WHERE rating IS NOT NULL"}
 ), stats AS (
 SELECT side,count(*) observations,percentile_cont(0.5) WITHIN GROUP (ORDER BY value) median,
 CASE WHEN count(*)>=2 THEN percentile_cont(0.25) WITHIN GROUP (ORDER BY value) END q1,
 CASE WHEN count(*)>=2 THEN percentile_cont(0.75) WITHIN GROUP (ORDER BY value) END q3
 FROM observations GROUP BY side
 ) SELECT * FROM coverage LEFT JOIN stats USING(side) ORDER BY side
 """
