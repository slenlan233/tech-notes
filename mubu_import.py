"""Read Mubu's exported HTML/OPML without needing a third-party Markdown converter.

Mubu exports image URLs, not image bytes. At build time this module attempts to
cache those URLs under cached_images, and reports when downloads fail.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


_IMG_REGEX = re.compile(r'!\[([^\]]*)\]\((https?://[^\s)]+)\)')
_ALLOWED_HOSTS = {'api2.mubu.com', 'document-image.mubu.com'}
FAILED_IMAGES: dict[str,str] = {}


def _escape(text: str) -> str:
    # Do not escape LaTeX commands and subscripts inside math delimiters.
    parts = re.split(r'(\$\$[\s\S]*?\$\$|\$(?!\$)[^\n$]*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])', text)
    return ''.join(part if i % 2 else re.sub(r'([\\`*_\[\]])', r'\\\1', part)
                   for i, part in enumerate(parts))


def _inline(element) -> str:
    """Turn common Mubu spans into Markdown, preserving bold and italic styles."""
    if isinstance(element, NavigableString):
        return _escape(str(element))
    if not isinstance(element, Tag):
        return ''
    if element.name == 'br':
        return '  \n'
    inner = ''.join(_inline(child) for child in element.children)
    cls = set(element.get('class', []))
    if element.name == 'a' and element.get('href'):
        return f'[{inner}]({element["href"]})'
    if element.name in {'b','strong'} or 'bold' in cls:
        return f'**{inner}**' if inner.strip() else inner
    if element.name in {'i','em'} or 'italic' in cls:
        return f'*{inner}*' if inner.strip() else inner
    if element.name == 'code':
        return f'`{inner}`'
    return inner


def _inline_html(fragment: str) -> str:
    soup = BeautifulSoup(fragment, 'html.parser')
    return ''.join(_inline(c) for c in soup.contents).strip()


def _markdown_tree(root_nodes, get_content, get_note, get_images, get_children, title: str) -> str:
    lines = [f'# {_escape(title)}', '']
    def visit(node, depth):
        text = get_content(node)
        note = get_note(node)
        images = get_images(node)
        kids = get_children(node)
        prefix = '    ' * depth
        if text:
            lines.append(prefix + '- ' + text)
        elif images:
            url = images.pop(0)
            lines.append(prefix + '- ![](' + url + ')')
        else:
            # Empty outline nodes may be containers, not actual bullet points.
            if kids:
                for child in kids:
                    visit(child, depth)
                return
            return
        if note:
            lines.append('')
            for line in note.splitlines():
                lines.append(prefix + '    > ' + line)
            lines.append('')
        for url in images:
            lines.append(prefix + '    ![](' + url + ')')
        for child in kids:
            visit(child, depth+1)
    for n in root_nodes:
        visit(n, 0)
    return '\n'.join(lines).rstrip() + '\n'


def mubu_html_to_markdown(path: Path) -> str:
    soup = BeautifulSoup(path.read_text(encoding='utf-8-sig'), 'html.parser')
    top = soup.body.find('ul', class_='node-list') if soup.body else None
    if not top:
        raise ValueError('未找到幕布 HTML 的 node-list 结构；请确认是幕布导出的 HTML')
    title = (soup.title.get_text(strip=True) if soup.title else path.stem).strip()
    def direct(node, name, cls):
        return node.find(name, class_=cls, recursive=False)
    def content(n):
        block = direct(n, 'div', 'content')
        return _inline_html(str(block.decode_contents())) if block else ''
    def note(n):
        block = direct(n, 'div', 'note')
        return _inline_html(str(block.decode_contents())) if block else ''
    def images(n):
        block = direct(n, 'ul', 'image-list')
        return [im.get('src','') for im in block.find_all('img')] if block else []
    def children(n):
        block = direct(n, 'div', 'children')
        sublist = block.find('ul', class_='node-list', recursive=False) if block else None
        return sublist.find_all('li', class_='node', recursive=False) if sublist else []
    return _markdown_tree(top.find_all('li', class_='node', recursive=False), content, note, images, children, title)


def mubu_opml_to_markdown(path: Path) -> str:
    root = ET.parse(path).getroot()
    title = root.findtext('./head/title') or path.stem
    body = root.find('body')
    if body is None:
        raise ValueError('不是有效的幕布 OPML：缺少 body')
    def content(n):
        raw = n.get('_mubu_text')
        return _inline_html(urllib.parse.unquote(raw)) if raw else _escape(n.get('text',''))
    def note(n):
        raw = n.get('_mubu_note')
        return _inline_html(urllib.parse.unquote(raw)) if raw else _escape(n.get('_note',''))
    def images(n):
        raw = n.get('_mubu_images')
        try: rows = json.loads(urllib.parse.unquote(raw)) if raw else []
        except (ValueError, TypeError): rows = []
        urls=[]
        for row in rows:
            uri = row.get('uri','')
            if uri.startswith('http'):
                urls.append(uri)
            elif uri:
                urls.append('https://api2.mubu.com/v3/' + uri.lstrip('/'))
        return urls
    def children(n):
        return list(n.findall('outline'))
    return _markdown_tree(list(body.findall('outline')), content, note, images, children, title)


def _valid_image(data: bytes) -> bool:
    return (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or
            (data.startswith(b'RIFF') and data[8:12] == b'WEBP') or
            data.lstrip().startswith(b'<svg'))


def cache_remote_images(text: str, article_dir: Path, cache_dir: Path) -> str:
    """Download Mubu images once (when accessible) and rewrite URLs to local assets."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    article_assets = article_dir / 'assets'
    count = 0
    failed = []
    def substitute(match):
        nonlocal count
        alt, url = match.groups()
        host = urllib.parse.urlsplit(url).hostname
        if host not in _ALLOWED_HOSTS:
            return match.group(0)
        extension = Path(urllib.parse.urlsplit(url).path).suffix.lower()
        if extension not in {'.png','.jpg','.jpeg','.webp','.svg','.gif'}:
            extension = '.png'
        key = hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]
        dest_cached = cache_dir / (key + extension)
        if not dest_cached.exists() or not _valid_image(dest_cached.read_bytes()):
            candidate_urls=[url]
            path=urllib.parse.urlsplit(url).path
            if host=='api2.mubu.com' and path.startswith('/v3/'):
                candidate_urls.append('https://document-image.mubu.com/'+path[len('/v3/'):])
            success = False
            for candidate in candidate_urls:
                try:
                    req=urllib.request.Request(candidate,headers={
                        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
                        'Referer':'https://mubu.com/',
                        'Accept':'image/avif,image/webp,image/apng,image/*,*/*;q=0.8'})
                    with urllib.request.urlopen(req,timeout=12) as r:
                        data = r.read(15*1024*1024+1)
                    if len(data) <= 15*1024*1024 and _valid_image(data):
                        dest_cached.write_bytes(data)
                        success=True
                        break
                except (OSError, urllib.error.URLError, ValueError):
                    pass
            if not success:
                failed.append((url, str(dest_cached.relative_to(cache_dir.parent))))
                FAILED_IMAGES[url] = dest_cached.name
                return match.group(0)
        FAILED_IMAGES.pop(url, None)
        article_assets.mkdir(parents=True, exist_ok=True)
        output_img = article_assets / dest_cached.name
        shutil.copy2(dest_cached, output_img)
        count += 1
        return f'![{alt}](assets/{dest_cached.name})'
    output = _IMG_REGEX.sub(substitute, text)
    if count:
        print(f'  图片缓存成功：{count} 张，已保存到本地 assets/')
    if failed:
        print(f'  ⚠ 图片缓存失败：{len(failed)} 张。原始文件没有图片数据，网页将继续尝试外链加载。')
        for url, local in failed[:6]:
            print('    未缓存：',url)
            print('    如果浏览器可以打开这张图，可手动保存为：',local)
    return output
