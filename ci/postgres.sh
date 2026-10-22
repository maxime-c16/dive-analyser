#!/bin/bash
# Never uses the application DB: calendar fixtures require calendar_test_*.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
: "${CALENDAR_TEST_DATABASE_URL:?Set a disposable calendar_test_* PostgreSQL URL}"
export AUTO_IMPORT=false DB_TEST=0
ROOT="$(ci_repo_root)"
export PYTHONPATH="$ROOT:$ROOT/backend"
mkdir -p "$(ci_cache_dir)/logs"
ci_backend_python
# Check URL before running any fixture that resets the disposable schema.
"$CI_BACKEND_PYTHON" -c 'import os; from sqlalchemy.engine import make_url; u=make_url(os.environ["CALENDAR_TEST_DATABASE_URL"]); assert u.get_backend_name()=="postgresql" and (u.database or "").startswith("calendar_test_"), "Disposable calendar_test_* PostgreSQL database required"'
cd "$ROOT/backend"
ci_run postgres-pytest "$CI_BACKEND_PYTHON" -m pytest \
    tests/test_postgres_activity.py \
    tests/test_postgres_media_cutover.py \
    tests/test_postgres_media_derivatives_d1.py \
    tests/test_postgres_derivative_publisher_d3b1.py \
    tests/test_postgres_derivative_read_d5.py \
    tests/test_postgres_playback_network_transaction.py \
    tests/test_postgres_media_job_fencing_d2.py \
    tests/test_postgres_web_package_fenced_slots_d3b2.py \
    tests/test_postgres_automatic_packages.py \
    tests/test_postgres_canary_budget_d3b2.py \
    tests/test_postgres_canary_admit_lock_d3b2.py \
    tests/test_calendar_domain.py::test_postgres_migration_matches_models \
    tests/test_calendar_domain.py::test_database_constraints \
    tests/test_calendar_domain.py::test_concurrent_manager_demotions_cannot_orphan_club \
    tests/test_calendar_task03.py::test_concurrent_retries_create_one_event \
    tests/test_calendar_task04.py::test_concurrent_applies_of_one_preview_change_once \
    tests/test_calendar_task05.py::test_two_workers_deliver_each_key_once \
    --junitxml="$(ci_cache_dir)/logs/postgres-junit.xml" \
    --strict-markers --asyncio-mode=auto -q --tb=short
