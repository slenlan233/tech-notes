/* Local-only admin controls injected by 127.0.0.1 admin.py; never built into site/. */
(function () {
  'use strict';
  const token = window.__TN_LOCAL_ADMIN_TOKEN;
  const nav = document.querySelector('.nav-items');
  const header = document.querySelector('.sidebar .side-label');
  if (!token || !nav || !header) return;

  const allGroups = () => [nav, ...nav.querySelectorAll('.nav-folder-children')];
  const childrenOf = group => Array.from(group.children).filter(el => el.hasAttribute('data-sort-key'));
  const parentKey = group => group === nav ? '' : group.closest('.nav-folder')?.dataset.folderPath || '';
  const noteRows = () => Array.from(nav.querySelectorAll('.nav-link[data-sort-key]'));
  const deepCopy = value => JSON.parse(JSON.stringify(value));
  const status = document.createElement('div');
  status.className = 'tn-local-state';
  status.setAttribute('role','status');

  async function api(path, data) {
    const init = {headers: {'X-TN-Admin': token}, cache: 'no-store'};
    if (data !== undefined) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(data);
    }
    const res = await fetch(path, init);
    const result = await res.json();
    if (!res.ok) throw new Error(result.error || `请求失败：${res.status}`);
    return result;
  }

  function collect() {
    const parents = {};
    allGroups().forEach(group => { parents[parentKey(group)] = childrenOf(group).map(el => el.dataset.sortKey); });
    return {version:1, parents};
  }
  function applyOrder(config) {
    if (!config || !config.parents) return;
    allGroups().forEach(group => {
      const preferred = config.parents[parentKey(group)];
      if (!Array.isArray(preferred)) return;
      const ranks = new Map(preferred.map((key,i)=>[key,i]));
      childrenOf(group).sort((a,b)=>(ranks.get(a.dataset.sortKey) ?? Infinity) - (ranks.get(b.dataset.sortKey) ?? Infinity))
        .forEach(el => group.append(el));
    });
    syncHomepageAndPager();
  }
  function syncHomepageAndPager() {
    const cards = document.querySelector('.article-grid');
    if (cards) {
      const map = new Map(Array.from(cards.querySelectorAll('.article-card')).map(card => [card.dataset.noteUrl,card]));
      noteRows().forEach(link => { const item = map.get(link.dataset.noteUrl); if (item) cards.append(item); });
    }
    const pager = document.querySelector('.article-pager');
    if (!pager) return;
    const rows = noteRows();
    const i = rows.findIndex(el => el.dataset.noteUrl === pager.dataset.currentUrl);
    if (i < 0) return;
    const prefix = document.getElementById('search')?.dataset.root || '';
    [['previous', i-1, '← 上一篇'], ['next',i+1,'下一篇 →']].forEach(([side, index, hint]) => {
      const slot = pager.querySelector('.pager-' + side);
      if (!slot) return;
      const link = rows[index];
      if (!link) { slot.replaceWith(Object.assign(document.createElement('span'),{className:'pager-placeholder pager-'+side})); return; }
      const a = document.createElement('a');
      a.className = 'pager-link pager-' + side;
      a.href = prefix + link.dataset.noteUrl;
      a.title = link.textContent.trim();
      const h = document.createElement('span'); h.className='pager-hint'; h.textContent=hint;
      const t = document.createElement('span'); t.className='pager-title'; t.textContent=link.textContent.trim();
      a.append(h,t);slot.replaceWith(a);
    });
  }

  const trigger = document.createElement('button');
  trigger.className = 'tn-admin-trigger'; trigger.type = 'button';
  trigger.textContent = '本地管理';
  trigger.title = '只在本地管理服务器显示，访客看不到';
  header.append(trigger);

  const panel = document.createElement('div');
  panel.className='tn-admin-panel';panel.hidden=true;
  const label = document.createElement('div');label.className='tn-admin-help';
  label.textContent='按住文章名并拖动，放到同一目录中想要的位置。灰色为悬停或拖动中的行，蓝线表示插入位置。';
  const buttons = document.createElement('div');buttons.className='tn-admin-buttons';
  function button(text, title) {
    const node=document.createElement('button');node.type='button';node.textContent=text;node.title=title||text;
    node.className='tn-admin-button';buttons.append(node);return node;
  }
  const undo = button('撤销');
  const reset = button('放弃未保存修改');
  const save = button('保存草稿');
  const publish = button('发布到全站');
  publish.classList.add('tn-admin-publish');
  panel.append(label, buttons, status);
  nav.parentElement.insertBefore(panel, nav);

  let active=false;
  let current=[];
  let saved=null;
  let dirty=false;
  let busy=false;
  let gitState=null;
  function message(text, kind='normal') {
    status.textContent=text;
    status.dataset.kind=kind;
  }
  function refreshControls() {
    undo.disabled=busy || !active || current.length===0;
    reset.disabled=busy || !active || !dirty;
    save.disabled=busy || !active || !dirty;
    publish.disabled=busy || dirty || !gitState || gitState.branch!=='main' || gitState.setup_pending || !gitState.unpublished;
    publish.title=dirty ? '请先保存草稿，再发布到全站' : '将 order.json 通过你电脑的 Git 身份推送到 origin/main';
  }
  function changed() {
    dirty=JSON.stringify(collect()) !== JSON.stringify(saved);
    message(dirty ? '有未保存修改。可撤销或保存草稿。' : '草稿与本地文件一致。');
    refreshControls();
  }
  function begin() {
    if (busy) return;
    active=!active;
    nav.classList.toggle('tn-admin-sorting',active);
    panel.hidden=!active;
    trigger.textContent=active?'退出排序':'本地管理';
    noteRows().forEach(el => {el.draggable=active;});
    nav.querySelectorAll('.nav-folder-title').forEach(el=>el.draggable=false);
    changed();
  }
  trigger.addEventListener('click', begin);
  nav.addEventListener('click', ev => {
    if (!active) return;
    if (ev.target.closest('.nav-link')) {
      ev.preventDefault();ev.stopImmediatePropagation();
    }
  }, true);

  let dragging=null;
  let over=null;
  function clearOver() {
    if (over) over.classList.remove('tn-insert-before','tn-insert-after');
    over=null;
  }
  nav.addEventListener('dragstart', ev=>{
    const target=ev.target.closest('.nav-link[data-sort-key]');
    if (!active || !target) return;
    dragging=target;
    dragging.classList.add('tn-dragging');
    if (ev.dataTransfer) {ev.dataTransfer.effectAllowed='move';ev.dataTransfer.setData('text/plain',target.dataset.sortKey);}
  });
  nav.addEventListener('dragover', ev=>{
    if (!active || !dragging) return;
    const target=ev.target.closest('.nav-link[data-sort-key]');
    if (!target || target===dragging || target.parentElement!==dragging.parentElement) {clearOver();return;}
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect='move';
    const rect=target.getBoundingClientRect();
    const after=ev.clientY>rect.top+rect.height/2;
    if (over!==target) {clearOver();over=target;}
    target.classList.toggle('tn-insert-before',!after);
    target.classList.toggle('tn-insert-after',after);
  });
  nav.addEventListener('drop', ev=>{
    const target=ev.target.closest('.nav-link[data-sort-key]');
    if (!active || !dragging || !target || target===dragging || target.parentElement!==dragging.parentElement) return;
    ev.preventDefault();
    const after=target.classList.contains('tn-insert-after');
    const before = JSON.stringify(collect());
    target.parentElement.insertBefore(dragging,after?target.nextSibling:target);
    if (JSON.stringify(collect())!==before) {current.push(JSON.parse(before));if(current.length>50)current.shift();changed();syncHomepageAndPager();}
    clearOver();
  });
  nav.addEventListener('dragend',()=>{if(dragging)dragging.classList.remove('tn-dragging');dragging=null;clearOver();});
  undo.addEventListener('click',()=>{if(!current.length)return;applyOrder(current.pop());changed();});
  reset.addEventListener('click',()=>{if(!saved)return;applyOrder(saved);current=[];changed();});

  save.addEventListener('click',async()=>{
    if(!dirty||busy)return;
    busy=true;refreshControls();message('正在保存并重新生成预览…');
    try {
      const payload=collect();
      const res=await api('/__tn/save',payload);
      saved=deepCopy(payload);gitState=res.git;current=[];changed();
      message('草稿已保存，预览已更新；尚未发布给访客。','success');
    }catch(e){message('保存失败：'+e.message,'error');}
    finally{busy=false;refreshControls();}
  });
  publish.addEventListener('click',async()=>{
    if(dirty||busy||!gitState?.unpublished)return;
    if(!window.confirm('确定发布文章排序吗？\n\n仅提交 order.json 并推送到 GitHub main 分支。\n发布成功后，GitHub Actions 会部署给所有访客。'))return;
    busy=true;refreshControls();message('正在提交并推送 GitHub…');
    try {
      const res=await api('/__tn/publish',{confirm:true});
      gitState=res.git;
      message('已推送到 GitHub。请打开 Actions 检查部署结果。','success');
    }catch(e){message('发布失败：'+e.message,'error');}
    finally{busy=false;refreshControls();}
  });

  api('/__tn/state').then(data=>{
    saved=deepCopy(data.manifest);
    gitState=data.git;
    changed();
    message(gitState.setup_pending?'升级文件尚未提交：请先执行安装说明中的 Git 命令，再发布。':(gitState.unpublished?'本地有尚未发布的顺序草稿。':'可开始拖拽；修改仅在本地生效。'));
  }).catch(e=>{message('无法读取管理状态：'+e.message,'error');save.disabled=true;publish.disabled=true;});
})();
