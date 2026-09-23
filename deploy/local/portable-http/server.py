"""Small real HTTP workload, with request-derived Prometheus text instrumentation.

Only /work is measured. Scrapes and failure controls cannot create request evidence.
No samples are emitted for a status code until a request actually produces it.
"""

import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOUNDS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float('inf'))


class Workload(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], namespace: str = 'opentelemetry-demo') -> None:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', namespace):
            raise ValueError('Invalid namespace')
        self.namespace = namespace
        self.lock = threading.Lock()
        self.failure_until = 0.0
        self.samples: dict[int, tuple[int, float, list[int]]] = {}
        super().__init__(address, Handler)

    def observe(self, code: int, elapsed: float) -> None:
        with self.lock:
            count, total, buckets = self.samples.get(code, (0, 0.0, [0] * len(BOUNDS)))
            self.samples[code] = (count + 1, total + elapsed,
                [value + int(elapsed <= bound) for value, bound in zip(buckets, BOUNDS)])

    def exposition(self) -> bytes:
        with self.lock:
            rows = list(sorted(self.samples.items()))
        labels = f'app="portable-http",namespace="{self.namespace}"'
        lines = ['# HELP local_http_requests_total Completed work requests.',
                 '# TYPE local_http_requests_total counter']
        for code, (count, _, _) in rows:
            lines.append(f'local_http_requests_total{{{labels},code="{code}"}} {count}')
        lines += ['# HELP local_http_request_duration_seconds Work request duration in seconds.',
                  '# TYPE local_http_request_duration_seconds histogram']
        for code, (count, total, buckets) in rows:
            for bound, value in zip(BOUNDS, buckets):
                le = '+Inf' if bound == float('inf') else str(bound)
                lines.append(f'local_http_request_duration_seconds_bucket{{{labels},code="{code}",le="{le}"}} {value}')
            lines.append(f'local_http_request_duration_seconds_sum{{{labels},code="{code}"}} {total}')
            lines.append(f'local_http_request_duration_seconds_count{{{labels},code="{code}"}} {count}')
        return ('\n'.join(lines) + '\n').encode()


class Handler(BaseHTTPRequestHandler):
    server: Workload

    def log_message(self, format: str, *args: object) -> None:
        pass

    def respond(self, code: int, body: bytes, content_type: str = 'text/plain; charset=utf-8') -> None:
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == '/metrics':
            self.respond(200, self.server.exposition(), 'text/plain; version=0.0.4; charset=utf-8')
        elif self.path == '/work':
            started = time.perf_counter()
            with self.server.lock:
                failing = time.monotonic() < self.server.failure_until
            code = 503 if failing else 200
            try:
                self.respond(code, b'Controlled failure\n' if failing else b'Work completed\n')
            finally:
                self.server.observe(code, time.perf_counter() - started)
        else:
            self.respond(404, b'Not found\n')

    def do_POST(self) -> None:
        if self.path not in ('/failure/on', '/failure/off'):
            self.respond(404, b'Not found\n')
            return
        with self.server.lock:
            # Reversible and self-expiring; only subsequent real requests produce errors.
            self.server.failure_until = time.monotonic() + 120 if self.path.endswith('/on') else 0.0
        self.respond(200, b'Failure enabled for at most 120 seconds\n' if self.path.endswith('/on') else b'Failure disabled\n')


if __name__ == '__main__':
    server = Workload(('0.0.0.0', 8080), os.environ.get('WORKLOAD_NAMESPACE', 'opentelemetry-demo'))
    try:
        server.serve_forever()
    finally:
        server.server_close()
