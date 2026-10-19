(() => {
  const get=id=>document.getElementById(id);
  let zotero=null;
  async function request(route,options={}) {const response=await fetch('/api/sync/'+route,{...options,headers:{'Content-Type':'application/json','X-Study-Client':'web'}});const value=await response.json();if(!response.ok)throw Error(value.detail||'请求失败');return value;}
  function node(tag,text){const value=document.createElement(tag);value.textContent=text;return value;}
  function renderZotero(){
    if(!zotero)return;
    get('zotero-status').textContent=zotero.message+(zotero.last_sync?' · '+new Date(zotero.last_sync).toLocaleString():'')+(!zotero.allowed_roots_configured?'\n本机附件目录尚未配置：请设置 zotero.allowed_roots。':'');
    const query=get('zotero-search').value.toLowerCase();get('zotero-items').replaceChildren();
    const items=zotero.items.filter(item=>!query||JSON.stringify(item.data).toLowerCase().includes(query));
    items.slice(0,200).forEach(item=>{const row=node('div','');row.className='zotero-entry';const body=node('div','');body.append(node('strong',item.title||item.data.filename||item.key));body.append(node('small',item.type+' · '+(item.message||item.data.DOI||item.key)));row.append(body);
      if(item.path){const link=node('a','打开附件');link.href='/api/files/download?path='+encodeURIComponent(item.path);row.append(link);}get('zotero-items').append(row);});
    if(items.length>200)get('zotero-items').append(node('p','仅展示前 200 条，请搜索缩小范围。'));
  }
  get('connections-open').onclick=async()=>{get('connections-dialog').showModal();try{const [storage,value]=await Promise.all([request('storage'),request('zotero')]);zotero=value;get('storage-summary').textContent='记录（Git）：'+storage.records_root+'\n资料：'+storage.media_root+'\n元数据由 Zotero 官方同步；附件经主机与 Syncthing 同步。';
    get('zotero-kind').value=value.settings.kind;get('zotero-id').value=value.settings.library_id;get('zotero-enabled').checked=value.settings.enabled;renderZotero();
    get('sync-items').replaceChildren();storage.selection.candidates.forEach(path=>{const label=node('label','');label.className='checkbox-label';const input=node('input','');input.type='checkbox';input.checked=!storage.selection.excluded.includes(path);input.dataset.path=path;label.append(input,node('span',path));get('sync-items').append(label);});get('sync-message').textContent=storage.selection.available?'':'此助手实例所在电脑尚未配置 SYNCTHING_API_KEY；可预览选择，应用需要配置。';
  }catch(error){get('zotero-status').textContent=error.message;}};
  get('connections-close').onclick=()=>get('connections-dialog').close();get('zotero-search').oninput=renderZotero;
  get('zotero-form').onsubmit=async event=>{event.preventDefault();try{zotero=await request('zotero',{method:'PUT',body:JSON.stringify({kind:get('zotero-kind').value,library_id:get('zotero-id').value,enabled:get('zotero-enabled').checked})});renderZotero();get('zotero-status').textContent+='\n已保存。';}catch(error){get('zotero-status').textContent=error.message;}};
  get('zotero-sync').onclick=async()=>{get('zotero-sync').disabled=true;get('zotero-status').textContent='正在读取本机 Zotero 并桥接附件…';try{zotero=await request('zotero/run',{method:'POST'});renderZotero();}catch(error){get('zotero-status').textContent=error.message;}finally{get('zotero-sync').disabled=false;}};
  get('sync-apply').onclick=async()=>{get('sync-apply').disabled=true;try{const excluded=[...get('sync-items').querySelectorAll('input')].filter(input=>!input.checked).map(input=>input.dataset.path);const result=await request('selection',{method:'POST',body:JSON.stringify({excluded})});get('sync-message').textContent=result.message;}catch(error){get('sync-message').textContent=error.message;}finally{get('sync-apply').disabled=false;}};
})();
