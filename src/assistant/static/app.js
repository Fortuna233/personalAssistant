const $ = id => document.getElementById(id);
let documents = [], current = null, progress = null, chapters = [];
async function api(path, options = {}) {
  const response = await fetch('/api/' + path, {...options, headers: {'Content-Type':'application/json','X-Study-Client':'web',...options.headers}});
  if (!response.ok) { const error = await response.json().catch(()=>({detail:response.statusText})); throw new Error(error.detail || '请求失败'); }
  return response.json();
}
function element(tag, text, className) { const el=document.createElement(tag); el.textContent=text; if(className)el.className=className; return el; }
function showMessage(error) { $('reader-message').textContent=error.message || error; }
async function refresh() {
  documents = await api('documents'); render();
  const state = await api('status');
  $('status').textContent=state.index.running?'正在更新索引…':state.index.error || (state.index.completed?'索引更新：'+new Date(state.index.completed).toLocaleString():'等待首次索引');
}
function render(results) {
  const list=$('documents'); list.replaceChildren();
  let rows=results || documents.filter(d=>!$('filter').value || ($('filter').value==='data'?!['.md','.pdf','.epub'].includes(d.kind):d.kind===$('filter').value));
  $('count').textContent=rows.length+' 条资料';
  if(!rows.length)list.append(element('p','暂无资料。请确认主机资料目录，或等待索引完成。'));
  rows.forEach(row=>{
    const doc=documents.find(d=>d.id===row.id); if(!doc)return;
    const card=element('button','','card'); card.append(element('span',doc.kind.slice(1).toUpperCase(),'type'),element('h3',doc.path.split('/').pop()),element('p',doc.path));
    card.append(element('p',row.excerpt || (doc.size/1024).toFixed(1)+' KB'));
    if(row.location)card.append(element('p',row.location));
    if(doc.error)card.append(element('p','索引提示：'+doc.error));
    card.onclick=()=>openDocument(doc).catch(showMessage); list.append(card);
  });
}
async function enter() { await refresh(); $('login').hidden=true; $('workspace').hidden=false; $('logout').hidden=false; }
$('login-form').onsubmit=async event=>{event.preventDefault();try{await api('login',{method:'POST',body:JSON.stringify({token:$('token').value})});$('token').value='';await enter();}catch(e){$('login-error').textContent=e.message;}};
$('logout').onclick=async()=>{await api('logout',{method:'POST'});location.reload();};
$('filter').onchange=()=>render();
$('search-form').onsubmit=async event=>{event.preventDefault();try{render(await api('search?q='+encodeURIComponent($('query').value)));}catch(e){$('status').textContent=e.message;}};
$('clear').onclick=()=>{$('query').value='';render();};
$('scan').onclick=async()=>{$('scan').disabled=true;try{await api('scan',{method:'POST'});await refresh();}catch(e){$('status').textContent=e.message;}finally{$('scan').disabled=false;}};
$('back').onclick=()=>{$('reader').hidden=true;document.querySelector('.library').hidden=false;$('content').replaceChildren();current=null;};
async function openDocument(doc) {
  current=doc; chapters=[]; $('reader-message').textContent='';
  document.querySelector('.library').hidden=true; $('reader').hidden=false;
  $('reader-title').textContent=doc.path; $('revision').textContent='原文版本 '+doc.revision.slice(0,12);
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
setInterval(()=>{if(!$('workspace').hidden&&!current)refresh().catch(()=>{$('status').textContent='主机暂不可达；Obsidian 本地笔记仍可离线编辑。';});},30000);

$('position').onchange=()=>{if(current&&current.kind==='.epub')renderChapter();};
