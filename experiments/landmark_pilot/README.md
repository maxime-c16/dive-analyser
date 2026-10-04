# Landmark Pilot Experiment Environment

**Status:** DEVELOPMENT ONLY — not for production use.

## Setup

```bash
cd ~/dive-analyser/experiments/landmark_pilot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Environment Identity

- Python: 3.11 (system)
- OpenCV: 4.10.0.84 (headless)
- NumPy: 2.4.6
- SciPy: 1.17.1
- Host: deb-serv (Debian 12)

## Scripts

-  — Motion energy + vertical centroid landmark proposer
-  — Run all 20 pilot dives through the proposer and persist results
-  — Generate review frame strips and timeline SVGs

## Output

Analysis runs are persisted in the production DB (pipeline_key=temporal_landmarks_v1).
Artifacts are written to .
All outputs are labeled EXPERIMENTAL and .
