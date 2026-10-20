"""Plan/apply bounded runtime slots on the media Mac; never prints config secrets.

Run with the deployed worker's Python and PYTHONPATH=code. Restart only through
ci/ship.sh mac --ref <deployed-sha> --force (dry-run first). Config backup is local,
mode 0600, and is deliberately not part of the repository or tool output.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone

import yaml
from src.config import Config

parser = argparse.ArgumentParser()
parser.add_argument('--slots', type=int, choices=[1, 2], required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
config = Path('/Users/Shared/services/data/diveanalyzer/state/config.yaml')
original = config.read_bytes()
data = yaml.safe_load(original)
validated = Config.from_file(str(config))
free = shutil.disk_usage(config.parent).free
# A canary adds headroom above the existing policy, never weakens that policy.
reserve = max(validated.media.source_vault.internal_stop_free_bytes, 8 * 1024**3)
peak = 2 * 1_250_000_000 if args.slots == 2 else 0
allowed = args.slots == 1 or free - peak >= reserve
result = {'dry_run': not args.apply, 'previous_slots': validated.media.max_jobs,
          'requested_slots': args.slots, 'free_bytes': free,
          'reserve_bytes': reserve, 'two_job_peak_budget_bytes': peak, 'allowed': allowed}
if args.apply and not allowed:
    print(json.dumps(result))
    raise SystemExit(2)
if args.apply and validated.media.max_jobs != args.slots:
    data.setdefault('media', {})['max_jobs'] = args.slots
    descriptor, temporary = tempfile.mkstemp(prefix='.slots-', dir=config.parent)
    try:
        with os.fdopen(descriptor, 'w') as target:
            yaml.safe_dump(data, target, sort_keys=False)
        Config.from_file(temporary)  # validate every field before replacing
        # Refuse to overwrite a concurrent configuration edit.
        if config.read_bytes() != original:
            raise RuntimeError('Configuration changed during planning')
        backup = config.with_name('config.pre-slots-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.yaml')
        with backup.open('xb') as target:
            os.chmod(backup, 0o600)
            target.write(original)
        os.replace(temporary, config)
        result['changed'] = True
    finally:
        Path(temporary).unlink(missing_ok=True)
print(json.dumps(result))
