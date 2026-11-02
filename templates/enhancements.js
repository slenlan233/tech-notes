/* TECH NOTES: public reader features only. Local admin is never shipped to GitHub Pages. */
(function () {
  'use strict';
  const article = document.querySelector('.article-content');
  const get = key => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const put = (key, value) => { try { localStorage.setItem(key, value); return true; } catch (_) { return false; } };
  const norm = s => String(s || '').normalize('NFKC').toLocaleLowerCase();

  // In full-text search, the destination receives a query so it can open the
  // right collapsed paragraph and highlight the original text rather than only
  // displaying a search-result snippet on the home/sidebar page.
  const resultPanel = document.getElementById('search-results');
  if (resultPanel) resultPanel.addEventListener('click', event => {
    const link = event.target.closest('.search-result-item');
    if (!link) return;
    const query = document.getElementById('search')?.value.trim();
    if (!query) return;
    const url = new URL(link.href);
    url.searchParams.set('q', query);
    link.href = url.toString();
  }, true);

  function findAndHighlight() {
    if (!article) return;
    const query = new URLSearchParams(location.search).get('q')?.trim();
    if (!query) return;
    const terms = [query, ...query.split(/\s+/)].map(norm).filter(Boolean);
    const texts = [];
    const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT, {
      acceptNode: node => {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (node.parentElement.closest('script, style, .MathJax, mjx-container')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    while (walker.nextNode()) texts.push(walker.currentNode);
    let foundTerm = terms.find(term => texts.some(node => norm(node.nodeValue).includes(term)));
    if (!foundTerm) return;
    const hits = [];
    for (const node of texts) {
      if (hits.length >= 40) break;
      const raw = node.nodeValue, normalized = norm(raw);
      // Prefer precise same-node highlighting; never inject HTML from a query.
      const positions = [];
      let start = 0, at;
      while ((at = normalized.indexOf(foundTerm, start)) >= 0 && positions.length < 10 && hits.length + positions.length < 40) {
        positions.push(at); start = at + foundTerm.length;
      }
      if (!positions.length) continue;
      const fragment = document.createDocumentFragment();
      let cursor = 0;
      for (const pos of positions) {
        fragment.append(document.createTextNode(raw.slice(cursor, pos)));
        const mark = document.createElement('mark');
        mark.className = 'tn-highlight';mark.textContent=raw.slice(pos,pos+foundTerm.length);
        fragment.append(mark);hits.push(mark);cursor=pos+foundTerm.length;
      }
      fragment.append(document.createTextNode(raw.slice(cursor)));
      node.replaceWith(fragment);
    }
    if (!hits.length) return;
    const bar = document.createElement('div');bar.className='tn-search-jump';
    const label = document.createElement('span');
    const prev = document.createElement('button');prev.type='button';prev.textContent='↑';prev.title='上一处匹配';
    const next = document.createElement('button');next.type='button';next.textContent='↓';next.title='下一处匹配';
    const close = document.createElement('button');close.type='button';close.textContent='✕';close.title='关闭查找高亮';
    let pos = 0;
    const go = index => {
      hits.forEach(hit=>hit.classList.remove('tn-highlight-active'));
      pos = (index + hits.length) % hits.length;
      const current = hits[pos];
      // Original app.js owns folding state; click the existing expand buttons.
      let hidden = current.closest('.outline-children[hidden]');
      while (hidden) {
        const toggle = Array.from(document.querySelectorAll('.outline-toggle'))
          .find(button => button.getAttribute('aria-controls') === hidden.id);
        if (toggle) toggle.click(); else hidden.hidden=false;
        hidden = current.closest('.outline-children[hidden]');
      }
      current.classList.add('tn-highlight-active');
      label.textContent = `正文定位：${pos+1} / ${hits.length}`;
      requestAnimationFrame(()=>current.scrollIntoView({block:'center',behavior:'auto'}));
    };
    prev.addEventListener('click',()=>go(pos-1));next.addEventListener('click',()=>go(pos+1));
    close.addEventListener('click',()=>{hits.forEach(hit=>hit.classList.remove('tn-highlight','tn-highlight-active'));bar.remove();});
    bar.append(label,prev,next,close);
    article.parentElement.insertBefore(bar,article);
    setTimeout(()=>go(0),180);
  }
  findAndHighlight();

  function setupReadingProgress() {
    if (!article) return;
    const canonical = document.querySelector('.article-pager')?.dataset.currentUrl || location.pathname;
    const key = 'tech-notes:read:' + canonical;
    let saved;
    try {saved=JSON.parse(get(key)||'null');}catch (_) {}
    const bar = document.createElement('div');bar.className='tn-read-progress';
    const fill = document.createElement('span');bar.append(fill);document.body.append(bar);
    const tools=document.createElement('div');tools.className='tn-reading-tools';
    const info=document.createElement('span');info.textContent='阅读进度 0%';tools.append(info);
    if (saved && saved.percent >= 2) {
      const resume=document.createElement('button');resume.type='button';
      resume.textContent=`继续上次阅读（${saved.percent}%）`;
      resume.addEventListener('click',()=>{
        const max = Math.max(0,document.documentElement.scrollHeight-innerHeight);
        const y = Math.min(max, Math.max(0, saved.y || 0));
        // Prefer ratio for responsive layouts / changed text and use the old y
        // when the window dimensions are still close to the previous session.
        const dest = Math.abs(innerWidth - (saved.width||innerWidth)) < 80 ? y : max*(saved.percent/100);
        window.scrollTo({top:dest,behavior:'smooth'});
        resume.remove();
      });tools.append(resume);
    }
    const heading=document.querySelector('.article-heading') || article;
    heading.parentElement.insertBefore(tools, heading.nextSibling);
    let last = 0, timer;
    const update = (shouldSave = true) => {
      const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
      const percent = Math.max(0, Math.min(100, Math.round(scrollY/max*100)));
      fill.style.width=percent+'%';info.textContent=`阅读进度 ${percent}%`;
      if (!shouldSave) return;
      const now=Date.now();
      if (now-last>650) {
        last=now;put(key,JSON.stringify({percent,y:scrollY,width:innerWidth,time:now}));
      } else {
        clearTimeout(timer);timer=setTimeout(()=>{
          put(key,JSON.stringify({percent,y:scrollY,width:innerWidth,time:Date.now()}));
        },750);
      }
    };
    window.addEventListener('scroll',()=>update(true),{passive:true});
    window.addEventListener('resize',()=>update(false),{passive:true});
    update(false);
  }
  setupReadingProgress();

})();

/* PERSONAL ARTICLE ORDER — public site, browser-only, no admin credentials. */
(function () {
  'use strict';
  // The local 127.0.0.1 manager has its own admin drag-and-drop workflow.
  // Do not apply visitors' personal order to the owner's publishing preview.
  if (window.__TN_LOCAL_ADMIN_TOKEN) return;
  const nav = document.querySelector('.nav-items');
  if (!nav) return;
  const STORAGE_KEY = 'tech-notes:personal-order:v1';
  const groups = () => [nav, ...nav.querySelectorAll('.nav-folder-children[data-parent-path]')];
  const keyFor = el => el === nav ? '' : el.dataset.parentPath;
  const isNote = el => el.matches('.nav-link[data-note-url][data-sort-key]');
  const children = el => Array.from(el.children).filter(n => n.hasAttribute('data-sort-key'));
  const noteChildren = el => children(el).filter(isNote);
  const allNotes = () => Array.from(nav.querySelectorAll('.nav-link[data-note-url][data-sort-key]'));
  const rootPrefix = document.getElementById('search')?.dataset.root || '';
  const personal = {};

  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    if (raw?.version === 1 && raw.parents && typeof raw.parents === 'object' && !Array.isArray(raw.parents)) {
      for (const [path, value] of Object.entries(raw.parents)) {
        if (typeof path === 'string' && Array.isArray(value) && value.every(k => typeof k === 'string')) {
          personal[path] = value.slice(0, 2000);
        }
      }
    }
  } catch (_) { /* Private mode / storage denied: still allow temporary sorting. */ }

  // Sorting changes only note slots; folder nodes keep their relative positions.
  // Saved IDs of deleted articles are ignored. Newly added articles are appended
  // after the visitor's retained sequence in the same folder.
  function applyPersonal() {
    for (const group of groups()) {
      const preferred = personal[keyFor(group)];
      if (!preferred || !preferred.length) continue;
      const all = children(group);
      const notes = all.filter(isNote);
      if (!notes.length) continue;
      const lookup = new Map(notes.map(n => [n.dataset.sortKey, n]));
      const used = new Set();
      const ordered = [];
      for (const key of preferred) {
        const node = lookup.get(key);
        if (node && !used.has(key)) { ordered.push(node); used.add(key); }
      }
      for (const note of notes) {
        if (!used.has(note.dataset.sortKey)) ordered.push(note);
      }
      let pos = 0;
      group.replaceChildren(...all.map(node => isNote(node) ? ordered[pos++] : node));
    }
  }

  function syncCardsAndPager() {
    const rows = allNotes();
    const grid = document.querySelector('.article-grid');
    if (grid) {
      const cards = new Map(Array.from(grid.querySelectorAll('.article-card[data-note-url]'))
        .map(card => [card.dataset.noteUrl, card]));
      for (const row of rows) {
        const card = cards.get(row.dataset.noteUrl);
        if (card) grid.appendChild(card);
      }
    }
    const pager = document.querySelector('.article-pager[data-current-url]');
    if (!pager) return;
    const index = rows.findIndex(row => row.dataset.noteUrl === pager.dataset.currentUrl);
    if (index < 0) return;
    for (const [side, neighbour, hint] of [
      ['previous', rows[index - 1], '← 上一篇'],
      ['next', rows[index + 1], '下一篇 →']
    ]) {
      const slot = pager.querySelector('.pager-' + side);
      if (!slot) continue;
      if (!neighbour) {
        if (slot.tagName !== 'SPAN') {
          const blank = document.createElement('span');
          blank.className = 'pager-placeholder pager-' + side;
          slot.replaceWith(blank);
        }
        continue;
      }
      const link = document.createElement('a');
      link.className = 'pager-link pager-' + side;
      link.href = rootPrefix + neighbour.dataset.noteUrl;
      link.title = neighbour.textContent.trim();
      const heading = document.createElement('span');
      heading.className = 'pager-hint'; heading.textContent = hint;
      const name = document.createElement('span');
      name.className = 'pager-title'; name.textContent = neighbour.textContent.trim();
      link.append(heading, name);
      slot.replaceWith(link);
    }
  }

  function persist() {
    try {
      if (Object.keys(personal).length) {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({version: 1, parents: personal}));
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
      return true;
    } catch (_) { return false; }
  }
  function record(group) {
    const path = keyFor(group);
    const ids = noteChildren(group).map(n => n.dataset.sortKey);
    if (ids.length) personal[path] = ids;
    const saved = persist();
    syncCardsAndPager();
    updateReset();
    notify(saved ? '已将当前目录顺序保存在此浏览器' : '当前浏览器阻止存储，刷新后可能恢复默认顺序');
  }
  // Move a note before/after another note but keep any nested folders fixed.
  function moveAmongNotes(parent, moved, other, after) {
    const original = children(parent);
    const notes = original.filter(isNote);
    const before = notes.map(el => el.dataset.sortKey).join('\u0000');
    const ordered = notes.filter(node => node !== moved);
    const index = ordered.indexOf(other);
    if (index < 0) return false;
    ordered.splice(index + (after ? 1 : 0), 0, moved);
    let i = 0;
    parent.replaceChildren(...original.map(node => isNote(node) ? ordered[i++] : node));
    return before !== ordered.map(el => el.dataset.sortKey).join('\u0000');
  }
  function searchIsActive() {
    return !!document.getElementById('search')?.value.trim();
  }

  let toastTimer;
  const toast = document.createElement('div');
  toast.className = 'tn-order-toast'; toast.setAttribute('role', 'status');
  toast.hidden = true; document.body.appendChild(toast);
  function notify(message) {
    toast.textContent = message; toast.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { toast.hidden = true; }, 2300);
  }

  // Small reset affordance only when a personal override actually exists.
  // No ordering arrows, drag handles, or permanent toolbar on the public site.
  const label = document.querySelector('.sidebar .side-label');
  const reset = document.createElement('button');
  reset.className = 'tn-order-reset'; reset.type = 'button';
  reset.textContent = '恢复默认顺序';
  reset.title = '清除本浏览器的个人排序，恢复站长发布的顺序';
  if (label) label.after(reset);
  function updateReset() { reset.hidden = Object.keys(personal).length === 0; }
  updateReset();
  reset.addEventListener('click', () => {
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    // Reset should use the actual currently published default order, not the
    // locally shuffled DOM. Reload reconstructs it from generated HTML.
    location.reload();
  });

  applyPersonal();
  syncCardsAndPager();
  nav.classList.add('tn-public-sortable');
  allNotes().forEach(n => { n.draggable = true; });

  let dragging = null;
  let target = null;
  let moved = false;
  let suppressUntil = 0;
  function markTarget(node, after) {
    if (target && target !== node) {
      target.classList.remove('tn-insert-before', 'tn-insert-after');
    }
    target = node;
    if (target) {
      target.classList.toggle('tn-insert-before', !after);
      target.classList.toggle('tn-insert-after', after);
    }
  }
  function cleanup() {
    if (dragging) dragging.classList.remove('tn-dragging');
    markTarget(null, false); dragging = null; moved = false;
  }
  nav.addEventListener('dragstart', event => {
    const node = event.target.closest('.nav-link[data-sort-key]');
    if (!node || !nav.contains(node) || searchIsActive()) {
      event.preventDefault();
      if (searchIsActive()) notify('请先清空搜索内容再调整顺序');
      return;
    }
    dragging = node;
    moved = false;
    node.classList.add('tn-dragging');
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', node.dataset.sortKey);
    }
  });
  nav.addEventListener('dragover', event => {
    if (!dragging) return;
    const node = event.target.closest('.nav-link[data-sort-key]');
    if (!node || node === dragging || node.parentElement !== dragging.parentElement) {
      markTarget(null, false); return;
    }
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    markTarget(node, event.clientY > node.getBoundingClientRect().top + node.getBoundingClientRect().height / 2);
  });
  nav.addEventListener('drop', event => {
    if (!dragging || !target || target.parentElement !== dragging.parentElement) return;
    event.preventDefault();
    const after = target.classList.contains('tn-insert-after');
    const parent = dragging.parentElement;
    if (moveAmongNotes(parent, dragging, target, after)) {
      moved = true; record(parent);
    }
    suppressUntil = Date.now() + 450;
    cleanup();
  });
  nav.addEventListener('dragend', () => {
    if (dragging) suppressUntil = Date.now() + 400;
    cleanup();
  });
  nav.addEventListener('click', event => {
    if (Date.now() > suppressUntil) return;
    if (event.target.closest('.nav-link[data-sort-key]')) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);

  // Touch: long press (400ms) to avoid interfering with normal scroll or tap.
  // Drag only over siblings within the same folder.
  let touch = null;
  const cancelTouchTimer = () => { if (touch?.timer) { clearTimeout(touch.timer); touch.timer = null; } };
  nav.addEventListener('touchstart', event => {
    if (event.touches.length !== 1 || searchIsActive()) return;
    const node = event.target.closest('.nav-link[data-sort-key]');
    if (!node) return;
    const finger = event.touches[0];
    touch = {node, x:finger.clientX, y:finger.clientY, active:false, timer:null};
    touch.timer = setTimeout(() => {
      if (!touch || touch.node !== node) return;
      touch.active = true; node.classList.add('tn-dragging');
      notify('已进入拖动排序，松开手指保存此浏览器的顺序');
    }, 420);
  }, {passive:true});
  nav.addEventListener('touchmove', event => {
    if (!touch || event.touches.length !== 1) return;
    const finger = event.touches[0];
    if (!touch.active) {
      if (Math.abs(finger.clientY-touch.y) > 10 || Math.abs(finger.clientX-touch.x) > 10) {
        cancelTouchTimer(); touch = null;
      }
      return;
    }
    event.preventDefault();
    const hit = document.elementFromPoint(finger.clientX, finger.clientY)?.closest('.nav-link[data-sort-key]');
    const valid = hit && hit !== touch.node && hit.parentElement === touch.node.parentElement;
    if (valid) markTarget(hit, finger.clientY > hit.getBoundingClientRect().top + hit.getBoundingClientRect().height/2);
    else markTarget(null, false);
  }, {passive:false});
  nav.addEventListener('touchend', event => {
    if (!touch) return;
    cancelTouchTimer();
    if (touch.active) {
      event.preventDefault(); suppressUntil = Date.now()+700;
      if (target && target.parentElement === touch.node.parentElement) {
        const parent = touch.node.parentElement;
        if (moveAmongNotes(parent, touch.node, target, target.classList.contains('tn-insert-after'))) record(parent);
      }
      touch.node.classList.remove('tn-dragging'); markTarget(null, false);
    }
    touch = null;
  }, {passive:false});
  nav.addEventListener('touchcancel', () => {
    if (touch) { cancelTouchTimer(); touch.node.classList.remove('tn-dragging'); touch = null; }
    markTarget(null, false);
  });
})();
