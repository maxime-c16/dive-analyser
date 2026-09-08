#!/usr/bin/env python3
import os, sys, subprocess

BASE = os.path.expanduser('~/dive-analyser')
LP = f'{BASE}/experiments/landmark_pilot'
SCIENCE = f'{BASE}/docs/science'
VE = f'{LP}/venv_c/bin/python3'

def run(label, script):
    print(f'\n{"="*60}')
    print(f'RUNNING: {label}')
    print('='*60)
    e = dict(os.environ)
    e['CUDA_VISIBLE_DEVICES'] = ''
    r = subprocess.run([VE, script], cwd=LP, env=e)
    if r.returncode != 0:
        print(f'ERROR: {label} exited with code {r.returncode}')
        sys.exit(r.returncode)
    print(f'OK: {label}')

abl_path = f'{SCIENCE}/reranker_v1/D5_VS_R1_ABLATION_V1.json'
traj_path = f'{SCIENCE}/PARIS_FULL_TRAJECTORY_V1.json'
assert os.path.exists(abl_path), f'Missing: {abl_path}'
assert os.path.exists(traj_path), f'Missing: {traj_path}'

run('Phase C — Perception Freeze', f'{LP}/phase_c_freeze.py')
run('Phase F/G — EL Real Test', f'{LP}/phase_fg_event_logic.py')
run('Phase K — Multi-dive Dev Eval', f'{LP}/phase_ijk_multidive.py')
run('Phase P — Test Suite', f'{LP}/test_perception_v1_closure.py')
run('Phase Q/R — Report and Manifest', f'{LP}/report_writer.py')
run('PROJECT_STATE update', f'{LP}/update_project_state.py')

print()
print('='*60)
print('CASCADE COMPLETE. All phases C through R done.')
print('Next: bash commit_phase_s.sh for Phase S (git commit + Mac sync).')
