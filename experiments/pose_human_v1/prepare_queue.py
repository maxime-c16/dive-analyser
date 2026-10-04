"""Freeze the 16-frame HUMAN anatomical pose queue from sealed FAX GT."""
import hashlib
import json
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
MEDIA = Path('/Users/maximecauchy/.perso/diveanalyzer/fresh_prep_authority/raw')
OUT = Path('/Users/maximecauchy/.perso/diveanalyzer/fresh_prep_authority/pose_human_v1')
GT = ROOT / 'docs/science/localization_annotations_v1'
QUEUE = {
    '2134': ('FAX8', 'inversion', [230, 247, 264, 280]),
    '1257': ('FAX8', 'small_flight', [157, 167, 177, 188]),
    '2120': ('FAX7', 'compact_pike', [270, 288, 297]),
    '47': ('FAX7', 'horizontal_rotation_entry', [304, 309, 324]),
    '952': ('FAX7', 'horizontal_rotation', [391, 399]),
}
JOINTS = [f'{side}_{joint}' for side in ('left', 'right') for joint in
          ('shoulder', 'elbow', 'wrist', 'hip', 'knee', 'ankle')]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = []
    for dive, (source, challenge, indexes) in QUEUE.items():
        raw = MEDIA / f'{dive}.mov'
        cap = cv2.VideoCapture(str(raw))
        if not cap.isOpened():
            raise RuntimeError(f'Cannot read {raw}')
        fps = cap.get(cv2.CAP_PROP_FPS)
        for index in indexes:
            gt_path = GT / f'FULL_ACTION_GT_HUMAN_{source}_FRESH' / f'{source}_{dive}_fl_f{index:05d}.json'
            gt = json.loads(gt_path.read_text())
            raw_index = round(gt['pts_s'] * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, raw_index)
            ok, image = cap.read()
            if not ok:
                raise RuntimeError(f'Cannot decode {dive} raw frame {raw_index}')
            h, w = image.shape[:2]
            name = f'{dive}_fl_f{index:05d}.jpg'
            image_path = OUT / name
            cv2.imwrite(str(image_path), image, [cv2.IMWRITE_JPEG_QUALITY, 94])
            x1, y1, x2, y2 = gt['bbox']
            sx, sy = w / gt['width'], h / gt['height']
            cx, cy = (x1 + x2) * sx / 2, (y1 + y2) * sy / 2
            size = max((x2-x1)*sx, (y2-y1)*sy) * 2.2
            xa, ya = max(0, int(cx-size/2)), max(0, int(cy-size/2))
            xb, yb = min(w, int(cx+size/2)), min(h, int(cy+size/2))
            crop = image[ya:yb, xa:xb]
            crop_name = f'{dive}_fl_f{index:05d}_crop.jpg'
            crop_path = OUT / crop_name
            cv2.imwrite(str(crop_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 96])
            frames.append(dict(id=f'{dive}_fl_f{index:05d}', dive_id=dive,
                               session_id={'2134':130,'1257':79,'2120':129,'47':15,'952':58}[dive],
                               challenge=challenge, flight_fraction=gt['flight_fraction'],
                               pts_s=gt['pts_s'], proxy_frame_index=index,
                               raw_frame_index=raw_index, raw_fps=fps,
                               raw_media_sha256=sha(raw), source_gt=str(gt_path.relative_to(ROOT)),
                               source_gt_sha256=sha(gt_path),
                               image=name, image_sha256=sha(image_path),
                               crop_image=crop_name, crop_sha256=sha(crop_path),
                               crop_xyxy=[xa,ya,xb,yb], image_width=w, image_height=h))
        cap.release()
    manifest = dict(authority='FROZEN_QUEUE_PRE_HUMAN_POSE_ANNOTATION_V1',
                    coordinate_frame='decoded_raw_HQ_pixels',
                    crop_note='Crop is raw HQ pixels around sealed HUMAN subject box, with no skeleton or model prediction.',
                    anatomy='Left/right mean the diver’s anatomical side, irrespective of image direction or inversion.',
                    joints=JOINTS, states=['visible','occluded','not_visible'],
                    head_face_excluded=True, frames=frames)
    path = ROOT / 'docs/science/pose_human_v1_queue.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(path, sha(path), len(frames))


if __name__ == '__main__':
    main()
