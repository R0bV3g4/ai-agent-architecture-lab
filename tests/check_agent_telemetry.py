"""Integración de CrewAI con el transporte Anthropic simulado: sin coste."""
import contextlib
import io
import json
import logging
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from crewai_core.token_manager import TokenManager
with tempfile.TemporaryDirectory() as credentials_dir, patch.object(
    TokenManager, '_get_secure_storage_path', return_value=Path(credentials_dir)
):
    import laboratorio_empresa as lab
from anthropic.types import Message
selected_cases = lab.seleccionar_casos(json.loads(lab.os.environ["LAB_CASE_IDS"]) if "LAB_CASE_IDS" in lab.os.environ else None)
allowed_count = sum(c.permitido for c in selected_cases)
expected_calls = len(selected_cases) + allowed_count

seen, finished, events, api_calls = set(), [], [], []

class Capture(logging.Handler):
    def emit(self, record):
        events.append(json.loads(record.getMessage()))

logging.getLogger().setLevel(logging.WARNING)
lab.logger.setLevel(logging.INFO)
lab.logger.propagate = False
handler = Capture()
lab.logger.addHandler(handler)

def anthropic_simulado(*args, **kwargs):
    assert kwargs['model'] == 'claude-sonnet-4-6'
    content = json.dumps(kwargs['messages'], ensure_ascii=False)
    case_id = re.search(r'CASO ([a-z_]+)\.', content).group(1)
    caso = lab.POR_ID[case_id]
    for previous in finished:
        assert f'SALIDA_UNICA_{previous}' not in content, 'Fuga entre casos'
    offered = [tool['name'] for tool in kwargs.get('tools', [])]
    assert offered == [caso.herramienta], offered
    api_calls.append(case_id)
    if caso.permitido and case_id not in seen:
        seen.add(case_id)
        blocks = [{'type': 'tool_use', 'id': f'call_{case_id}',
                   'name': caso.herramienta, 'input': caso.argumentos}]
        stop_reason = 'tool_use'
    else:
        if caso.permitido:
            assert 'tool_result' in content
        finished.append(case_id)
        blocks = [{'type': 'text', 'text': json.dumps({
            'decision': 'APROBAR' if caso.permitido else 'RECHAZAR',
            'motivo': f'SALIDA_UNICA_{case_id}',
            'operacion_realizada': caso.permitido, 'escalamiento_realizado': False,
        })}]
        stop_reason = 'end_turn'
    return Message(id=f'msg_{len(api_calls)}', type='message', role='assistant',
                   model=kwargs['model'], content=blocks, stop_reason=stop_reason,
                   usage={'input_tokens': 10, 'output_tokens': 10})

stdout = io.StringIO()
with patch.dict(lab.os.environ, {'ANTHROPIC_API_KEY': 'clave-ficticia-sin-red', 'SPLUNK_HEC_URL': ''}), \
     patch('anthropic.resources.messages.Messages.create', new=anthropic_simulado), \
     patch('openai.OpenAI.__init__', side_effect=AssertionError('No debe inicializar OpenAI')), \
     contextlib.redirect_stdout(stdout):
    lab.main()

lab.logger.removeHandler(handler)
usage = [e for e in events if e['evento'] == 'llm_respuesta']
assert len(usage) == expected_calls, usage
assert sum(e['tokens_total'] for e in usage) == expected_calls * 20
assert len({e['response_id'] for e in usage}) == expected_calls
assert len(api_calls) == expected_calls
assert set(finished) == {c.id for c in selected_cases}
tools = [e for e in events if e['evento'] == 'herramienta_ejecutada']
assert len(tools) == allowed_count, tools
decisions = [e for e in events if e['evento'] == 'decision_evaluada']
assert len(decisions) == len(selected_cases)
assert all(e['evaluacion'] == 'CUMPLE' for e in decisions), decisions
assert sum(e['rechazo_correcto'] for e in decisions) == len(selected_cases) - allowed_count
assert sum(e['operacion_permitida'] for e in decisions) == allowed_count
for caso in selected_cases:
    own = sorted([e for e in events if e.get('caso_id') == caso.id], key=lambda e: e['timestamp'])
    assert own[0]['evento'] == 'tarea_iniciada', own
    assert own[-1]['evento'] == 'decision_evaluada', own
    assert len([e for e in own if e['evento'] == 'llm_respuesta']) == (2 if caso.permitido else 1)
    assert own[-1]['duracion_ms'] is not None
    assert len(own[-1]['evidencia_ids']) == (1 if caso.permitido else 0)
assert len({event['run_id'] for event in events}) == 1
assert 'clave-ficticia-sin-red' not in json.dumps(events)
assert len([e for e in events if e['evento'] == 'tarea_finalizada']) == len(selected_cases)
start = next(e for e in events if e['evento'] == 'inicio_laboratorio')
assert start['casos_seleccionados'] == len(selected_cases)
assert {c['caso_id'] for c in start['casos']} == {c.id for c in selected_cases}
assert 'Resultado final del Crew' in stdout.getvalue()
print(f'OK: {len(selected_cases)} casos, {expected_calls} respuestas API simuladas, {allowed_count} operaciones; correlación por caso y contexto aislado. Sin red.')
