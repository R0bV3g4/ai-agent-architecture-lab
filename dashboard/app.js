'use strict';
const $=id=>document.getElementById(id);
const people=[
  {id:'finanzas',name:'Finanzas',role:'Especialista de facturación',job:'Revisando pagos',color:'#55e6ef',soft:'#152e39',room:'#0d202b',skin:'#e0b495',hair:'#272d40'},
  {id:'soporte',name:'Soporte',role:'Atención al cliente',job:'Atendiendo el caso',color:'#ffbe70',soft:'#342b25',room:'#251d1b',skin:'#b88260',hair:'#292632'},
  {id:'rrhh',name:'RR. HH.',role:'Gestión de talento',job:'Revisando la solicitud',color:'#d4a0ff',soft:'#2d2540',room:'#1f192e',skin:'#ebc0a2',hair:'#322d48'},
  {id:'compras',name:'Compras',role:'Comprador corporativo',job:'Comparando proveedores',color:'#c6f171',soft:'#253426',room:'#19251e',skin:'#c79774',hair:'#2a3035'},
];
const labels={idle:'En reposo',waiting:'En espera',working:'Trabajando',done:'Terminado',error:'Error',unknown:'Sin señal actual',excluded:'No participa'};
const eventLabels={inicio_laboratorio:'Inició la ronda',tarea_iniciada:'Empezó a trabajar',tarea_finalizada:'Tarea terminada',herramienta_ejecutada:'Herramienta ejecutada',llm_respuesta:'Anthropic respondió',llm_error:'Error del modelo',fin_laboratorio:'Ronda terminada',tarea_fallida:'Falló la tarea',error_laboratorio:'Falló la ronda',decision_evaluada:'Decisión contrastada con evidencia',envio_splunk_fallido:'Envío a Splunk fallido'};
const number=new Intl.NumberFormat('es-MX');
let state=null,selection='latest',selected=null,journal=false,sending=false,toastTimer,lastDetail='',selectedCase=null;
let catalog=[];
function missionCases(){
  return catalog.filter(c=>($('mission-agent').value==='all'||c.agente===$('mission-agent').value)&&($('mission-case').value==='all'||c.caso_id===$('mission-case').value));
}
function updateMission(reset=false){
  const current=reset?'all':$('mission-case').value;
  const available=catalog.filter(c=>$('mission-agent').value==='all'||c.agente===$('mission-agent').value);
  $('mission-case').replaceChildren(new Option('Todos los casos disponibles','all'));
  for(const c of available)$('mission-case').add(new Option(c.caso_titulo+' · '+(c.tipo_caso==='permitido'?'Permitido':'Adversarial'),c.caso_id));
  $('mission-case').value=available.some(c=>c.caso_id===current)?current:'all';
  const cases=missionCases();
  $('mission-preview').textContent=cases.length===1?cases[0].solicitud+' · Esperado: '+cases[0].decision_esperada:
    cases.length+' casos por sesión · '+new Set(cases.map(c=>c.agente)).size+' agentes. Elige un escenario para ver su solicitud.';
  render();
}
function time(ts){return new Date(ts).toLocaleTimeString('es-MX',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{$('toast').hidden=true;},5000);}
function station(p,index){
  return [
  '<svg class="station" viewBox="0 0 280 180" aria-hidden="true">',
  '<defs><linearGradient id="floor-'+p.id+'" x2="0" y2="1"><stop stop-color="'+p.color+'" stop-opacity=".1"/><stop offset="1" stop-color="'+p.color+'" stop-opacity="0"/></linearGradient><linearGradient id="light-'+p.id+'"><stop stop-color="'+p.color+'" stop-opacity="0"/><stop offset="1" stop-color="'+p.color+'" stop-opacity=".13"/></linearGradient></defs>',
  '<path class="room" d="M22 137L71 115H236L264 142 212 170H66z"/>',
  '<path d="M22 137L71 115H236L264 142 212 170H66z" fill="url(#floor-'+p.id+')" stroke="'+p.color+'" stroke-opacity=".25" stroke-width=".7"/>',
  '<path d="M35 145h222M51 156h187M64 136h191M96 118l-21 50m66-50-2 50m37-49 18 49m17-47 31 30" fill="none" stroke="'+p.color+'" stroke-opacity=".09" stroke-width=".6"/>',
  '<path d="M28 120V31h217v98M32 31v-6h20m193 28v-22h-21" fill="none" stroke="#29404f" stroke-width="1"/>',
  '<path d="M32 25h20m178 6h15v15" fill="none" stroke="'+p.color+'" stroke-width="1.5" opacity=".6"/>',
  '<g fill="#15212e"><path d="M40 94V66h10V49h8v20h12V41h15v53zm115-48V22h10v24zm65-7V16h9v23z"/><path d="M153 94V52h13v42m75-52h-9V66h9"/></g>',
  '<path d="M74 47v26m5-26v17M44 74v12m11-12v4m106-45v7m61-18v9" stroke="'+p.color+'" stroke-opacity=".25" stroke-dasharray="2 4"/>',
  '<rect x="40" y="87" width="27" height="45" rx="2" fill="#121e2b" stroke="#2b4050"/>',
  '<path d="M45 95h17m-17 7h17m-17 7h17m-17 7h17" stroke="#344957" stroke-width="2"/><path class="rack-lights" d="M46 95h3m-3 7h3m-3 7h3m-3 7h3" stroke="'+p.color+'" stroke-width="2"/>',
  '<path d="M51 132v6h27" fill="none" stroke="#34515a"/>',
  '<ellipse cx="153" cy="157" rx="71" ry="8" fill="#030811" opacity=".7"/>',
  '<path d="M96 113v38m-13 7 13-7 13 7m-13-7 15-8" fill="none" stroke="#354651" stroke-width="4" stroke-linecap="round"/>',
  '<rect x="78" y="76" width="38" height="45" rx="8" fill="#152332" stroke="#385463"/><rect x="83" y="80" width="29" height="29" rx="5" fill="#213443"/><path d="M82 84v18" stroke="'+p.color+'" stroke-width="2" opacity=".5"/>',
  '<path d="M108 124l23 9 15 16m-38-25 6 15 15 14" fill="none" stroke="#2e3d51" stroke-width="12" stroke-linecap="round"/>',
  '<path d="M145 150l10 2m-28 2 9 1" fill="none" stroke="#647784" stroke-width="7" stroke-linecap="round"/>',
  '<path class="shirt" d="M107 75q18-4 29 10l4 25-12 17-28-2q-5-31 7-50z"/>',
  '<path d="M104 82l-3 35m6 4h18" fill="none" stroke="'+p.color+'" stroke-width="1.5"/><path d="M117 82l7 5-3 8-7-5z" fill="'+p.color+'" opacity=".6"/>',
  '<g class="person-head">',
  index===2?'<path d="M110 44q25-12 33 13l-3 32h-32z" fill="'+p.hair+'"/>':'',
  '<path d="M118 66v14q5 6 12-1V66" fill="'+p.skin+'"/>',
  '<ellipse cx="124" cy="56" rx="17" ry="20" fill="'+p.skin+'"/>',
  '<path d="M107 57q-5-22 15-23 22-1 23 18l-10-4-2-7-7 7-15 2-1 12z" fill="'+p.hair+'"/>',
  '<circle cx="111" cy="60" r="4" fill="'+p.skin+'"/>',
  '<path d="M128 55h2m8 0h1" stroke="#443d32" stroke-width="2" stroke-linecap="round"/>',
  '<path d="M131 65q4 2 7-1" fill="none" stroke="#ad775b" stroke-width="1.3" stroke-linecap="round"/>',
  index===0?'<g fill="#162b42" fill-opacity=".8" stroke="'+p.color+'" stroke-width="1"><rect x="123" y="50" width="9" height="8" rx="2"/><rect x="135" y="50" width="8" height="8" rx="2"/><path d="M132 53h3m-10 0-13-1"/></g>':'',
  index===1?'<path d="M109 51q0-23 26-16" fill="none" stroke="#53677b" stroke-width="3"/><rect x="106" y="52" width="6" height="12" rx="3" fill="'+p.color+'"/><path d="M110 62q4 12 22 8" fill="none" stroke="#53677b" stroke-width="2"/>':'',
  index===2?'<path d="M112 43l8-3" stroke="'+p.color+'" stroke-width="2"/>':'',
  '</g>',
  '<path d="M142 113v40m87-40v40" stroke="#344757" stroke-width="5" stroke-linecap="round"/>',
  '<path d="M125 106h115l5 12H122z" fill="#304351"/><path d="M122 118h123v5H122z" fill="#182c3c"/><path class="desk-neon" d="M123 120h121" stroke="'+p.color+'" stroke-width="1.5"/>',
  '<path d="M191 90v17m-11 0h26" fill="none" stroke="#435e6e" stroke-width="3" stroke-linecap="round"/>',
  '<path class="monitor-light" d="M169 54L122 41v56l47-5z" fill="url(#light-'+p.id+')"/>',
  '<rect x="166" y="50" width="72" height="47" rx="3" fill="#162736" stroke="'+p.color+'" stroke-opacity=".65" stroke-width=".8"/>',
  '<rect class="screen-glass" x="170" y="54" width="64" height="38" rx="2"/>',
  '<path d="M173 59h57" stroke="'+p.color+'" opacity=".25"/><circle cx="175" cy="57" r=".8" fill="'+p.color+'"/>',
  '<g><path class="screen-line" d="M175 64h4m3 0h17m3 0h7"/><path class="screen-line" d="M179 69h11m3 0h17m3 0h10"/><path class="screen-line" d="M179 74h7m3 0h12m3 0h12"/><path class="screen-line" d="M175 79h4m3 0h10m3 0h9"/></g>',
  '<rect class="screen-cursor" x="175" y="84" width="4" height="2" fill="'+p.color+'"/>',
  '<rect class="screen-scan" x="171" y="61" width="62" height="1" fill="'+p.color+'" opacity=".3"/>',
  '<path d="M165 105h41l6 9h-49z" fill="#152938" stroke="#47606d" stroke-width=".6"/><path d="M171 109h28" stroke="'+p.color+'" stroke-width="2" stroke-dasharray="2 2" opacity=".65"/>',
  '<g class="hand-left"><path d="M113 89l20 19 35 3" fill="none" stroke="'+p.soft+'" stroke-width="10" stroke-linecap="round"/><path d="M113 86l22 19 26 4" fill="none" stroke="'+p.color+'" stroke-opacity=".6" stroke-width="1.2"/><path d="M165 111h10" stroke="'+p.skin+'" stroke-width="6" stroke-linecap="round"/></g>',
  '<g class="hand-right"><path d="M130 85l18 15 29 5" fill="none" stroke="'+p.soft+'" stroke-width="9" stroke-linecap="round"/><path d="M176 106l9 2" stroke="'+p.skin+'" stroke-width="6" stroke-linecap="round"/></g>',
  '<path class="desk-paper" d="M212 108h11l4 6h-13z"/><path d="M230 103h9v8h-9z" fill="'+p.color+'"/><path d="M239 104q6 0 2 5h-2" fill="none" stroke="'+p.color+'" stroke-width="2"/>',
  '<g class="activity-dots" fill="'+p.color+'"><circle cx="181" cy="36" r="2.5"/><circle cx="190" cy="36" r="2.5"/><circle cx="199" cy="36" r="2.5"/></g></svg>'].join('');
}
for(const [i,p] of people.entries()){
  const card=document.createElement('button');card.className='agent-card';card.dataset.agent=p.id;card.dataset.status='idle';
  card.style.setProperty('--accent',p.color);card.style.setProperty('--soft',p.soft);card.style.setProperty('--room',p.room);
  card.setAttribute('aria-label','Ver '+p.name);
  card.innerHTML='<div class="card-header"><span class="card-identity"><span class="agent-number" aria-hidden="true">0'+(i+1)+'</span><span class="card-title">'+p.name+'</span></span><span class="badge">En reposo</span></div><div class="station-frame">'+station(p,i)+'<span class="station-label" aria-hidden="true">CREW / 0'+(i+1)+'</span></div><div class="case-list"></div><div class="agent-metrics"></div><div class="card-bottom"><span class="agent-activity">Esperando una misión</span><span class="details-hint">Ver detalle ↗</span></div>';
  card.addEventListener('click',()=>openDetail(p.id));$('agents').append(card);
}
function renderCases(card,summary,status,finished){
  const list=card.querySelector('.case-list');list.replaceChildren();
  for(const c of summary.cases){
    const row=document.createElement('div'),title=document.createElement('span'),badge=document.createElement('span');
    row.className='case-row';title.textContent=c.title;title.title=c.title;badge.className='case-result';
    const r=c.result;
    badge.textContent=c.failure?'Error':r?(r.evaluacion==='INCUMPLE'?'Hallazgo':r.evaluacion==='REVISAR'?'Revisar':r.rechazo_correcto?'Rechazada':'Ejecutada'):
      c.end?(c.kind==='legacy'||finished?'Sin evaluación':'Evaluando'):c.start?(status==='working'?'En curso':'Sin señal'):'Pendiente';
    badge.dataset.result=c.failure?'INCUMPLE':r?.evaluacion||'pending';
    row.append(title,badge);list.append(row);
  }
  if(!summary.cases.length){const row=document.createElement('p');row.className='case-placeholder';row.textContent=summary.expected===0?'Fuera de esta misión':'Esperando los casos seleccionados';list.append(row);}
  card.querySelector('.agent-metrics').textContent=summary.cases.length&&summary.cases.every(c=>c.kind==='legacy')?
    summary.completed+' caso · '+summary.tools+(summary.tools===1?' herramienta':' herramientas')+' · sin evaluación':
    summary.completed+'/'+summary.expected+' casos · '+summary.approved+(summary.approved===1?' operación':' operaciones')+' · '+summary.rejected+(summary.rejected===1?' rechazo':' rechazos');
}
function setTab(name){
  for(const b of document.querySelectorAll('[data-tab]')){b.classList.toggle('active',b.dataset.tab===name);b.setAttribute('aria-current',b.dataset.tab===name?'page':'false');}
  for(const key of ['answer','actions','activity'])$('tab-'+key).hidden=key!==name;
}
function openDetail(id){
  selected=id;journal=!id;lastDetail='';setTab(journal?'activity':'answer');render();
  if(!$('inspector').open)$('inspector').showModal();
}
function closeDetail(){$('inspector').close();selected=null;journal=false;}
function render(){
  if(!state)return;
  const v=LabState.view(state,selection),{run,events}=v,usage=run?.usage;
  $('connection').textContent=v.connected?'AWS conectado':'Sin conexión con AWS';
  $('connection-dot').className=v.connected?'ok':'error';
  $('error').hidden=!state.error;$('error').textContent=state.error||'';
  const busy=sending||state.batch_active||state.running>0||state.pending>0;
  $('start').disabled=!v.connected||busy||!missionCases().length;$('rounds').disabled=busy;$('stop').hidden=!state.batch_active;
  $('mission-agent').disabled=busy;$('mission-case').disabled=busy;
  $('start').textContent=sending?'Enviando…':state.batch_active?'Misión en curso':'▶ Iniciar misión';
  $('batch').textContent=state.batch_active||state.batch.status==='error'?state.batch.message:missionCases().length+' casos por sesión · '+Number($('rounds').value)*missionCases().length+' ejecuciones de casos. Usa AWS y Anthropic; las operaciones son simuladas.';
  const worker=people.find(p=>v.agents[p.id]==='working');
  $('run-status').textContent=!v.connected?'Sin señal actual':worker?worker.name+' está trabajando':v.failed?'La ronda tuvo un error':state.batch_active&&!run?'Preparando agentes en AWS…':v.finished?'Ronda terminada':v.running?'Esperando actividad de los agentes…':run?'Ejecución sin cierre registrado':'Listos para empezar';
  $('run-dot').className='run-dot'+(worker?' working':'');
  $('run-caption').textContent=!v.connected?'La animación se detiene hasta recuperar la conexión.':worker?'Los agentes resuelven sus casos uno por uno.':state.batch_active&&!run?'AWS está preparando los casos seleccionados.':v.running&&!v.modern?'Esta imagen antigua no informa qué agente está activo.':v.finished?'Misión finalizada. Puedes elegir otro escenario.':'Los personajes se animan al recibir su caso.';
  $('model').textContent=events.find(e=>e.evento==='inicio_laboratorio')?.modelo||state.model;
  $('tokens').textContent=usage?.total_tokens==null?'—':number.format(usage.total_tokens)+(usage.partial?'+':'');
  $('calls').textContent=usage?number.format(usage.calls):'—';
  $('completed').textContent=Object.values(v.summaries).reduce((n,a)=>n+a.completed,0)+'/'+v.totalExpected;
  $('usage-note').textContent=!usage||usage.total_tokens==null?'Sin métricas de tokens todavía. “—” no significa consumo cero.':usage.partial?'Consumo mínimo confirmado: esta versión registró métricas de '+usage.measured_calls+' de '+usage.calls+' respuestas.':number.format(usage.input_tokens)+' de entrada · '+number.format(usage.output_tokens)+' de salida · métricas recibidas de Anthropic.';
  $('sync').textContent=state.last_sync?'Actualizado '+time(state.last_sync):'Esperando AWS';
  for(const p of people){
    const card=document.querySelector('[data-agent="'+p.id+'"]'),status=v.agents[p.id];
    card.dataset.status=status;card.querySelector('.badge').textContent=labels[status];
    const summary=v.summaries[p.id];
    renderCases(card,summary,status,v.finished);
    card.querySelector('.agent-activity').textContent=status==='excluded'?'No seleccionado en esta misión':status==='working'?'Caso '+(summary.completed+1)+' de '+summary.expected+' · '+p.job:
      summary.tokens!==null?number.format(summary.tokens)+' tokens'+(summary.duration!==null?' · '+Math.round(summary.duration)+' s':''):
      status==='waiting'?'Esperando su turno':status==='unknown'?'Esperando telemetría':status==='error'?'Revisa el registro':'Esperando una misión';
  }
  const signature=['latest',...state.runs.map(r=>r.run_id)].join();
  if(Array.from($('run-select').options).map(o=>o.value).join()!==signature){
    $('run-select').replaceChildren(new Option('Última ejecución','latest'));
    for(const r of state.runs)$('run-select').add(new Option(new Date(r.timestamp).toLocaleString('es-MX'),r.run_id));
    if(selection!=='latest'&&!state.runs.some(r=>r.run_id===selection))selection='latest';
    $('run-select').value=selection;
  }
  if(selected||journal)renderDetail(v);
}
function renderDetail(v){
  const p=people.find(p=>p.id===selected),summary=selected?v.summaries[selected]:null;
  const cases=summary?.cases||[];
  // A completed mission opens its first case, rather than always the final refusal.
  if(!cases.some(c=>c.id===selectedCase))selectedCase=summary?.active?.id||cases[0]?.id||null;
  const chosen=cases.find(c=>c.id===selectedCase);
  $('case-summary').hidden=journal||!cases.length;
  $('case-summary').textContent=summary?summary.completed+'/'+summary.expected+' casos · '+summary.approved+(summary.approved===1?' operación permitida':' operaciones permitidas')+' · '+summary.rejected+(summary.rejected===1?' rechazo correcto':' rechazos correctos'):'';
  const selector=$('case-select');selector.hidden=journal||!cases.length;
  if(Array.from(selector.options).map(o=>o.value).join()!==cases.map(c=>c.id).join()){
    selector.replaceChildren();
    for(const [i,c] of cases.entries()){
      const kind=c.kind==='permitido'?'Permitido':c.kind==='adversarial'?'Adversarial':'Histórico';
      selector.add(new Option((i+1)+'/'+cases.length+' · '+kind+' · '+c.title,c.id));
    }
  }
  selector.value=selectedCase||'';
  const events=journal?v.events:chosen?.events||v.events.filter(e=>e.agente===selected);
  $('detail-title').textContent=journal?'Registro de la ronda':p.name;
  $('detail-role').textContent=journal?'EVENTOS REALES DE AWS':p.role;
  $('detail-status').textContent=journal?(v.finished?'Terminada':v.running?'En ejecución':'En espera'):labels[v.agents[selected]];
  const calls=events.filter(e=>e.evento==='herramienta_ejecutada');
  $('call-count').textContent=journal?events.length+' eventos':calls.length+(calls.length===1?' acción':' acciones');
  $('legacy').hidden=v.modern||!v.run;
  const signature=[v.run?.run_id,selected,selectedCase,journal,events.map(e=>e.event_id).join()].join(':');
  if(lastDetail!==signature){
    lastDetail=signature;
    $('request').textContent=events.find(e=>e.evento==='tarea_iniciada')?.solicitud||'El inicio no quedó registrado en esta versión.';
    const result=chosen?.result;
    $('answer').textContent=result?[result.decision+' · '+result.evaluacion,result.motivo,
      'Operaciones registradas: '+result.operaciones,
      ...(result.hallazgos||[]).map(h=>'• '+h),
      'Evaluación de controles del caso. El texto requiere revisión humana.'].join('\n\n'):
      events.findLast(e=>e.evento==='tarea_finalizada')?.respuesta||'La respuesta aparecerá cuando termine este caso.';
    $('actions').textContent=calls.length?calls.map(e=>e.herramienta+'\n'+JSON.stringify(e.argumentos,null,2)+'\n'+e.resultado).join('\n\n'):'Sin llamadas a herramientas.';
    $('timeline').replaceChildren();
    for(const e of events.slice(-100).reverse()){
      const li=document.createElement('li'),date=document.createElement('time'),label=document.createElement('span'),detail=document.createElement('small');
      date.textContent=time(e.timestamp);label.textContent=eventLabels[e.evento]||e.evento;
      detail.textContent=[people.find(a=>a.id===e.agente)?.name,e.caso_titulo,e.herramienta,e.evento==='decision_evaluada'?e.evaluacion:null,e.evento==='llm_respuesta'?number.format(e.tokens_total)+' tokens':null].filter(Boolean).join(' · ');
      li.append(date,label,detail);$('timeline').append(li);
    }
    if(!events.length){const li=document.createElement('li');li.textContent='Todavía no hay eventos.';$('timeline').append(li);}
  }
  $('run-id').textContent=v.run?'RUN '+v.run.run_id.slice(0,8):'Sin ejecución';
}
async function refresh(){
  try{const r=await fetch('/api/state');if(!r.ok)throw Error();state=await r.json();render();}
  catch{
    if(state){state={...state,error:'No se pudo leer el panel local. Comprueba que ./lab dashboard sigue abierto.'};render();}
    else{$('connection').textContent='Panel desconectado';$('connection-dot').className='error';$('start').disabled=true;$('run-status').textContent='Abre ./lab dashboard para conectar';}
  }
}
async function act(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Lab-Token':state.csrf_token},body:JSON.stringify(body)});
  const result=await r.json();if(!r.ok)throw Error(result.error||'No se pudo completar la acción');
}
$('start').addEventListener('click',async()=>{
  sending=true;selection='latest';$('run-select').value='latest';render();
  try{await act('/api/run',{rounds:Number($('rounds').value),case_ids:missionCases().map(c=>c.caso_id)});toast('Misión enviada. AWS está preparando los casos seleccionados.');}
  catch(e){toast(e.message);}finally{sending=false;await refresh();}
});
$('stop').addEventListener('click',async()=>{try{await act('/api/stop',{});toast('Terminará esta ronda y se cancelarán las siguientes.');await refresh();}catch(e){toast(e.message);}});
$('run-select').addEventListener('change',()=>{selection=$('run-select').value;lastDetail='';render();});
$('case-select').addEventListener('change',()=>{selectedCase=$('case-select').value;lastDetail='';render();});
$('journal').addEventListener('click',()=>openDetail(null));
$('close-inspector').addEventListener('click',closeDetail);
$('inspector').addEventListener('close',()=>{selected=null;journal=false;});
for(const b of document.querySelectorAll('[data-tab]'))b.addEventListener('click',()=>{if(journal&&b.dataset.tab!=='activity'){selected=people[0].id;journal=false;lastDetail='';render();}setTab(b.dataset.tab);});
$('copy').addEventListener('click',async()=>{const run=LabState.currentRun(state,selection);if(!run)return;const query='service:agent-compliance-lab @run_id:'+run.run_id;try{await navigator.clipboard.writeText(query);toast('Búsqueda de Datadog copiada.');}catch{toast(query);}});
$('mission-agent').addEventListener('change',()=>updateMission(true));
$('mission-case').addEventListener('change',()=>updateMission());
$('rounds').addEventListener('change',render);
fetch('/api/cases').then(r=>{if(!r.ok)throw Error();return r.json();}).then(c=>{catalog=c;updateMission();}).catch(()=>{$('mission-preview').textContent='No se pudo cargar el catálogo. Reinicia ./lab dashboard y recarga.';});
document.addEventListener('keydown',e=>{if(e.target.matches('input,select,textarea'))return;if(/^[1-4]$/.test(e.key))openDetail(people[Number(e.key)-1].id);});
(async function poll(){await refresh();setTimeout(poll,1500);})();
