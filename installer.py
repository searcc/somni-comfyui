#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import os, sys, json, shutil, threading, webbrowser, time
import urllib.request, urllib.error, tempfile, zipfile

GITHUB_REPO = 'searcc/somni-comfyui'

PORT       = 8081
SOMNI_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SOMNI_DIR, 'somni_config.json')

REQUIRED_SOMNI_FILES = ('server.py', 'index.html', 'icon.png')

def _read_local_version():
    try:
        with open(os.path.join(SOMNI_DIR, 'version.txt'), 'r', encoding='utf-8') as f:
            return f.readline().strip().lstrip('v')
    except Exception:
        return ''
SOMNI_VERSION = _read_local_version()

def _send_json(handler, obj, status=200):
    body = json.dumps(obj).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler):
    length = int(handler.headers.get('Content-Length', 0))
    raw = handler.rfile.read(length) if length else b''
    try:
        return json.loads(raw.decode('utf-8')) if raw else {}
    except Exception:
        return {}


def _norm(path):
    return os.path.normpath(os.path.expanduser(path or '').strip().strip('"'))


def _guess_comfyui_dir():
    candidates = [
        os.path.normpath(os.path.join(SOMNI_DIR, '..')),
        r'C:\ComfyUI',
        r'D:\ComfyUI',
        os.path.expanduser(r'~\ComfyUI'),
        os.path.expanduser(r'~\Documents\ComfyUI'),
    ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, 'main.py')):
            return c
    return ''


