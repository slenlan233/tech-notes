#!/usr/bin/env python3
"""Import exported Markdown ZIPs and generate a zero-server static technical blog."""
from __future__ import annotations

import html
import base64
import urllib.parse
import json
import re
import shutil
import sys
import unicodedata
import zipfile
from collections import defaultdict
from hashlib import sha1
from pathlib import Path, PurePosixPath
from mubu_import import mubu_html_to_markdown, mubu_opml_to_markdown, cache_remote_images, FAILED_IMAGES, _valid_image
from mubu_rescue import create_rescue_page

try:
    from markdown_it import MarkdownIt
    from mdit_py_plugins.dollarmath import dollarmath_plugin
    from pygments import lex, format as pygments_format
    from pygments.formatters import HtmlFormatter
    from pygments.token import Keyword, Name, Text, Punctuation
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
except ImportError:
    print('缺少依赖。请先运行: python -m pip install -r requirements.txt')
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'incoming'
SITE = ROOT / 'site'
POSTS = SITE / 'posts'
TEMPLATES = ROOT / 'templates'
md = MarkdownIt('default', {'html': False, 'linkify': False, 'typographer': True})

# TECH_NOTES_DOLLARMATH_FIX_V1
# Markdown must recognize math blocks BEFORE interpreting an isolated '=' as
# a Setext heading or interpreting TeX underscores as Markdown formatting.
# No source note/ZIP is rewritten: MathJax renders the resulting delimited text.
def _math_for_mathjax(content: str, options: dict) -> str:
    latex = html.escape(content, quote=False)
    if options.get('display_mode'):
        return '\\[' + latex + '\\]'
    return '\\(' + latex + '\\)'

md.use(
    dollarmath_plugin,
    renderer=_math_for_mathjax,
    allow_blank_lines=True,
    # Stand-alone $$ blocks come before inline parsing; don't turn $$ in
    # ordinary paragraphs into <div> nested inside a <p>.
    double_inline=False,
)

CODE_FORMATTER = HtmlFormatter(nowrap=True, cssclass='highlight')
PLAIN_LANGUAGES = {'text', 'txt', 'plaintext', 'plain', 'none', 'output'}

