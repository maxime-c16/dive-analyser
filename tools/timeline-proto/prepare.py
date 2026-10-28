"""Read-only, independent B2 preparation benchmarks. Never stores the original."""
import json, os, re, resource, subprocess, time
from pathlib import Path
import boto3
from botocore.config import Config
OUT=Path(os.environ.get('TL_DATA','/tmp/tl-stack/data'));OUT.mkdir(parents=True,exist_ok=True)
FF=os.environ.get('FFMPEG','/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg')
def client():
    return boto3.client('s3',endpoint_url=os.environ['SESSION_LAB_ENDPOINT'],region_name=os.environ['SESSION_LAB_REGION'],aws_access_key_id=os.environ['SESSION_LAB_KEY_ID'],aws_secret_access_key=os.environ['SESSION_LAB_KEY_SECRET'],config=Config(signature_version='s3v4'))
def url():
    return client().generate_presigned_url('get_object',Params={'Bucket':os.environ['SESSION_LAB_BUCKET'],'Key':'inbox/IMG_2651.MOV'},ExpiresIn=21600)
def cpu():
    r=resource.getrusage(resource.RUSAGE_CHILDREN);return r.ru_utime+r.ru_stime

def local(cmd,source):
    result=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    if result.returncode:raise SystemExit('Local encoding failed: '+result.stderr.replace(source,'<source>')[-1000:])

if __name__=='__main__':
    start=time.monotonic();source=os.environ.get('SESSION_LAB_SOURCE_URL') or url()
    staging=OUT/'frames';staging.mkdir(parents=True,exist_ok=True)
    p=subprocess.run(['ffprobe','-v','quiet','-select_streams','v:0','-show_streams','-show_format','-of','json',source],capture_output=True,timeout=90)
    probe=json.loads(p.stdout);v=probe['streams'][0];rotation=next((d['rotation'] for d in v.get('side_data_list',[]) if 'rotation' in d),0)
    w,h=v['width'],v['height']
    if abs(rotation)%180==90:w,h=h,w
    width=270;height=round(h/w*width/2)*2
    tone='zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=hable:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=tv,format=yuv420p'
    cmd=[FF,'-y','-hide_banner','-loglevel','info','-threads','2','-discard:v','nokey','-skip_frame:v','nokey','-discard:a','all','-i',source,'-map','0:v:0','-an','-sn','-dn','-vf',f'fps=1,scale={width}:{height},{tone},showinfo','-fps_mode','vfr','-q:v','2',str(staging/'frame-%05d.jpg')]
    proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True);times=[];errors=[]
    for line in proc.stderr:
        m=re.search(r'\bn:\s*\d+.*?pts_time:([\d.]+)',line)
        if m:
            times.append(float(m[1]))
            if len(times)%20==0:(OUT/'progress.json').write_text(json.dumps({'phase':'shared extraction','frames':len(times),'last_time':times[-1],'elapsed_seconds':time.monotonic()-start}))
        elif any(s in line.lower() for s in ['error','failed','invalid']):errors.append(line.replace(source,'<source>')[-400:])
    if proc.wait() or not times:raise SystemExit('Extraction failed: '+''.join(errors[-5:]))
    shared=time.monotonic()-start;shared_cpu=cpu();duration=float(probe['format']['duration']);reports={}
    for mode in ['video','images']:
        dest=OUT/mode;dest.mkdir(parents=True,exist_ok=True);begin=time.monotonic();before=cpu()
        cmd=[FF,'-y','-v','error','-framerate','1','-i',str(staging/'frame-%05d.jpg'),'-an']
        if mode=='video':
            cw,ch=width,height
            cmd+=['-c:v','libx264','-pix_fmt','yuv420p','-profile:v','main','-preset','fast','-crf','28','-g','1','-keyint_min','1','-sc_threshold','0','-movflags','+faststart','-video_track_timescale','1000',str(dest/'search.mp4')]
        else:
            cw=160;ch=round(h/w*cw/2)*2
            cmd+=['-vf',f'scale={cw}:{ch},tile=10x10','-fps_mode','vfr','-q:v','4',str(dest/'sheet-%03d.jpg')]
        local(cmd,source)
        if mode=='video':
            local([FF,'-y','-v','error','-framerate','30','-i',str(staging/'frame-%05d.jpg'),'-an','-c:v','libx264','-pix_fmt','yuv420p','-profile:v','main','-preset','fast','-crf','28','-g','1','-keyint_min','1','-sc_threshold','0','-movflags','+faststart','-video_track_timescale','30000',str(dest/'fast.mp4')],source)
        pack=time.monotonic()-begin;pack_cpu=cpu()-before
        files=[dest/'search.mp4',dest/'fast.mp4'] if mode=='video' else list(dest.glob('sheet-*.jpg'))
        index={'duration':duration,'width':cw,'height':ch,'columns':10,'perSheet':100,'times':times,'content':{'x':0,'y':0,'width':cw,'height':ch},'source':{'width':v['width'],'height':v['height'],'rotation':[rotation],'transfer':v.get('color_transfer')}}
        (dest/'index.json').write_text(json.dumps(index))
        report={'mode':mode,'shared_extraction_seconds':shared,'shared_cpu_seconds':shared_cpu,'pack_seconds':pack,'pack_cpu_seconds':pack_cpu,'total_seconds':shared+pack,'total_cpu_seconds':shared_cpu+pack_cpu,'frames':len(times),'files':len(files),'bytes':sum(p.stat().st_size for p in files),'width':cw,'height':ch,'audio':False}
        if mode=='video':report.update(search_bytes=(dest/'search.mp4').stat().st_size,fast_bytes=(dest/'fast.mp4').stat().st_size,fast_duration_seconds=len(times)/30)
        (dest/'preparation.json').write_text(json.dumps(report,indent=2));reports[mode]=report
    reports['combined_seconds']=time.monotonic()-start;reports['max_child_rss_bytes']=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    (OUT/'comparison.json').write_text(json.dumps(reports,indent=2));print(json.dumps(reports))
