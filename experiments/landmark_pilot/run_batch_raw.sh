#!/bin/bash
set -e
cd ~/dive-analyser/experiments/landmark_pilot
mkdir -p runs/target_selection_v1
W=~/dive-analyser/models/frozen/DIVER_DETECTOR_D3_V8N_best.pt
declare -A MK
MK[1040]=9cb42af1a2aa79bb3a11a07c8b29baaf8c00d5ebda68826eb4c52c5a9202324e
MK[133]=c26271fda2aaa252e1dd9eb3c43a8f5374f69fea667b07fdcd1768240a9649eb
MK[2169]=85c81842b1f892d0919d8db1dcaee3ed01a93d294d3cc350643b198988e844b0
MK[2341]=3e01c635ade0139c1ad3eb39fed14790c06d7c64972169af1b8ced04d0aeeafc
MK[2387]=e7bb8646edf66df370f0ff4958c1bf4736cb41df0e461428084fa6fa6486fc4a
MK[2541]=cf92e9a817dfb9e5ad0ff553bb545cc63719fa25770514ec11126618c0578358
MK[2555]=dd7a8621a89bd00af627560e2121dec4bacecb313d8b5ecd5027d91f2f9c9e44
MK[2625]=4dc9064e1692518c412a4e6e55f67f92d26959d2bfecb3147617e914da3d84fd
MK[2680]=d887b0fd8e173c80885dcd5fd15222c6202998a53bc6d493c571656a3f6661a1
MK[311]=dc1d176ed1ed24e004a6634f0ee91ae3e5150645a85380f33db399f55bedf10c
MK[524]=552d34613e606af9241e4a561c65a3dfb374479205b2dd76543fbdb8a376029f
MK[676]=2b512f91e6b244198942b974b9438163a12ece12c1422aa33dd93c966304d1f6
for id in "${!MK[@]}"; do
  mk=${MK[$id]}
  p1=${mk:0:2}; p2=${mk:2:2}
  vid=~/dive-analyser/media/cache/proxy_360p/$p1/$p2/$mk.mp4
  out=runs/target_selection_v1/${id}_raw.json
  if [ -f "$out" ]; then echo "SKIP $id (exists)"; continue; fi
  echo "=== $id ==="
  ./venv_c/bin/python3 d3_infer.py "$vid" "$W" "$out" --conf 0.05 2>/dev/null
done
echo ALL_DONE
