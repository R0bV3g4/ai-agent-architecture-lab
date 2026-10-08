"""Envío opcional a HEC estándar, compatible con un token sin indexer ACK."""

from __future__ import annotations

from datetime import datetime
import json
import os
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class HECError(RuntimeError):
    """Error de entrega cuyo mensaje no contiene el token ni el cuerpo enviado."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # No reenviar Authorization a otro destino si la URL está mal configurada.
        return None


class HECClient:
    def __init__(self, base_url: str, token: str, timeout: float = 5.0,
                 verify_tls: bool = True):
        url = urlsplit(base_url)
        if (url.scheme != "https" or not url.hostname or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("SPLUNK_HEC_URL debe ser la URL base HTTPS, sin ruta, usuario ni parámetros.")
        try:
            port = url.port
        except ValueError:
            raise ValueError("El puerto de SPLUNK_HEC_URL no es válido.") from None
        if port == 0:
            raise ValueError("El puerto de SPLUNK_HEC_URL no es válido.")
        if not token.strip() or any(char in token for char in "\r\n"):
            raise ValueError("Falta un SPLUNK_HEC_TOKEN válido.")
        self.url = base_url.rstrip("/") + "/services/collector/event"
        self._token = token.strip()
        self.timeout = timeout
        tls_context = ssl.create_default_context() if verify_tls else ssl._create_unverified_context()
        self._opener = build_opener(HTTPSHandler(context=tls_context), NoRedirects())

    @classmethod
    def from_environment(cls) -> HECClient | None:
        endpoint = os.environ.get("SPLUNK_HEC_URL", "").strip()
        if not endpoint:
            return None
        verify_value = os.environ.get("SPLUNK_HEC_VERIFY_TLS", "true").strip().lower()
        if verify_value not in {"true", "false"}:
            raise ValueError("SPLUNK_HEC_VERIFY_TLS debe ser true o false.")
        return cls(endpoint, os.environ.get("SPLUNK_HEC_TOKEN", ""),
                   verify_tls=verify_value == "true")

    def send(self, event: dict) -> None:
        """Comprobar aceptación HEC; no equivale a confirmar su indexación."""
        body = json.dumps({
            "time": datetime.fromisoformat(event["timestamp"]).timestamp(),
            "source": "crewai-lab", "sourcetype": "_json", "event": event,
        }, ensure_ascii=False).encode("utf-8")
        request = Request(self.url, data=body, method="POST", headers={
            "Authorization": f"Splunk {self._token}",
            "Content-Type": "application/json",
        })
        error = "Entrega fallida"
        for attempt in range(3):
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    result = json.loads(response.read(65536))
                if not isinstance(result, dict) or not isinstance(result.get("code"), int):
                    raise HECError("Respuesta HEC no válida")
                if result["code"] != 0:
                    raise HECError(f"HEC rechazó el evento (código {result['code']})")
                return
            except HTTPError as exc:
                error = f"HTTP {exc.code}"
                exc.close()
                if exc.code != 429 and exc.code < 500:
                    raise HECError(error) from None
            except (URLError, TimeoutError, OSError):
                error = "Error de conexión con HEC"
            except (ValueError, UnicodeError):
                raise HECError("Respuesta HEC no válida") from None
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise HECError(error)
