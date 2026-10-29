"""Read-only static preview; imports no project services and starts no solver."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).resolve().parents[1] / 'lsprepost_mcp/web/static'


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.serve(False)

    def do_HEAD(self):
        self.serve(True)

    def serve(self, head):
        parsed = urlsplit(self.path)
        if parsed.path.startswith('/api/'):
            self.send_error(404, 'Static preview only; existing project records are untouched')
            return
        routes = {'/cpu-blast': 'cpu_blast.html', '/cpu-blast/': 'cpu_blast.html',
                  '/refined-building-blast': 'index.html',
                  '/fixed-building-pressure': 'fixed_building_preview.html',
                  '/fixed-building-pressure/response': 'fixed_building_response.html',
                  '/structural-pressure': 'fixed_building_tnt.html'}
        name = routes.get(parsed.path)
        if parsed.path.rstrip('/') == '/cpu-blast' and parse_qs(parsed.query).get('legacy') == ['1']:
            name = 'scene_blast.html'
        if name:
            self.path = '/' + name
        elif parsed.path.startswith('/static/'):
            self.path = parsed.path[len('/static'):]
        return super().do_HEAD() if head else super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8918)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(PreviewHandler, directory=str(STATIC)))
    server.serve_forever()
