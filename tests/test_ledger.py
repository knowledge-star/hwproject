from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.request
import urllib.error
import pytest
from skill_optimizer.adapters.ledger import request_ledger


def test_wire_relay_exact_count_stream_bytes_and_provider_errors():
    seen=[]
    class Upstream(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            seen.append((self.headers['Authorization'],raw))
            self.send_response(429 if raw==b'fail' else 200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            self.wfile.write(b'data: {"value":5}\n\ndata: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with request_ledger(f'http://127.0.0.1:{server.server_port}/v1','SYNTHETIC_TEST_CREDENTIAL') as ledger:
            def call(data):
                req=urllib.request.Request(ledger['endpoint']+'/chat/completions',data=data,
                    headers={'Authorization':'Bearer '+ledger['marker']})
                return urllib.request.urlopen(req)
            with call(b'{"model":"synthetic"}') as response:
                assert response.read()==b'data: {"value":5}\n\ndata: [DONE]\n\n'
            with pytest.raises(urllib.error.HTTPError) as error:call(b'fail')
            assert error.value.code==429
        assert len(ledger['records'])==2
        assert ledger['records'][0]['status']=='complete'
        assert ledger['records'][1]['status']=='provider_failure'
        assert seen==[('Bearer SYNTHETIC_TEST_CREDENTIAL',b'{"model":"synthetic"}'),('Bearer SYNTHETIC_TEST_CREDENTIAL',b'fail')]
        assert 'SYNTHETIC_TEST_CREDENTIAL' not in json.dumps(ledger['records'])
    finally:
        server.shutdown();server.server_close();thread.join()
