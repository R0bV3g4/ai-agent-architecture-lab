"""Datadog opcional: trazas instrumentadas y logs de auditoría por HTTPS."""
from contextlib import nullcontext
import json
import logging
import os
import threading
import time
from urllib import request, error

SITES = {"datadoghq.com", "us3.datadoghq.com", "us5.datadoghq.com",
         "datadoghq.eu", "ap1.datadoghq.com", "ap2.datadoghq.com"}
FIELDS = set("timestamp level run_id event_id evento simulado agente caso_id tarea tipo_caso herramienta evaluacion decision operaciones evidencia_ids operacion_permitida rechazo_correcto duracion_ms modelo proveedor response_id tokens_entrada tokens_salida tokens_total tokens_cache_lectura tokens_cache_escritura tareas tareas_completadas telemetria_version casos_por_agente".split())
FIELDS.add("casos_seleccionados")


def redact_span(span):
    # No exportar mensajes, resultados de herramientas ni metadatos libres.
    # En ddtrace 4.15 una lista vacía no reemplaza campos de tipo value.
    span.input = [{"content": "[REDACTED]", "role": "user"}]
    span.output = [{"content": "[REDACTED]", "role": "assistant"}]
    span.metadata.clear()
    return span


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Nunca reenviar la API key a otro host.


class DatadogAuditor:
    def __init__(self):
        self.enabled = False
        self.llmobs = None
        self.events = []
        self.lock = threading.Lock()

    def configure(self, run_id, *, traces=True):
        if os.environ.get("OBSERVABILITY_PROVIDER", "none") != "datadog":
            return False
        if os.environ.get("OPIK_ENABLED", "false").lower() == "true":
            raise ValueError("Desactiva OPIK_ENABLED al utilizar Datadog.")
        self.site = os.environ.get("DD_SITE", "datadoghq.com")
        if self.site not in SITES:
            raise ValueError("DD_SITE no admitido; utiliza el dominio de tu organización Datadog.")
        self.key = os.environ.get("DD_API_KEY", "").strip()
        if not self.key:
            raise ValueError("Falta DD_API_KEY.")
        self.service = os.environ.get("DD_SERVICE", "agent-compliance-lab")
        self.env = os.environ.get("DD_ENV", "lab")
        self.run_id = run_id
        if traces:
            os.environ["DD_APM_TRACING_ENABLED"] = "false"
            os.environ["DD_INSTRUMENTATION_TELEMETRY_ENABLED"] = "false"
            from ddtrace.llmobs import LLMObs
            LLMObs.enable(ml_app=self.service, service=self.service, env=self.env,
                          site=self.site, api_key=self.key, agentless_enabled=True,
                          span_processor=redact_span)
            self.llmobs = LLMObs
        self.enabled = True
        return True

    def context(self, **tags):
        return (self.llmobs.annotation_context(tags={"run_id": self.run_id, **tags})
                if self.llmobs else nullcontext())

    def record(self, event):
        if not self.enabled:
            return
        payload = {k: v for k, v in event.items() if k in FIELDS}
        payload.update(service=self.service, ddsource="crewai", ddtags=f"env:{self.env}",
                       message=event["evento"])
        with self.lock:
            self.events.append(payload)

    def _send(self, batch):
        req = request.Request(f"https://http-intake.logs.{self.site}/api/v2/logs",
                              data=json.dumps(batch).encode(), method="POST",
                              headers={"DD-API-KEY": self.key, "Content-Type": "application/json"})
        opener = request.build_opener(NoRedirect())
        for attempt in range(3):
            try:
                with opener.open(req, timeout=10) as response:
                    if response.status != 202:
                        raise RuntimeError("Datadog Logs no aceptó el lote.")
                return
            except error.HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise RuntimeError(f"Datadog Logs rechazó el lote: HTTP {exc.code}.") from None
            except (error.URLError, TimeoutError, OSError):
                pass
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise RuntimeError("No se pudo entregar el lote a Datadog Logs tras tres intentos.")

    def flush(self, *, strict=False):
        if not self.enabled:
            return
        try:
            # Retener pendientes ante fallo; event_id permite detectar duplicados.
            with self.lock:
                while self.events:
                    batch = self.events[:100]
                    self._send(batch)
                    del self.events[:len(batch)]
        except RuntimeError:
            logging.getLogger("laboratorio.datadog").error(
                '{"evento":"datadog_envio_fallido","destino":"logs"}')
            if strict:
                raise
        finally:
            if self.llmobs:
                self.llmobs.flush()
