#!/usr/bin/env python3
"""DIVE_ANALYZER_FLIGHT_SEARCH_RECOVERY_V1 — genuine HUMAN flight-phase subject GT.

Why: every pre-existing human subject box near the flight phase is also a
D5 detector training/validation label (the DEVELOPMENT landmark boxes and the
D5-mined +-15-frame neighbourhoods), hurdle "chains" are evaluator-seeded,
interpolated and snapped to D5 candidates, and STANDING Level-A has 1-3 flight
anchors per dive. Mid-flight subject position therefore has no independent
human authority. This tool collects a small, method-independent set:

- EVENT dives (HUMAN takeoff/water-contact already frozen): 7 interior flight
  frames per dive at fractions k/8 (k=1..7) of the HUMAN flight window.
- INDEP dives (Level-B dives without event authority): the annotator first
  marks takeoff (last frame with foot contact on the board/platform before the
  dive's own flight, i.e. after the last bounce) and water contact (first frame
  with any body part in the water); 9 frames at fractions k/8 (k=0..8) of that
  window are then boxed.
- 6 deterministic repeat items measure annotator repeatability.

Blind: no detector box, no candidate track, no draft is ever shown. Every
stored item is drawn by the human. Frame display uses the HQ rendition
resampled to proxy geometry where the manifest map is identity + PTS-verified
(fsr_hq_cache_v1 alignment), otherwise the proxy frame; boxes are always
stored in PROXY pixel coordinates (202x360), the frozen annotation timeline.

Workflow is one dive at a time: (INDEP) takeoff -> water contact -> that dive's
boxes; (EVENT) boxes. Repeats come last.

Commands: queue | extract | serve [--port] | validate | freeze
"""
from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PERSO = ROOT.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fsr_hq_cache_v1 as hqc  # noqa: E402

LABEL = 'FLIGHT_GT_HUMAN_V1'
WORK = ROOT / 'runs/flight_search_recovery_v1/flight_gt_annotation'
QUEUE_PATH = WORK / 'queue.json'
DRAFT_PATH = WORK / 'annotations_draft.json'
PTS_INDEX = WORK / 'frozen_pts_index.json'
FREEZE_DIR = ROOT / 'docs/science/localization_annotations_v1' / LABEL
EVENT_DOC = ROOT / 'docs/science/pilot_annotations_v2/DEVELOPMENT_DESIGN'
CACHES = {
    'hurdle': PERSO / 'diveanalyzer-cand-quality-v3/runs/hurdle_identity_v1/R5_FULLCLIP_CANDIDATES_V1.json',
    'cohort': PERSO / 'diveanalyzer-cand-quality-v3/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_COHORT_V1.json',
    'indep': PERSO / 'diveanalyzer-independent-gt/runs/subject_resolution/R5_FULLCLIP_CANDIDATES_INDEP_V1.json'}
PROXY_DIRS = [PERSO / 'diveanalyzer-perception/media/perception_decomposition_v1/proxies',
              PERSO / 'diveanalyzer-independent-gt/media/perception_decomposition_v1/proxies']
EVENT_DIVES = ['1040', '2169', '2341', '2353', '2541', '133', '311', '676', '2387']
INDEP_DIVES = ['1304', '2204', '2223', '2526', '2583', '2839']
HQ_DISPLAY = {d for d in hqc.HQ if d != '676'}  # identity spatial map only
N_FRAC = 8
N_REPEATS = 6
CTX = 3  # context frames each side (view only)
UP = 3  # extracted image scale vs proxy geometry
PW, PH = 202, 360
LOCK = threading.Lock()


def sha256_file(p):
    return hqc.sha256_file(p)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def proxy_path(d):
    for base in PROXY_DIRS:
        if (base / f'{d}.mp4').exists():
            return base / f'{d}.mp4'
    raise FileNotFoundError(d)


@functools.lru_cache(maxsize=None)
def _pts_index():
    """Frozen-cache frame PTS per dive (parsed once; the caches are ~90 MB)."""
    if PTS_INDEX.exists():
        return json.loads(PTS_INDEX.read_text())
    idx = {}
    for p in CACHES.values():
        raw = json.loads(p.read_text())
        for d, x in raw['dives'].items():
            idx[d] = [f['pts_s'] for f in x['frames']]
    WORK.mkdir(parents=True, exist_ok=True)
    PTS_INDEX.write_text(json.dumps(idx))
    return idx