def normalize_siyuan_markdown(text: str) -> str:
    """Normalize SiYuan export zero-width separators without touching fenced code."""
    out = []
    fence_char = None
    fence_len = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^[ ]{0,3}(`{3,}|~{3,})', line)
        if marker:
            run = marker.group(1)
            if fence_char is None:
                fence_char, fence_len = run[0], len(run)
            elif run[0] == fence_char and len(run) >= fence_len:
                fence_char, fence_len = None, 0
            out.append(line)
            continue
        if fence_char is not None:
            out.append(line)
            continue
        # These U+200B marks come from SiYuan rich-text editing around
        # inline code/bold. They are not meaningful Markdown separators.
        # SiYuan exports frequently insert U+200B beside emphasis/code markers.
        # Also normalize related invisible joiners from copied rich text, but
        # leave code fences intact. Input archives are never rewritten.
        line = line.replace('\u200b', '').replace('\u2060', '').replace('\ufeff', '')
        # Two adjacent bold spans turn into four consecutive stars after the
        # U+200B is removed. Add a visible spacing boundary so MarkdownIt
        # recognizes both spans; do not alter four-star runs in fenced code.
        line = re.sub(r'(?<=\S)\*\*\*\*(?=\S)', '** **', line)
        # Mubu HTML -> Markdown can produce **线程私有。**在任何时刻.
        # CommonMark sees the Chinese full stop as punctuation and may reject
        # the closing ** when the next character is another letter.
        # An HTML-entity zero-width separator makes the boundary unambiguous
        # without changing the visible Chinese text or modifying source files.
        line = re.sub(r'([，。！？：；、）】》」』,.!?;:)\]])\*\*(?=\S)',
                      r'\1**&#8203;', line)
        out.append(line)
    return ''.join(out)



def highlight_code(source: str, lexer, lang: str) -> str:
    """Highlight code without modifying its text; enhance Java method-call tokens.

    Pygments already recognizes many Java declarations and dot-qualified calls.
    Extend it to unqualified calls (e.g. check()) and method references (::run).
    Only actual Pygments Name tokens are examined, so strings/comments remain intact.
    This is syntax-oriented highlighting, not Java symbol resolution.
    """
    tokens = list(lex(source, lexer))
    if lang == 'java':
        enriched = []
        for i, (kind, value) in enumerate(tokens):
            if kind == Name or kind == Name.Attribute:
                # A call is a name followed by (, allowing spaces/newlines.
                following = i + 1
                while following < len(tokens) and tokens[following][0] in Text.Whitespace:
                    following += 1
                is_call = (
                    following < len(tokens)
                    and tokens[following][0] in Punctuation
                    and tokens[following][1].startswith('(')
                )

                preceding = i - 1
                while preceding >= 0 and tokens[preceding][0] in Text.Whitespace:
                    preceding -= 1
                is_method_reference = (
                    preceding >= 1
                    and tokens[preceding][0] in Punctuation
                    and tokens[preceding][1] == ':'
                    and tokens[preceding - 1][0] in Punctuation
                    and tokens[preceding - 1][1] == ':'
                )
                is_constructor = (
                    preceding >= 0
                    and tokens[preceding][0] in Keyword
                    and tokens[preceding][1] == 'new'
                )

                if is_method_reference or (is_call and not is_constructor and
                                           (kind == Name.Attribute or not value[:1].isupper())):
                    kind = Name.Function
                elif kind == Name and value and value[0].isupper():
                    # Keep probable type names and constructors purple.
                    kind = Name.Class
            elif kind in Keyword and value in {'this', 'super'}:
                kind = Name.Builtin.Pseudo
            elif kind in Keyword and value == 'new':
                kind = Keyword.Pseudo
            enriched.append((kind, value))
        tokens = enriched
    return pygments_format(tokens, CODE_FORMATTER)

def render_fenced_code(self, tokens, index, options, env):
    """Use the explicit Markdown fence language; never guess unspecified languages."""
    token = tokens[index]
    lang = token.info.strip().split()[0].lower() if token.info.strip() else ''
    label = lang or 'TEXT'
    if lang and lang not in PLAIN_LANGUAGES:
        try:
            lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
            code_html = highlight_code(token.content, lexer, lang)
        except ClassNotFound:
            code_html = html.escape(token.content)
    else:
        code_html = html.escape(token.content)
    safe_label = html.escape(label.upper())
    safe_lang = re.sub(r"[^a-z0-9_-]", "-", lang) or "text"
    return (f'<div class="codeblock"><div class="codeblock-label">{safe_label}</div>'
            f'<pre><code class="hl-code lang-{safe_lang}">{code_html}</code></pre></div>')


def render_inline_code(self, tokens, index, options, env):
    """Render SiYuan backtick inline spans distinctly, escaping code safely."""
    return f'<code class="inline-code">{html.escape(tokens[index].content)}</code>'


md.add_render_rule('fence', render_fenced_code)
md.add_render_rule('code_inline', render_inline_code)


def title_from(text: str, filename: str) -> str:
    m = re.search(r'^\s{0,3}#\s+(.+?)\s*$', text, flags=re.M)
    return re.sub(r'\s+#+$', '', m.group(1)).strip() if m else Path(filename).stem


def excerpt(text: str) -> str:
    """Generate plain-text card summaries, never half of a LaTeX formula.

    An exported note may begin with a multi-line $$...$$ expression; simply
    cutting 145 characters can leave broken LaTeX delimiters on the homepage.
    Full article text and formulas are NOT changed.
    """
    clean = re.sub(r'```[\s\S]*?```|~~~[\s\S]*?~~~', ' ', text)
    # Remove math *before* taking a substring (display and inline formats).
    clean = re.sub(r'\$\$[\s\S]*?\$\$', ' ', clean)
    clean = re.sub(r'\\\[[\s\S]*?\\\]', ' ', clean)
    clean = re.sub(r'\\\([\s\S]*?\\\)', ' ', clean)
    clean = re.sub(r'(?<!\\)\$(?!\$)[^\n$]*?(?<!\\)\$', ' ', clean)
    clean = re.sub(r'!\[[^]]*\]\([^)]*\)', ' ', clean)
    clean = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', clean)
    clean = re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-+*]\s+|\d+[.)]\s+|>\s*)', '', clean)
    clean = re.sub(r'[`*_~]+', '', clean)
    clean = clean.replace('&#8203;', '').replace('&#x200b;', '').replace('&ZeroWidthSpace;', '')
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:145] + ('…' if len(clean) > 145 else '')


