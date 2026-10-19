(() => {
  let jobs = [], settings = null, activeJob = null, exportJob = null, previewRevision = null;
  let questionBusy = false, submitting = false, inlineRevision = null, inlineDirty = false;
  const labels = {background:'背景、目的及意义',methods:'研究设计与方法',results:'结果与结论',author_discussion:'作者讨论',assistant_analysis:'助手分析',suggested_questions:'建议思考（助手）',limitations:'未覆盖与待核对'};
  const statusLabels = {queued:'等待执行',running:'处理中',completed:'待核对',failed:'失败',cancelled:'已取消'};
  function message(error) { const text=error.message||error;$('lit-state').textContent=text;$('lit-chat-status').textContent=text; }
  function setView(literature) {
    if(inlineDirty&&!confirm('尚有未保存的想法，确定切换？'))return;inlineDirty=false;
    $('connections-open').hidden=false;
    $('workspace').classList.toggle('literature-mode',literature);
    $('literature-view').hidden = !literature;
    document.querySelector('.library').hidden = literature;
    $('reader').hidden = true; current = null;
    if(literature)refreshLiterature().catch(message);
  }
  window.openLiteratureWorkspace = async documentId => {
    $('workspace').classList.add('literature-mode');$('literature-view').hidden=false;document.querySelector('.library').hidden=true;await refreshLiterature();
    if(documentId){$('lit-source').value=documentId;$('lit-source').dispatchEvent(new Event('change'));}
  };
  window.activeReadingContext = () => activeJob ? {job_id:activeJob.id,section_id:$('lit-section').value} : null;
  window.canLeaveReading = () => !inlineDirty||confirm('尚有未保存的想法，确定切换？');
  $('literature-tab').onclick=()=>setView(true);
  $('files-tab').onclick=()=>setView(false);
  window.literatureReady = async () => {
    try {
      settings = await api('literature/settings');
      updateModelState();
    } catch(error) { message(error); }
  };
  function updateModelState() {
    $('connections-open').hidden=false;if(!settings)return;
    $('lit-start').disabled=!settings.model_status.ready;$('lit-question-form').querySelector('button').disabled=!settings.model_status.ready;
    message(settings.model_status.ready?'':'尚未配置模型：'+settings.model_status.missing.join('、'));
  }
  function fillSources() {
    const selected=$('lit-source').value;
    $('lit-source').replaceChildren();
    $('lit-source').append(element('option','选择原文'));
    $('lit-source').firstChild.value='';
    documents.filter(doc=>['.pdf','.epub','.md','.txt'].includes(doc.kind)).forEach(doc=>{
      const option=element('option',doc.path);option.value=doc.id;$('lit-source').append(option);
    });
    if([...$('lit-source').options].some(option=>option.value===selected))$('lit-source').value=selected;
  }
  async function refreshLiterature() {
    [jobs,settings]=await Promise.all([api('literature/jobs'),api('literature/settings')]);
    fillSources();updateModelState();renderJobs();renderAnswers();
  }
  function appendAnalysis(cell,sections,fields) {
    sections.forEach(section=>{
      const values=fields.flatMap(field=>(section.analysis[field]||[]).map(value=>({field,value})));
      if(!values.length)return;
      cell.append(element('strong',section.title,'lit-subheading'));
      values.forEach(({field,value})=>cell.append(element('p',(fields.length>1?labels[field]+'：':'')+value)));
    });
  }
  async function action(id,command) {
    try { await api('literature/jobs/'+id+'/'+command,{method:'POST'});await refreshLiterature(); }
    catch(error){message(error);}
  }
  function renderJobs() {
    const filter=$('lit-topic-filter').value;
    const topics=[...new Set(jobs.filter(job=>job.kind==='read').map(job=>job.topic))].sort();
    $('lit-topics').replaceChildren();topics.forEach(topic=>{const option=element('option',topic);option.value=topic;$('lit-topics').append(option);});
    $('lit-topic-filter').replaceChildren();const all=element('option','全部');all.value='';$('lit-topic-filter').append(all);
    topics.forEach(topic=>{const option=element('option',topic);option.value=topic;$('lit-topic-filter').append(option);});$('lit-topic-filter').value=filter;
    $('lit-jobs').replaceChildren();
    const seen=new Set();
    const rows=jobs.filter(job=>{if(job.kind!=='read'||(filter&&job.topic!==filter))return false;const key=job.document_id+'|'+job.topic;if(seen.has(key))return false;seen.add(key);return true;});
    if(!rows.length){const tr=document.createElement('tr');const cell=element('td','选择原文与主题，手动开始阅读。','empty-state');cell.colSpan=5;tr.append(cell);$('lit-jobs').append(tr);}
    rows.forEach(job=>{
      const tr=document.createElement('tr');const meta=document.createElement('td');const result=job.result;
      const title=element('button',result?.metadata.title||documents.find(doc=>doc.id===job.document_id)?.path||'文献任务','file-name');
      title.onclick=()=>openStudy(job.id).catch(message);title.disabled=job.status!=='completed';meta.append(title);
      if(result){const info=result.metadata;[info.authors.join('；'),info.affiliations.join('；'),info.published_date,info.venue,info.doi].filter(Boolean).forEach(value=>meta.append(element('p',value)));}
      meta.append(element('small',job.topic+' · '+statusLabels[job.status]));meta.append(element('p',job.error||job.progress,'lit-task-state'));
      const actions=element('div','','lit-row-actions');
      if(job.status==='completed') {
        const study=element('button','逐节阅读','quiet');study.onclick=()=>openStudy(job.id).catch(message);
        const save=element('button','保存笔记','quiet');save.onclick=()=>openNotes(job).catch(message);actions.append(study,save);
      } else if(['failed','cancelled'].includes(job.status)) {
        const retry=element('button','继续重试','quiet');retry.onclick=()=>action(job.id,'retry');actions.append(retry);
      } else {const cancel=element('button','取消','quiet');cancel.onclick=()=>action(job.id,'cancel');actions.append(cancel);}
      meta.append(actions);tr.append(meta);
      const background=document.createElement('td'), methods=document.createElement('td'), discussion=document.createElement('td'), ideas=document.createElement('td');
      if(result){
        appendAnalysis(background,result.sections,['background']);appendAnalysis(methods,result.sections,['methods','results']);
        appendAnalysis(discussion,result.sections,['author_discussion','assistant_analysis','limitations','suggested_questions']);
        result.limitations.forEach(value=>discussion.append(element('p',value,'hint')));
        ideas.append(element('p',job.personal_ideas||'留给你填写',job.personal_ideas?'':'hint'));const edit=element('button','我的想法','quiet');edit.onclick=()=>openNotes(job).catch(message);ideas.append(edit);
      } else {background.append(element('p','—'));methods.append(element('p','—'));discussion.append(element('p','—'));}
      tr.append(background,methods,discussion,ideas);$('lit-jobs').append(tr);
    });
  }
  $('lit-topic-filter').onchange=renderJobs;
  $('lit-refresh').onclick=()=>refreshLiterature().catch(message);
  $('lit-source').onchange=async()=>{
    if(!$('lit-source').value){$('lit-metadata-wrap').hidden=true;return;}
    try{const value=await api('literature/metadata/'+$('lit-source').value);$('lit-metadata').replaceChildren();
      $('lit-metadata').append(element('p',value.metadata.title));if(value.metadata.doi)$('lit-metadata').append(element('p','DOI：'+value.metadata.doi));
      value.warnings.forEach(warning=>$('lit-metadata').append(element('p',warning,'hint')));$('lit-metadata-wrap').hidden=false;
    }catch(error){message(error);}
  };
  $('lit-start-form').onsubmit=async event=>{
    event.preventDefault();if(submitting)return;submitting=true;$('lit-start').disabled=true;
    try {const job=await api('literature/jobs',{method:'POST',body:JSON.stringify({document_id:$('lit-source').value,topic:$('lit-topic').value,purpose:$('lit-purpose').value})});await refreshLiterature();message(job.status==='completed'?'已复用相同原文、模型与规则的初稿。':'任务已保存，可关闭页面；主机会继续处理。');}
    catch(error){message(error);}finally{submitting=false;$('lit-start').disabled=!settings?.model_status.ready;}
  };
  async function openStudy(id) {
    if(inlineDirty&&!confirm('尚有未保存的想法，确定切换文献？'))return;
    activeJob=await api('literature/jobs/'+id);if(activeJob.status!=='completed')return;
    $('lit-study-title').textContent=activeJob.result.metadata.title;
    $('lit-section').replaceChildren();activeJob.result.sections.forEach(section=>{const option=element('option',section.title);option.value=section.id;$('lit-section').append(option);});
    $('lit-study').hidden=false;$('literature-view').classList.add('studying');window.dispatchEvent(new Event('reading-context-changed'));renderSection();renderAnswers();
    const doc=documents.find(doc=>doc.id===activeJob.document_id), url='/api/documents/'+activeJob.document_id+'/file';
    $('lit-original').href=url;$('lit-paper-frame').hidden=doc?.kind!=='.pdf';$('lit-section-source').hidden=doc?.kind==='.pdf';
    if(doc?.kind==='.pdf')$('lit-paper-frame').src=url;
    const value=await api('literature/jobs/'+id+'/notes');inlineRevision=value.notes_revision;inlineDirty=false;
    $('lit-inline-ideas').value=value.ideas;$('lit-inline-preview').textContent=value.existing_markdown||value.markdown;
    $('lit-inline-save').disabled=!value.ready;$('lit-inline-status').textContent=value.ready?value.note_path:value.reason;
  }
  function renderSection() {
    if(!activeJob)return;const section=activeJob.result.sections.find(s=>s.id===$('lit-section').value);if(!section)return;
    $('lit-section-source').textContent=section.blocks.map(block=>'['+block.location+' / '+block.id+']\n'+block.text).join('\n\n');
    $('lit-section-analysis').replaceChildren();
    Object.entries(labels).forEach(([key,title])=>{const values=section.analysis[key]||[];if(values.length){$('lit-section-analysis').append(element('h4',title));values.forEach(value=>$('lit-section-analysis').append(element('p',value)));}});
    if(section.analysis.evidence?.length){$('lit-section-analysis').append(element('h4','原文证据'));section.analysis.evidence.forEach(e=>$('lit-section-analysis').append(element('blockquote','['+e.block_id+'] '+e.quote)));}
    renderAnswers();
  }
  $('lit-section').onchange=renderSection;
  $('lit-inline-ideas').oninput=()=>{inlineDirty=true;};
  $('lit-inline-save').onclick=async()=>{if(!activeJob)return;$('lit-inline-save').disabled=true;
    try{const result=await api('literature/jobs/'+activeJob.id+'/notes/save',{method:'POST',body:JSON.stringify({ideas:$('lit-inline-ideas').value,notes_revision:inlineRevision})});const value=await api('literature/jobs/'+activeJob.id+'/notes');inlineRevision=value.notes_revision;inlineDirty=false;$('lit-inline-preview').textContent=value.existing_markdown||value.markdown;$('lit-inline-status').textContent=result.version_pending?'文件已保存，Git 提交待处理：'+result.error:'已提交 '+result.commit.slice(0,12);await refreshLiterature();}
    catch(error){$('lit-inline-status').textContent=error.message;}finally{$('lit-inline-save').disabled=false;}};
  $('lit-study-close').onclick=()=>{if(inlineDirty&&!confirm('尚有未保存的想法，确定离开？'))return;$('lit-study').hidden=true;$('literature-view').classList.remove('studying');$('lit-paper-frame').removeAttribute('src');activeJob=null;inlineDirty=false;window.dispatchEvent(new Event('reading-context-changed'));};
  window.addEventListener('beforeunload',event=>{if(inlineDirty){event.preventDefault();event.returnValue='';}});
  $('lit-question-form').onsubmit=async event=>{
    event.preventDefault();if(!activeJob||questionBusy)return;questionBusy=true;
    try{await api('literature/jobs/'+activeJob.id+'/questions/new',{method:'POST',body:JSON.stringify({section_id:$('lit-section').value,text:$('lit-question').value})});$('lit-question').value='';await refreshLiterature();}
    catch(error){message(error);}finally{questionBusy=false;}
  };
  function renderAnswers(){
    $('lit-answers').replaceChildren();if(!activeJob)return;
    jobs.filter(job=>job.kind==='question'&&job.question_context?.parent_job_id===activeJob.id&&job.question_context?.section_id===$('lit-section').value).reverse().forEach(job=>{
      const entry=element('article','','lit-answer');entry.append(element('strong',job.purpose));
      if(job.result)job.result.answers.forEach(answer=>{entry.append(element('p',answer.answer));answer.evidence.forEach(e=>entry.append(element('blockquote','['+e.block_id+'] '+e.quote)));answer.limitations.forEach(v=>entry.append(element('p',v,'hint')));});
      else entry.append(element('p',job.error||job.progress));$('lit-answers').append(entry);
    });
  }
  $('lit-settings-open').onclick=async()=>{
    try{settings=await api('literature/settings');const value=settings.settings;
      $('lit-provider').value=value.provider;$('lit-model').value=value.model;$('lit-base').value=value.base_url;$('lit-api-mode').value=value.api_mode;$('lit-max-output').value=value.max_output_tokens;$('lit-json-mode').checked=value.json_mode;
      $('lit-rules').value=settings.capability.rules;$('lit-rule-title').textContent='阅读规则 v'+settings.capability.version;
      $('lit-key-status').textContent='密钥仅从主机环境变量 '+value.key_env+' 读取。'+(settings.model_status.ready?'已就绪。':'缺少：'+settings.model_status.missing.join('、'));
      $('lit-settings-error').textContent='';$('lit-rule-message').textContent='';$('lit-settings-dialog').showModal();
    }catch(error){message(error);}
  };
  $('lit-provider').onchange=()=>{const profile=settings.providers[$('lit-provider').value];$('lit-base').value=profile.base_url;$('lit-api-mode').value=profile.api_mode;$('lit-model').value='';$('lit-key-status').textContent='在主机设置 '+profile.key_env+'，不要把密钥填入模型名称或服务地址。';};
  $('lit-settings-close').onclick=()=>$('lit-settings-dialog').close();
  $('lit-settings-form').onsubmit=async event=>{event.preventDefault();try{settings=await api('literature/settings',{method:'PUT',body:JSON.stringify({provider:$('lit-provider').value,model:$('lit-model').value,base_url:$('lit-base').value,api_mode:$('lit-api-mode').value,json_mode:$('lit-json-mode').checked,max_output_tokens:Number($('lit-max-output').value)})});updateModelState();$('lit-settings-error').textContent=settings.model_status.ready?'已保存':'已保存，仍需设置：'+settings.model_status.missing.join('、');}catch(error){$('lit-settings-error').textContent=error.message;}};
  $('lit-save-rules').onclick=async()=>{try{const value=await api('literature/rules',{method:'PUT',body:JSON.stringify({text:$('lit-rules').value,expected_version:settings.capability.version})});settings.capability=value;$('lit-rule-title').textContent='阅读规则 v'+value.version;$('lit-rule-message').textContent='已启用；新任务自动加载，已有任务保留原快照。';}catch(error){$('lit-rule-message').textContent=error.message;}};
  async function openNotes(job){
    exportJob=job;const value=await api('literature/jobs/'+job.id+'/notes');previewRevision=value.notes_revision;
    $('lit-ideas').value=value.ideas;$('lit-note-preview').textContent=value.markdown;$('lit-notes-path').textContent=value.ready?value.note_path+'\n'+value.table_path:value.reason;
    $('lit-save-notes').disabled=!value.ready;$('lit-notes-message').textContent='';$('lit-download').href='/api/literature/jobs/'+job.id+'/notes/download';$('lit-notes-dialog').showModal();
  }
  $('lit-notes-close').onclick=()=>$('lit-notes-dialog').close();
  $('lit-save-notes').onclick=async()=>{
    $('lit-save-notes').disabled=true;try{const result=await api('literature/jobs/'+exportJob.id+'/notes/save',{method:'POST',body:JSON.stringify({ideas:$('lit-ideas').value,notes_revision:previewRevision})});$('lit-notes-message').textContent=result.version_pending?'文件已保存，Git 提交待处理：'+result.error:'已保存并提交：'+result.commit.slice(0,12);const value=await api('literature/jobs/'+exportJob.id+'/notes');previewRevision=value.notes_revision;await refreshLiterature();}
    catch(error){$('lit-notes-message').textContent=error.message;}finally{$('lit-save-notes').disabled=false;}
  };
  setInterval(()=>{if(!$('literature-view').hidden&&!$('lit-settings-dialog').open&&!$('lit-notes-dialog').open)refreshLiterature().catch(message);},4000);
  if(!$('workspace').hidden)window.literatureReady();
})();
