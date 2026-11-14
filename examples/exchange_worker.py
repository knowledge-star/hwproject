"""Synthetic script worker: demonstrates exchange plumbing, NOT Xiaoyi/OpenClaw."""
from pathlib import Path
import sys
from skill_optimizer.adapters.synthetic import SyntheticHarness
from skill_optimizer.adapters.exchange import write_response
from skill_optimizer.storage import read

request_path, response_path = map(Path, sys.argv[1:3])
request = read(request_path)
skill = (request_path.parent / request['skill_file']).read_text(encoding='utf-8')
execution = SyntheticHarness().execute(request['task'], skill, request_path.parent)
write_response(request_path, execution, response_path)
