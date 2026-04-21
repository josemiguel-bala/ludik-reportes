#!/usr/bin/env python3
"""
LUDiK Report Server
Sirve la app + endpoint POST /save para guardar JSONs desde el admin.
Al guardar, automáticamente sube a Vercel (deploy público).
Uso: python3 server.py [puerto]
"""
import http.server
import json
import os
import sys
import subprocess
import threading

import re

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, 'data')

def rebuild_manifest():
    """Scan data/ for BRAND_YYYY-MM.json files and rebuild manifest.json."""
    manifest = {}
    pattern = re.compile(r'^([A-Z0-9]+)_(\d{4}-\d{2})\.json$')
    for fname in os.listdir(DATA_DIR):
        m = pattern.match(fname)
        if m:
            brand, period = m.groups()
            manifest.setdefault(brand, []).append(period)
    for brand in manifest:
        manifest[brand].sort(reverse=True)
    manifest_path = os.path.join(DATA_DIR, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  📋 Manifest actualizado: {len(manifest)} marcas")

# Build manifest on startup
rebuild_manifest()

def deploy_to_vercel(filename):
    """Deploy to Vercel in background after saving."""
    try:
        # Git add + commit + push
        subprocess.run(['git', 'add', f'data/{filename}', 'data/manifest.json'], cwd=APP_DIR, capture_output=True)
        subprocess.run(['git', 'commit', '-m', f'Update {filename} from admin'], cwd=APP_DIR, capture_output=True)
        # Deploy to Vercel
        result = subprocess.run(['vercel', '--prod', '--yes'], cwd=APP_DIR, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            print(f"  🚀 Deployado a Vercel: {filename}")
        else:
            print(f"  ⚠ Vercel deploy falló: {result.stderr[:200]}")
    except Exception as e:
        print(f"  ⚠ Deploy error: {e}")

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
                self.wfile.write(json.dumps({"ok": True, "file": filename, "deploying": True}).encode())
                print(f"  ✓ Guardado: data/{filename}")
                rebuild_manifest()
                # Deploy en background (no bloquea la respuesta al admin)
                threading.Thread(target=deploy_to_vercel, args=(filename,), daemon=True).start()
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
print(f"  Auto-deploy a Vercel: ACTIVADO")
http.server.HTTPServer(('', PORT), ReportHandler).serve_forever()