def searchable_text(markdown_text: str) -> str:
    """Extract ALL searchable text, including fenced code, without storing image URLs.

    The original Markdown is never modified. This plain-text representation is
    only embedded into the static search index, making searches work over file://.
    """
    parts = []
    for token in md.parse(markdown_text):
        if token.type not in {'inline', 'fence', 'code_block', 'html_block'}:
            continue
        raw = token.content
        if token.type == 'inline':
            raw = re.sub(r'!\[([^]]*)\]\([^)]*\)', r' \1 ', raw)
            raw = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', raw)
            raw = re.sub(r'<[^>]+>', ' ', raw)
            raw = re.sub(r'[`*_~]+', '', raw)
        parts.append(html.unescape(raw))
    return re.sub(r'\s+', ' ', ' '.join(parts)).strip()


def write_search_index(notes):
    """A JS data file, not fetch/JSON, so local file:// preview is supported."""
    records = [
        {'title': n['title'], 'category': n['category'],
         'url': n['url'], 'body': searchable_text(n['text'])}
        for n in notes
    ]
    payload = json.dumps(records, ensure_ascii=False, separators=(',', ':'))
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e')
    (SITE / 'search-index.js').write_text(
        'window.TECH_NOTES_SEARCH_INDEX = ' + payload + ';\n', encoding='utf-8'
    )
    return records


def category(title: str, text: str) -> str:
    corpus = (title + ' ' + text[:1000]).lower()
    if any(k in corpus for k in ['agent', 'langgraph', 'mcp', 'rag', 'transformer']):
        return 'AI Agent'
    if any(k in corpus for k in ['mysql', 'redis', '数据库', 'sql', '事务']):
        return '数据库与中间件'
    if any(k in corpus for k in ['jvm', 'spring', 'java', '并发', '集合']):
        return 'Java 后端'
    if any(k in corpus for k in ['leetcode', '算法', '链表', '动态规划']):
        return '算法与计算机基础'
    return '其他笔记'


def slug_for(name: str) -> str:
    base = unicodedata.normalize('NFKC', name).removesuffix('.md.zip').removesuffix('.zip')
    base = re.sub(r'[^\w\u4e00-\u9fff-]+', '-', base, flags=re.UNICODE).strip('-_')[:54]
    if not base:
        base = 'article'
    suffix = sha1(name.encode('utf-8')).hexdigest()[:6]
    return f'{base}-{suffix}'