def _load_saved_config():
    if not os.path.isfile(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _verify_comfy_dir(path):
    p = _norm(path)
    if not p or not os.path.isdir(p):
        return {'ok': False, 'reason': 'Folder does not exist.'}
    if not os.path.isfile(os.path.join(p, 'main.py')):
        return {'ok': False, 'reason': "main.py not found in that folder — doesn't look like ComfyUI."}
    portable = os.path.isfile(os.path.join(p, 'python_embeded', 'python.exe'))
    return {'ok': True, 'path': p, 'portable': portable}


def _verify_venv(path):
    p = _norm(path)
    if not p:
        return {'ok': False, 'reason': 'Provide a venv folder path.'}
    if not os.path.isdir(p):
        return {'ok': False, 'reason': 'Folder does not exist.'}
    activate = os.path.join(p, 'Scripts', 'activate.bat')
    pyexe    = os.path.join(p, 'Scripts', 'python.exe')
    if os.path.isfile(activate) and os.path.isfile(pyexe):
        return {'ok': True, 'path': p, 'activate': activate, 'python': pyexe}
    return {'ok': False, 'reason': 'No Scripts\\activate.bat or python.exe inside — not a venv.'}


def _verify_install_dir(path):
    p = _norm(path)
    if not p:
        return {'ok': False, 'reason': 'Provide an install path.'}
    if os.path.isdir(p):
        ok = all(os.path.isfile(os.path.join(p, f)) for f in REQUIRED_SOMNI_FILES)
        if ok:
            return {'ok': True, 'path': p, 'note': 'Existing somni install found here.'}
        return {'ok': True, 'path': p, 'note': 'Folder exists; somni files will be copied here.'}
    return {'ok': True, 'path': p, 'note': 'Folder will be created.'}


def _bat_quote(path):
    return '"' + path.replace('"', '') + '"'


def _do_install(cfg):
    comfy_dir   = _norm(cfg.get('comfyDir'))
    python_mode = cfg.get('pythonMode', 'system')
    venv_dir    = _norm(cfg.get('venvDir'))
    install_dir = _norm(cfg.get('installDir')) or os.path.join(comfy_dir, 'somni') if comfy_dir else SOMNI_DIR
    open_browser = bool(cfg.get('openBrowser', True))
    boot_delay   = int(cfg.get('bootDelay', 8) or 8)

    v = _verify_comfy_dir(comfy_dir)
    if not v['ok']:
        raise RuntimeError(f"ComfyUI path: {v['reason']}")
    comfy_dir = v['path']

    if python_mode == 'venv':
        vv = _verify_venv(venv_dir)
        if not vv['ok']:
            raise RuntimeError(f"Virtual env: {vv['reason']}")

    if python_mode == 'portable':
        if not os.path.isfile(os.path.join(comfy_dir, 'python_embeded', 'python.exe')):
            raise RuntimeError("Portable Python not found at <ComfyUI>/python_embeded/python.exe.")

    os.makedirs(install_dir, exist_ok=True)
    copy_list = list(REQUIRED_SOMNI_FILES) + ['icon.ico', 'version.txt', 'README.md', 'LICENSE']
    for fname in copy_list:
        src = os.path.join(SOMNI_DIR, fname)
        if os.path.isfile(src) and os.path.normcase(src) != os.path.normcase(os.path.join(install_dir, fname)):
            shutil.copy2(src, os.path.join(install_dir, fname))

    somni_py_quoted = _bat_quote(sys.executable)

    if python_mode == 'portable':
        comfy_start = (
            f'cd /d {_bat_quote(comfy_dir)} && '
            f'{_bat_quote(os.path.join(comfy_dir, "python_embeded", "python.exe"))} -s main.py'
        )
    elif python_mode == 'venv':
        activate = os.path.join(venv_dir, 'Scripts', 'activate.bat')
        comfy_start = (
            f'call {_bat_quote(activate)} && '
            f'cd /d {_bat_quote(comfy_dir)} && '
            f'python main.py'
        )
    else:
        comfy_start = f'cd /d {_bat_quote(comfy_dir)} && python main.py'

    somni_cmd = f'{somni_py_quoted} server.py'
    if open_browser:
        somni_cmd += ' --open'

    somni_only = (
        "@echo off\r\n"
        "title somni\r\n"
        f'cd /d {_bat_quote(install_dir)}\r\n'
        f'{somni_cmd}\r\n'
    )
    with open(os.path.join(install_dir, 'launch_somni.bat'), 'w', encoding='utf-8') as f:
        f.write(somni_only)

    parts = ["@echo off", "title ComfyUI + somni", ""]
    parts.append(f'start "ComfyUI" cmd /k "{comfy_start}"')
    parts.append("")
    parts.append(f"timeout /t {boot_delay} /nobreak >nul")
    parts.append("")
    parts.append(f'cd /d {_bat_quote(install_dir)}')
    parts.append(somni_cmd)
    parts.append("")
    with open(os.path.join(install_dir, 'launch_comfyui_and_somni.bat'), 'w', encoding='utf-8') as f:
        f.write("\r\n".join(parts))

    saved = {
        'comfyDir':    comfy_dir,
        'pythonMode':  python_mode,
        'venvDir':     venv_dir if python_mode == 'venv' else '',
        'installDir':  install_dir,
        'openBrowser': open_browser,
        'bootDelay':   boot_delay,
        'somniPython': sys.executable,
    }
    try:
        with open(os.path.join(install_dir, 'somni_config.json'), 'w', encoding='utf-8') as f:
            json.dump(saved, f, indent=2)
    except Exception:
        pass

    return {
        'installDir': install_dir,
        'files': ['launch_somni.bat', 'launch_comfyui_and_somni.bat', 'somni_config.json'],
    }


def _fetch_latest_release():
    if not GITHUB_REPO or '/' not in GITHUB_REPO or 'OWNER' in GITHUB_REPO:
        return None
    try:
        req = urllib.request.Request(
            f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'somni-installer'}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None


def _check_for_update():
    info = _fetch_latest_release()
    if not info:
        return {'local': SOMNI_VERSION, 'latest': '', 'hasUpdate': False, 'error': 'GitHub unreachable or repo not configured.'}
    tag = (info.get('tag_name') or '').lstrip('v')
    return {
        'local': SOMNI_VERSION,
        'latest': tag,
        'hasUpdate': bool(tag and SOMNI_VERSION and tag != SOMNI_VERSION),
        'name': info.get('name') or '',
        'htmlUrl': info.get('html_url') or '',
        'body': info.get('body') or '',
    }


def _pick_release_zip_url(info):
    for asset in (info.get('assets') or []):
        name = (asset.get('name') or '').lower()
        if name.endswith('.zip'):
            return asset.get('browser_download_url')
    return info.get('zipball_url')


def _fetch_release_by_tag(tag):
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}', headers={'User-Agent': 'somni-installer'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None

