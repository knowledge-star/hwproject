"""Small wire-preserving local relay for exact OpenClaw request accounting.

Replaces research relay's credential/server coupling. No retries, credentials,
request bodies, response bodies or auth headers are persisted. This relay does
not reproduce the research-only progress/loop stopping instrumentation.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import urllib.request
import urllib.error
import uuid


@contextmanager
def request_ledger(base_url, api_key, timeout=360):
    records = []
    lock = threading.Lock()
    marker = 'local-' + uuid.uuid4().hex
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer ' + marker:
                self.send_error(403)
                return
            if self.path != '/v1/chat/completions':
                self.send_error(404)
                return
            data = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            row = dict(status='inflight', bytes_received=0)
            with lock:
                records.append(row)
            request = urllib.request.Request(base_url.rstrip('/') + '/chat/completions', data=data,
                       headers={'Authorization': 'Bearer ' + api_key,
                                'Content-Type': self.headers.get('Content-Type', 'application/json')}, method='POST')
            try:
                try:
                    response = opener.open(request, timeout=timeout)
                except urllib.error.HTTPError as exc:
                    response = exc
                with response:
                    code = response.status
                    self.send_response(code)
                    self.send_header('Content-Type', response.headers.get('Content-Type','application/json'))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    # read1 preserves streaming latency, while forwarding content
                    # bytes unchanged (HTTP chunk framing is handled by urllib).
                    while True:
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        row['bytes_received'] += len(chunk)
                    row.update(http_status=code, status='complete' if code < 400 else 'provider_failure')
            except Exception as exc:
                row.update(status='transport_failure', error_type=type(exc).__name__)
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield dict(endpoint=f'http://127.0.0.1:{server.server_port}/v1', marker=marker, records=records)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
