"""Summarize browser measurements by run, scrub variant and playback speed."""
import argparse,json
from collections import defaultdict
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('path',nargs='?',default='/tmp/tl-stack/metrics.jsonl');parser.add_argument('--human-only',action='store_true');parser.add_argument('--json',action='store_true');args=parser.parse_args()
runs=defaultdict(lambda:defaultdict(list));counts=defaultdict(dict)
for line in Path(args.path).read_text().splitlines():
    row=json.loads(line)
    if args.human_only and row['run'].startswith('webkit-'):continue
    for e in row['events']:
        key=(row['run'],e.get('variant','legacy'),e.get('speed',1))
        if 'ms' in e:runs[key][e['event']].append(e['ms'])
        if 'count' in e:counts[key][e['event']]=e['count']
keys=['page_ready','atlas_ready','mini_ready','scrub_paint','mini_seek_ready','seeked','resume_frame','release_to_frame','fast_frame']
results=[]
for (run,variant,speed),events in runs.items():
    result={'run':run,'variant':variant,'speed':speed,'metrics':{},'counts':counts[(run,variant,speed)]}
    for event in keys:
        if event in events:
            a=sorted(events[event]);result['metrics'][event]={'n':len(a),'p50_ms':a[len(a)//2],'p95_ms':a[min(len(a)-1,int(len(a)*.95))],'max_ms':a[-1]}
    results.append(result)
if args.json:print(json.dumps(results,indent=2))
else:
    for r in results:
        print(r['run'],r['variant'],f"×{r['speed']}")
        for event,m in r['metrics'].items():print(f"  {event}: n={m['n']}, p50={m['p50_ms']:.1f} ms, p95={m['p95_ms']:.1f} ms, max={m['max_ms']:.1f} ms")
        if r['counts']:print(' ',r['counts'])
