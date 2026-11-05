#!/usr/bin/env python3
"""Regressions for SiYuan formulas rendered by the actual TECH NOTES build.py.

Run from the repository: python tests/test_math_rendering.py
Uses stdlib assertions; no pytest required. Never changes the source ZIP.
"""
from __future__ import annotations

import html
import importlib.util
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def find_real_note(filename: str = '强化学习.md.zip') -> str:
    archives = sorted((ROOT / 'incoming').rglob(filename))
    if not archives:
        raise AssertionError('未找到 incoming/**/强化学习.md.zip，无法执行原始笔记回归测试。')
    with zipfile.ZipFile(archives[0]) as z:
        names = [n for n in z.namelist() if n.lower().endswith('.md')]
        check(bool(names), '原始 ZIP 内没有 Markdown')
        return z.read(names[0]).decode('utf-8-sig')


def test():
    spec = importlib.util.spec_from_file_location('tech_notes_build_math_test', ROOT / 'build.py')
    check(spec is not None and spec.loader is not None, '无法加载 build.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    md = mod.md

    # The failure reported in screenshots: '=' must stay math, not h1.
    sample = (
        '1. 样本平均：\n\n'
        '    $$\n'
        '    Q_t(1)\n'
        '    =\n'
        '    \\frac{\\text{选择动作1后获得的全部奖励之和}}\n'
        '    {\\text{动作1被选择的次数}}\n'
        '    $$\n\n'
        '2. 继续阅读。\n'
    )
    rendered, _ = mod.render_article(sample)
    check('\\[Q_t(1)' in rendered or ('\\[' in rendered and 'Q_t(1)' in rendered),
          '多行块级公式没有保留下 MathJax 定界符')
    check('\\frac{' in rendered and '\\]' in rendered, '分式被 Markdown 拆断')
    check('<h1>' not in rendered, '公式内部的 = 被错误解析为 Markdown 标题')
    check('<ol>' in rendered and '<li>' in rendered, '列表结构受损')

    # Inline math must remain math; code samples must not be treated as math.
    inline = md.render('行内公式 $x_i+y_i$ 和 `原样 $x_i$`。')
    check('\\(x_i+y_i\\)' in inline, '行内公式未交给 MathJax')
    check('<code class="inline-code">原样 $x_i$</code>' in inline,
          '行内代码被数学解析器错误处理')
    fenced = md.render('```text\n$$\nQ_t(1)\n=\n$$\n```\n')
    check('class="codeblock"' in fenced and '\\[Q_t' not in fenced,
          '代码围栏被错误当作数学公式')

    # Links and tables/images unaffected by parser extension.
    other = md.render('![配图](assets/figure.png)\n\n| A | B |\n|---|---|\n| 1 | 2 |')
    check('<img' in other and 'assets/figure.png' in other,
          '图片 Markdown 解析受损')
    check('<table>' in other, '表格解析受损')

    raw = find_real_note()
    normalized = mod.normalize_siyuan_markdown(raw)
    opening = normalized.count('$$')
    check(opening % 2 == 0 and opening >= 1000,
          f'原笔记的成对数学定界符数量意外变化：{opening}')
    tokens = md.parse(normalized)
    blocks = [t for t in tokens if t.type in {'math_block', 'math_block_label'}]
    check(len(blocks) >= 500,
          f'原笔记中数学块识别明显不足：{len(blocks)} / {opening // 2}')
    for t in blocks:
        check(t.markup == '$$' and t.content.strip(), '存在空的或格式错误的数学块')
    check(any('Q_t(1)' in t.content and '\\frac' in t.content for t in blocks),
          '实际笔记截图中的 Q_t(1) 多行分式未被完整识别')
    rendered_real, _ = mod.render_article(normalized)
    check('<h1>$$' not in rendered_real, '真实笔记中仍有 $$ 被误当作标题')
    check('class="math block"' in rendered_real,
          '页面 HTML 未包含数学块输出')
    print(f'✅ 《强化学习》：识别数学块 {len(blocks)}/{opening // 2} 个。')
    check(len(blocks) == opening // 2,
          f'真实笔记部分公式未完整识别：{len(blocks)}/{opening // 2}')

    # Companion notebooks with heavy math. Optional because repositories can
    # legitimately remove/rename a note later without breaking the generator.
    for filename in ('Transformer.md.zip', 'Fine tune 微调.md.zip',
                     'RLHF：基于人类反馈的强化学习 Reinforcement Learning from Human Feedback.md.zip'):
        if not list((ROOT / 'incoming').rglob(filename)):
            continue
        companion = mod.normalize_siyuan_markdown(find_real_note(filename))
        expected_pairs = companion.count('$$') // 2
        companion_blocks = [tok for tok in md.parse(companion)
                            if tok.type in {'math_block', 'math_block_label'}]
        print(f'✅ {filename}：识别数学块 {len(companion_blocks)}/{expected_pairs} 个。')
        check(len(companion_blocks) == expected_pairs,
              f'{filename} 中数学块未完整识别')
    print('注意：此处检查 HTML/Token，浏览器 MathJax 最终排版仍需上线后抽查。')


if __name__ == '__main__':
    try:
        test()
    except Exception as exc:
        print(f'❌ 公式回归测试失败：{exc}', file=sys.stderr)
        sys.exit(1)
