#!/usr/bin/env python3
"""TECH NOTES local-only article organizer.

Serves the generated site on 127.0.0.1 and injects admin controls at response
 time. The controls/API are NOT written into site/ or deployed to GitHub Pages.
Requires the user's existing local Git authentication for optional publishing.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
SITE = ROOT / 'site'
ASSETS = ROOT / 'admin_assets'
LOCK = threading.Lock()
TOKEN = secrets.token_urlsafe(32)
MAX_POST = 256_000


def run_command(args, timeout=90):
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(str(e)) from e
    if proc.returncode:
        raise RuntimeError((proc.stdout + '\n' + proc.stderr).strip()[-2800:] or f'退出码 {proc.returncode}')
    return (proc.stdout + '\n' + proc.stderr).strip()


def build_site():
    return run_command([sys.executable, 'build.py'], timeout=180)


def manifest():
    path = SITE / 'order-manifest.json'
    return json.loads(path.read_text(encoding='utf-8'))


def validate_order(payload):
    expected = manifest().get('parents', {})
    if not isinstance(payload, dict) or payload.get('version') != 1:
        raise ValueError('排序数据版本不正确')
    parents = payload.get('parents')
    if not isinstance(parents, dict) or set(parents) != set(expected):
        raise ValueError('目录列表与当前笔记不一致，请刷新管理页面后重试')
    for path, keys in parents.items():
        if not isinstance(keys, list) or len(keys) != len(expected[path]):
            raise ValueError(f'目录项目数量不一致：{path}')
        if len(set(keys)) != len(keys) or set(keys) != set(expected[path]):
            raise ValueError(f'只允许调整同级项目的顺序：{path}')
        if len(keys) > 2000 or any(not isinstance(key, str) for key in keys):
            raise ValueError('无效的排序数据')
        # Current version intentionally preserves all folder positions; only
        # leaf articles within the same existing parent may be moved.
        original = expected[path]
        before_folders = [(i, k) for i, k in enumerate(original) if k.startswith('folder:')]
        after_folders = [(i, k) for i, k in enumerate(keys) if k.startswith('folder:')]
        if before_folders != after_folders:
            raise ValueError('本版本只支持同一文件夹中的文章排序，不移动分类文件夹')
    return {'version': 1, 'parents': parents}


def save_order(payload):
    config = validate_order(payload)
    dst = ROOT / 'order.json'
    previous = dst.read_bytes() if dst.exists() else None
    temp = ROOT / 'order.json.tmp'
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, dst)
    try:
        build_site()
    except Exception:
        if previous is None:
            dst.unlink(missing_ok=True)
        else:
            dst.write_bytes(previous)
        try:
            build_site()
        except Exception:
            pass
        raise


def git_state():
    try:
        branch = run_command(['git', 'branch', '--show-current'], timeout=12).strip()
        status = run_command(['git', 'status', '--porcelain', '--', 'order.json'], timeout=12)
        setup = run_command(['git', 'status', '--porcelain', '--',
                             'build.py', 'templates/layout.html', 'site_features.py',
                             'templates/enhancements.js', 'templates/enhancements.css',
                             'admin.py', 'admin_assets'], timeout=12)
        return {'branch': branch, 'unpublished': bool(status), 'setup_pending': bool(setup)}
    except Exception as e:
        return {'branch': None, 'unpublished': True, 'warning': str(e)[:240]}


def publish():
    info = git_state()
    if info['branch'] != 'main':
        raise RuntimeError('仅允许从本地 main 分支发布。请先切换到 main。')
    if info.get('setup_pending'):
        raise RuntimeError('升级文件尚未提交。请先按照安装说明提交并推送升级代码，再使用一键发布排序。')
    # Do not inadvertently push unrelated ahead-of-origin commits.
    pending = int(run_command(['git', 'rev-list', '--count', 'origin/main..HEAD'], timeout=12))
    if pending:
        raise RuntimeError(f'本地还有 {pending} 个未推送的其他提交。为避免意外一起发布，请先手动检查 Git 状态。')
    status = run_command(['git', 'status', '--porcelain', '--', 'order.json'], timeout=12)
    if not status:
        return '排序配置已与本地提交一致，无须再次发布。'
    run_command(['git', 'add', '--', 'order.json'], timeout=12)
    # --only makes the commit specific to order.json even if other files staged.
    commit = run_command(['git', 'commit', '--only', '-m', 'docs: Update knowledge base article order', '--', 'order.json'], timeout=45)
    push = run_command(['git', 'push', 'origin', 'main'], timeout=120)
    return commit[-450:] + '\n' + push[-450:]


def make_handler(port):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(SITE), **kw)

        def _allowed_host(self):
            return self.headers.get('Host', '') in {f'127.0.0.1:{port}', f'localhost:{port}'}

        def end_headers(self):
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'same-origin')
            super().end_headers()

        def send_json(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._allowed_host():
                self.send_error(403, 'Invalid Host')
                return
            path = urlsplit(self.path).path
            if path in ('/__tn_admin.js', '/__tn_admin.css'):
                source = ASSETS / ('admin.js' if path.endswith('.js') else 'admin.css')
                if not source.exists():
                    self.send_error(404)
                    return
                data = source.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path == '/__tn/state':
                if self.headers.get('X-TN-Admin') != TOKEN:
                    self.send_json(403, {'error': '无效的管理会话'})
                else:
                    self.send_json(200, {'manifest': manifest(), 'git': git_state()})
                return
            if path.endswith('.html') or path == '/':
                rel = path.lstrip('/') or 'index.html'
                target = (SITE / rel).resolve()
                if SITE.resolve() not in target.parents or not target.is_file():
                    return super().do_GET()
                content = target.read_text(encoding='utf-8')
                # Inject runtime-only controls. Build artifacts never contain token/UI.
                addition = (f'<script>window.__TN_LOCAL_ADMIN_TOKEN={json.dumps(TOKEN)};</script>'
                            '<link rel="stylesheet" href="/__tn_admin.css?v=2">'
                            '<script defer src="/__tn_admin.js?v=2"></script>')
                content = content.replace('</head>', addition + '</head>', 1)
                data = content.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

        def do_POST(self):
            if not self._allowed_host():
                self.send_json(403, {'error': '无效 Host'})
                return
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}:
                self.send_json(403, {'error': '无效 Origin'})
                return
            if self.headers.get('X-TN-Admin') != TOKEN or self.headers.get('Content-Type','').split(';')[0].strip() != 'application/json':
                self.send_json(403, {'error': '无效的管理会话'})
                return
            path = urlsplit(self.path).path
            if path not in ('/__tn/save', '/__tn/publish'):
                self.send_json(404, {'error': '接口不存在'})
                return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if length < 2 or length > MAX_POST:
                    raise ValueError('数据大小超出限制')
                data = json.loads(self.rfile.read(length).decode('utf-8'))
                with LOCK:
                    if path == '/__tn/save':
                        save_order(data)
                        message = '草稿已保存到本地 order.json，并重新生成预览。'
                    else:
                        if data != {'confirm': True}:
                            raise ValueError('请明确确认发布')
                        message = publish()
                    self.send_json(200, {'ok': True, 'message': message, 'git': git_state()})
            except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as e:
                self.send_json(400, {'error': str(e)[:1800]})
            except Exception as e:
                self.send_json(500, {'error': f'{type(e).__name__}: {str(e)[:800]}'})

    return Handler


def main():
    if not (ROOT / 'build.py').is_file() or not (ROOT / 'site_features.py').is_file():
        raise SystemExit('请在原 tech-notes 仓库里安装升级包，再运行 admin.py。')
    if not (SITE / 'order-manifest.json').is_file():
        print('首次运行：生成本站预览...', flush=True)
        build_site()
    server = None
    for port in range(8765, 8775):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(port))
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit('本地端口 8765–8774 均被占用，无法启动。')
    url = f'http://127.0.0.1:{port}/index.html'
    print(f'\nTECH NOTES 本地排序管理：{url}', flush=True)
    print('只允许当前电脑访问；保持窗口运行，浏览器关闭后按 Ctrl+C 停止服务。', flush=True)
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
