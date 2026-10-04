"""Local, raw-image-only HUMAN anatomical pose annotation interface.

Run: python3 experiments/pose_human_v1/annotate_server.py
Open: http://127.0.0.1:8765
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
QUEUE_PATH = ROOT / 'docs/science/pose_human_v1_queue.json'
IMAGES = Path('/Users/maximecauchy/.perso/diveanalyzer/fresh_prep_authority/pose_human_v1')
LABELS = IMAGES / 'annotations_draft.json'
QUEUE_BYTES = QUEUE_PATH.read_bytes()
QUEUE_SHA = hashlib.sha256(QUEUE_BYTES).hexdigest()
QUEUE = json.loads(QUEUE_BYTES)
FRAME_BY_ID = {f['id']: f for f in QUEUE['frames']}
JOINTS = set(QUEUE['joints'])

HTML = r'''<!doctype html><html><head><meta charset="utf-8"><title>Dive Analyzer HUMAN pose</title>
<style>body{font:14px system-ui;background:#111820;color:#e9f1f8;margin:0;overflow:hidden}header{box-sizing:border-box;height:78px;padding:9px 16px;background:#1d2a36}main{box-sizing:border-box;height:calc(100vh - 78px);display:grid;grid-template-columns:minmax(440px,1fr) minmax(510px,0.9fr);gap:14px;padding:10px 14px}main>div{min-height:0;display:flex;flex-direction:column;align-items:flex-start}canvas{max-width:100%;max-height:calc(100vh - 280px);width:auto;height:auto;background:#050809;cursor:crosshair;border:1px solid #496078}button{font:inherit;padding:5px 7px;background:#25384a;color:white;border:1px solid #698198;border-radius:5px}button:hover{background:#37546c}.active{background:#008d98!important}.done{color:#77d9a2}.row{display:flex;align-items:center;gap:3px;margin:3px 0;white-space:nowrap}.row b{width:74px;font-size:12px}.row button{font-size:11px;padding:4px}.row .coord{font-size:11px;color:#a9c2d4}aside{min-height:0;overflow:hidden}#jointRows{display:grid;grid-template-columns:1fr 1fr;column-gap:8px}#full{height:92px;max-width:100%;object-fit:contain;display:block;margin:4px 0}#meta{font-size:12px;margin:4px 0}small{color:#bed0db;font-size:12px}</style></head>
<body><header><b>HUMAN anatomical pose V1</b> · <span id="position"></span> · <span id="progress"></span><br>
<small>Click each visible joint on the enlarged raw HQ crop. Anatomical LEFT/RIGHT belong to the diver, including when inverted. Mark hidden joints occluded; mark joints outside frame or impossible to identify not visible. No head or face. No model skeleton shown.</small></header>
<main><div><img id="full"><canvas id="crop"></canvas><p id="meta"></p><div><button onclick="prev()">← Previous</button> <button onclick="next()">Next →</button> <button onclick="save()">Save frame</button> <span id="status"></span></div></div><aside><p>Select a joint, then click its location in the crop. All 12 need a state before saving.</p><div id="jointRows"></div></aside></main>
<script>
let queue, annotations={}, index=0, active=null, img=new Image();
const canvas=document.getElementById('crop'), ctx=canvas.getContext('2d');
const sides=['left','right'], names=['shoulder','elbow','wrist','hip','knee','ankle'];
async function start(){queue=await(await fetch('/api/queue')).json(); annotations=await(await fetch('/api/labels')).json(); render()}
function current(){return queue.frames[index]}
function values(){return annotations[current().id]||{}}
function render(){let f=current(); document.getElementById('position').textContent=`${index+1}/${queue.frames.length} · ${f.id} · ${f.challenge}`;
 document.getElementById('progress').textContent=`${Object.keys(annotations).length} saved`;
 document.getElementById('full').src='/image/'+f.image;
 document.getElementById('meta').textContent=`Dive ${f.dive_id}, session ${f.session_id}, ${f.flight_fraction}, raw HQ ${f.image_width}×${f.image_height}, PTS ${f.pts_s.toFixed(3)} s. Full raw frame above; enlarged unmodified raw crop below.`;
 img.onload=()=>{canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;draw()}; img.src='/image/'+f.crop_image;
 let box=document.getElementById('jointRows');box.innerHTML='';
 for(let side of sides)for(let name of names){let joint=side+'_'+name,v=values()[joint],row=document.createElement('div');row.className='row';
 let title=document.createElement('b');title.textContent=joint.replace('_',' '); if(v)title.className='done';row.append(title);
 let vis=document.createElement('button');vis.textContent='Place';vis.title='Click visible joint on the image';vis.className=active===joint?'active':'';vis.onclick=()=>{active=joint;render()};row.append(vis);
 for(let state of ['occluded','not_visible']){let b=document.createElement('button');b.textContent=state==='occluded'?'Occ':'N/V';b.title=state==='occluded'?'Occluded':'Not visible';b.className=v?.state===state?'active':'';b.onclick=()=>{setJoint(joint,{state});active=null;render()};row.append(b)}
 let coord=document.createElement('span');coord.className='coord';coord.textContent=v?.state==='visible'?`${v.x.toFixed(0)},${v.y.toFixed(0)}`:'';row.append(coord);box.append(row)}
 document.getElementById('status').textContent='';draw()}
function setJoint(j,v){let f=current();annotations[f.id] ||= {};annotations[f.id][j]=v}
function draw(){if(!img.complete||!img.naturalWidth)return;ctx.drawImage(img,0,0);let f=current();for(let [j,v] of Object.entries(values())){if(v.state!=='visible')continue;let x=v.x-f.crop_xyxy[0],y=v.y-f.crop_xyxy[1];ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fillStyle=j.startsWith('left')?'#00e5ff':'#ffcd63';ctx.fill();ctx.strokeStyle='#05131a';ctx.lineWidth=1;ctx.stroke();ctx.fillStyle='white';ctx.font='14px sans-serif';ctx.fillText(j,x+7,y-5)}}
canvas.onclick=e=>{if(!active){document.getElementById('status').textContent='Select a joint first';return}let r=canvas.getBoundingClientRect(),f=current(),x=(e.clientX-r.left)*canvas.width/r.width+f.crop_xyxy[0],y=(e.clientY-r.top)*canvas.height/r.height+f.crop_xyxy[1];setJoint(active,{state:'visible',x:+x.toFixed(2),y:+y.toFixed(2)});active=null;render()};
async function save(){let f=current(),v=values(),missing=queue.joints.filter(j=>!v[j]);if(missing.length){document.getElementById('status').textContent=`Mark ${missing.length} remaining joints`;return}let response=await fetch('/api/labels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({queue_sha256:queue.queue_sha256,frame_id:f.id,joints:v})});let data=await response.json();document.getElementById('status').textContent=data.error||'Saved';if(response.ok)document.getElementById('progress').textContent=`${Object.keys(annotations).length} saved`}
function prev(){if(index>0){index--;active=null;render()}}function next(){if(index<queue.frames.length-1){index++;active=null;render()}}
start();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def send(self, data, content_type='application/json', status=200):
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode()
        elif isinstance(data, str):
            data = data.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            return self.send(HTML, 'text/html; charset=utf-8')
        if self.path == '/api/queue':
            return self.send({**QUEUE, 'queue_sha256': QUEUE_SHA})
        if self.path == '/api/labels':
            return self.send(json.loads(LABELS.read_text()) if LABELS.exists() else {})
        if self.path.startswith('/image/'):
            name = unquote(self.path.removeprefix('/image/'))
            allowed = {f[k] for f in QUEUE['frames'] for k in ('image', 'crop_image')}
            if name not in allowed:
                return self.send({'error':'unknown image'}, status=404)
            return self.send((IMAGES/name).read_bytes(), 'image/jpeg')
        self.send({'error':'unknown path'}, status=404)

    def do_POST(self):
        if self.path != '/api/labels':
            return self.send({'error':'unknown path'}, status=404)
        try:
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            if payload['queue_sha256'] != QUEUE_SHA or payload['frame_id'] not in FRAME_BY_ID:
                raise ValueError('queue identity mismatch')
            frame=FRAME_BY_ID[payload['frame_id']]
            joints=payload['joints']
            if set(joints) != JOINTS:
                raise ValueError('all 12 joints require an explicit state')
            for joint, value in joints.items():
                if value.get('state') not in ('visible','occluded','not_visible'):
                    raise ValueError(f'{joint}: invalid state')
                if value['state']=='visible':
                    if not (isinstance(value.get('x'),(int,float)) and isinstance(value.get('y'),(int,float)) and
                            0 <= value['x'] < frame['image_width'] and 0 <= value['y'] < frame['image_height']):
                        raise ValueError(f'{joint}: invalid raw HQ coordinate')
                elif 'x' in value or 'y' in value:
                    raise ValueError(f'{joint}: hidden joint must not have coordinates')
            labels=json.loads(LABELS.read_text()) if LABELS.exists() else {}
            labels[frame['id']]=joints
            tmp=LABELS.with_suffix('.tmp')
            tmp.write_text(json.dumps(labels,indent=2)+'\n')
            tmp.replace(LABELS)
            self.send({'saved':frame['id']})
        except (KeyError, ValueError, json.JSONDecodeError) as error:
            self.send({'error':str(error)},status=400)


if __name__ == '__main__':
    print(f'Queue SHA256: {QUEUE_SHA}; 16 raw HQ frames; http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
