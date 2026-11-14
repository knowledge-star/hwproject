"""Synthetic CLI/proxy test, separate from the real offline discovery report."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import json
import sys
import threading
from skill_optimizer.adapters.openclaw import OpenClawAdapter
from skill_optimizer.core import render_bank
from skill_optimizer.storage import read


def test_native_adapter_snapshot_trace_final_and_exact_ledger(tmp_path,monkeypatch):
    script=tmp_path/'synthetic_cli.py'
    script.write_text('''
from pathlib import Path
import json,os,sys,urllib.request
args=sys.argv[1:]
cfg=json.loads(Path(os.environ['OPENCLAW_CONFIG_PATH']).read_text())
if args==['skills','list','--json']:
    enabled=cfg['skills'].get('entries',{}).get('portable-skill',{}).get('enabled',True)
    print(json.dumps({'skills':[{'name':'portable-skill','eligible':True,'disabled':not enabled}]}))
elif args and args[0]=='agent':
    p=cfg['models']['providers']['experiment']
    req=urllib.request.Request(p['baseUrl']+'/chat/completions',data=b'{}',headers={'Authorization':'Bearer '+p['apiKey']})
    with urllib.request.urlopen(req) as response: response.read()
    rows=[{'id':'m1','timestamp':'01','message':{'role':'assistant','content':[{'type':'toolCall','name':'sum','arguments':{'a':2,'b':3}}]}},
          {'id':'m2','timestamp':'02','message':{'role':'toolResult','content':'5'}}]
    folder=Path(os.environ['OPENCLAW_STATE_DIR'])/'agents/main/sessions'
    folder.mkdir(parents=True)
    (folder/'session.jsonl').write_text('\\n'.join(json.dumps(row) for row in rows))
    print(json.dumps({'payloads':[{'text':'5'}]}))
else: raise RuntimeError('Unexpected synthetic command')
''')
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('SKILL_TEST_AGENT_KEY','SYNTHETIC_ONLY')
    cfg=dict(models=dict(providers=dict(experiment=dict(baseUrl=f'http://127.0.0.1:{server.server_port}/v1',apiKey='${SKILL_TEST_AGENT_KEY}'))))
    adapter=OpenClawAdapter(command=[sys.executable,str(script)],native_config=cfg,timeout=5)
    text,_=render_bank(dict(version='test',base_skill='Base',cards=[],config=dict(contract=False)))
    try:
        result=adapter.execute(dict(id='synthetic',prompt='Total of 2 and 3'),text,tmp_path/'delivery')
        assert result.final_answer=='5' and len(result.conversation)==2 and result.api_requests==1
        assert result.metadata['api_requests_estimated'] is False
        assert read(tmp_path/'delivery/request-ledger.json')[0]['status']=='complete'
        assert 'SYNTHETIC_ONLY' not in json.dumps(result.metadata)
        assert cfg['models']['providers']['experiment']['apiKey']=='${SKILL_TEST_AGENT_KEY}'
    finally:
        server.shutdown();server.server_close();thread.join()
