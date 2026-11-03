"""Small generic application used only by the container smoke test."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

state = Path('/data/hub/starts.txt')
starts = int(state.read_text()) + 1 if state.exists() else 1
state.write_text(str(starts))
body = json.dumps({'version': Path('app.jar').read_text().strip(), 'starts': starts}).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)


HTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