def _do_install_version(version):
    if version == 'latest':
        info = _fetch_latest_release()
    else:
        info = _fetch_release_by_tag(version)
    if not info:
        raise RuntimeError('Could not reach GitHub. Check your internet or the GITHUB_REPO constant.')
    url = _pick_release_zip_url(info)
    if not url:
        raise RuntimeError('No release zip found on GitHub for the specified tag.')

    fd, tmp_zip = tempfile.mkstemp(suffix='.zip', prefix='somni-update-')
    os.close(fd)
    req = urllib.request.Request(url, headers={'User-Agent': 'somni-installer'})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp_zip, 'wb') as out:
        shutil.copyfileobj(r, out)

    tmp_dir = tempfile.mkdtemp(prefix='somni-update-')
    try:
        with zipfile.ZipFile(tmp_zip) as z:
            z.extractall(tmp_dir)
        entries = os.listdir(tmp_dir)
        root = tmp_dir
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp_dir, entries[0])):
            root = os.path.join(tmp_dir, entries[0])

        preserved = {'somni_config.json', 'launch_somni.bat', 'launch_comfyui_and_somni.bat'}
        for name in os.listdir(root):
            if name in preserved:
                continue
            src = os.path.join(root, name)
            dst = os.path.join(SOMNI_DIR, name)
            if os.path.isdir(src):
                if os.path.isdir(dst):
                    for sub in os.listdir(src):
                        ssub, dsub = os.path.join(src, sub), os.path.join(dst, sub)
                        if os.path.isdir(ssub):
                            shutil.copytree(ssub, dsub, dirs_exist_ok=True)
                        else:
                            shutil.copy2(ssub, dsub)
                else:
                    shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
    finally:
        try: os.remove(tmp_zip)
        except Exception: pass
        try: shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception: pass

    new_version = ''
    try:
        with open(os.path.join(SOMNI_DIR, 'version.txt'), 'r', encoding='utf-8') as f:
            new_version = f.readline().strip().lstrip('v')
    except Exception:
        pass
    return {'newVersion': new_version}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        if self.path in ('/', '/index.html', '/installer'):
            self._serve_file(os.path.join(SOMNI_DIR, 'installer.html'), 'text/html; charset=utf-8')
            return
        if self.path == '/icon.png':
            self._serve_file(os.path.join(SOMNI_DIR, 'icon.png'), 'image/png')
            return
        if self.path.startswith('/fonts/'):
            font_path = os.path.join(SOMNI_DIR, self.path.lstrip('/'))
            if os.path.exists(font_path):
                ext = os.path.splitext(font_path)[1].lower()
                mime = 'font/woff2' if ext == '.woff2' else 'font/woff' if ext == '.woff' else 'font/ttf' if ext == '.ttf' else 'application/octet-stream'
                self._serve_file(font_path, mime)
                return
        if self.path == '/api/detect':
            saved = _load_saved_config()
            _send_json(self, {
                'somniDir':     SOMNI_DIR,
                'guessedComfy': saved.get('comfyDir') or _guess_comfyui_dir(),
                'savedConfig':  saved,
                'version':      SOMNI_VERSION,
                'repo':         GITHUB_REPO,
            })
            return
        if self.path == '/api/check-update':
            _send_json(self, _check_for_update())
            return
        self.send_error(404)

    def do_POST(self):
        body = _read_json_body(self)
        if self.path == '/api/verify-comfy':
            _send_json(self, _verify_comfy_dir(body.get('path', '')))
            return
        if self.path == '/api/verify-venv':
            _send_json(self, _verify_venv(body.get('path', '')))
            return
        if self.path == '/api/verify-install':
            _send_json(self, _verify_install_dir(body.get('path', '')))
            return
        if self.path == '/api/install':
            try:
                result = _do_install(body)
                _send_json(self, {'ok': True, **result})
            except Exception as e:
                _send_json(self, {'ok': False, 'error': str(e)})
            return
        if self.path == '/api/install-update':
            try:
                result = _do_install_version('latest')
                _send_json(self, {'ok': True, **result})
            except Exception as e:
                _send_json(self, {'ok': False, 'error': str(e)})
            return
        if self.path == '/api/install-version':
            try:
                version = body.get('version', 'latest')
                result = _do_install_version(version)
                _send_json(self, {'ok': True, **result})
            except Exception as e:
                _send_json(self, {'ok': False, 'error': str(e)})
            return
        if self.path == '/api/install-zip':
            try:
                content_type = self.headers.get('Content-Type', '')
                if 'multipart/form-data' in content_type:
                    boundary = content_type.split('boundary=')[1].encode()
                    body_bytes = self.rfile.read(int(self.headers['Content-Length']))
                    
                    parts = body_bytes.split(b'--' + boundary)
                    zip_data = None
                    version = ''
                    
                    for part in parts[1:-1]:
                        if b'name="zip"' in part:
                            headers_end = part.find(b'\r\n\r\n')
                            if headers_end != -1:
                                zip_data = part[headers_end + 4:]
                        if b'name="version"' in part:
                            headers_end = part.find(b'\r\n\r\n')
                            if headers_end != -1:
                                version = part[headers_end + 4:].decode('utf-8').strip()
                    
                    if not zip_data:
                        raise RuntimeError('No zip file provided')
                    
                    fd, tmp_zip = tempfile.mkstemp(suffix='.zip', prefix='somni-update-')
                    os.close(fd)
                    with open(tmp_zip, 'wb') as f:
                        f.write(zip_data)
                    
                    tmp_dir = tempfile.mkdtemp(prefix='somni-update-')
                    try:
                        with zipfile.ZipFile(tmp_zip) as z:
                            z.extractall(tmp_dir)
                        entries = os.listdir(tmp_dir)
                        root = tmp_dir
                        if len(entries) == 1 and os.path.isdir(os.path.join(tmp_dir, entries[0])):
                            root = os.path.join(tmp_dir, entries[0])
                        for item in REQUIRED_SOMNI_FILES:
                            src = os.path.join(root, item)
                            dst = os.path.join(SOMNI_DIR, item)
                            if os.path.exists(src):
                                if os.path.isdir(src):
                                    if os.path.exists(dst):
                                        shutil.rmtree(dst)
                                    shutil.copytree(src, dst)
                                else:
                                    shutil.copy2(src, dst)
                    finally:
                        try: os.remove(tmp_zip)
                        except Exception: pass
                        try: shutil.rmtree(tmp_dir, ignore_errors=True)
                        except Exception: pass
                    
                    new_version = version
                    _send_json(self, {'ok': True, 'newVersion': new_version})
                else:
                    raise RuntimeError('Expected multipart/form-data')
            except Exception as e:
                _send_json(self, {'ok': False, 'error': str(e)})
            return
        self.send_error(404)

    def _serve_file(self, path, mime):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_error(404, 'Not found')
        except Exception as e:
            self.send_error(500, str(e))

    def log_message(self, fmt, *args):
        sys.stdout.write(f'  [installer] {self.address_string()} - {fmt % args}\n')


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _open_browser_soon(url):
    def _t():
        time.sleep(0.5)
        try: webbrowser.open(url)
        except Exception: pass
    threading.Thread(target=_t, daemon=True).start()


if __name__ == '__main__':
    url = f'http://localhost:{PORT}/'
    print('=' * 60)
    print('  somni installer')
    print('=' * 60)
    print(f'  Open in your browser: {url}')
    print('  Press Ctrl+C in this window to quit.')
    print()
    _open_browser_soon(url)
    try:
        ThreadedServer(('127.0.0.1', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\n  Installer closed.')
