#!/usr/bin/env python3
"""
LUDiK Report Server
Sirve la app + endpoint POST /save para guardar JSONs desde el admin.
Uso: python3 server.py [puerto]
"""
import http.server
import json
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')

class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def do_POST(self):
        if self.path == '/save':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length))
                brand_id = body.get('brand_id', 'UNKNOWN')
                period = body.get('period', 'draft')
                filename = f"{brand_id}_{period}.json"
                filepath = os.path.join(DATA_DIR, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(body, f, ensure_ascii=False, indent=2)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "file": filename}).encode())
                print(f"  ✓ Guardado: data/{filename}")
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

print(f"LUDiK Report Server → http://localhost:{PORT}")
print(f"  Admin:   http://localhost:{PORT}/admin.html")
print(f"  Reporte: http://localhost:{PORT}/reporte.html")
print(f"  Data:    {DATA_DIR}/")
http.server.HTTPServer(('', PORT), ReportHandler).serve_forever()
