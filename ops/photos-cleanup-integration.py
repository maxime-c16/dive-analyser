#!/usr/bin/env python3
"""Exercise the real cleanup queue/native UI on ONLY a recorded synthetic asset.

Server eligibility and upload receipts are synthetic here: no B2 write, live
server mutation or historical cleanup. Backend proof/identity tests run separately.
Run from a one-shot Aqua LaunchAgent with an isolated copy of mac-agent/src.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--state-dir', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--video', required=True)
    parser.add_argument('--library-path', required=True)
    parser.add_argument('--refuse-after-unlock', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, args.runtime)
    from src.photos_cleanup import PhotosCleanup, PhotoKitLibrary, atomic_json
    from src.config import DualWriteConfig
    manifest = Path(args.manifest)
    asset = json.loads(manifest.read_text())
    if asset.get('synthetic_canary') is not True or asset.get('removed'):
        raise RuntimeError('only_a_fresh_synthetic_manifest_is_allowed')
    local = asset['photos_uuid']
    if PhotoKitLibrary().version(local) != asset['version']:
        raise RuntimeError('synthetic_asset_changed')
    root = Path(args.state_dir)
    video = str(uuid.uuid4())
    config = NS(dual_write=DualWriteConfig(enabled=True, continuous_new_ingest=True,
        photos_cleanup_mode='delete', photos_cleanup_keeper_diver_id=1, photos_cleanup_automated=True),
        object_store=NS(state_dir=str(root), environment='prod'), agent=NS(id='synthetic-integration'),
        photos=NS(library_path=args.library_path))
    sha = hashlib.sha256(Path(args.video).read_bytes()).hexdigest()
    blob = {'sha256':sha, 'byte_size':Path(args.video).stat().st_size,
            'object_key':'synthetic-not-uploaded', 'bucket':'synthetic-not-uploaded'}
    checks = []
    def check(request):
        assert request['photos_uuid'] == local and request['video_uuid'] == video
        checks.append(1)
        return dict(eligible=not (args.refuse_after_unlock and len(checks)>1), video_uuid=video, photos_uuid=local, blob_sha256=sha)
    worker = PhotosCleanup(config, check=check)
    snapshot = worker.snapshot(local)
    guard = dict(photos_uuid=local, version=asset['version'], snapshot=snapshot, source_sha256=sha)
    atomic_json(root / f'{video}.stage.json', {'cleanup_export_guard':guard})
    atomic_json(root / f'{video}.json', {'video_uuid':video, 'state':'CACHE_CLEANED', 'remote':{'verified':True},
        'db_commit':{'committed':True}, 'media':blob, 'caption':{'sha256':snapshot['caption_sha256']}})
    atomic_json(root / f'{video}.commit_receipt.json', {'input':{'payload':{
        'video_uuid':video, 'blob':blob, 'caption':{'sha256':snapshot['caption_sha256']},
        'rendition_semantics':'photos_edited_rendition'}, 'extra':{'environment':'prod',
        'photos_edit_fingerprint':snapshot['edit_fingerprint'], 'source_provenance':{'photos_asset_uuid':local}}},
        'result':{'blob_sha256':sha}})
    worker.enqueue(video, local)
    worker.process_pending()
    receipt = worker.queue.parent / 'completed' / f'{video}.json'
    if not receipt.exists():
        pending = json.loads((worker.queue/f'{video}.json').read_text())
        from src.photos_automation import session_state
        kept = PhotoKitLibrary().version(local) == asset['version']
        passed = (args.refuse_after_unlock and pending['outcome']=='deferred' and kept
                  and len(checks)==2 and session_state()==(True,0)
                  and pending.get('reason')=='cleanup_automation_deferred:revalidation')
        result = {'passed':passed, 'pending':pending['outcome'], 'kept':kept,
                  'refusal_after_unlock':args.refuse_after_unlock, 'eligibility_checks':len(checks)}
        atomic_json(root/'integration-refusal-result.json',result)
        print(json.dumps(result),flush=True)
        raise SystemExit(0 if passed else 1)
    outcome = json.loads(receipt.read_text())['outcome']
    asset['removed'] = PhotoKitLibrary().version(local) is None
    atomic_json(manifest, asset)
    result = {'passed':outcome=='removed' and asset['removed'], 'outcome':outcome,
              'eligibility_checks':len(checks), 'synthetic_only':True}
    atomic_json(root/'integration-result.json', result)
    print(json.dumps(result),flush=True)
    if not result['passed']:raise SystemExit(1)


if __name__ == '__main__':
    main()