def unpack_archive(archive: Path, destination: Path) -> list[Path]:
    files = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            path = PurePosixPath(info.filename.replace('\\', '/'))
            if info.is_dir() or path.is_absolute() or '..' in path.parts or any(p.startswith('.') for p in path.parts):
                continue
            if not path.parts or info.file_size > 100 * 1024 * 1024:
                continue
            out = destination.joinpath(*path.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as inp, out.open('wb') as dest:
                shutil.copyfileobj(inp, dest)
            files.append(out)
    return files



# Small/medium exported images are embedded directly in each generated article.
# This avoids file:// path issues, missing copied asset folders, and differences
# between local preview and hosting providers. Original ZIPs/assets remain intact.
LOCAL_IMAGE_PATTERN = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
SRC_PATTERN = re.compile(r'\bsrc=("([^"]*)"|\'([^\']*)\')', re.IGNORECASE)
SUPPORTED_INLINE = {
    '.png': ('image/png', b'\x89PNG\r\n\x1a\n'),
    '.jpg': ('image/jpeg', b'\xff\xd8\xff'),
    '.jpeg': ('image/jpeg', b'\xff\xd8\xff'),
    '.gif': ('image/gif', b'GIF8'),
    '.webp': ('image/webp', b'RIFF'),
}


def embed_article_images(rendered_html: str, article_folder: Path, article_name: str) -> str:
    embedded, missing, external, oversized = 0, [], 0, 0
    article_root = article_folder.resolve()
    # A ZIP sometimes has an extra top-level directory; search only its article area.
    def local_candidate(raw_url):
        parsed = urllib.parse.urlsplit(html.unescape(raw_url))
        if parsed.scheme or parsed.netloc or raw_url.startswith('//'):
            return None
        relative = urllib.parse.unquote(parsed.path).replace('\\', '/')
        if relative.startswith('/') or not relative:
            return False
        resolved = (article_folder / relative).resolve()
        if not resolved.is_relative_to(article_root):
            return False
        if resolved.is_file():
            return resolved
        # Recover images from differently nested exports when filename is unique.
        name = Path(relative).name
        matches = [q for q in article_folder.rglob(name) if q.is_file()]
        if len(matches) == 1:
            return matches[0]
        return False

    def replace_tag(match):
        nonlocal embedded, external, oversized
        tag = match.group(0)
        src = SRC_PATTERN.search(tag)
        if not src:
            return tag
        raw = src.group(2) if src.group(2) is not None else src.group(3)
        image_path = local_candidate(raw)
        if image_path is None:
            external += 1
            # External images may be blocked by the origin server. If that
            # happens, show a useful source link instead of a blank bullet.
            host = urllib.parse.urlsplit(html.unescape(raw)).hostname
            if host in {'api2.mubu.com', 'document-image.mubu.com'}:
                safe_src = html.escape(html.unescape(raw), quote=True)
                img = tag[:-1] + ' onerror="this.hidden=true;this.nextElementSibling.hidden=false">' if tag.endswith('>') else tag
                return (f'<span class="remote-image-wrap">{img}'
                        f'<span class="remote-image-fallback" hidden>幕布图片未能加载。'
                        f'<a href="{safe_src}" target="_blank" rel="noopener noreferrer">打开原图</a></span></span>')
            return tag
        if image_path is False:
            missing.append(raw)
            return tag
        info = SUPPORTED_INLINE.get(image_path.suffix.lower())
        if not info:
            # SVG or other supported browser formats remain as relative references.
            return tag
        mime, signature = info
        if image_path.stat().st_size > 12 * 1024 * 1024:
            oversized += 1
            return tag
        data = image_path.read_bytes()
        if not data.startswith(signature) or (mime == 'image/webp' and data[8:12] != b'WEBP'):
            missing.append(raw + ' (图片内容格式不正确)')
            return tag
        encoded = base64.b64encode(data).decode('ascii')
        new_src = f'data:{mime};base64,{encoded}'
        embedded += 1
        return tag[:src.start(1)] + '"' + new_src + '"' + tag[src.end(1):]

    result = LOCAL_IMAGE_PATTERN.sub(replace_tag, rendered_html)
    print(f'  图片检查 [{article_name}]：已内嵌 {embedded} 张 / 外链 {external} 张 / 资源缺失 {len(missing)} 张 / 大图保留原路径 {oversized} 张')
    for path in missing[:12]:
        print(f'    ⚠ 找不到图片：{path}；检查源 ZIP 中是否存在 assets 文件夹')
    return result

def find_heading_items(markdown_text: str) -> list[tuple[int, str, str]]:
    results = []
    for line in markdown_text.splitlines():
        m = re.match(r'^(#{2,4})\s+(.+?)\s*$', line)
        if m:
            level, name = len(m.group(1)), re.sub(r'[*`]+', '', m.group(2))
            anchor = f'section-{len(results)+1}'
            results.append((level, name, anchor))
    return results


def render_article(markdown_text: str) -> tuple[str, list]:
    # Adds stable IDs to heading output without rewriting any original notes.
    headings = find_heading_items(markdown_text)
    rendered = md.render(markdown_text)
    i = 0
    def repl(match):
        nonlocal i
        level = int(match.group(1))
        if level < 2 or level > 4:
            return match.group(0)
        if i >= len(headings):
            return match.group(0)
        anchor = headings[i][2]
        i += 1
        return f'<h{level} id="{anchor}">'
    rendered = re.sub(r'<h([1-6])>', repl, rendered)
    return rendered, headings


def import_notes():
    items = []
    seen = set()
    # Prefer original HTML (rich formatting), then OPML, then third-party converted Markdown.
    # This only de-duplicates files with the same base name in the same folder.
    source_files = [p for p in INPUT.rglob('*') if p.is_file() and p.suffix.lower() in {'.zip','.md','.markdown','.html','.opml'}]
    priority = {'.html': 0, '.opml': 1, '.zip': 2, '.md': 3, '.markdown': 3}
    best_source = {}
    for file in source_files:
        base = re.sub(r'\.md\.zip$|\.(?:zip|md|markdown|html|opml)$', '', file.name, flags=re.I)
        key = (file.parent, base.casefold())
        if key not in best_source or priority[file.suffix.lower()] < priority[best_source[key].suffix.lower()]:
            best_source[key] = file
    sources = sorted(best_source.values(), key=lambda p: str(p.relative_to(INPUT)).casefold())
    for source in sources:
        relative_source = source.relative_to(INPUT)
        category_folders = relative_source.parts[:-1]
        slug = slug_for(relative_source.as_posix())
        destination = POSTS / slug
        destination.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() == '.zip':
            try:
                files = unpack_archive(source, destination)
            except (zipfile.BadZipFile, OSError) as error:
                print(f'跳过 {source.name}: {error}')
                continue
            md_files = [p for p in files if p.suffix.lower() in {'.md', '.markdown'}]
        elif source.suffix.lower() in {'.html','.opml'}:
            target = destination / (source.stem + '.md')
            try:
                converted = (mubu_html_to_markdown(source) if source.suffix.lower()=='.html'
                             else mubu_opml_to_markdown(source))
                target.write_text(converted, encoding='utf-8')
                print(f'幕布格式转换: {source.name} → {target.name}')
                md_files = [target]
            except Exception as error:
                print(f'无法解析幕布文件 {source.name}: {error}')
                continue
        else:
            target = destination / source.name
            shutil.copy2(source, target)
            md_files = [target]
        if not md_files:
            print(f'警告：{source.name} 没有找到 .md 文档')
            continue
        for n, file in enumerate(md_files):
            text = file.read_text(encoding='utf-8-sig', errors='replace')
            # SiYuan sometimes inserts U+200B around code ticks and bold delimiters.
            # In combinations like **是的，**<ZWSP>**<ZWSP>`name`<ZWSP>**,
            # those invisible characters make markdown-it emit malformed emphasis
            # and visible ** markers. Only normalize the rendering copy; never
            # rewrite the exported .md inside its original ZIP.
            text = normalize_siyuan_markdown(text)
            title = title_from(text, file.name)
            actual_slug = slug if n == 0 else f'{slug}-{n+1}'
            if n:
                target_dir = POSTS / actual_slug
                target_dir.mkdir(parents=True, exist_ok=True)
                # Multi-document ZIPs can share an asset directory.
                for original in files:
                    if original.is_file() and original.suffix.lower() not in {'.md', '.markdown'}:
                        new = target_dir / original.relative_to(destination)
                        new.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(original, new)
                new_md = target_dir / file.relative_to(destination)
                new_md.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, new_md)
                file = new_md
            # Cache images referenced by remote Mubu URLs to local assets when reachable.
            # Never claim missing images have been successfully bundled.
            text = cache_remote_images(text, file.parent, ROOT / 'cached_images')
            # If the Markdown lives in a nested folder inside a ZIP, render the article next to it
            # so relative assets/... paths continue to work.
            article_folder = file.parent
            rel_url = article_folder.relative_to(SITE).as_posix() + '/index.html'
            if rel_url in seen:
                continue
            seen.add(rel_url)
            folders = category_folders or (category(title, text),)
            items.append({
                'title': title,
                'slug': actual_slug,
                'url': rel_url,
                'category': ' / '.join(folders),
                'folders': folders,
                'excerpt': excerpt(text),
                'text': text,
                'folder': article_folder,
            })
    return items


