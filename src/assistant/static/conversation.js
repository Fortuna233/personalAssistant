(() => {
  let sessionId=null, busy=false, lastMessages='', pendingRequest=null, panel=null;
  const names={literature:'文献阅读',files:'资料库',tasks:'任务进度'};
  function status(text){$('conversation-status').textContent=text;}
  function rememberSession(id){sessionId=id;localStorage.setItem('assistant-conversation',id);}
  async function sessions(){
    const rows=await api('conversations');$('conversation-session').replaceChildren();
    rows.forEach(row=>{const option=element('option',row.title);option.value=row.id;$('conversation-session').append(option);});
    $('conversation-session').value=sessionId;
  }
  async function transcript(){
    if(!sessionId)return;const value=await api('conversations/'+sessionId), serialized=JSON.stringify(value.messages);if(serialized===lastMessages)return;lastMessages=serialized;
    const box=$('conversation-messages');const atEnd=box.scrollHeight-box.scrollTop-box.clientHeight<60;box.replaceChildren();
    if(!value.messages.length)box.append(element('p','想做什么，直接告诉我。','conversation-empty'));
    value.messages.forEach(row=>{const entry=element('article','','conversation-message '+row.role);entry.append(element('small',row.role==='user'?'你':'沈轻媞'));entry.append(element('p',row.text));
      (row.evidence||[]).forEach(e=>entry.append(element('blockquote','['+e.block_id+'] '+e.quote)));
      if(row.workspace&&row.workspace!=='none'){const button=element('button','打开'+names[row.workspace],'quiet');button.onclick=()=>openPanel(row.workspace,row.document_id).catch(error=>status(error.message));entry.append(button);}
      if(row.task_status)entry.append(element('small','任务：'+row.task_status));box.append(entry);});
    if(atEnd)box.scrollTop=box.scrollHeight;
  }
  async function openPanel(workspace,documentId){
    if(!names[workspace])return;
    panel=workspace;$('task-panel').hidden=false;$('workspace').classList.add('workbench-open');$('task-panel-title').textContent=names[workspace];
    $('file-workspace').hidden=workspace!=='files';$('literature-view').hidden=workspace!=='literature';$('tasks-view').hidden=workspace!=='tasks';
    if(workspace==='literature')await window.openLiteratureWorkspace(documentId);
    if(workspace==='files'){$('workspace').classList.remove('literature-mode');document.querySelector('.library').hidden=false;$('reader').hidden=true;await refresh();}
    if(workspace==='tasks')await renderTasks();updateContext();
  }
  async function renderTasks(){
    const jobs=await api('literature/jobs');const box=$('conversation-tasks');box.replaceChildren();
    if(!jobs.length)box.append(element('p','暂无任务','hint'));
    jobs.forEach(job=>{const row=element('article','','conversation-task');row.append(element('strong',job.topic+' · '+job.status));row.append(element('p',job.error||job.progress));row.append(element('code',job.id));const button=element('button','打开文献阅读','quiet');button.onclick=()=>openPanel('literature',job.document_id).catch(error=>status(error.message));row.append(button);box.append(row);});
  }
  function updateContext(){const context=panel==='literature'&&window.activeReadingContext?.();$('conversation-input').placeholder=context?'针对当前论文小节提问…':'说说你想做什么…';}
  $('task-panel-close').onclick=()=>{panel=null;if(names[location.hash.slice(1)])history.replaceState(null,'',location.pathname+location.search);$('task-panel').hidden=true;$('workspace').classList.remove('workbench-open');updateContext();};
  $('literature-tab').onclick=()=>{$('conversation-view').hidden=false;$('task-panel-close').click();};
  $('files-tab').onclick=()=>openPanel('files').catch(error=>status(error.message));
  $('conversation-settings').onclick=()=>$('lit-settings-open').click();
  $('conversation-new').onclick=async()=>{try{const value=await api('conversations',{method:'POST'});rememberSession(value.id);$('task-panel-close').click();lastMessages='';pendingRequest=null;await sessions();await transcript();status('');}catch(error){status(error.message);}};
  $('conversation-session').onchange=async()=>{rememberSession($('conversation-session').value);$('task-panel-close').click();lastMessages='';pendingRequest=null;await transcript().catch(error=>status(error.message));};
  $('conversation-form').onsubmit=async event=>{
    event.preventDefault();if(busy||!sessionId)return;const text=$('conversation-input').value.trim();if(!text)return;
    const context=panel==='literature'?window.activeReadingContext?.():null;
    const signature=JSON.stringify({text,context});if(!pendingRequest||pendingRequest.signature!==signature)pendingRequest={signature,id:Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('')};
    busy=true;$('conversation-send').disabled=true;$('conversation-new').disabled=true;$('conversation-session').disabled=true;status('处理中…');
    try{const reply=await api('conversations/'+sessionId+'/messages',{method:'POST',body:JSON.stringify({text,request_id:pendingRequest.id,context:context||null})});$('conversation-input').value='';pendingRequest=null;await transcript();await sessions();status('');if(reply.workspace&&reply.workspace!=='none')await openPanel(reply.workspace,reply.document_id);}
    catch(error){status(error.message);}finally{busy=false;$('conversation-send').disabled=false;$('conversation-new').disabled=false;$('conversation-session').disabled=false;}
  };
  window.addEventListener('reading-context-changed',updateContext);
  window.conversationReady=async()=>{try{rememberSession(localStorage.getItem('assistant-conversation'));if(sessionId){try{await transcript();}catch(error){if(error.message!=='对话不存在')throw error;sessionId=null;}}if(!sessionId){const value=await api('conversations',{method:'POST'});rememberSession(value.id);await transcript();}await sessions();const workspace=location.hash.slice(1);if(names[workspace])await openPanel(workspace);}catch(error){status(error.message);}};
  setInterval(()=>{if(!$('workspace').hidden&&!busy){transcript().catch(error=>status(error.message));if(panel==='tasks')renderTasks().catch(error=>status(error.message));}},3000);
  if(!$('workspace').hidden)window.conversationReady();
})();
