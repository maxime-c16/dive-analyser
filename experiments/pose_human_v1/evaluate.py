"""HUMAN-grounded evaluation of frozen track-crop YOLO pose.

Runs only after annotations are sealed. Predictions and results are written outside Git.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
DATA = Path('/Users/maximecauchy/.perso/diveanalyzer/fresh_prep_authority/pose_human_v1')
QUEUE = json.loads((ROOT/'docs/science/pose_human_v1_queue.json').read_text())
KPT = {'left_shoulder':5,'right_shoulder':6,'left_elbow':7,'right_elbow':8,
       'left_wrist':9,'right_wrist':10,'left_hip':11,'right_hip':12,
       'left_knee':13,'right_knee':14,'left_ankle':15,'right_ankle':16}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_crop(image, gt):
    """Accepted successor: proxy HUMAN box scaled to raw, +30%, square ×1.15."""
    h,w=image.shape[:2]
    x1,y1,x2,y2=gt['bbox']
    sx,sy=w/gt['width'],h/gt['height']
    cx,cy=(x1+x2)*sx/2,(y1+y2)*sy/2
    size=max((x2-x1)*sx,(y2-y1)*sy)*1.3*1.15
    xa,ya=max(0,int(cx-size/2)),max(0,int(cy-size/2))
    xb,yb=min(w,int(cx+size/2)),min(h,int(cy+size/2))
    return image[ya:yb,xa:xb],(xa,ya)


def predict(model,frame):
    image=cv2.imread(str(DATA/frame['image']))
    gt=json.loads((ROOT/frame['source_gt']).read_text())
    crop,(ox,oy)=model_crop(image,gt)
    result=model.predict(crop,imgsz=640,conf=0.25,iou=0.45,verbose=False)[0]
    if result.boxes is None or len(result.boxes)==0:
        return {'detected':False,'reason':'zero_detections'}
    boxes=result.boxes.xyxy.cpu().numpy()
    scores=result.boxes.conf.cpu().numpy()
    center=np.array([(gt['bbox'][0]+gt['bbox'][2])/2/gt['width'],
                     (gt['bbox'][1]+gt['bbox'][3])/2/gt['height']])
    centers=np.stack(((boxes[:,0]+boxes[:,2])/2+ox,(boxes[:,1]+boxes[:,3])/2+oy),axis=1)
    distances=np.linalg.norm(centers/np.array([image.shape[1],image.shape[0]])-center,axis=1)
    choice=int(np.argmin(distances))
    if distances[choice]>0.15:
        return {'detected':False,'reason':'outside_track_gate','nearest_distance':float(distances[choice])}
    xy=result.keypoints.xy[choice].cpu().numpy()
    conf=result.keypoints.conf[choice].cpu().numpy()
    return {'detected':True,'track_distance':float(distances[choice]),'box_conf':float(scores[choice]),
            'joints':{name:{'x':float(xy[idx,0]+ox),'y':float(xy[idx,1]+oy),'conf':float(conf[idx])}
                      for name,idx in KPT.items()}}


def scale(label,frame):
    # Shoulders-to-hips is the preferred anatomical torso scale. A visible
    # shoulder/hip pair on either side suffices; no model geometry is used.
    lengths=[]
    for side in ('left','right'):
        s,h=label[f'{side}_shoulder'],label[f'{side}_hip']
        if s['state']==h['state']=='visible':
            lengths.append(math.dist((s['x'],s['y']),(h['x'],h['y'])))
    if lengths:return float(np.median(lengths)),'human_torso'
    # Fallback only for frames whose torso is hidden; report separately.
    return math.hypot(frame['image_width'],frame['image_height'])*0.1,'image_diagonal_fallback'


def score(labels,predictions):
    rows=[]
    for frame in QUEUE['frames']:
        label=labels[frame['id']]; pred=predictions[frame['id']]
        torso,scale_type=scale(label,frame)
        for joint in KPT:
            gt=label[joint]
            if gt['state']!='visible':continue
            pj=pred.get('joints',{}).get(joint)
            if pj is None or pj['conf']<0.5:
                rows.append({'frame':frame['id'],'challenge':frame['challenge'],'joint':joint,
                             'state':'missing','scale_type':scale_type})
                continue
            d=math.dist((gt['x'],gt['y']),(pj['x'],pj['y']))/torso
            other=joint.replace('left_','right_') if joint.startswith('left_') else joint.replace('right_','left_')
            op=pred['joints'][other]
            swap=op['conf']>=0.5 and math.dist((gt['x'],gt['y']),(op['x'],op['y']))/torso+0.1<d
            rows.append({'frame':frame['id'],'challenge':frame['challenge'],'joint':joint,
                         'state':'predicted','error_torso':d,'pck_0_2':d<=0.2,
                         'pck_0_5':d<=0.5,'opposite_side_closer':swap,'scale_type':scale_type})
    return rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--weights',default='/Users/maximecauchy/.perso/diveanalyzer/yolov8n-pose.pt')
    parser.add_argument('--labels',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    labels=json.loads(Path(args.labels).read_text())
    if set(labels)!={f['id'] for f in QUEUE['frames']}:
        raise SystemExit('All 16 frozen frames must be sealed before evaluation')
    model=YOLO(args.weights)
    predictions={f['id']:predict(model,f) for f in QUEUE['frames']}
    rows=score(labels,predictions)
    output={'queue_sha256':sha(ROOT/'docs/science/pose_human_v1_queue.json'),
            'labels_sha256':sha(args.labels),'weights_sha256':sha(args.weights),
            'detected_frames':sum(x['detected'] for x in predictions.values()),
            'total_frames':len(predictions),'predictions':predictions,'visible_joint_rows':rows}
    Path(args.out).write_text(json.dumps(output,indent=2)+'\n')
    found=[x for x in rows if x['state']=='predicted']
    print(json.dumps({'frames_detected':output['detected_frames'],'visible_joints':len(rows),
                      'predicted_joints':len(found),'median_torso_error':float(np.median([x['error_torso'] for x in found])) if found else None,
                      'PCK_0.2':sum(x['pck_0_2'] for x in found)/len(rows) if rows else None,
                      'opposite_side_closer':sum(x['opposite_side_closer'] for x in found)},indent=2))


if __name__=='__main__':main()
