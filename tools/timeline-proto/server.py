"""Disposable LAN-only lab. Read-only B2 signing, local derivatives and metrics."""
import json,re,time,threading
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from prepare import url,OUT
SIGN_LOCK=threading.Lock();SIGNED=None;SIGNED_AT=0
def playback_url():
    global SIGNED,SIGNED_AT
    with SIGN_LOCK:
        if not SIGNED or time.monotonic()-SIGNED_AT>21000:SIGNED=url();SIGNED_AT=time.monotonic()
        return SIGNED
ROOT=Path(__file__).resolve().parents[2];LOG=OUT.parent/'metrics.jsonl'
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
    def json(self,data):
        raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();
        if self.command!='HEAD':self.wfile.write(raw)
    def do_HEAD(self):self.do_GET()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/timeline/config':return self.json({'imagesRoot':'images/' if (OUT/'images/preparation.json').exists() else '', 'videoReady':(OUT/'video/preparation.json').exists() and (OUT/'video/fast.mp4').exists(),'imagesReady':(OUT/'index.json').exists() or (OUT/'images/preparation.json').exists(),'duration':1936.801667})
        if path=='/api/timeline/play':
            self.send_response(302);self.send_header('Location',playback_url());self.send_header('Cache-Control','no-store');self.end_headers();return
        if path=='/api/timeline/metrics':
            self.send_response(200);self.send_header('Content-Type','application/x-ndjson');self.end_headers()
            if LOG.exists() and self.command!='HEAD':self.wfile.write(LOG.read_bytes())
            return
        if path=='/proto/timeline/1':file=ROOT/'frontend/public/proto/timeline/index.html'
        elif path.startswith('/api/timeline/data/'):
            name=path[len('/api/timeline/data/'):]
            if not re.fullmatch(r'(?:(?:images|video)/)?(?:index\.json|preparation\.json|comparison\.json|sheet-\d+\.jpg|(?:search|fast)\.mp4)',name):self.send_error(404);return
            file=OUT/name
        else:self.send_error(404);return
        if not file.is_file():self.send_error(404);return
        size=file.stat().st_size;start=0;end=size-1;partial=False
        if self.headers.get('Range'):
            match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range'])
            if not match:self.send_error(416);return
            start=int(match[1]);end=min(int(match[2]) if match[2] else end,end);partial=True
            if start>end:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
        self.send_response(206 if partial else 200);self.send_header('Accept-Ranges','bytes');
        if file.suffix=='.html':self.send_header('Cache-Control','no-store')
        self.send_header('Content-Type',{'.json':'application/json','.jpg':'image/jpeg','.mp4':'video/mp4'}.get(file.suffix,'text/html'));self.send_header('Content-Length',str(end-start+1))
        if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command=='HEAD':return
        try:
            with file.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_POST(self):
        if self.path!='/api/timeline/metrics':self.send_error(404);return
        try:size=int(self.headers.get('Content-Length','0'))
        except ValueError:self.send_error(400);return
        if not 0<size<=32768:self.send_error(413);return
        try:
            body=json.loads(self.rfile.read(size));events=body['events'][:100]
            clean={'received':time.time(),'run':str(body.get('run',''))[:80],'ua':str(body.get('ua',''))[:240],'events':[{k:v for k,v in e.items() if k in ('event','variant','speed','elapsed','ms','build','requested','applied','before','input','trusted','revision','status','method','error','mediaTime','delta','inertia_ms','ready','buffered','seekable','time','target','count','generation','width','height') and isinstance(v,(str,int,float))} for e in events]}
            with open(LOG,'a') as f:f.write(json.dumps(clean)+'\n')
        except (ValueError,KeyError,TypeError):self.send_error(400);return
        self.send_response(204);self.end_headers()
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',8796),Handler).serve_forever()
