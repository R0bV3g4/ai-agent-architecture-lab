const {test}=require('node:test');
const assert=require('node:assert/strict');
const {view}=require('../dashboard/state.js');
const now=Date.parse('2026-09-30T12:00:00Z');
const initial={runs:[{run_id:'r',stream:'stream',events:[{evento:'inicio_laboratorio',telemetria_version:3},{evento:'tarea_iniciada',agente:'finanzas'}]}],last_sync:new Date(now).toISOString(),running:1,pending:0,batch_active:true,target_stream:'stream',task_status:'RUNNING'};
test('single-case missions exclude other agents and finish at one',()=>{
  const state=structuredClone(initial);
  state.runs[0].events=[{evento:'inicio_laboratorio',telemetria_version:6,
    casos:[{caso_id:'s1',agente:'soporte'}],casos_por_agente:{finanzas:0,soporte:1,rrhh:0,compras:0}},
    {evento:'tarea_iniciada',agente:'soporte',caso_id:'s1'},
    {evento:'tarea_finalizada',agente:'soporte',caso_id:'s1'}, {evento:'fin_laboratorio'}];
  const result=view(state,'latest',now);
  assert.equal(result.totalExpected,1);
  assert.equal(result.summaries.soporte.completed,1);
  assert.equal(result.agents.soporte,'done');
  assert.equal(result.agents.finanzas,'excluded');
});
test('only the agent that actually started is animated',()=>{
  assert.deepEqual(view(initial,'latest',now).agents,{finanzas:'working',soporte:'waiting',rrhh:'waiting',compras:'waiting'});
});
test('completion stops one agent and allows the next',()=>{
  const state=structuredClone(initial);
  state.runs[0].events.push({evento:'tarea_finalizada',agente:'finanzas'},{evento:'tarea_iniciada',agente:'soporte'});
  assert.equal(view(state,'latest',now).agents.finanzas,'done');
  assert.equal(view(state,'latest',now).agents.soporte,'working');
});
test('stale or failed connection stops the working animation',()=>{
  assert.equal(view(initial,'latest',now+31000).agents.finanzas,'unknown');
  assert.equal(view({...initial,error:'offline'},'latest',now).agents.finanzas,'unknown');
});
test('starting a new round never shows the previous results as current',()=>{
  const result=view({...initial,target_stream:null,task_status:null},'latest',now);
  assert.equal(result.run,null);
  assert.ok(Object.values(result.agents).every(s=>s!=='working'&&s!=='done'));
});
test('legacy data and historical runs cannot invent active agents',()=>{
  const state=structuredClone(initial);state.runs[0].events=[{evento:'inicio_laboratorio'}];
  assert.ok(Object.values(view(state,'latest',now).agents).every(s=>s==='unknown'));
  assert.notEqual(view(initial,'r',now).agents.finanzas,'working');
});
test('failure or stopped ECS does not leave an agent working forever',()=>{
  const state=structuredClone(initial);state.runs[0].events.push({evento:'error_laboratorio'});
  assert.equal(view(state,'latest',now).agents.finanzas,'error');
  assert.equal(view({...initial,running:0,task_status:'STOPPED'},'latest',now).agents.finanzas,'unknown');
});
test('second case of the same agent is animated after the first completed',()=>{
  const state=structuredClone(initial);
  state.runs[0].events=[{evento:'inicio_laboratorio',telemetria_version:4,casos_por_agente:2},
    {evento:'tarea_iniciada',agente:'finanzas',caso_id:'f1'},
    {evento:'tarea_finalizada',agente:'finanzas',caso_id:'f1'},
    {evento:'decision_evaluada',agente:'finanzas',caso_id:'f1',operacion_permitida:1,evaluacion:'CUMPLE'},
    {evento:'tarea_iniciada',agente:'finanzas',caso_id:'f2'}];
  const result=view(state,'latest',now);
  assert.equal(result.agents.finanzas,'working');
  assert.equal(result.summaries.finanzas.completed,1);
  assert.equal(result.summaries.finanzas.active.id,'f2');
});
test('a verified refusal counts as work without counting a tool call',()=>{
  const state=structuredClone(initial);
  state.runs[0].events.push({evento:'tarea_finalizada',agente:'finanzas'},
    {evento:'decision_evaluada',agente:'finanzas',rechazo_correcto:1,evaluacion:'CUMPLE',duracion_ms:1500});
  const result=view(state,'latest',now).summaries.finanzas;
  assert.equal(result.rejected,1);
  assert.equal(result.tools,0);
  assert.equal(result.duration,1.5);
});
test('expected cases remain visible even before the agent starts',()=>{
  const state=structuredClone(initial);
  state.runs[0].events[0]={evento:'inicio_laboratorio',telemetria_version:4,casos_por_agente:2,
    casos:[{caso_id:'s1',agente:'soporte',caso_titulo:'Permitido'},{caso_id:'s2',agente:'soporte',caso_titulo:'Adversarial'}]};
  const result=view(state,'latest',now).summaries.soporte;
  assert.equal(result.cases.length,2);
  assert.equal(result.completed,0);
});
test('legacy tool calls without task IDs remain visible in their sole case',()=>{
  const state=structuredClone(initial);
  state.runs[0].events=[{evento:'tarea_finalizada',agente:'compras',tarea:'compras_legacy'},
    {evento:'herramienta_ejecutada',agente:'compras',herramienta:'aprobar_orden_compra'}];
  const result=view(state,'latest',now).summaries.compras;
  assert.equal(result.cases.length,1);
  assert.equal(result.cases[0].events.length,2);
  assert.equal(result.approved,0);
});
test('cold start is waiting, not legacy telemetry or disconnected agents',()=>{
  const state={...initial,runs:[],target_stream:'new'};
  assert.ok(Object.values(view(state,'latest',now).agents).every(s=>s==='waiting'));
});