def frozen_pts(d):
    return _pts_index()[d]


def nearest_idx(pts, t):
    return min(range(len(pts)), key=lambda i: abs(pts[i] - t))


def frac_items(d, pts, t0, t1, ks, source):
    out = []
    for k in ks:
        t = t0 + k / N_FRAC * (t1 - t0)
        fi = nearest_idx(pts, t)
        out.append({'id': f'FGT1_{d}_f{fi:05d}', 'dive_id': d, 'frame_index': fi,
                    'pts_s': pts[fi], 'flight_fraction': f'{k}/{N_FRAC}',
                    'window_source': source, 'kind': 'box'})
    return out


@functools.lru_cache(maxsize=None)
def _event_windows():
    out = {}
    for d in EVENT_DIVES:
        g = yaml.safe_load((EVENT_DOC / f'dive_{d}.yaml').read_text())
        out[d] = (g['landmarks']['takeoff']['timestamp_seconds'],
                  g['landmarks']['water_contact']['timestamp_seconds'])
    return out


def _dedupe(items):
    seen, uniq = set(), []
    for it in items:
        if it['id'] not in seen:
            seen.add(it['id'])
            uniq.append(it)
    return uniq


def build_queue(draft=None):
    """Deterministic queue, ordered one dive at a time.

    steps = [EVENT-dive boxes..., for each INDEP dive: takeoff, water_contact,
    boxes (only once both events are set)..., repeats]. `items` = box steps.
    """
    draft = draft or {'items': {}, 'events': {}}
    steps, event_items = [], []
    for d in EVENT_DIVES:
        t0, t1 = _event_windows()[d]
        its = _dedupe(frac_items(d, frozen_pts(d), t0, t1, range(1, N_FRAC),
                                 'HUMAN_EVENT_YAML_DEVELOPMENT_DESIGN'))
        event_items += its
        steps += its
    events = []
    for d in INDEP_DIVES:
        pts = frozen_pts(d)
        for ev in ('takeoff', 'water_contact'):
            e = {'id': f'FGT1_EV_{d}_{ev}', 'dive_id': d, 'event': ev,
                 'n_frames': len(pts), 'kind': 'event'}
            events.append(e)
            steps.append(e)
        a = draft['events'].get(f'FGT1_EV_{d}_takeoff')
        b = draft['events'].get(f'FGT1_EV_{d}_water_contact')
        if a and b and pts[b['frame_index']] > pts[a['frame_index']]:
            steps += _dedupe(frac_items(d, pts, pts[a['frame_index']], pts[b['frame_index']],
                                        range(0, N_FRAC + 1), 'HUMAN_EVENT_MARKED_IN_THIS_TOOL'))
    # deterministic repeats over the EVENT-dive items only (stable)
    step = max(len(event_items) // N_REPEATS, 1)
    reps = [dict(it, id=it['id'] + '_R', repeat_of=it['id'])
            for it in event_items[step // 2::step][:N_REPEATS]]
    steps += reps
    items = [s for s in steps if s['kind'] == 'box']
    return {'label': LABEL, 'events': events, 'items': items, 'steps': steps,
            'n_frac': N_FRAC,
            'created_rule': 'fractions k/8 of HUMAN flight window, nearest frozen-cache frame by PTS'}


def image_path(d, fi):
    return WORK / 'frames' / d / f'f{fi:05d}.jpg'


def cmd_extract(args):
    import cv2
    import numpy as np
    draft = load_draft()
    q = build_queue(draft)
    want = {}
    for it in q['items']:
        n = len(frozen_pts(it['dive_id']))
        for o in range(-CTX, CTX + 1):
            if 0 <= it['frame_index'] + o < n:
                want.setdefault(it['dive_id'], set()).add(it['frame_index'] + o)
    for ev in q['events']:  # scrubber needs every frame (proxy, small)
        want.setdefault(ev['dive_id'], set()).update(range(ev['n_frames']))
    man_path = WORK / 'frames_manifest.json'
    man = json.loads(man_path.read_text()) if man_path.exists() else {'frames': {}}
    for d, idxs in sorted(want.items()):
        need = sorted(i for i in idxs if not image_path(d, i).exists())
        if not need:
            continue
        (WORK / 'frames' / d).mkdir(parents=True, exist_ok=True)
        pts = frozen_pts(d)
        if d in HQ_DISPLAY:
            m = hqc.MAPS[d]
            probe = cv2.VideoCapture(str(hqc.hq_path(d)))
            hpts = []
            while probe.grab():
                hpts.append(probe.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            probe.release()
            ha = np.array(hpts)
            targets = {}
            for i in need:
                j = hqc.nearest(ha, pts[i] - m['dt'])
                if j is not None and abs(ha[j] - (pts[i] - m['dt'])) <= 0.5 / 24:
                    targets.setdefault(j, []).append(i)
            cap = cv2.VideoCapture(str(hqc.hq_path(d)))
            j = 0
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                for i in targets.get(j, []):
                    img = cv2.resize(fr, (PW * UP, PH * UP), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(image_path(d, i)), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    man['frames'].setdefault(d, {})[str(i)] = {
                        'representation': 'hq_display_resampled_to_proxy_geometry',
                        'hq_sha256': hqc.HQ[d][1], 'hq_frame': j}
                j += 1
            cap.release()
        cap = cv2.VideoCapture(str(proxy_path(d)))
        i = 0
        needset = {k for k in need if not image_path(d, k).exists()}
        while needset and i <= max(needset):
            ok, fr = cap.read()
            if not ok:
                break
            if i in needset:
                img = cv2.resize(fr, (PW * 2, PH * 2), interpolation=cv2.INTER_CUBIC)
                cv2.imwrite(str(image_path(d, i)), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                man['frames'].setdefault(d, {})[str(i)] = {
                    'representation': 'proxy_360p_native_decoded_frame_upscaled'}
            i += 1
        cap.release()
        print('extracted', d, len(need), 'hq' if d in HQ_DISPLAY else 'proxy', flush=True)
    for d in man['frames']:
        psha = sha256_file(proxy_path(d))
        for v in man['frames'][d].values():
            v['proxy_sha256'] = psha
    man_path.write_text(json.dumps(man, indent=1, sort_keys=True))


def load_draft():
    if DRAFT_PATH.exists():
        return json.loads(DRAFT_PATH.read_text())
    return {'items': {}, 'events': {}}


def save_draft(draft):
    tmp = DRAFT_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(draft, indent=1, sort_keys=True))
    tmp.replace(DRAFT_PATH)


_UI = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Flight GT (human)</title>
<style>
 html,body{height:100%;overflow:hidden}
 body{font-family:-apple-system,Helvetica,sans-serif;background:#111;color:#eee;margin:0;display:flex;flex-direction:row;align-items:flex-start;gap:14px;padding:8px;box-sizing:border-box}
 #stage{position:relative;border:1px solid #444;cursor:crosshair;flex:none}
 canvas{display:block}
 #toast{position:absolute;left:0;right:0;top:40%;margin:auto;width:86%;padding:14px;border-radius:10px;background:rgba(46,125,50,.95);color:#fff;font-size:18px;font-weight:700;text-align:center;display:none}
 #panel{display:flex;flex-direction:column;gap:8px;width:360px;height:calc(100vh - 16px);overflow:hidden}
 #task{background:#263238;border-left:6px solid #29b6f6;padding:10px;border-radius:6px;font-size:16px;font-weight:700;line-height:1.35}
 #task .sub{font-size:13px;font-weight:400;color:#cfd8dc;margin-top:4px}
 .row{display:flex;gap:6px;flex-wrap:wrap}
 button{padding:8px 12px;font-size:14px;border:0;border-radius:6px;cursor:pointer;background:#444;color:#eee}
 button:focus{outline:none}
 .g{background:#2e7d32;color:#fff}.r{background:#b71c1c;color:#fff}.o{background:#e65100;color:#fff}.b{background:#1565c0;color:#fff;font-size:16px;padding:12px}
 #msg{min-height:18px;color:#ffb74d;font-size:13px} #help{color:#9e9e9e;font-size:12px}
 input[type=range]{width:100%}
 #dives{font-size:12px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px}
 #dives div{background:#222;padding:3px 5px;border-radius:4px;cursor:pointer}
 #dives div.done{background:#1b5e20} #dives div.cur{outline:2px solid #29b6f6}
</style></head><body>
<div id="stage"><canvas id="cv" width="300" height="540"></canvas><div id="toast"></div></div>
<div id="panel">
 <div id="task">&mdash;</div>
 <div id="evrow" style="display:none;flex-direction:column;gap:6px">
  <input type="range" id="scrub" min="0" max="10" value="0">
  <div class="row"><button id="m10">-10 ([)</button><button id="m1">-1 (,)</button><button id="p1">+1 (.)</button><button id="p10">+10 (])</button></div>
  <button class="b" id="setev">SET THIS FRAME (Enter)</button>
 </div>
 <div id="boxrow" style="display:none;flex-direction:column;gap:6px">
  <div class="row"><button id="ctxm">&lt; peek -1 (,)</button><button id="ctxp">peek +1 (.) &gt;</button></div>
  <button class="g" id="vis">SAVE VISIBLE (s)</button>
  <button class="o" id="part">SAVE PARTIAL (p)</button>
  <div class="row"><button class="r" id="nv">NOT VISIBLE (n)</button><button class="r" id="amb">AMBIGUOUS (m)</button></div>
 </div>
 <div class="row"><button id="back">&larr; previous step</button><button id="next">skip / next step &rarr;</button></div>
 <div id="msg"></div>
 <div id="prog"></div>
 <div id="dives"></div>
 <div id="help"></div>
</div>
<script>
let S=1.5,st=null,list=[],pos=0,rect=null,drag=null,img=null,peek=0,evframe=0,busy=false;
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const $=id=>document.getElementById(id);
function fit(){S=Math.max(1,(window.innerHeight-20)/360);cv.width=Math.round(202*S);cv.height=Math.round(360*S);$('stage').style.width=cv.width+'px';draw();}
window.addEventListener('resize',fit);
const H_BOX="Drag a box around the DIVER PERFORMING THE DIVE (whole visible body) on this frame, then SAVE. "+
 "PARTIAL = only part of the diver in frame / occluded (box the visible part). NOT VISIBLE = diver out of frame or hidden. "+
 "AMBIGUOUS = cannot tell where the diver is. Peek (, .) shows neighbouring frames for context only.";
const H_EV={takeoff:"TAKEOFF = the LAST frame where the feet still touch the board/platform before the dive's own flight (after the last bounce; earlier hurdle/preparatory bounces are not the flight).",
 water_contact:"WATER CONTACT = the FIRST frame where any part of the diver's body touches the water."};
async function api(p,o){const r=await fetch(p,o);return r.json();}
function toast(t,color){const e=$('toast');e.textContent=t;e.style.background=color||'rgba(46,125,50,.95)';e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',1400);}
function draw(){ctx.fillStyle='#000';ctx.fillRect(0,0,cv.width,cv.height);
 if(img&&img.complete&&img.naturalWidth)ctx.drawImage(img,0,0,cv.width,cv.height);
 const it=list[pos];
 if(it&&it.kind=='box'&&rect&&peek==0){ctx.strokeStyle='#00e676';ctx.lineWidth=2;ctx.strokeRect(rect[0]*S,rect[1]*S,(rect[2]-rect[0])*S,(rect[3]-rect[1])*S);}
 if(peek!=0){ctx.fillStyle='rgba(255,152,0,.9)';ctx.fillRect(0,0,cv.width,30);ctx.fillStyle='#000';ctx.font='bold 16px sans-serif';ctx.fillText('PEEK '+(peek>0?'+':'')+peek+' (context only, not saved)',10,21);}
}
async function refresh(){st=await api('/api/state');list=st.steps;}
function firstOpen(){const i=list.findIndex(s=>!s.resolved);return i<0?list.length-1:i;}
function src(d,f){return `/frames/${d}/f${String(f).padStart(5,'0')}.jpg`;}
function setimg(u){img=new Image();img.onload=draw;img.src=u;}
function renderSide(){const it=list[pos];
 const done=list.filter(s=>s.resolved).length;
 $('prog').textContent=`Overall: ${done}/${list.length} steps done`+(st.pending_indep?' (boxes for event-less dives appear after their 2 events are set)':'');
 const per={};list.forEach(s=>{const k=s.repeat_of?'repeats':s.dive_id;per[k]=per[k]||{n:0,d:0};per[k].n++;if(s.resolved)per[k].d++;});
 $('dives').innerHTML=Object.entries(per).map(([k,v])=>`<div data-k="${k}" class="${v.d==v.n?'done':''} ${((it.repeat_of?'repeats':it.dive_id)==k)?'cur':''}">${k}: ${v.d}/${v.n}</div>`).join('');
 [...$('dives').children].forEach(el=>el.onclick=()=>{const k=el.dataset.k;const i=list.findIndex(s=>(s.repeat_of?'repeats':s.dive_id)==k&&!s.resolved);pos=i>=0?i:list.findIndex(s=>(s.repeat_of?'repeats':s.dive_id)==k);show();});}
function show(){if(pos<0)pos=0;if(pos>=list.length)pos=list.length-1;const it=list[pos];peek=0;rect=null;msg('');
 const ev=it.kind=='event';
 $('evrow').style.display=ev?'flex':'none';$('boxrow').style.display=ev?'none':'flex';
 const dsteps=list.filter(s=>s.dive_id==it.dive_id&&!s.repeat_of);const di=dsteps.indexOf(it)+1;
 if(ev){const sc=$('scrub');sc.max=it.n_frames-1;
  evframe=it.frame_index!=null?it.frame_index:(it.suggest_from!=null?it.suggest_from:0);sc.value=evframe;
  $('task').innerHTML=`Dive ${it.dive_id} &mdash; step ${di}/${dsteps.length}: set <u>${it.event.replace('_',' ').toUpperCase()}</u>`+
   `<div class="sub">${H_EV[it.event]}<br>Scrub with the slider or , . [ ] then press SET THIS FRAME (Enter).`+(it.resolved?`<br><b>Already saved: frame ${it.frame_index}</b> (setting again overwrites).`:'')+`</div>`;
  $('help').textContent='';evshow();}
 else{rect=it.bbox?it.bbox.slice():null;
  $('task').innerHTML=(it.repeat_of?`Repeat check &mdash; `:`Dive ${it.dive_id} &mdash; step ${di}/${dsteps.length}: `)+`draw the diver box`+
   `<div class="sub">frame ${it.frame_index}, t=${it.pts_s.toFixed(3)}s, flight fraction ${it.flight_fraction}`+(it.resolved?`<br><b>Already saved: ${it.visibility}</b> (saving again overwrites).`:'')+`</div>`;
  $('help').textContent=H_BOX;setimg(src(it.dive_id,it.frame_index));}
 renderSide();}
function evshow(){setimg(src(list[pos].dive_id,evframe));msg(`showing frame ${evframe} / ${list[pos].n_frames-1}`);}
function step(k){const it=list[pos];evframe=Math.max(0,Math.min(it.n_frames-1,evframe+k));$('scrub').value=evframe;evshow();}
$('scrub').oninput=e=>{evframe=+e.target.value;evshow();};
[['m10',-10],['m1',-1],['p1',1],['p10',10]].forEach(([id,k])=>$(id).onclick=e=>{e.currentTarget.blur();step(k);});
async function setEvent(){if(busy)return;const it=list[pos];if(it.kind!='event')return;busy=true;
 try{const r=await api('/api/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:it.id,frame_index:evframe,confirm:false})});
  if(r.warn&&!confirm(r.warn+'\n\nSave anyway?')){msg('not saved');return;}
  let r2=r;if(r.warn){r2=await api('/api/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:it.id,frame_index:evframe,confirm:true})});}
  if(!r2.ok){toast(r2.error||'error','rgba(183,28,28,.95)');return;}
  toast(`✔ ${it.event.replace('_',' ').toUpperCase()} saved: dive ${it.dive_id}, frame ${evframe}`);
  const id=it.id;await refresh();const i=list.findIndex(s=>s.id==id);pos=Math.min(i+1,list.length-1);show();}
 finally{busy=false;}}
$('setev').onclick=e=>{e.currentTarget.blur();setEvent();};
function doPeek(k){const it=list[pos];if(it.kind!='box')return;const np=peek+k;if(Math.abs(np)>3)return;peek=np;
 if(peek==0){setimg(src(it.dive_id,it.frame_index));}else setimg(src(it.dive_id,it.frame_index+peek));}
$('ctxm').onclick=e=>{e.currentTarget.blur();doPeek(-1);};$('ctxp').onclick=e=>{e.currentTarget.blur();doPeek(1);};
function evpos(e){const r=cv.getBoundingClientRect();return [(e.clientX-r.left)/S,(e.clientY-r.top)/S].map(v=>Math.round(v*10)/10);}
cv.addEventListener('mousedown',e=>{if(list[pos].kind!='box')return;if(peek!=0){peek=0;setimg(src(list[pos].dive_id,list[pos].frame_index));}drag=evpos(e);rect=[drag[0],drag[1],drag[0],drag[1]];});
cv.addEventListener('mousemove',e=>{if(!drag)return;const p=evpos(e);rect=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.max(drag[0],p[0]),Math.max(drag[1],p[1])];draw();});
window.addEventListener('mouseup',()=>{drag=null;});
async function commit(vis){if(busy)return;const it=list[pos];if(it.kind!='box')return;
 const body={id:it.id,visibility:vis,bbox:null};
 if(vis=='visible'||vis=='partial'){if(!rect||rect[2]-rect[0]<2||rect[3]-rect[1]<2){toast('Draw a box on the target frame first','rgba(230,81,0,.95)');return;}body.bbox=rect;}
 busy=true;try{const r=await api('/api/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(!r.ok){toast(r.error||'save failed','rgba(183,28,28,.95)');return;}
  toast(`✔ saved ${vis.replace('_',' ').toUpperCase()} (dive ${it.dive_id}, frame ${it.frame_index})`);
  const id=it.id;await refresh();const i=list.findIndex(s=>s.id==id);
  const nxt=list.findIndex((s,k)=>k>i&&!s.resolved);pos=nxt>=0?nxt:Math.min(i+1,list.length-1);show();
  if(list.every(s=>s.resolved))toast('✔ ALL DONE — thank you!','rgba(21,101,192,.95)');}
 finally{busy=false;}}
function msg(t){$('msg').textContent=t;}
[['vis','visible'],['part','partial'],['nv','not_visible'],['amb','ambiguous']].forEach(([id,v])=>$(id).onclick=e=>{e.currentTarget.blur();commit(v);});
$('next').onclick=e=>{e&&e.currentTarget&&e.currentTarget.blur();if(pos<list.length-1){pos++;show();}};
$('back').onclick=e=>{e&&e.currentTarget&&e.currentTarget.blur();if(pos>0){pos--;show();}};
window.addEventListener('keydown',e=>{const it=list[pos];if(!it)return;if(e.repeat&&(e.key=='Enter'||'spnm'.includes(e.key)))return;
 const k=e.key;
 if(['Enter',',','.','[',']','s','p','n','m','ArrowLeft','ArrowRight',' '].includes(k))e.preventDefault();
 if(k=='ArrowRight')return $('next').onclick();
 if(k=='ArrowLeft')return $('back').onclick();
 if(it.kind=='event'){if(k==',')step(-1);if(k=='.')step(1);if(k=='[')step(-10);if(k==']')step(10);if(k=='Enter')setEvent();return;}
 if(k==',')doPeek(-1);if(k=='.')doPeek(1);
 if(k=='s')commit('visible');if(k=='p')commit('partial');if(k=='n')commit('not_visible');if(k=='m')commit('ambiguous');});
(async()=>{fit();await refresh();pos=firstOpen();show();})();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj).encode())

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self._send(200, _UI.encode(), 'text/html')
        if self.path == '/api/state':
            with LOCK:
                draft = load_draft()
            q = build_queue(draft)
            steps = []
            for s in q['steps']:
                if s['kind'] == 'event':
                    a = draft['events'].get(s['id'])
                    sugg = None
                    if s['event'] == 'water_contact':
                        t = draft['events'].get(s['id'].replace('water_contact', 'takeoff'))
                        sugg = min(t['frame_index'] + 1, s['n_frames'] - 1) if t else None
                    steps.append({**s, 'resolved': bool(a), 'frame_index': a['frame_index'] if a else None,
                                  'suggest_from': sugg})
                else:
                    a = draft['items'].get(s['id'])
                    steps.append({**s, 'resolved': bool(a), 'bbox': a.get('bbox') if a else None,
                                  'visibility': a.get('visibility') if a else None})
            pending = any(not s['resolved'] for s in steps if s['kind'] == 'event')
            return self._json({'steps': steps, 'pending_indep': pending})
        if self.path.startswith('/frames/'):
            fp = (WORK / self.path.lstrip('/')).resolve()
            if not str(fp).startswith(str((WORK / 'frames').resolve())) or not fp.exists():
                return self._send(404, b'not found', 'text/plain')
            return self._send(200, fp.read_bytes(), 'image/jpeg')
        self._send(404, b'not found', 'text/plain')

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        req = json.loads(self.rfile.read(n))
        with LOCK:
            draft = load_draft()
            if self.path == '/api/event':
                q = build_queue(draft)
                ev = {e['id']: e for e in q['events']}.get(req.get('id'))
                fi = req.get('frame_index')
                if not ev or not isinstance(fi, int) or not 0 <= fi < ev['n_frames']:
                    return self._json({'ok': False, 'error': 'bad event'}, 400)
                pts = frozen_pts(ev['dive_id'])
                other_id = ev['id'].replace('takeoff', 'water_contact') if ev['event'] == 'takeoff' \
                    else ev['id'].replace('water_contact', 'takeoff')
                other = draft['events'].get(other_id)
                if other and not req.get('confirm'):
                    t0, t1 = (pts[fi], pts[other['frame_index']]) if ev['event'] == 'takeoff' \
                        else (pts[other['frame_index']], pts[fi])
                    if t1 <= t0:
                        return self._json({'ok': False, 'error': 'water contact must be after takeoff'}, 400)
                    if not 0.3 <= t1 - t0 <= 2.5:
                        return self._json({'ok': True, 'warn': f'Flight duration takeoff->water = {t1 - t0:.2f}s looks unusual (typical 0.6-1.8s).'})
                prev = draft['events'].get(ev['id'])
                if prev and prev['frame_index'] != fi:
                    # event moved: the dive's fraction frames change -> archive its boxes
                    old = [k for k, v in draft['items'].items() if v['dive_id'] == ev['dive_id']]
                    for k in old:
                        draft.setdefault('superseded', {})[k + '@' + now()] = {**draft['items'].pop(k),
                                                                                'reason': 'event_frame_changed'}
                    draft.setdefault('superseded_events', {})[ev['id'] + '@' + now()] = prev
                draft['events'][ev['id']] = {'dive_id': ev['dive_id'], 'event': ev['event'], 'frame_index': fi,
                                             'pts_s': pts[fi], 'authority': 'HUMAN_REVIEWED', 'annotator': 'maxime',
                                             'created_at': now()}
                save_draft(draft)
                return self._json({'ok': True})
            if self.path == '/api/annotate':
                q = build_queue(draft)
                it = {i['id']: i for i in q['items']}.get(req.get('id'))
                vis, bbox = req.get('visibility'), req.get('bbox')
                if not it or vis not in ('visible', 'partial', 'not_visible', 'ambiguous'):
                    return self._json({'ok': False, 'error': 'bad item/visibility'}, 400)
                if vis in ('visible', 'partial'):
                    if not (isinstance(bbox, list) and len(bbox) == 4 and bbox[2] > bbox[0] and bbox[3] > bbox[1]):
                        return self._json({'ok': False, 'error': 'bad bbox'}, 400)
                    bbox = [max(0.0, float(bbox[0])), max(0.0, float(bbox[1])),
                            min(float(PW), float(bbox[2])), min(float(PH), float(bbox[3]))]
                else:
                    bbox = None
                if not image_path(it['dive_id'], it['frame_index']).exists():
                    return self._json({'ok': False, 'error': 'frame image missing (run extract)'}, 400)
                man = json.loads((WORK / 'frames_manifest.json').read_text())
                fmeta = man['frames'].get(it['dive_id'], {}).get(str(it['frame_index']), {})
                draft['items'][it['id']] = {
                    **{k: it[k] for k in ('dive_id', 'frame_index', 'pts_s', 'flight_fraction', 'window_source')},
                    'repeat_of': it.get('repeat_of'), 'bbox': bbox, 'visibility': vis,
                    'authority': 'HUMAN_REVIEWED', 'annotator': 'maxime', 'method': 'human_drawn_blind',
                    'source_identity': 'intended Dive Analyzer subject (diver performing the dive)',
                    'representation': fmeta.get('representation'), 'display_hq_sha256': fmeta.get('hq_sha256'),
                    'media_sha256': fmeta.get('proxy_sha256'),
                    'image_sha256': sha256_file(image_path(it['dive_id'], it['frame_index'])),
                    'width': PW, 'height': PH, 'coordinate_frame': 'proxy_pixels_202x360', 'created_at': now()}
                save_draft(draft)
                return self._json({'ok': True})
        self._send(404, b'not found', 'text/plain')


def cmd_serve(args):
    WORK.mkdir(parents=True, exist_ok=True)
    if not DRAFT_PATH.exists():
        save_draft({'items': {}, 'events': {}})
    _pts_index()
    srv = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'flight GT UI: http://127.0.0.1:{args.port}', flush=True)
    srv.serve_forever()


def cmd_queue(args):
    q = build_queue(load_draft())
    WORK.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(q, indent=1))
    print(len(q['events']), 'events', len(q['items']), 'items', len(q['steps']), 'steps')


def cmd_validate(args):
    draft = load_draft()
    q = build_queue(draft)
    miss_ev = [e['id'] for e in q['events'] if e['id'] not in draft['events']]
    miss = [i['id'] for i in q['items'] if i['id'] not in draft['items']]
    from collections import Counter
    vis = Counter(v['visibility'] for v in draft['items'].values())
    rep = []
    for i in q['items']:
        if i.get('repeat_of') and i['id'] in draft['items'] and i['repeat_of'] in draft['items']:
            a, b = draft['items'][i['id']], draft['items'][i['repeat_of']]
            if a['bbox'] and b['bbox']:
                ca = ((a['bbox'][0] + a['bbox'][2]) / 2 / PW, (a['bbox'][1] + a['bbox'][3]) / 2 / PH)
                cb = ((b['bbox'][0] + b['bbox'][2]) / 2 / PW, (b['bbox'][1] + b['bbox'][3]) / 2 / PH)
                rep.append(round(((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** .5, 4))
            else:
                rep.append(None if a['visibility'] == b['visibility'] else 'VISIBILITY_DISAGREE')
    durations = {}
    for d in INDEP_DIVES:
        a = draft['events'].get(f'FGT1_EV_{d}_takeoff')
        b = draft['events'].get(f'FGT1_EV_{d}_water_contact')
        if a and b:
            durations[d] = round(b['pts_s'] - a['pts_s'], 4)
    rpt = {'missing_events': miss_ev, 'missing_items': miss, 'visibility': dict(vis),
           'repeat_center_dist_norm': rep, 'indep_flight_durations_s': durations,
           'complete': not miss_ev and not miss}
    print(json.dumps(rpt, indent=1))
    return rpt


def cmd_freeze(args):
    rpt = cmd_validate(args)
    assert rpt['complete'], 'incomplete'
    draft = load_draft()
    q = build_queue(draft)
    live = {i['id'] for i in q['items']}
    FREEZE_DIR.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for k, v in sorted(draft['items'].items()):
        if k not in live:
            continue
        p = FREEZE_DIR / f'{k}.json'
        p.write_text(json.dumps({'id': k, **v}, indent=1, sort_keys=True) + '\n')
        hashes[p.name] = sha256_file(p)
    ev = FREEZE_DIR / 'FGT1_EVENTS.json'
    ev.write_text(json.dumps(draft['events'], indent=1, sort_keys=True) + '\n')
    hashes[ev.name] = sha256_file(ev)
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    (FREEZE_DIR / 'MANIFEST.json').write_text(json.dumps(
        {'label': LABEL, 'frozen_at': now(), 'digest': digest, 'files': hashes,
         'validation': rpt, 'queue_rule': q['created_rule'],
         'superseded_count': len(draft.get('superseded', {})) + len(draft.get('superseded_events', {})),
         'discarded_pre_fix': draft.get('discarded_pre_fix', {}),
         'blind': 'no detector/candidate/draft shown; every box human-drawn'}, indent=1, sort_keys=True) + '\n')
    print('frozen', LABEL, digest)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['queue', 'extract', 'serve', 'validate', 'freeze'])
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    {'queue': cmd_queue, 'extract': cmd_extract, 'serve': cmd_serve,
     'validate': cmd_validate, 'freeze': cmd_freeze}[a.cmd](a)
