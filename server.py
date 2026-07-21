#!/usr/bin/env python3
"""somni proxy: serves index.html and forwards HTTP + WebSocket to ComfyUI,
stripping Origin/Referer so ComfyUI's loopback host-origin check passes."""
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.request, urllib.error, urllib.parse
import os, sys, json, socket, threading, time, webbrowser
import tempfile, zipfile, shutil, subprocess
import hashlib, secrets, http.cookies



# ----------------------------------------------------------------------
GITHUB_REPO = 'searcc/somni-comfyui'
# ----------------------------------------------------------------------

# This stays 127.0.0.1 because the proxy talks to ComfyUI on the same PC
COMFY  = 'http://127.0.0.1:8188'
DIR    = os.path.dirname(os.path.abspath(__file__))
PARSED = urllib.parse.urlparse(COMFY)

# ── Custom: Auth ──────────────────────────────────────────────────────
AUTH_FILE = os.path.join(DIR, 'somni_users.json')
ACTIVE_SESSIONS = {} # token -> username

def _hash(val):
    return hashlib.sha256(val.encode('utf-8')).hexdigest()

def _has_users():
    return os.path.isfile(AUTH_FILE) and os.path.getsize(AUTH_FILE) > 2

def _get_authenticated_user(headers):
    if not _has_users():
        return None
    cookie_header = headers.get('Cookie')
    if cookie_header:
        cookies = http.cookies.SimpleCookie(cookie_header)
        if 'somni_session' in cookies:
            token = cookies['somni_session'].value
            return ACTIVE_SESSIONS.get(token)
    return None

def _is_authenticated(headers):
    return _get_authenticated_user(headers) is not None

def _read_local_version():
    try:
        with open(os.path.join(DIR, 'version.txt'), 'r', encoding='utf-8') as f:
            return f.readline().strip().lstrip('v')
    except Exception:
        return ''

SOMNI_VERSION = _read_local_version()

def _resolve_comfy_root():
    """Resolve the ComfyUI root folder for output/input/temp directory lookups.
    Priority: somni_config.json comfyDir → parent of DIR (legacy)."""
    cfg_path = os.path.join(DIR, 'somni_config.json')
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            d = cfg.get('comfyDir')
            if d and os.path.isdir(d):
                return d
        except Exception:
            pass
    # Fall back: assume somni is a child of ComfyUI (legacy layout)
    return os.path.normpath(os.path.join(DIR, '..'))

COMFY_ROOT = _resolve_comfy_root()
TYPE_DIRS  = {
    'output': os.path.join(COMFY_ROOT, 'output'),
    'input':  os.path.join(COMFY_ROOT, 'input'),
    'temp':   os.path.join(COMFY_ROOT, 'temp'),
}

SKIP_REQ_HEADERS  = {'host', 'content-length', 'connection', 'origin', 'referer'}
SKIP_RESP_HEADERS = {'transfer-encoding', 'connection'}

# ── Self-update helpers ───────────────────────────────────────────────
def _fetch_latest_release_info():
    if not GITHUB_REPO or '/' not in GITHUB_REPO or 'OWNER' in GITHUB_REPO:
        return None
    try:
        req = urllib.request.Request(
            f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'somni'}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception:
        return None

def _pick_release_zip_url(info):
    for asset in (info.get('assets') or []):
        if (asset.get('name') or '').lower().endswith('.zip'):
            return asset.get('browser_download_url')
    return info.get('zipball_url')

