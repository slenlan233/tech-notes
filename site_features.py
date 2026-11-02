"""Non-invasive navigation ordering for the static TECH NOTES site.

The order.json file is optional.  It is exported by the site's directory
organizer, then committed alongside build.py for consistent public ordering.
Original .md.zip / .html sources and existing article URLs remain unchanged.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_order() -> dict[str, list[str]]:
    path = ROOT / 'order.json'
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text(encoding='utf-8-sig'))
        if config.get('version') != 1 or not isinstance(config.get('parents'), dict):
            raise ValueError('version/parents 格式不正确')
        return {key: value for key, value in config['parents'].items()
                if isinstance(key, str) and isinstance(value, list)
                and all(isinstance(item, str) for item in value)}
    except (OSError, ValueError) as error:
        print(f'⚠ order.json 无法解析，改用默认排序：{error}')
        return {}


def build_tree(notes):
    root = {'children': {}, 'notes': []}
    for note in notes:
        node = root
        for folder in note['folders']:
            node = node['children'].setdefault(folder, {'children': {}, 'notes': []})
        node['notes'].append(note)
    return root


def sorted_entries(node, parent_path, order):
    entries = []
    for name, child in node['children'].items():
        path = f'{parent_path}/{name}' if parent_path else name
        entries.append(('folder:' + path, name, 'folder', child, path))
    for note in node['notes']:
        entries.append(('note:' + note['url'], note['title'], 'note', note, parent_path))

    preferred = order.get(parent_path, [])
    positions = {key: i for i, key in enumerate(preferred)}
    # Explicitly ordered items first. New articles are appended alphabetically,
    # with folders preceding articles when not covered by the config.
    entries.sort(key=lambda entry: (0, positions[entry[0]]) if entry[0] in positions
                 else (1, 0 if entry[2] == 'folder' else 1, entry[1].casefold()))
    return entries


def ordered_notes(notes):
    order = load_order()
    tree = build_tree(notes)
    output = []

    def walk(node, path=''):
        for key, label, kind, child, child_path in sorted_entries(node, path, order):
            if kind == 'note':
                output.append(child)
            else:
                walk(child, child_path)

    walk(tree)
    return output


def build_nav(notes, root_prefix):
    order = load_order()
    tree = build_tree(notes)

    def count(node):
        return len(node['notes']) + sum(count(child) for child in node['children'].values())

    def esc(s):
        return html.escape(str(s), quote=True)

    def render(node, parent_path=''):
        pieces = []
        for key, label, kind, item, child_path in sorted_entries(node, parent_path, order):
            if kind == 'folder':
                pieces.append(
                    f'<details class="nav-folder" open data-sort-key="{esc(key)}" data-folder-path="{esc(child_path)}">'
                    f'<summary class="nav-folder-title"><span class="folder-arrow">▸</span>'
                    f'<span class="folder-text">{esc(label)}</span>'
                    f'<span class="folder-count">{count(item)}</span></summary>'
                    f'<div class="nav-folder-children" data-parent-path="{esc(child_path)}">'
                    f'{render(item, child_path)}</div></details>'
                )
            else:
                n = item
                search = esc((n['title'] + ' ' + n['category']).casefold())
                pieces.append(
                    f'<a class="nav-link" data-sort-key="{esc(key)}" data-search="{search}" '
                    f'data-note-url="{esc(n["url"])}" href="{esc(root_prefix + n["url"])}">'
                    f'{esc(n["title"])}</a>'
                )
        return ''.join(pieces)

    return render(tree)


def pager_html(note, notes, prefix):
    pos = next((i for i, n in enumerate(notes) if n['url'] == note['url']), -1)
    if pos < 0:
        return ''

    def link(n, cls, prefix_text):
        if n is None:
            return f'<span class="pager-placeholder {cls}"></span>'
        title = html.escape(n['title'])
        href = html.escape(prefix + n['url'], quote=True)
        return (f'<a class="pager-link {cls}" href="{href}" title="{title}">'
                f'<span class="pager-hint">{prefix_text}</span><span class="pager-title">{title}</span></a>')

    previous = notes[pos - 1] if pos > 0 else None
    following = notes[pos + 1] if pos + 1 < len(notes) else None
    return ('<nav class="article-pager" aria-label="前后文章导航" '
            f'data-current-url="{html.escape(note["url"], quote=True)}">'
            + link(previous, 'pager-previous', '← 上一篇')
            + link(following, 'pager-next', '下一篇 →') + '</nav>')


def order_manifest(notes):
    """The exact keys permitted in every folder, used to validate local admin saves."""
    order = load_order()
    tree = build_tree(notes)
    result = {}

    def visit(node, path=''):
        entries = sorted_entries(node, path, order)
        result[path] = [entry[0] for entry in entries]
        for key, label, kind, child, child_path in entries:
            if kind == 'folder':
                visit(child, child_path)
    visit(tree)
    return {'version': 1, 'parents': result}