def build_nav_original(notes, root_prefix):
    """Create a collapsible folder tree from incoming/ directory names."""
    def new_node():
        return {'children': {}, 'notes': []}

    tree = new_node()
    for note in notes:
        node = tree
        for part in note['folders']:
            node = node['children'].setdefault(part, new_node())
        node['notes'].append(note)

    def render(node, depth=0):
        result = []
        for folder, child in sorted(node['children'].items(), key=lambda p: p[0].casefold()):
            count = count_articles(child)
            inside = render(child, depth + 1)
            result.append(
                f'<details class="nav-folder" open>'
                f'<summary class="nav-folder-title"><span class="folder-arrow">▸</span>'
                f'<span class="folder-text">{html.escape(folder)}</span>'
                f'<span class="folder-count">{count}</span></summary>'
                f'<div class="nav-folder-children">{inside}</div></details>'
            )
        for note in sorted(node['notes'], key=lambda n: n['title'].casefold()):
            search = html.escape((note['title'] + ' ' + note['category']).casefold(), quote=True)
            result.append(f'<a class="nav-link" data-search="{search}" data-note-url="{html.escape(note["url"], quote=True)}" href="{html.escape(root_prefix + note["url"], quote=True)}">{html.escape(note["title"])}</a>')
        return ''.join(result)

    def count_articles(node):
        return len(node['notes']) + sum(count_articles(c) for c in node['children'].values())

    return render(tree)