def _do_self_update(nightly=False):
    """Download latest release, extract runtime files into DIR. Returns new version string."""
    if nightly:
        try:
            req = urllib.request.Request(
                f'https://api.github.com/repos/{GITHUB_REPO}/releases/tags/nightly',
                headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'somni'}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                info = json.loads(r.read().decode('utf-8'))
        except Exception:
            raise RuntimeError('Could not reach GitHub nightly release. Check your internet or GITHUB_REPO constant.')
    else:
        info = _fetch_latest_release_info()
        if not info:
            raise RuntimeError('Could not reach GitHub. Check your internet or GITHUB_REPO constant.')
    url = _pick_release_zip_url(info)
    if not url:
        raise RuntimeError('No release zip found.')

    fd, tmp_zip = tempfile.mkstemp(suffix='.zip', prefix='somni-update-')
    os.close(fd)
    req = urllib.request.Request(url, headers={'User-Agent': 'somni'})
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

        # Per-user files we never touch + installer files we never copy.
        preserved = {'somni_config.json', 'launch_somni.bat', 'launch_comfyui_and_somni.bat'}
        exclude   = {'installer.bat', 'installer.py', 'installer.html'}
        for name in os.listdir(root):
            if name in preserved or name in exclude:
                continue
            src = os.path.join(root, name)
            dst = os.path.join(DIR, name)
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

    try:
        with open(os.path.join(DIR, 'version.txt'), 'r', encoding='utf-8') as f:
            return f.readline().strip().lstrip('v')
    except Exception:
        return ''

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            if _has_users() and not _is_authenticated(self.headers):
                self.send_error(401, "Unauthorized")
                return
            self._proxy_ws()
            return

        # ── Logout via GET (browser navigation) ──
        if self.path == '/api/auth/logout':
            cookie_header = self.headers.get('Cookie')
            if cookie_header:
                cookies = http.cookies.SimpleCookie(cookie_header)
                if 'somni_session' in cookies:
                    token = cookies['somni_session'].value
                    user_to_clear = ACTIVE_SESSIONS.get(token)
                    if user_to_clear:
                        tokens_to_remove = [t for t, u in ACTIVE_SESSIONS.items() if u == user_to_clear]
                        for t in tokens_to_remove:
                            ACTIVE_SESSIONS.pop(t, None)
                        print(f"LOGOUT: Cleared all sessions for {user_to_clear}")
                    else:
                        ACTIVE_SESSIONS.pop(token, None)
            self.send_response(302)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', 'somni_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

        # Serve index.html
        if self.path in ('/', '/index.html'):
            self._serve_file(os.path.join(DIR, 'index.html'), 'text/html')
            return

        # Serve favicon.ico locally
        if self.path == '/favicon.ico':
            self._serve_file(os.path.join(DIR, 'favicon.ico'), 'image/x-icon')
            return

        # ── Custom: auth status ──────────────────────────────
        if self.path == '/api/auth/status':
            user = _get_authenticated_user(self.headers)
            hostname = socket.gethostname()
            body = json.dumps({
                'authenticated': user is not None,
                'username': user,
                'hostname': hostname,
                'has_users': _has_users()
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        is_static = self.path in ('/', '/index.html', '/favicon.ico', '/icon.ico', '/icon.png', '/icon-256.ico')
        if not is_static and _has_users() and not _is_authenticated(self.headers):
            self.send_error(401, "Unauthorized")
            return

        # ── Custom: version + update check ─────────────────────────
        if self.path == '/api/version':
            local_ver = _read_local_version()
            body = __import__('json').dumps({'version': local_ver, 'repo': GITHUB_REPO}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/api/check-update':
            self._handle_check_update()
            return

        # ── Custom: list output files ──────────────────────────────
        if self.path.startswith('/__list'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            folder_type = qs.get('type', ['output'])[0]
            folder = TYPE_DIRS.get(folder_type)
            items = []
            if folder and os.path.isdir(folder):
                for fname in sorted(os.listdir(folder), key=lambda f: os.path.getmtime(os.path.join(folder, f)), reverse=True):
                    if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.webm')):
                        items.append({'filename': fname, 'subfolder': '', 'type': folder_type})
            # If directory doesn't exist or is empty, return 404 to trigger frontend fallback to ComfyUI history API
            if not items:
                self.send_error(404, "Directory not found or empty")
                return
            body = __import__('json').dumps(items).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', len(body))
            self.end_headers()
            self.wfile.write(body)
            return

        # Serve other local assets (like icon.jpg) if they exist in the folder
        local_path = os.path.join(DIR, self.path.lstrip('/'))
        if os.path.isfile(local_path):
            ext = os.path.splitext(local_path)[1].lower()
            mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.css': 'text/css', '.js': 'text/javascript'}.get(ext, 'application/octet-stream')
            self._serve_file(local_path, mime)
            return

        # Otherwise, proxy to ComfyUI
        self._proxy_http()

    def do_POST(self):
        # ── Custom: start ComfyUI ───────────────────────────────────────
        if self.path.startswith('/api/start-comfyui'):
            import json as _json
            print(f"DEBUG: start-comfyui endpoint called, path={self.path}")
            if self.command != 'POST':
                self.send_error(405, 'Method Not Allowed')
                return
            try:
                # Find and run start_comfyui.bat
                comfy_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                print(f"DEBUG: comfy_dir={comfy_dir}")
                bat_path = os.path.join(comfy_dir, 'run_nvidia_gpu.bat')
                if not os.path.exists(bat_path):
                    bat_path = os.path.join(comfy_dir, 'start_comfyui.bat')
                if not os.path.exists(bat_path):
                    bat_path = os.path.join(comfy_dir, 'run_cpu.bat')
                print(f"DEBUG: bat_path={bat_path}, exists={os.path.exists(bat_path)}")
                
                if os.path.exists(bat_path):
                    subprocess.Popen([bat_path], shell=True, cwd=comfy_dir)
                    body = _json.dumps({'ok': True}).encode()
                    self.send_response(200)
                else:
                    body = _json.dumps({'ok': False, 'error': 'Could not find ComfyUI startup script'}).encode()
                    self.send_response(404)
                
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                print(f"DEBUG: start-comfyui response sent")
            except Exception as e:
                print(f"DEBUG: start-comfyui error: {e}")
                body = _json.dumps({'ok': False, 'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            return

        # ── Custom: Auth Endpoints ─────────────────────────────────
        if self.path == '/api/auth/register':
            import json as _json
            content_len = int(self.headers.get('Content-Length', 0))
            payload = _json.loads(self.rfile.read(content_len))
            if _has_users():
                self.send_error(400, "Account already exists")
                return
            hostname = socket.gethostname()
            password = payload.get('password', '')
            recovery = payload.get('recovery', '')
            if not password or not recovery:
                self.send_error(400, "Missing credentials")
                return
            with open(AUTH_FILE, 'w', encoding='utf-8') as f:
                _json.dump({hostname: {
                    'password': _hash(password),
                    'recovery': _hash(recovery)
                }}, f)
            token = secrets.token_hex(32)
            ACTIVE_SESSIONS[token] = hostname
            self.send_response(200)
            self.send_header('Set-Cookie', f'somni_session={token}; Path=/; HttpOnly; SameSite=Lax')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return

        if self.path == '/api/auth/login':
            import json as _json
            content_len = int(self.headers.get('Content-Length', 0))
            payload = _json.loads(self.rfile.read(content_len))
            password = payload.get('password', '')
            hostname = socket.gethostname()
            try:
                with open(AUTH_FILE, 'r', encoding='utf-8') as f:
                    users = _json.load(f)
            except Exception:
                users = {}
            # Find the account (there's only one)
            user_key = hostname if hostname in users else (list(users.keys())[0] if users else None)
            user_data = users.get(user_key) if user_key else None
            if user_data:
                stored_hash = user_data['password'] if isinstance(user_data, dict) else user_data
                if stored_hash == _hash(password):
                    token = secrets.token_hex(32)
                    ACTIVE_SESSIONS[token] = user_key
                    self.send_response(200)
                    self.send_header('Set-Cookie', f'somni_session={token}; Path=/; HttpOnly; SameSite=Lax')
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"ok":true}')
                    return
            self.send_error(401, "Wrong password")
            return

        if self.path == '/api/change-password':
            import json as _json
            user = _get_authenticated_user(self.headers)
            if not user:
                self.send_error(401, "Not authenticated")
                return
            content_len = int(self.headers.get('Content-Length', 0))
            payload = _json.loads(self.rfile.read(content_len))
            current_password = payload.get('currentPassword', '')
            new_password = payload.get('newPassword', '')
            
            if not current_password or not new_password:
                body = _json.dumps({'ok': False, 'error': 'Missing password fields'}).encode()
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            
            try:
                with open(AUTH_FILE, 'r', encoding='utf-8') as f:
                    users = _json.load(f)
            except Exception:
                body = _json.dumps({'ok': False, 'error': 'Failed to read user data'}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            
            user_data = users.get(user)
            if not user_data:
                body = _json.dumps({'ok': False, 'error': 'User not found'}).encode()
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            
            stored_hash = user_data['password'] if isinstance(user_data, dict) else user_data
            if stored_hash != _hash(current_password):
                body = _json.dumps({'ok': False, 'error': 'Current password is incorrect'}).encode()
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            
            # Update password
            if isinstance(user_data, dict):
                user_data['password'] = _hash(new_password)
            else:
                users[user] = {'password': _hash(new_password)}
            
            try:
                with open(AUTH_FILE, 'w', encoding='utf-8') as f:
                    _json.dump(users, f)
                body = _json.dumps({'ok': True}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = _json.dumps({'ok': False, 'error': 'Failed to update password'}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            return

        if self.path == '/api/auth/logout':
            print("DEBUG: Logout called")
            cookie_header = self.headers.get('Cookie')
            if cookie_header:
                cookies = http.cookies.SimpleCookie(cookie_header)
                if 'somni_session' in cookies:
                    token = cookies['somni_session'].value
                    user_to_clear = ACTIVE_SESSIONS.get(token)
                    if user_to_clear:
                        # Aggressively clear all sessions for this user
                        tokens_to_remove = [t for t, u in ACTIVE_SESSIONS.items() if u == user_to_clear]
                        for t in tokens_to_remove:
                            ACTIVE_SESSIONS.pop(t, None)
                        print(f"DEBUG: Cleared {len(tokens_to_remove)} sessions for {user_to_clear}")
                    else:
                        ACTIVE_SESSIONS.pop(token, None)
            self.send_response(200)
            self.send_header('Set-Cookie', 'somni_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT')
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            print("DEBUG: Logout success")
            return

        if self.path == '/api/auth/reset':
            import json as _json
            content_len = int(self.headers.get('Content-Length', 0))
            payload = _json.loads(self.rfile.read(content_len))
            recovery = payload.get('recovery', '')
            new_password = payload.get('password', '')
            if not recovery or not new_password:
                self.send_error(400, 'Missing fields')
                return
            try:
                with open(AUTH_FILE, 'r', encoding='utf-8') as f:
                    users = _json.load(f)
            except Exception:
                users = {}
            hostname = socket.gethostname()
            user_data = users.get(hostname)
            if user_data and isinstance(user_data, dict) and user_data.get('recovery') == _hash(recovery):
                user_data['password'] = _hash(new_password)
                with open(AUTH_FILE, 'w', encoding='utf-8') as f:
                    _json.dump(users, f)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                return
            self.send_error(401, "Invalid recovery key")
            return

        # ── Custom: install custom node ───────────────────────────────
        if self.path.startswith('/api/install-node/'):
            import json as _json
            node_name = self.path.split('/')[-1]
            custom_nodes_dir = os.path.join(COMFY_ROOT, 'custom_nodes')
            
            # Map node names to their GitHub repos
            node_repos = {
                'save-image-extended-comfyui': 'https://github.com/audioscavenger/save-image-extended-comfyui.git'
            }
            
            if node_name not in node_repos:
                body = _json.dumps({'ok': False, 'error': 'Unknown node'}).encode()
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
                return
            
            repo_url = node_repos[node_name]
            target_dir = os.path.join(custom_nodes_dir, node_name)
            
            try:
                if not os.path.isdir(custom_nodes_dir):
                    os.makedirs(custom_nodes_dir)
                
                # Clone the repo
                result = subprocess.run(
                    ['git', 'clone', repo_url, target_dir],
                    capture_output=True, text=True, timeout=120
                )
                
                if result.returncode != 0:
                    body = _json.dumps({'ok': False, 'error': result.stderr}).encode()
                    self.send_response(500)
                else:
                    body = _json.dumps({'ok': True}).encode()
                    self.send_response(200)
                
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except subprocess.TimeoutExpired:
                body = _json.dumps({'ok': False, 'error': 'Git clone timed out'}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                body = _json.dumps({'ok': False, 'error': str(e)}).encode()
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            return
            
        if _has_users() and not _is_authenticated(self.headers):
            self.send_error(401, "Unauthorized")
            return

        # ── Custom: install specific version ─────────────────────────────
        if self.path == '/api/install-version':
            self._handle_install_version()
            return

        # ── Custom: download latest release, apply, relaunch ───────
        if self.path == '/api/install-update':
            self._handle_install_update()
            return

        # ── Custom: delete output file ─────────────────────────────
        if self.path == '/__delete':
            import json as _json
            content_len = int(self.headers.get('Content-Length', 0))
            payload = _json.loads(self.rfile.read(content_len))
            folder_type = payload.get('type', 'output')
            subfolder   = payload.get('subfolder', '')
            filename    = payload.get('filename', '')
            folder = TYPE_DIRS.get(folder_type, TYPE_DIRS['output'])
            target = os.path.normpath(os.path.join(folder, subfolder, filename))
            # Security: ensure path stays within the intended folder
            if not target.startswith(os.path.normpath(folder)):
                self.send_error(400, 'Invalid path')
                return
            try:
                if os.path.isfile(target):
                    os.remove(target)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(body))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(500, str(e))
            return

        self._proxy_http()

    def _handle_check_update(self):
        import json as _json
        local_ver = _read_local_version()
        result = {'local': local_ver, 'latest': '', 'hasUpdate': False, 'htmlUrl': '', 'name': '', 'body': ''}
        
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        is_nightly = qs.get('nightly', ['false'])[0].lower() == 'true'
        
        if GITHUB_REPO and '/' in GITHUB_REPO and 'OWNER' not in GITHUB_REPO:
            try:
                if is_nightly:
                    req = urllib.request.Request(
                        f'https://api.github.com/repos/{GITHUB_REPO}/releases/tags/nightly',
                        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'somni'}
                    )
                else:
                    req = urllib.request.Request(
                        f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest',
                        headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'somni'}
                    )
                with urllib.request.urlopen(req, timeout=6) as r:
                    data = _json.loads(r.read().decode('utf-8'))
                tag = (data.get('tag_name') or '').lstrip('v')
                result['latest']  = tag
                result['name']    = data.get('name') or ''
                result['htmlUrl'] = data.get('html_url') or ''
                result['body']    = data.get('body') or ''
                if tag and local_ver and tag != local_ver:
                    result['hasUpdate'] = True
            except Exception as e:
                result['error'] = str(e)
        body = _json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _handle_install_version(self):
        """Download specific release zip from GitHub by version tag, apply runtime files in place."""
        import json as _json
        ok, new_version, err = False, '', ''
        try:
            content_len = int(self.headers.get('Content-Length', 0))
            body_bytes = self.rfile.read(content_len) if content_len else b''
            body = _json.loads(body_bytes.decode('utf-8')) if body_bytes else {}
            version = body.get('version', 'latest')
            
            req = urllib.request.Request(f'https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{version}', headers={'User-Agent': 'somni'})
            with urllib.request.urlopen(req, timeout=30) as r:
                release = _json.loads(r.read().decode('utf-8'))
            
            zip_url = None
            for asset in release.get('assets', []):
                if asset.get('name', '').endswith('.zip'):
                    zip_url = asset.get('browser_download_url')
                    break
            
            if not zip_url:
                raise RuntimeError('No zip file found in release')
            
            fd, tmp_zip = tempfile.mkstemp(suffix='.zip', prefix='somni-update-')
            os.close(fd)
            try:
                req = urllib.request.Request(zip_url, headers={'User-Agent': 'somni'})
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
                    exclude   = {'installer.bat', 'installer.py', 'installer.html'}
                    for name in os.listdir(root):
                        if name in preserved or name in exclude:
                            continue
                        src = os.path.join(root, name)
                        dst = os.path.join(DIR, name)
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
                
                new_version = version
                ok = True
            except Exception as e:
                try: os.remove(tmp_zip)
                except Exception: pass
                raise
        except Exception as e:
            err = str(e)
        body = _json.dumps({'ok': ok, 'newVersion': new_version, 'error': err}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
        if ok:
            def _relaunch_and_exit():
                time.sleep(0.6)
                bat = os.path.join(DIR, 'launch_somni.bat')
                if os.path.isfile(bat):
                    try:
                        subprocess.Popen(['cmd', '/c', 'start', '', bat], cwd=DIR, close_fds=True)
                    except Exception:
                        pass
                os._exit(0)
            threading.Thread(target=_relaunch_and_exit, daemon=True).start()

    def _handle_install_update(self):
        """Download latest release zip from GitHub, apply runtime files in place,
        then relaunch somni via launch_somni.bat. Installer files in the zip are
        ignored because they don't belong in the somni install dir."""
        import json as _json
        ok, new_version, err = False, '', ''
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            is_nightly = qs.get('nightly', ['false'])[0].lower() == 'true'
            new_version = _do_self_update(nightly=is_nightly)
            ok = True
        except Exception as e:
            err = str(e)
        body = _json.dumps({'ok': ok, 'newVersion': new_version, 'error': err}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
        if ok:
            def _relaunch_and_exit():
                time.sleep(0.6)
                bat = os.path.join(DIR, 'launch_somni.bat')
                if os.path.isfile(bat):
                    try:
                        subprocess.Popen(['cmd', '/c', 'start', '', bat], cwd=DIR, close_fds=True)
                    except Exception:
                        pass
                os._exit(0)
            threading.Thread(target=_relaunch_and_exit, daemon=True).start()

    def _serve_file(self, path, mime):
        try:
            with open(path, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_error(404, str(e))

    def _proxy_http(self):
        url = f"{COMFY}{self.path}"
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_REQ_HEADERS}
        
        # Add a placeholder for Origin/Referer to keep the backend happy
        headers['Origin'] = COMFY
        headers['Referer'] = COMFY + '/'
        headers['Host'] = f"{PARSED.hostname}:{PARSED.port}"

        data = None
        if self.command == 'POST':
            content_len = int(self.headers.get('Content-Length', 0))
            data = self.rfile.read(content_len)

        req = urllib.request.Request(url, data=data, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                self.send_response(r.status)
                for k, v in r.getheaders():
                    if k.lower() not in SKIP_RESP_HEADERS:
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(r.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_error(502, str(e))

    def _proxy_ws(self):
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            upstream.connect((PARSED.hostname, PARSED.port))
        except Exception as e:
            self.send_error(502, f"WS Connect Fail: {e}")
            return

        # Minimal handshake forwarding
        upstream_host = f"{PARSED.hostname}:{PARSED.port}"
        lines = [f"GET {self.path} HTTP/1.1"]
        for k, v in self.headers.items():
            lk = k.lower()
            if lk == 'host':
                lines.append(f"Host: {upstream_host}")
            elif lk in ('origin', 'referer'):
                lines.append(f"{k}: {COMFY}")
            else:
                lines.append(f"{k}: {v}")
        lines.extend(["", ""])
        upstream.sendall("\r\n".join(lines).encode())

        client = self.connection
        client.settimeout(None)
        upstream.settimeout(None)

        done = threading.Event()

        def pump(src, dst):
            try:
                while not done.is_set():
                    chunk = src.recv(8192)
                    if not chunk: break
                    dst.sendall(chunk)
            except OSError:
                pass
            finally:
                done.set()
                for s in (src, dst):
                    try: s.shutdown(socket.SHUT_RD)
                    except OSError: pass

        t1 = threading.Thread(target=pump, args=(upstream, client), daemon=True)
        t2 = threading.Thread(target=pump, args=(client, upstream), daemon=True)
        t1.start(); t2.start()
        done.wait()
        try: upstream.close()
        except OSError: pass
        self.close_connection = True

    def log_message(self, format, *args):
        # Console output for visibility
        print(f"Request: {args[0]} from {self.address_string()}")


class ThreadedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _open_browser_when_ready(port):
    """Background thread that waits until the server accepts connections, then opens the browser."""
    for _ in range(40):  # up to ~4 seconds
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    try: webbrowser.open(f'http://localhost:{port}/')
    except Exception: pass


if __name__ == '__main__':
    PORT = 8080
    open_browser = '--open' in sys.argv
    print(f'somni proxy active on port {PORT}')
    print(f'ComfyUI root: {COMFY_ROOT}')
    print('Check your batch terminal for the IP address to use on your phone!')
    if open_browser:
        threading.Thread(target=_open_browser_when_ready, args=(PORT,), daemon=True).start()
    try:
        ThreadedServer(('0.0.0.0', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass