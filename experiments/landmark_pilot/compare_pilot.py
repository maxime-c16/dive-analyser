#!/usr/bin/env python3
"""Phase O: Pairwise temporal alignment prototype.

Computes landmark-normalized alignment between pairs of APPLICABLE dives.
For each pair:
  - Normalize apex: (apex_frame - takeoff_frame) / (water_contact_frame - takeoff_frame)
  - apex_normalized_delta, flight_duration_delta_s, ascent_duration_delta_s
  - landmark_similarity_score = max(0, 1 - apex_delta)

Stores results in analysis_comparisons + analysis_comparison_metrics.
"""
import sys, json, hashlib, itertools
from datetime import datetime

sys.path.insert(0, '/home/mcauchy/dive-analyser/experiments/landmark_pilot')
import annotate

METHOD_KEY = 'temporal_landmark_pairwise_v1'
METHOD_VERSION = '1.0.0'


def get_applicable_dives():
    conn = annotate._connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            ar.dive_id, ar.id AS run_id,
            t_lm.frame_index, t_lm.timestamp_seconds,
            a_lm.frame_index, a_lm.timestamp_seconds,
            w_lm.frame_index, w_lm.timestamp_seconds,
            t_lm.confidence, a_lm.confidence, w_lm.confidence
        FROM analysis_runs ar
        JOIN analysis_landmarks t_lm ON t_lm.run_id = ar.id
            AND t_lm.landmark_key = 'takeoff' AND t_lm.applicability = 'APPLICABLE'
        JOIN analysis_landmarks a_lm ON a_lm.run_id = ar.id
            AND a_lm.landmark_key = 'apex' AND a_lm.applicability = 'APPLICABLE'
        JOIN analysis_landmarks w_lm ON w_lm.run_id = ar.id
            AND w_lm.landmark_key = 'water_contact' AND w_lm.applicability = 'APPLICABLE'
        WHERE ar.pipeline_key = 'temporal_landmarks_baseline_a_v1'
          AND ar.status NOT IN ('failed', 'cancelled', 'superseded')
          AND t_lm.frame_index < a_lm.frame_index
          AND a_lm.frame_index < w_lm.frame_index
        ORDER BY ar.dive_id
    """)
    rows = cur.fetchall()
    conn.close()

    dives = []
    for r in rows:
        (dive_id, run_id,
         t_fi, t_ts, a_fi, a_ts, w_fi, w_ts,
         t_conf, a_conf, w_conf) = r
        flight_dur = float(w_ts) - float(t_ts)
        ascent_dur = float(a_ts) - float(t_ts)
        apex_norm = (float(a_fi) - float(t_fi)) / (float(w_fi) - float(t_fi))
        dives.append({
            'dive_id': dive_id, 'run_id': run_id,
            't_fi': t_fi, 'a_fi': a_fi, 'w_fi': w_fi,
            't_ts': float(t_ts), 'a_ts': float(a_ts), 'w_ts': float(w_ts),
            'flight_dur': flight_dur, 'ascent_dur': ascent_dur,
            'apex_norm': apex_norm,
        })
    return dives


def _fingerprint(target_run_id, ref_run_id, method_key, method_version, params):
    payload = json.dumps({
        'target_run_id': target_run_id,
        'reference_run_id': ref_run_id,
        'method_key': method_key,
        'method_version': method_version,
        'parameters': params,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def compare_pair(d_a, d_b):
    apex_delta = abs(d_a['apex_norm'] - d_b['apex_norm'])
    flight_delta = abs(d_a['flight_dur'] - d_b['flight_dur'])
    ascent_delta = abs(d_a['ascent_dur'] - d_b['ascent_dur'])
    similarity = max(0.0, 1.0 - apex_delta)
    return {
        'apex_norm_target': d_a['apex_norm'],
        'apex_norm_reference': d_b['apex_norm'],
        'apex_delta': apex_delta,
        'flight_delta_s': flight_delta,
        'ascent_delta_s': ascent_delta,
        'similarity': similarity,
    }


def store_comparison(conn, target_run_id, ref_run_id, metrics, params=None):
    if params is None:
        params = {}
    fp = _fingerprint(target_run_id, ref_run_id, METHOD_KEY, METHOD_VERSION, params)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO analysis_comparisons
            (target_run_id, reference_run_id, method_key, method_version,
             canonical_parameters, spec_fingerprint, status, completed_at)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, 'succeeded', CURRENT_TIMESTAMP)
        ON CONFLICT (spec_fingerprint) WHERE status IN ('pending','running','succeeded') DO UPDATE
          SET status = 'succeeded', completed_at = CURRENT_TIMESTAMP
        RETURNING id
    """, (target_run_id, ref_run_id, METHOD_KEY, METHOD_VERSION,
          json.dumps(params), fp))
    comp_id = cur.fetchone()[0]

    for key, val in [
        ('apex_normalized_delta',     metrics['apex_delta']),
        ('flight_duration_delta_s',   metrics['flight_delta_s']),
        ('ascent_duration_delta_s',   metrics['ascent_delta_s']),
        ('landmark_similarity_score', metrics['similarity']),
    ]:
        cur.execute("""
            INSERT INTO analysis_comparison_metrics
                (comparison_id, metric_key, value_numeric, metric_version)
            VALUES (%s, %s, %s, 'v1')
            ON CONFLICT (comparison_id, metric_key) DO UPDATE
              SET value_numeric = EXCLUDED.value_numeric
        """, (comp_id, key, val))

    return comp_id


def main():
    dives = get_applicable_dives()
    print(f'Found {len(dives)} APPLICABLE dives for pairwise comparison')

    pairs = list(itertools.combinations(dives, 2))
    print(f'Computing {len(pairs)} pairs...')

    conn = annotate._connect()
    results = []
    for d_a, d_b in pairs:
        m = compare_pair(d_a, d_b)
        comp_id = store_comparison(conn, d_a['run_id'], d_b['run_id'], m)
        results.append({
            'comp_id': comp_id,
            'dive_a': d_a['dive_id'], 'dive_b': d_b['dive_id'],
            **m,
        })
    conn.commit()
    conn.close()

    results.sort(key=lambda r: -r['similarity'])
    print()
    print(f"{'Pair':>13}  {'apex_T':>6}  {'apex_R':>6}  {'delta':>6}  {'simil':>6}  {'flight_ds':>10}")
    print('-' * 58)
    for r in results[:20]:
        pair = f"{r['dive_a']}/{r['dive_b']}"
        print(f"{pair:>13}  {r['apex_norm_target']:6.3f}  {r['apex_norm_reference']:6.3f}"
              f"  {r['apex_delta']:6.3f}  {r['similarity']:6.3f}  {r['flight_delta_s']:10.3f}")
    if len(pairs) > 20:
        print(f'  ...{len(pairs)-20} more')

    print(f'\nStored {len(results)} comparison records in analysis_comparisons.')
    best = results[0]
    print(f"\nMost similar: dive {best['dive_a']} vs {best['dive_b']}"
          f"  apex_delta={best['apex_delta']:.4f}  flight_delta={best['flight_delta_s']:.3f}s"
          f"  similarity={best['similarity']:.3f}")
    worst = results[-1]
    print(f"Most different: dive {worst['dive_a']} vs {worst['dive_b']}"
          f"  apex_delta={worst['apex_delta']:.4f}  flight_delta={worst['flight_delta_s']:.3f}s")


if __name__ == '__main__':
    main()
