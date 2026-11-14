"""Package actual manually exported evidence. Does not drive Xiaoyi or invent traces."""
import argparse
from pathlib import Path
from skill_optimizer import Execution
from skill_optimizer.adapters.exchange import write_response
from skill_optimizer.storage import read, sha

ap=argparse.ArgumentParser()
ap.add_argument('--request',required=True,type=Path)
ap.add_argument('--trace',required=True,type=Path,help='Actual full exported conversation JSON array')
ap.add_argument('--final',required=True,type=Path,help='Exact final delivery text')
ap.add_argument('--api-requests',type=int,default=None,help='Actual measured count; leave unknown as null')
ap.add_argument('--judge',type=Path,help='Independent {hard,soft,feedback,qualified} JSON')
ap.add_argument('--metadata',type=Path,help='Actual session id, Skill loading and evidence completeness JSON')
ap.add_argument('--status',choices=['complete','normal_failure','infrastructure_failure'],default='complete')
args=ap.parse_args()
request=read(args.request)
metadata=read(args.metadata) if args.metadata else {}
if not isinstance(metadata,dict):
    raise ValueError('Execution metadata must be an object')
metadata.update(evidence_source='operator-supplied actual export',
                trace_file_sha256=sha(args.trace), final_file_sha256=sha(args.final),
                requested_skill_sha256=request['skill_sha256'])
execution=Execution(request['task']['id'],args.final.read_text(encoding='utf-8'),read(args.trace),
                    status=args.status,api_requests=args.api_requests,
                    metadata=metadata)
print(write_response(args.request,execution,judge_feedback=read(args.judge) if args.judge else None))
