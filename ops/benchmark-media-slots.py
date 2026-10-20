"""Bounded synthetic ffmpeg benchmark; no credentials, Photos, or job writes.

python ops/benchmark-media-slots.py --ffmpeg /path/to/ffmpeg
Runs the same four conversions serially and with two slots, twice in reverse
order to reduce warm-cache/order bias. Temporary files are removed on exit.
This measures conversion capacity, not production queue or network latency.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import resource
import subprocess
import tempfile
import time


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ffmpeg", default="ffmpeg")
args = parser.parse_args()


def run(command):
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


with tempfile.TemporaryDirectory(prefix="dive-slots-benchmark-") as temporary:
    root = Path(temporary)
    source = root / "source.mp4"
    run([args.ffmpeg, "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=1920x1080:rate=30", "-t", "6", "-c:v", "libx264",
         "-threads", "2", "-preset", "ultrafast", "-crf", "22", str(source)])
    results = []
    for round_index, slots in enumerate([1, 2, 2, 1]):
        def convert(index):
            output = root / f"{round_index}-{index}.mp4"
            started = time.monotonic()
            run([args.ffmpeg, "-v", "error", "-threads", "2", "-i", str(source),
                 "-an", "-vf", "scale=-2:720,format=yuv420p", "-filter_threads", "1",
                 "-c:v", "libx264", "-threads", "2", "-preset", "veryfast",
                 "-crf", "25", "-profile:v", "main", "-movflags", "+faststart", str(output)])
            return {"seconds": round(time.monotonic()-started, 3), "bytes": output.stat().st_size}

        started = time.monotonic()
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        with ThreadPoolExecutor(max_workers=slots) as executor:
            jobs = list(executor.map(convert, range(4)))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        results.append({"slots": slots, "jobs": jobs,
                        "wall_seconds": round(time.monotonic()-started, 3),
                        "child_cpu_seconds": round(after.ru_utime + after.ru_stime-before.ru_utime-before.ru_stime, 3)})
    print(json.dumps({"kind": "synthetic_conversion_capacity", "source": "6s 1080p30 testsrc2",
                      "jobs_per_round": 4, "encoder_threads_per_job": 2, "rounds": results}, indent=2))
