"""Integración opcional y local de Opik para el laboratorio de CrewAI.

No envía razonamiento privado ni secretos. Las trazas automáticas de CrewAI se
complementan con una traza corta por evaluación de compliance.
"""

from __future__ import annotations

import os
from typing import Any


class OpikAuditor:
    """Activa Opik sólo cuando OPIK_ENABLED=true está configurado."""

    def __init__(self) -> None:
        self.enabled = False
        self._track: Any = None
        self._context: Any = None

    def configure(self, crew: Any, *, project_name: str, run_id: str) -> bool:
        if os.environ.get("OPIK_ENABLED", "false").strip().lower() != "true":
            return False
        os.environ.setdefault("OPIK_PROJECT_NAME", project_name)
        os.environ.setdefault("OPIK_ENVIRONMENT", "laboratorio")
        try:
            from opik import opik_context, track
            from opik.integrations.crewai import track_crewai
        except ImportError as error:
            raise RuntimeError(
                "Opik está activado, pero falta la dependencia. Ejecuta: python -m pip install -r requirements.txt"
            ) from error

        # La configuración procede exclusivamente de variables de entorno. Así
        # el script no escribe ~/.opik.config ni guarda claves en el proyecto.
        track_crewai(project_name=project_name, crew=crew)
        self.enabled = True
        self._track = track
        self._context = opik_context
        return True

    def decision(self, evidence: dict[str, Any]) -> None:
        """Guardar el veredicto determinista como una traza independiente.

        Los listeners de CrewAI pueden ejecutarse en un hilo distinto al de la
        traza del crew. Por eso se crea una traza correlacionada por run_id y
        caso_id en lugar de atribuirla incorrectamente a otra tarea.
        """
        if not self.enabled:
            return

        @self._track(name="compliance.decision_evaluada")
        def registrar() -> dict[str, Any]:
            resultado = {
                "esperado": evidence.get("esperado"),
                "observado": evidence.get("observado"),
                "evaluacion": evidence.get("evaluacion"),
                "operaciones_validas": evidence.get("operaciones_validas", 0),
            }
            self._context.update_current_trace(
                input={"run_id": evidence.get("run_id"), "caso_id": evidence.get("caso_id")},
                output=resultado,
                metadata={
                    "agente": evidence.get("agente"),
                    "herramienta": evidence.get("herramienta"),
                    "telemetria_version": 5,
                },
                tags=["compliance", str(evidence.get("evaluacion", "SIN_EVALUAR")).lower()],
                feedback_scores=[{
                    "name": "cumplimiento",
                    "value": 1.0 if evidence.get("evaluacion") == "CUMPLE" else 0.0,
                }],
            )
            return resultado

        registrar()

    def flush(self) -> None:
        # La versión del SDK puede cambiar su mecanismo de flush. La integración
        # ya entrega de forma asíncrona; no fallar una misión por la telemetría.
        return None