# TECH_NOTES_FEATURES_V1
from site_features import ordered_notes, build_nav as build_nav_features, pager_html, order_manifest

def build_nav(notes, root_prefix):
    return build_nav_features(notes, root_prefix)


def layout(title, content, notes, root_prefix='', active_url=None, toc=''):
    template = (TEMPLATES / 'layout.html').read_text(encoding='utf8')
    return (template.replace('{{PAGE_TITLE}}', html.escape(title))
        .replace('{{PAGE_CONTENT}}', content)
        .replace('{{ROOT_PREFIX}}', root_prefix)
        .replace('{{NAV_ITEMS}}', build_nav(notes, root_prefix))
        .replace('{{COUNT}}', str(len(notes)))
        .replace('{{TOC}}', toc))


def import_rescue_zips():
    """Import ZIPs downloaded from browser helper, with safe file validation."""
    cache_dir = ROOT / 'cached_images'
    cache_dir.mkdir(exist_ok=True)
    for archive in cache_dir.glob('*.zip'):
        imported, ignored = 0, 0
        try:
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    # A browser helper ZIP consists only of SHA-256-prefix image filenames.
                    name = info.filename
                    if not re.fullmatch(r'[a-f0-9]{20}\.(png|jpg|jpeg|gif|webp|svg)', name, flags=re.I):
                        ignored += 1
                        continue
                    if info.file_size > 15 * 1024 * 1024:
                        ignored += 1
                        continue
                    data = z.read(info)
                    if not _valid_image(data):
                        ignored += 1
                        continue
                    (cache_dir / name).write_bytes(data)
                    imported += 1
            print(f'已导入浏览器补充图片包：{archive.name}（成功 {imported} 张，跳过 {ignored} 张）')
        except (zipfile.BadZipFile, OSError) as e:
            print(f'⚠ 无法读取图片补充包 {archive.name}: {e}')


