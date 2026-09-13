\set ON_ERROR_STOP on
BEGIN;

DO $$
DECLARE
  n_set int; n_phantom int; v_name text; v_primary bool;
  n_upd int; n_back int; n_rest int; n_diff int;
BEGIN
  -- ==== Preconditions ====
  SELECT count(*) INTO n_set FROM dives WHERE id IN (217,1919,1957,2169,2388,2713);
  IF n_set <> 6 THEN RAISE EXCEPTION 'PRECONDITION_FAIL: expected 6 target rows, found %', n_set; END IF;

  SELECT count(*) INTO n_phantom FROM dives WHERE diver_id = 19;
  IF n_phantom <> 6 THEN RAISE EXCEPTION 'PRECONDITION_FAIL: diver 19 population is % (expected exactly 6)', n_phantom; END IF;

  IF EXISTS (SELECT 1 FROM dives WHERE id IN (217,1919,1957,2169,2388,2713) AND diver_id <> 19)
  THEN RAISE EXCEPTION 'PRECONDITION_FAIL: a target row no longer has diver_id=19'; END IF;

  SELECT display_name, is_primary_user INTO v_name, v_primary FROM divers WHERE id = 1;
  IF NOT FOUND THEN RAISE EXCEPTION 'PRECONDITION_FAIL: diver 1 missing'; END IF;
  IF v_name <> 'Maxime' OR v_primary IS NOT TRUE
  THEN RAISE EXCEPTION 'PRECONDITION_FAIL: diver 1 is (%,%), expected (Maxime,true)', v_name, v_primary; END IF;

  -- ==== Snapshot: prove no field other than diver_id changes ====
  CREATE TEMP TABLE snap_19 AS
  SELECT d.id, (to_jsonb(d) - 'diver_id') AS payload
  FROM dives d WHERE d.id IN (217,1919,1957,2169,2388,2713);

  -- ==== Mutation (single statement, exact scope) ====
  EXECUTE 'UPDATE dives SET diver_id = 1 WHERE id IN (217,1919,1957,2169,2388,2713) AND diver_id = 19';
  GET DIAGNOSTICS n_upd = ROW_COUNT;
  IF n_upd <> 6 THEN RAISE EXCEPTION 'INVARIANT_FAIL: update rowcount % (expected 6)', n_upd; END IF;

  -- ==== In-transaction invariants (pre-COMMIT) ====
  SELECT count(*) INTO n_back FROM dives WHERE id IN (217,1919,1957,2169,2388,2713) AND diver_id = 1;
  IF n_back <> 6 THEN RAISE EXCEPTION 'INVARIANT_FAIL: only % target rows now diver_id=1', n_back; END IF;

  SELECT count(*) INTO n_rest FROM dives WHERE diver_id = 19;
  IF n_rest <> 0 THEN RAISE EXCEPTION 'INVARIANT_FAIL: % rows still reference phantom diver 19', n_rest; END IF;

  SELECT count(*) INTO n_diff
  FROM snap_19 s JOIN dives d ON d.id = s.id
  WHERE (to_jsonb(d) - 'diver_id') IS DISTINCT FROM s.payload;
  IF n_diff <> 0 THEN RAISE EXCEPTION 'INVARIANT_FAIL: % rows changed fields other than diver_id', n_diff; END IF;
END $$;

COMMIT;
