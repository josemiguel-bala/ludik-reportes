#!/usr/bin/env python3
"""
Recorre un JSON de reporte, encuentra TODAS las URLs externas en campos
de imagen (coverImageUrl, imageUrl, image, thumbnail) y las descarga
localmente. Reemplaza la URL en el JSON por el path relativo local.

Idempotente — si la imagen ya existe localmente, skip.
Dinámico — no hardcodea canales ni rutas del schema; recorre recursivamente.

Uso:
  python3 download_thumbnails.py data/WELLAPRO_2026-04.json
  python3 download_thumbnails.py data/*.json
  python3 download_thumbnails.py --all   # procesa todos los data/*.json
"""

import argparse
import glob
import hashlib
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Campos del JSON que se considera "url de imagen"
IMAGE_FIELDS = {'coverImageUrl', 'imageUrl', 'image', 'thumbnail', 'cover', 'photo'}

# Prefijos que indican "ya es local, no descargar"
LOCAL_PREFIXES = ('images/', 'img/', '/images/', '/img/', './images/', './img/')

# Timeout descarga (seg)
TIMEOUT = 15

# Sleep entre descargas (anti rate-limit IG/TikTok CDN). Seg.
THROTTLE = 1.2

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

# Referer por host: algunos CDNs (Instagram, TikTok) bloquean si no viene de su propio dominio
HOST_REFERER = {
    'cdninstagram.com': 'https://www.instagram.com/',
    'fbcdn.net': 'https://www.facebook.com/',
    'tiktokcdn.com': 'https://www.tiktok.com/',
    'tiktokcdn-us.com': 'https://www.tiktok.com/',
    'tiktok.com': 'https://www.tiktok.com/',
    'ytimg.com': 'https://www.youtube.com/',
    'linkedin.com': 'https://www.linkedin.com/'
}

def referer_for(url: str) -> str:
    for host, ref in HOST_REFERER.items():
        if host in url:
            return ref
    return ''


def is_external_url(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if s.startswith(LOCAL_PREFIXES):
        return False
    return s.startswith(('http://', 'https://'))


def url_extension(url: str) -> str:
    """Extrae la extensión del archivo de la URL (.jpg, .png, etc.) o .jpg por defecto"""
    path = url.split('?')[0].split('#')[0]
    m = re.search(r'\.(jpe?g|png|gif|webp|mp4|mov)$', path, re.IGNORECASE)
    if m:
        return '.' + m.group(1).lower().replace('jpeg', 'jpg')
    # Heurística por content-type query
    if 'video' in url.lower():
        return '.mp4'
    return '.jpg'


def stable_filename(url: str) -> str:
    """Hash sha1[:12] de la URL para nombre estable e idempotente"""
    h = hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]
    return h + url_extension(url)


def download(url: str, dest: Path) -> bool:
    """Descarga url a dest. Devuelve True si OK, False si falla."""
    if dest.exists() and dest.stat().st_size > 0:
        return True  # idempotente
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
        'Accept-Language': 'es-PE,es;q=0.9,en;q=0.8'
    }
    ref = referer_for(url)
    if ref:
        headers['Referer'] = ref
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            if not data:
                return False
            tmp = dest.with_suffix(dest.suffix + '.tmp')
            tmp.write_bytes(data)
            tmp.rename(dest)
            return True
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
        print(f'  ⚠ Falló descarga de {url[:60]}... → {e}')
        return False


def walk_and_download(node, image_dir: Path, rel_prefix: str, stats: dict, parent_key: str = '', breadcrumb: str = ''):
    """
    Recorre el JSON recursivamente. Cuando encuentra un campo de imagen con URL externa:
      1. Descarga a image_dir/<hash>.<ext>
      2. Reemplaza el valor en el JSON por rel_prefix + <hash>.<ext>
    """
    if isinstance(node, dict):
        for k, v in list(node.items()):
            new_breadcrumb = f'{breadcrumb}.{k}' if breadcrumb else k
            if k in IMAGE_FIELDS and isinstance(v, str) and is_external_url(v):
                fname = stable_filename(v)
                dest = image_dir / fname
                stats['found'] += 1
                if dest.exists() and dest.stat().st_size > 0:
                    stats['cached'] += 1
                    node[k] = rel_prefix + fname
                    continue
                # Throttle anti rate-limit (IG/TikTok CDN bloquean ráfagas)
                if stats['downloaded'] > 0:
                    time.sleep(THROTTLE)
                ok = download(v, dest)
                if not ok:
                    # Retry una vez con backoff más largo
                    time.sleep(3)
                    ok = download(v, dest)
                if ok:
                    stats['downloaded'] += 1
                    node[k] = rel_prefix + fname
                    print(f'  ✓ {new_breadcrumb} → {fname}')
                else:
                    stats['failed'] += 1
            else:
                walk_and_download(v, image_dir, rel_prefix, stats, k, new_breadcrumb)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk_and_download(item, image_dir, rel_prefix, stats, parent_key, f'{breadcrumb}[{i}]')


def process_json(json_path: Path) -> dict:
    """Procesa un JSON: descarga imágenes externas y guarda el JSON actualizado."""
    with json_path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    brand_id = (data.get('brand_id') or data.get('brand') or json_path.stem.split('_')[0]).lower()
    # Limpia caracteres no aptos para path
    brand_id = re.sub(r'[^a-z0-9_-]', '', brand_id) or 'unknown'
    period = data.get('period') or 'unknown'
    period = re.sub(r'[^a-zA-Z0-9_-]', '', period) or 'unknown'

    # Directorio destino (relativo al JSON, que vive en data/, así que ../images/ desde el JSON o images/ desde la raíz del app)
    app_root = json_path.parent.parent if json_path.parent.name == 'data' else json_path.parent
    image_dir = app_root / 'images' / brand_id / period
    # Rel prefix tal como debe quedar en el JSON (relativo a reporte.html que vive en app root)
    rel_prefix = f'images/{brand_id}/{period}/'

    print(f'\n→ {json_path.name}  (brand={brand_id}, period={period})')

    stats = {'found': 0, 'downloaded': 0, 'cached': 0, 'failed': 0}
    walk_and_download(data, image_dir, rel_prefix, stats)

    if stats['downloaded'] > 0 or (stats['cached'] > 0 and stats['failed'] == 0):
        with json_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'  → found={stats["found"]}  downloaded={stats["downloaded"]}  cached={stats["cached"]}  failed={stats["failed"]}')
    return stats


def main():
    parser = argparse.ArgumentParser(description='Descarga thumbnails externos de un JSON de reporte y reemplaza por path local.')
    parser.add_argument('paths', nargs='*', help='JSONs a procesar')
    parser.add_argument('--all', action='store_true', help='Procesa todos los data/*.json')
    args = parser.parse_args()

    if args.all:
        script_dir = Path(__file__).parent
        targets = sorted(script_dir.glob('data/*.json'))
        # Excluir manifest.json
        targets = [t for t in targets if t.name != 'manifest.json']
    else:
        targets = []
        for p in args.paths:
            for m in glob.glob(p):
                targets.append(Path(m))

    if not targets:
        print('No hay JSONs que procesar.', file=sys.stderr)
        sys.exit(1)

    grand = {'found': 0, 'downloaded': 0, 'cached': 0, 'failed': 0}
    for t in targets:
        s = process_json(t)
        for k in grand:
            grand[k] += s[k]

    print(f'\n═══ TOTAL ═══  found={grand["found"]}  downloaded={grand["downloaded"]}  cached={grand["cached"]}  failed={grand["failed"]}')


if __name__ == '__main__':
    main()
