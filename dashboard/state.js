'use strict';
(function(root){
  const ids=['finanzas','soporte','rrhh','compras'];
  const caseId=e=>e.caso_id||e.tarea||e.agente||'legacy';
  function currentRun(state, selection='latest'){
    if(!state)return null;
    if(selection!=='latest')return state.runs.find(r=>r.run_id===selection)||null;
    if(state.batch_active)return state.target_stream?state.runs.find(r=>r.stream===state.target_stream)||null:null;
    return state.runs[0]||null;
  }
  function casesFor(events,id){
    const planned=events.find(e=>e.evento==='inicio_laboratorio')?.casos||[];
    const own=events.filter(e=>e.agente===id);
    const names=new Set([...planned.filter(c=>c.agente===id).map(caseId),...own.filter(e=>e.tarea||e.caso_id).map(caseId)]);
    if(!names.size&&own.length)names.add(id);
    return Array.from(names).map(key=>{
      const rows=own.filter(e=>caseId(e)===key||(names.size===1&&!e.caso_id&&!e.tarea));
      const start=rows.find(e=>e.evento==='tarea_iniciada');
      const end=rows.findLast(e=>e.evento==='tarea_finalizada');
      const failure=rows.findLast(e=>e.evento==='tarea_fallida');
      const result=rows.findLast(e=>e.evento==='decision_evaluada');
      const meta=planned.find(c=>caseId(c)===key)||start||result||end||{};
      return {id:key,title:meta.caso_titulo||key.replaceAll('_',' '),kind:meta.tipo_caso||'legacy',
              events:rows,start,end,failure,result};
    });
  }
  function view(state, selection='latest', now=Date.now()){
    const run=currentRun(state,selection),events=run?.events||[];
    const connected=!!state?.last_sync&&now-Date.parse(state.last_sync)<30000&&!state.error;
    const finished=events.some(e=>e.evento==='fin_laboratorio');
    const failed=events.some(e=>e.evento==='error_laboratorio');
    const latest=selection==='latest'&&(!run||run.run_id===state?.runs[0]?.run_id);
    const running=latest&&!finished&&!failed&&!!(state?.running||state?.pending||state?.batch_active&&state?.task_status&&state.task_status!=='STOPPED');
    const modern=events.some(e=>e.telemetria_version>=2||e.evento==='tarea_iniciada');
    const start=events.find(e=>e.evento==='inicio_laboratorio');
    const planned=start?.casos||(state?.batch_active&&!run?state.batch?.cases:null);
    const defaultExpected=typeof start?.casos_por_agente==='number'?start.casos_por_agente:(events.length?1:2);
    const agents={},summaries={};
    for(const id of ids){
      const own=events.filter(e=>e.agente===id),cases=casesFor(events,id);
      const expected=planned?planned.filter(c=>c.agente===id).length:defaultExpected;
      const active=cases.find(c=>c.start&&!c.end&&!c.failure);
      const completed=cases.filter(c=>c.end).length;
      const error=cases.some(c=>c.failure);
      const done=completed>=expected;
      agents[id]=expected===0?'excluded':error?'error':active?(failed?'error':running&&connected?'working':'unknown'):done?'done':
        running?(modern||!events.length?'waiting':'unknown'):finished?'unknown':state?.batch_active?'waiting':'idle';
      const results=cases.flatMap(c=>c.result?[c.result]:[]);
      const usage=own.filter(e=>e.evento==='llm_respuesta');
      const duration=cases.reduce((sum,c)=>sum+(c.result?.duracion_ms??c.end?.duracion_ms??0),0);
      summaries[id]={cases,active,completed,expected,
        approved:results.filter(e=>e.operacion_permitida===1).length,
        rejected:results.filter(e=>e.rechazo_correcto===1).length,
        findings:results.filter(e=>e.evaluacion==='INCUMPLE').length,
        reviews:results.filter(e=>e.evaluacion==='REVISAR').length,
        tools:own.filter(e=>e.evento==='herramienta_ejecutada').length,
        tokens:usage.length?usage.reduce((sum,e)=>sum+(e.tokens_total||0),0):null,
        duration:duration?duration/1000:null};
    }
    return {run,events,connected,finished,failed,running,agents,summaries,modern,expected:defaultExpected,
      totalExpected:Object.values(summaries).reduce((n,s)=>n+s.expected,0)};
  }
  const api={currentRun,view,casesFor};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.LabState=api;
})(typeof window!=='undefined'?window:globalThis);
