"""CrewAI real, Anthropic simulado y captura local de la salida Datadog."""
import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

# Configurar antes de importar ddtrace: no hay Agent ni telemetría de instalación.
os.environ.update(DD_INSTRUMENTATION_TELEMETRY_ENABLED="false", DD_APM_TRACING_ENABLED="false",
                  OBSERVABILITY_PROVIDER="datadog", DD_API_KEY="fake-no-network",
                  DD_SITE="datadoghq.com", OPIK_ENABLED="false")
from ddtrace.llmobs._writer import LLMObsSpanWriter
from ddtrace.llmobs import LLMObs
from datadog_observability import DatadogAuditor

spans, logs = [], []
with patch.object(LLMObsSpanWriter, "enqueue", side_effect=spans.append), \
     patch.object(DatadogAuditor, "_send", side_effect=lambda batch: logs.extend(batch)):
    runpy.run_path(str(Path(__file__).with_name("check_agent_telemetry.py")))
    LLMObs.flush()
    LLMObs.disable()

assert len([e for e in logs if e["evento"] == "decision_evaluada"]) == 8
assert len([s for s in spans if s["name"] in {e.get("caso_id") for e in logs}]) == 8
assert any(s["name"] == "CrewAI Crew" for s in spans), [s["name"] for s in spans]
assert all("run_id:" in str(s.get("tags")) for s in spans)
llm_spans = [s for s in spans if s["meta"]["span"]["kind"] == "llm"]
tool_spans = [s for s in spans if s["meta"]["span"]["kind"] == "tool"]
assert len(llm_spans) == 12, len(llm_spans)
assert len(tool_spans) == 4, len(tool_spans)
assert sum(s["metrics"]["total_tokens"] for s in llm_spans) == 240
def private_paths(value, path=""):
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in private_paths(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in private_paths(v, f"{path}[{i}]")]
    return [path] if isinstance(value, str) and "SALIDA_UNICA" in value else []

assert not private_paths(spans), private_paths(spans)
assert "fake-no-network" not in json.dumps(spans + logs)
print(f"OK Datadog: {len(spans)} spans, 12 llamadas LLM, 240 tokens simulados, 4 herramientas y {len(logs)} logs; 8 evaluaciones. Sin envío externo.")