def main():
    print('知识库生成器：首页数学摘要修复 + 幕布加粗修复 2026-11-02')
    INPUT.mkdir(exist_ok=True)
    FAILED_IMAGES.clear()
    import_rescue_zips()
    if SITE.exists():
        shutil.rmtree(SITE)
    POSTS.mkdir(parents=True)
    for name in ('style.css', 'app.js', 'enhancements.css', 'enhancements.js'):
        shutil.copy2(TEMPLATES / name, SITE / name)
    # Bundle math renderer locally so exported HTML works with no internet.
    shutil.copytree(TEMPLATES / 'mathjax', SITE / 'mathjax')
    notes = import_notes()
    notes = ordered_notes(notes)
    write_search_index(notes)
    (SITE / "order-manifest.json").write_text(json.dumps(order_manifest(notes), ensure_ascii=False, indent=2), encoding="utf-8")
    groups = defaultdict(list)
    for note in notes:
        groups[note['category']].append(note)
    cards = ''.join(f'<a href="{html.escape(n["url"], quote=True)}" class="article-card" data-note-url="{html.escape(n["url"], quote=True)}" data-search="{html.escape((n["title"] + " " + n["category"] + " " + n["excerpt"]).casefold(), quote=True)}"><span class="card-category">{html.escape(n["category"])}</span><h3>{html.escape(n["title"])}</h3><p>{html.escape(n["excerpt"])}</p><span class="read-more">阅读全文 →</span></a>' for n in notes)
    home = f'''<div class="hero"><div class="eyebrow">TECH NOTES · KNOWLEDGE BASE</div><h1>技术知识库<span class="hero-dot">.</span></h1><p>Java 后端、数据库与 AI Agent 学习笔记。</p><div class="hero-meta"><span>📚 {len(notes)} 篇文章</span><span>🗂 {len(groups)} 个主题</span><span>✨ 持续更新</span></div><div class="hero-epigraph" aria-label="学习箴言"><p>知不足，然后能自反也；知困，然后能自强也。</p><cite>——《礼记·学记》</cite></div></div><div class="section-heading"><h2>全部文章</h2><p>点击左侧分类，或使用搜索框查找笔记。</p></div><div id="search-no-results" class="search-result-empty" hidden>没有符合搜索词的文章，请换个关键词。</div><div class="article-grid">{cards or '<p>将思源导出的 .md.zip 放到 incoming 文件夹，然后运行 build.bat。</p>'}</div>'''
    (SITE / 'index.html').write_text(layout('技术知识库', home, notes), encoding='utf8')
    for note in notes:
        article, headings = render_article(note['text'])
        article = embed_article_images(article, note['folder'], note['title'])
        toc = '' if not headings else '<aside class="toc"><div class="toc-title">本页目录</div>' + ''.join(f'<a href="#{anchor}" class="toc-link toc-level-{level}">{html.escape(name)}</a>' for level, name, anchor in headings) + '</aside>'
        relative_depth = len(Path(note['url']).parts) - 1
        prefix = '../' * relative_depth
        body = f'<div class="crumb"><a href="{prefix}index.html">首页</a><span>/</span>{html.escape(note["category"])}</div><div class="article-heading"><div class="eyebrow">{html.escape(note["category"])}</div></div><div class="article-content">{article}</div><div class="article-end"><a href="{prefix}index.html">← 返回全部文章</a></div>'
        body = body.replace('<div class="article-end">', pager_html(note, notes, prefix) + '<div class="article-end">', 1)
        (note['folder'] / 'index.html').write_text(layout(note['title'], body, notes, prefix, note['url'], toc), encoding='utf8')
    if FAILED_IMAGES:
        missing = [{'url':url,'name':name} for url,name in sorted(FAILED_IMAGES.items())]
        page = create_rescue_page(ROOT, missing)
        print(f'\n⚠ 有 {len(missing)} 张幕布图片未保存成功，不能保证网页显示。')
        print(f'  请双击「{page.name}」，尝试浏览器批量下载补充包。')
    else:
        page = ROOT / '恢复幕布图片.html'
        if page.exists():
            page.unlink()
        print('幕布图片检查：无未缓存的幕布外链图片。')
    print(f'成功生成 {len(notes)} 篇文章 → {SITE}')
    for note in notes: print('  -', note['title'], '=>', note['url'])


if __name__ == '__main__':
    main()
