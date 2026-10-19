const $ = id => document.getElementById(id);
let documents = [], current = null, progress = null, chapters = [];
async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {...options, headers: {'Content-Type':'application/json','X-Study-Client':'web',...options.headers}});
  if (!response.ok) { const error = await response.json().catch(()=>({detail:response.statusText})); throw new Error(error.detail || '请求失败'); }
  return response.json();
}
function element(tag, text, className) { const el=document.createElement(tag); el.textContent=text; if(className)el.className=className; return el; }
function showMessage(error) { $('reader-message').textContent=error.message || error; }
let entries = [], selectedPath = null, directory = null, searchResults = null;
let sortBy = localStorage.getItem('study-sort') || 'name';
if (!['name','kind','size','created_at','modified_at'].includes(sortBy)) sortBy = 'name';
let sortDirection = localStorage.getItem('study-direction') === 'desc' ? 'desc' : 'asc';
let dialogAction = null, actionEntry = null, busy = false;
const expanded = new Set();
const parentOf = path => path.includes('/') ? path.slice(0,path.lastIndexOf('/')) : '';
const joinPath = (folder,name) => folder ? folder + '/' + name : name;
const formatDate = value => new Date(value).toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const formatSize = bytes => bytes == null ? '—' : bytes < 1024 ? bytes + ' B' : bytes < 1048576 ? (bytes/1024).toFixed(1) + ' KB' : (bytes/1048576).toFixed(1) + ' MB';
const typeName = entry => entry.is_dir ? '文件夹' : entry.kind ? entry.kind.slice(1).toUpperCase() : '文件';
function fileMessage(message) { $('file-message').textContent = message; }
async function refresh() {
  [documents, entries] = await Promise.all([api('documents'),api('files')]);
  if (selectedPath && !entries.some(e=>e.path===selectedPath)) selectedPath = null;
  if (directory && !entries.some(e=>e.path===directory && e.is_dir)) directory = null;
  if ($('query').value.trim()) searchResults = await api('search?q='+encodeURIComponent($('query').value));
  renderTree(); render();
  const state = await api('status');
  $('status').textContent=state.index.running?'更新中…':state.index.error || '';
  $('scan').title=state.index.completed?'上次更新：'+new Date(state.index.completed).toLocaleString():'更新资料索引';
}
function choose(entry) {
  selectedPath = entry.path;
  if (entry.is_dir) { directory = entry.path; expanded.add(entry.path); } else { directory = entry.parent; }
  current = null; $('reader').hidden=true; document.querySelector('.library').hidden=false;
  renderTree(); render();
}
function navigate(folder) {
  directory = folder; selectedPath = null; searchResults = null; $('query').value='';
  current=null; $('reader').hidden=true; document.querySelector('.library').hidden=false;
  renderTree(); render();
}
function renderTree() {
  const tree = $('file-tree'); tree.replaceChildren();
  const root = element('button','▦ 全部资料','tree-root'); root.onclick=()=>navigate(null); tree.append(root);
  const rootFolder = element('button','▱ 资料库根目录','tree-root'); rootFolder.onclick=()=>navigate(''); tree.append(rootFolder);
  function branch(parent,container) {
    entries.filter(e=>e.parent===parent).sort((a,b)=>Number(b.is_dir)-Number(a.is_dir)||a.name.localeCompare(b.name,'zh-CN',{numeric:true})).forEach(entry=>{
      const node=element('div','','tree-node');
      if(entry.is_dir) {
        const details=document.createElement('details'); details.open=expanded.has(entry.path);
        const summary=document.createElement('summary'); const select=element('button','▱ '+entry.name,'tree-label');
        select.title=entry.path; select.classList.toggle('selected',selectedPath===entry.path||directory===entry.path);
        select.onclick=event=>{event.preventDefault();choose(entry);}; summary.append(select);details.append(summary);
        details.ontoggle=()=>{if(details.open)expanded.add(entry.path);else expanded.delete(entry.path);};
        const children=element('div','','tree-children');branch(entry.path,children);details.append(children);node.append(details);
      } else {
        const select=element('button','· '+entry.name,'tree-label');select.title=entry.path;
        select.classList.toggle('selected',selectedPath===entry.path);select.onclick=()=>choose(entry);node.append(select);
      }
      container.append(node);
    });
  }
  branch('',tree);
}
function render() {
  const list=$('documents');list.replaceChildren();
  let rows=entries.filter(entry=>directory===null ? !entry.is_dir : entry.parent===directory);
  const filter=$('filter').value;
  if(filter)rows=rows.filter(e=>!e.is_dir&&(filter==='data'?!['.md','.pdf','.epub'].includes(e.kind):e.kind===filter));
  if(searchResults) {
    const hits=new Map(); searchResults.forEach(hit=>{if(!hits.has(hit.id))hits.set(hit.id,hit);});
    rows=rows.filter(e=>hits.has(e.document_id)).map(e=>({...e,hit:hits.get(e.document_id)}));
  }
  rows.sort((a,b)=>{
    if(a.is_dir!==b.is_dir)return a.is_dir?-1:1;
    let result=sortBy==='size' ? (a.size||0)-(b.size||0) : String(a[sortBy]||'').localeCompare(String(b[sortBy]||''),'zh-CN',{numeric:true});
    if(!result)result=a.path.localeCompare(b.path,'zh-CN',{numeric:true});
    return sortDirection==='asc'?result:-result;
  });
  $('count').textContent=rows.length+' 项';
  $('sort-by').value=sortBy; $('sort-direction').textContent=sortDirection==='asc'?'升序 ↑':'降序 ↓';
  document.querySelectorAll('[data-sort]').forEach(button=>{const active=button.dataset.sort===sortBy;button.textContent=({name:'名称',kind:'类型',size:'大小',created_at:'创建日期',modified_at:'最近修改'})[button.dataset.sort]+(active?(sortDirection==='asc'?' ↑':' ↓'):'');button.parentElement.setAttribute('aria-sort',active?(sortDirection==='asc'?'ascending':'descending'):'none');});
  if(!rows.length){const tr=document.createElement('tr');const td=element('td','暂无文件','empty-state');td.colSpan=6;tr.append(td);list.append(tr);}
  rows.forEach(entry=>{
    const tr=document.createElement('tr');tr.classList.toggle('selected',selectedPath===entry.path);
    const selection=document.createElement('td');const radio=document.createElement('input');radio.type='radio';radio.name='selected-file';radio.checked=selectedPath===entry.path;radio.setAttribute('aria-label','选择 '+entry.name);radio.onchange=()=>{selectedPath=entry.path;renderTree();render();};selection.append(radio);
    const name=document.createElement('td');const link=element('button',(entry.is_dir?'▱ ':'')+entry.name,'file-name');
    link.onclick=()=>{if(entry.is_dir){choose(entry);}else{const doc=documents.find(d=>d.id===entry.document_id);if(doc)openDocument(doc).catch(showMessage);else {const a=document.createElement('a');a.href='/api/files/download?path='+encodeURIComponent(entry.path);a.download=entry.name;a.click();}}};name.append(link,element('small',entry.path,'file-path'));
    if(entry.hit)name.append(element('small',entry.hit.location+' · '+entry.hit.excerpt,'search-excerpt'));
    if(entry.error)name.append(element('small','索引提示：'+entry.error,'search-excerpt'));
    const created=element('td',formatDate(entry.created_at)+(entry.created_source==='first_seen'?' *':''));created.title=entry.created_source==='first_seen'?'系统未提供创建日期，使用首次发现时间':'文件系统创建时间';
    tr.append(selection,name,element('td',typeName(entry),'type-cell'),element('td',formatSize(entry.size)),created,element('td',formatDate(entry.modified_at)));
    tr.onclick=event=>{if(!event.target.closest('button,input,a')){selectedPath=entry.path;renderTree();render();}};list.append(tr);
  });
  const selected=entries.find(e=>e.path===selectedPath);
  $('selection-info').textContent=selected?selected.name:'';
  ['rename','move','copy','delete'].forEach(id=>$(id).disabled=!selected||busy);
  document.querySelectorAll('[data-tree-action]').forEach(button=>button.disabled=['rename','move','copy','delete'].includes(button.dataset.treeAction)&&(!selected||busy));
  const crumbs=$('breadcrumbs');crumbs.replaceChildren();const all=element('button','全部资料','quiet');all.onclick=()=>navigate(null);crumbs.append(all);
  if(directory!==null){const root=element('button','/ 资料库','quiet');root.onclick=()=>navigate('');crumbs.append(root);let path='';directory.split('/').filter(Boolean).forEach(part=>{path=joinPath(path,part);const destination=path;const button=element('button','/ '+part,'quiet');button.onclick=()=>navigate(destination);crumbs.append(button);});}
}
function changeSort(key, toggle=false) {
  if(toggle&&sortBy===key)sortDirection=sortDirection==='asc'?'desc':'asc';else sortBy=key;
  localStorage.setItem('study-sort',sortBy);localStorage.setItem('study-direction',sortDirection);render();
}
function openOperation(action) {
  actionEntry=entries.find(e=>e.path===selectedPath)||null;dialogAction=action;
  if(['move','copy','rename','delete'].includes(action)&&!actionEntry)return;
  const titles={create_file:'新建文件',create_folder:'新建文件夹',rename:'重命名',move:'移动',copy:'复制',delete:'移入回收区'};
  $('dialog-title').textContent=titles[action];$('dialog-error').textContent='';
  $('dialog-description').textContent=action==='delete'?'将“'+actionEntry.path+'”移入主机回收区。其他设备会同步删除；可在此恢复。':action==='rename'||action==='move'?'现有阅读进度与批注会保留。笔记中的链接不会自动改写。':action==='create_file'?'支持 .md、.txt、.csv；例如“课程笔记.md”。':'';
  const deleting=action==='delete';$('name-field').hidden=deleting;$('entry-name').required=!deleting;
  $('destination-field').hidden=deleting||action==='rename';$('text-field').hidden=action!=='create_file';
  const destination=$('destination');destination.replaceChildren();
  const folders=[{path:'',name:'资料库根目录'},...entries.filter(e=>e.is_dir).sort((a,b)=>a.path.localeCompare(b.path))];
  folders.forEach(folder=>{if(actionEntry?.is_dir&&['move','copy'].includes(action)&&(folder.path===actionEntry.path||folder.path.startsWith(actionEntry.path+'/')))return;const option=element('option',folder.path||folder.name);option.value=folder.path;destination.append(option);});
  destination.value=['move','copy'].includes(action)?actionEntry.parent:(actionEntry?.is_dir?actionEntry.path:directory||actionEntry?.parent||'');
  $('entry-name').value=actionEntry&&['rename','move','copy'].includes(action)?actionEntry.name:action==='create_file'?'新建笔记.md':'';
  if(action==='copy') {const name=actionEntry.name;const dot=actionEntry.is_dir?-1:name.lastIndexOf('.');$('entry-name').value=dot>0?name.slice(0,dot)+' - 副本'+name.slice(dot):name+' - 副本';}
  $('entry-content').value='';$('dialog-submit').textContent=deleting?'移入回收区':'确认';$('dialog-submit').disabled=false;
  $('file-dialog').showModal(); if(!deleting){$('entry-name').focus();$('entry-name').select();}
}
$('file-form').onsubmit=async event=>{
  event.preventDefault();if(busy)return;busy=true;$('dialog-submit').disabled=true;
  try {
    const name=$('entry-name').value.trim();if(dialogAction!=='delete'&&(!name||name.includes('/')||name.includes('\\')))throw new Error('请输入单个有效名称，目录请在目标文件夹中选择');
    const target=dialogAction==='rename'?joinPath(actionEntry.parent,name):joinPath($('destination').value,name);
    const result=await api('files/operations',{method:'POST',body:JSON.stringify({action:dialogAction==='rename'?'move':dialogAction,path:actionEntry?.path||'',expected_version:actionEntry?.version||'',target:dialogAction==='delete'?'':target,content:$('entry-content').value})});
    $('file-dialog').close();selectedPath=result.path||null;if(result.path){directory=parentOf(result.path);if(directory)expanded.add(directory);}
    await refresh();fileMessage(dialogAction==='delete'?'已移入回收区，可随时恢复。':'已完成');
  }catch(error){$('dialog-error').textContent=error.message;}finally{busy=false;$('dialog-submit').disabled=false;render();}
};
$('dialog-cancel').onclick=()=>{if(!busy)$('file-dialog').close();};
$('file-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
document.querySelectorAll('[data-tree-action]').forEach(button=>button.onclick=()=>openOperation(button.dataset.treeAction));
$('new-file').onclick=()=>openOperation('create_file');$('new-folder').onclick=()=>openOperation('create_folder');
['rename','move','copy','delete'].forEach(action=>$(action).onclick=()=>openOperation(action));
$('sort-by').onchange=()=>changeSort($('sort-by').value);$('sort-direction').onclick=()=>changeSort(sortBy,true);
document.querySelectorAll('[data-sort]').forEach(button=>button.onclick=()=>changeSort(button.dataset.sort,true));
async function loadTrash(){const rows=await api('files/trash');$('trash-list').replaceChildren();if(!rows.length)$('trash-list').append(element('p','回收区为空'));rows.forEach(row=>{const item=element('div','','trash-item');item.append(element('strong',row.path),element('small',formatDate(row.deleted_at)));const restore=element('button','恢复');restore.onclick=async()=>{restore.disabled=true;try{await api('files/trash/'+row.id+'/restore',{method:'POST'});await refresh();await loadTrash();fileMessage('已恢复：'+row.path);}catch(error){$('trash-error').textContent=error.message;restore.disabled=false;}};item.append(restore);$('trash-list').append(item);});}
$('trash-open').onclick=async()=>{$('trash-error').textContent='';$('trash-dialog').showModal();try{await loadTrash();}catch(error){$('trash-error').textContent=error.message;}};
$('trash-close').onclick=()=>$('trash-dialog').close();
async function enter() { await refresh(); $('login').hidden=true; $('workspace').hidden=false; $('logout').hidden=false; $('view-tabs').hidden=false; if(window.literatureReady)window.literatureReady(); }
$('login-form').onsubmit=async event=>{event.preventDefault();try{await api('login',{method:'POST',body:JSON.stringify({token:$('token').value})});$('token').value='';await enter();}catch(e){$('login-error').textContent=e.message;}};
$('logout').onclick=async()=>{await api('logout',{method:'POST'});location.reload();};
$('filter').onchange=()=>render();
$('search-form').onsubmit=async event=>{event.preventDefault();try{searchResults=await api('search?q='+encodeURIComponent($('query').value));render();}catch(e){$('status').textContent=e.message;}};
$('clear').onclick=()=>{$('query').value='';searchResults=null;render();};
$('scan').onclick=async()=>{$('scan').disabled=true;try{await api('scan',{method:'POST'});await refresh();}catch(e){$('status').textContent=e.message;}finally{$('scan').disabled=false;}};
$('back').onclick=()=>{$('reader').hidden=true;document.querySelector('.library').hidden=false;$('content').replaceChildren();current=null;};
async function openDocument(doc) {
  current=doc; chapters=[]; $('reader-message').textContent='';
  document.querySelector('.library').hidden=true; $('reader').hidden=false;
  $('reader-title').textContent=doc.path; $('reader-title').title='原文版本 '+doc.revision.slice(0,12);
  $('download').href='/api/documents/'+doc.id+'/file'; $('download').target='_blank';$('download').rel='noopener';
  const state=await api('documents/'+doc.id+'/reading');progress=state.progress;
  if(progress.revision!==doc.revision)showMessage('原文已变化，旧进度和批注仍保留；请核对位置。');
  $('position').value=progress.position; renderNotes(state.annotations);
  $('prev').hidden=$('next').hidden=doc.kind!=='.epub';
  const content=$('content');content.replaceChildren();
  if(doc.kind==='.pdf') {
    content.append(element('p','PDF 使用浏览器阅读器。翻页后请在上方填写页码并保存；手机若无法内嵌显示，请打开原文件。'));
    const frame=document.createElement('iframe');frame.title='PDF 阅读器';frame.src=$('download').href+'#page='+progress.position;content.append(frame);
  } else if(['.png','.jpg','.jpeg','.webp'].includes(doc.kind)) {
    const img=document.createElement('img');img.src=$('download').href;img.alt=doc.path;content.append(img);
  } else {
    const data=await api('documents/'+doc.id+'/content');
    if(data.chapters){chapters=data.chapters;renderChapter();}else{content.innerHTML=data.html || '';content.querySelectorAll('a').forEach(a=>{a.target='_blank';a.rel='noopener noreferrer';});}
  }
}
function renderChapter(){let index=Math.min(Math.max(Number($('position').value)||1,1),chapters.length);$('position').value=index;const chapter=chapters[index-1];$('content').replaceChildren();if(chapter){$('content').append(element('h2',chapter.title));chapter.text.split('\n\n').filter((p,i)=>i!==0||p!==chapter.title).forEach(p=>$('content').append(element('p',p)));}else $('content').append(element('p','未发现可读章节'));}
$('prev').onclick=()=>{$('position').value=Math.max(1,Number($('position').value)-1);renderChapter();};
$('next').onclick=()=>{$('position').value=Math.min(chapters.length,Number($('position').value)+1);renderChapter();};
$('save-progress').onclick=async()=>{try{const result=await api('documents/'+current.id+'/reading',{method:'PUT',body:JSON.stringify({revision:current.revision,position:Number($('position').value),version:progress.version})});progress.version=result.version;showMessage('进度已保存到主机');}catch(e){showMessage(e);}};
function renderNotes(notes){$('notes').replaceChildren();notes.forEach(n=>{const node=element('article','','note');node.append(element('small',n.location+' · '+n.created+(n.revision!==current.revision?' · 旧原文版本':'')));if(n.quote)node.append(element('blockquote',n.quote));node.append(element('p',n.note));$('notes').append(node);});}
$('note-form').onsubmit=async event=>{event.preventDefault();try{await api('documents/'+current.id+'/annotations',{method:'POST',body:JSON.stringify({revision:current.revision,location:(current.kind==='.epub'?'章 ':current.kind==='.pdf'?'页 ':'位置 ')+$('position').value,quote:$('quote').value,note:$('note').value})});$('note').value='';$('quote').value='';renderNotes((await api('documents/'+current.id+'/reading')).annotations);showMessage('批注已保存');}catch(e){showMessage(e);}};
enter().catch(()=>{});
setInterval(()=>{if(!$('workspace').hidden&&!current&&!busy&&!$('file-dialog').open&&!$('trash-dialog').open)refresh().catch(()=>{$('status').textContent='主机暂不可达；Obsidian 本地笔记仍可离线编辑。';});},30000);

$('position').onchange=()=>{if(current&&current.kind==='.epub')renderChapter();};
