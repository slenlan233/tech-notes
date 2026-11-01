(function(){
  'use strict';
  const root = document.documentElement;
  const key = 'tech-notes-theme';
  try { if (localStorage.getItem(key) === 'dark') root.dataset.theme = 'dark'; } catch (_) {}
  const theme = document.getElementById('theme-switch');
  if (theme) theme.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem(key, next); } catch (_) {}
  });
  const toggle = document.getElementById('menu-toggle');
  const sidebar = document.getElementById('sidebar');
  if (toggle && sidebar) toggle.addEventListener('click', () => sidebar.classList.toggle('open'));

  const input = document.getElementById('search');
  const resultsBox = document.getElementById('search-results');
  const records = Array.isArray(window.TECH_NOTES_SEARCH_INDEX)
    ? window.TECH_NOTES_SEARCH_INDEX : [];
  const normal = s => String(s || '').normalize('NFKC').toLocaleLowerCase();
  const indexed = records.map(n => ({
    ...n,
    titleLower: normal(n.title),
    categoryLower: normal(n.category),
    bodyLower: normal(n.body)
  }));
  const maxResults = 30;

  function markMatch(target, value, q) {
    value = String(value || '');
    if (!q) { target.textContent = value; return; }
    const pos = normal(value).indexOf(q);
    if (pos < 0) { target.textContent = value; return; }
    // Keep all DOM fragments as text nodes, never insert untrusted HTML.
    target.append(document.createTextNode(value.slice(0, pos)));
    const mark = document.createElement('mark');
    mark.textContent = value.slice(pos, pos + q.length);
    target.append(mark, document.createTextNode(value.slice(pos + q.length)));
  }

  function snippet(note, terms) {
    const body = note.body || '';
    const normalized = note.bodyLower;
    let pos = -1, len = 0;
    for (const term of terms) {
      const at = normalized.indexOf(term);
      if (at !== -1 && (pos < 0 || at < pos)) { pos = at; len = term.length; }
    }
    if (pos < 0) return body.slice(0, 115) + (body.length > 115 ? '…' : '');
    const start = Math.max(0, pos - 50);
    const end = Math.min(body.length, pos + Math.max(len, 50) + 70);
    return (start ? '…' : '') + body.slice(start, end) + (end < body.length ? '…' : '');
  }

  function filterExisting(matchedUrls, active) {
    document.querySelectorAll('.nav-link').forEach(a => {
      a.hidden = active && !matchedUrls.has(a.getAttribute('data-note-url'));
    });
    document.querySelectorAll('.article-card').forEach(a => {
      a.hidden = active && !matchedUrls.has(a.getAttribute('data-note-url'));
    });
    document.querySelectorAll('.nav-folder').forEach(g => {
      g.hidden = active && !Array.from(g.querySelectorAll('.nav-link')).some(a => !a.hidden);
      if (active && !g.hidden) g.open = true;
    });
    const noResults = document.getElementById('search-no-results');
    if (noResults) noResults.hidden = !active || matchedUrls.size !== 0;
  }

  function doSearch() {
    if (!input || !resultsBox) return;
    const query = normal(input.value.trim());
    resultsBox.replaceChildren();
    if (!query) {
      resultsBox.hidden = true;
      filterExisting(new Set(), false);
      return;
    }
    const terms = query.split(/\s+/).filter(Boolean);
    const matches = indexed.filter(n => terms.every(term =>
      n.titleLower.includes(term) || n.categoryLower.includes(term) || n.bodyLower.includes(term)
    )).map(n => {
      const weight = terms.reduce((sum, term) => sum +
        (n.titleLower.includes(term) ? 10 : 0) +
        (n.categoryLower.includes(term) ? 3 : 0) +
        (n.bodyLower.includes(term) ? 1 : 0), 0);
      return { note: n, weight };
    }).sort((a,b) => b.weight-a.weight || a.note.title.localeCompare(b.note.title, 'zh'));
    const matchedUrls = new Set(matches.map(x=>x.note.url));
    filterExisting(matchedUrls, true);
    const header = document.createElement('div');
    header.className = 'search-result-header';
    header.textContent = `找到 ${matches.length} 篇匹配文章`;
    resultsBox.append(header);
    const rootPrefix = input.dataset.root || '';
    for (const {note} of matches.slice(0, maxResults)) {
      const link = document.createElement('a');
      link.className = 'search-result-item';
      link.href = rootPrefix + note.url;
      const name = document.createElement('div');
      name.className = 'search-result-title';
      markMatch(name, note.title, terms.find(t => note.titleLower.includes(t)) || '');
      const cat = document.createElement('div');
      cat.className = 'search-result-category';
      cat.textContent = note.category;
      const context = document.createElement('div');
      context.className = 'search-result-context';
      const contextText = snippet(note, terms);
      markMatch(context, contextText, terms.find(t => normal(contextText).includes(t)) || '');
      link.append(name, cat, context);
      resultsBox.append(link);
    }
    if (!matches.length) {
      const empty = document.createElement('div');
      empty.className = 'search-result-empty';
      empty.textContent = '没找到匹配的笔记，试试缩短关键词。';
      resultsBox.append(empty);
    } else if (matches.length > maxResults) {
      const more = document.createElement('div');
      more.className = 'search-result-empty';
      more.textContent = `只显示前 ${maxResults} 篇，请补充关键词缩小范围。`;
      resultsBox.append(more);
    }
    resultsBox.hidden = false;
  }

  if (input) {
    input.addEventListener('input', doSearch);
    input.addEventListener('focus', () => { if (input.value.trim()) doSearch(); });
    input.addEventListener('keydown', e => {
      if (e.key === 'Escape') { input.value = ''; doSearch(); }
      if (e.key === 'Enter') {
        const first = resultsBox && resultsBox.querySelector('.search-result-item');
        if (first) { e.preventDefault(); first.click(); }
      }
    });
    document.addEventListener('click', e => {
      if (resultsBox && !e.target.closest('.search-container')) resultsBox.hidden = true;
    });
  }
  const path = decodeURI(location.pathname);
  document.querySelectorAll('.nav-link').forEach(a => {
    try { if (decodeURI(new URL(a.href).pathname) === path) a.classList.add('active'); } catch (_) {}
  });


  // --- Article outline folding: imported Mubu / SiYuan lists and Markdown headings. ---
  // The original Markdown is untouched. Native nested lists remain in the DOM;
  // we only wrap child content in a visually collapsible container.
  function initArticleOutline() {
    const article = document.querySelector('.article-content');
    if (!article) return;
    const controlList = [];
    const savedKey = 'tech-notes-fold:' + location.pathname;
    let savePending = false;

    function makeToggle(body, host, kind) {
      if (!body || !body.childNodes.length) return null;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'outline-toggle outline-toggle-' + kind;
      button.setAttribute('aria-label', '折叠子内容');
      button.setAttribute('aria-expanded', 'true');
      button.setAttribute('title', '折叠 / 展开子内容');
      const id = 'outline-body-' + (controlList.length + 1);
      body.id = id;
      body.classList.add('outline-children');
      button.setAttribute('aria-controls', id);
      const arrow = document.createElement('span');
      arrow.className = 'outline-chevron';
      arrow.setAttribute('aria-hidden', 'true');
      button.append(arrow);
      if (kind === 'heading') {
        host.insertBefore(button, host.firstChild);
      } else {
        const p = Array.from(host.children).find(el => el.tagName === 'P' && el !== body);
        const anchor = p || host;
        anchor.insertBefore(button, anchor.firstChild);
      }
      body.dataset.outlineId = String(controlList.length);
      controlList.push({button, body});
      button.addEventListener('click', ev => {
        ev.preventDefault();
        ev.stopPropagation();
        setOpen({button, body}, body.hidden, true);
      });
      return button;
    }

    // Headings in standard Markdown documents: fold all blocks beneath a
    // heading until the next heading of the same or higher level.
    const level = node => /^H[2-6]$/.test(node.tagName || '') ? Number(node.tagName[1]) : 0;
    function foldHeadings(parent) {
      let node = parent.firstElementChild;
      while (node) {
        const headLevel = level(node);
        if (!headLevel) { node = node.nextElementSibling; continue; }
        const following = node.nextElementSibling;
        if (!following || (level(following) && level(following) <= headLevel)) {
          node = following;
          continue;
        }
        const body = document.createElement('div');
        body.className = 'outline-section-body';
        parent.insertBefore(body, following);
        while (body.nextElementSibling && !(level(body.nextElementSibling) && level(body.nextElementSibling) <= headLevel)) {
          body.append(body.nextElementSibling);
        }
        if (body.children.length) {
          makeToggle(body, node, 'heading');
          foldHeadings(body);
        } else {
          body.replaceWith(...Array.from(body.childNodes));
        }
        node = body.nextElementSibling;
      }
    }
    foldHeadings(article);

    // Outline-style nested list nodes, common in Mubu exports and SiYuan notes.
    // Child list, quote, or additional paragraph belongs to that node and can
    // be folded without affecting siblings, numbering, or Markdown formatting.
    const listItems = Array.from(article.querySelectorAll('li'));
    for (const li of listItems) {
      const children = Array.from(li.childNodes);
      const leadParagraph = Array.from(li.children).find(el => el.tagName === 'P');
      let cut = -1;
      for (let i = 0; i < children.length; i++) {
        const n = children[i];
        if (n.nodeType !== 1) continue;
        if (['UL', 'OL', 'BLOCKQUOTE'].includes(n.tagName)) { cut = i; break; }
        // Several paragraphs within one node: keep the first visible.
        if (n.tagName === 'P' && leadParagraph && n !== leadParagraph) { cut = i; break; }
      }
      if (cut < 0) continue;
      // Avoid creating an arrow with no visible node label.
      const lead = children.slice(0, cut).some(n =>
        n.nodeType === 3 ? Boolean(n.textContent.trim()) :
        (n.nodeType === 1 && Boolean(n.textContent.trim()))
      );
      if (!lead) continue;
      const body = document.createElement('div');
      body.className = 'outline-list-body';
      li.insertBefore(body, children[cut]);
      for (const n of children.slice(cut)) body.append(n);
      makeToggle(body, li, 'list');
    }

    if (!controlList.length) return;

    function setOpen(item, open, persist) {
      item.body.hidden = !open;
      item.button.setAttribute('aria-expanded', String(open));
      item.button.setAttribute('aria-label', open ? '折叠子内容' : '展开子内容');
      if (open && persist && window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
        // Collapsed formulas may have been skipped when MathJax initialized.
        window.MathJax.typesetPromise([item.body]).catch(() => {});
      }
      if (persist) saveState();
    }
    function saveState() {
      if (savePending) return;
      savePending = true;
      // Coalesce batches such as "全部折叠" into one storage write.
      queueMicrotask(() => {
        savePending = false;
        try {
          localStorage.setItem(savedKey, JSON.stringify(controlList
            .map((item, i) => item.body.hidden ? i : -1).filter(i => i !== -1)));
        } catch (_) { /* file:// or private mode may disallow storage */ }
      });
    }
    try {
      const collapsed = JSON.parse(localStorage.getItem(savedKey) || '[]');
      if (Array.isArray(collapsed)) {
        for (const i of collapsed) if (Number.isInteger(i) && controlList[i]) setOpen(controlList[i], false, false);
      }
    } catch (_) {}

    const toolbar = document.createElement('div');
    toolbar.className = 'outline-toolbar';
    const label = document.createElement('span');
    label.className = 'outline-toolbar-label';
    label.textContent = `正文大纲 · ${controlList.length} 个可折叠节点`;
    const expandAll = document.createElement('button');
    expandAll.type = 'button';
    expandAll.textContent = '全部展开';
    const collapseAll = document.createElement('button');
    collapseAll.type = 'button';
    collapseAll.textContent = '全部折叠';
    expandAll.addEventListener('click', () => {
      for (const item of controlList) setOpen(item, true, false);
      if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
        window.MathJax.typesetPromise([article]).catch(() => {});
      }
      saveState();
    });
    collapseAll.addEventListener('click', () => {
      for (const item of controlList) setOpen(item, false, false);
      saveState();
    });
    toolbar.append(label, expandAll, collapseAll);
    article.parentElement.insertBefore(toolbar, article);

    function revealAnchor(hash) {
      if (!hash || hash.length < 2) return;
      let target;
      try { target = document.getElementById(decodeURIComponent(hash.slice(1))); } catch (_) { return; }
      if (!target || !article.contains(target)) return;
      // Open all ancestor folds, preserving the rest of the page.
      let wrapper = target.closest('.outline-children');
      while (wrapper && article.contains(wrapper)) {
        const item = controlList.find(x => x.body === wrapper);
        if (item) setOpen(item, true, false);
        wrapper = wrapper.parentElement?.closest('.outline-children');
      }
      if (window.MathJax && typeof window.MathJax.typesetPromise === 'function') {
        window.MathJax.typesetPromise([target.parentElement || article]).catch(() => {});
      }
      saveState();
      requestAnimationFrame(() => target.scrollIntoView({block:'start', behavior:'auto'}));
    }
    document.querySelectorAll('.toc-link[href^="#"]').forEach(a => {
      a.addEventListener('click', () => revealAnchor(a.getAttribute('href')));
    });
    if (location.hash) revealAnchor(location.hash);
    window.addEventListener('hashchange', () => revealAnchor(location.hash));
  }
  initArticleOutline();

})();
