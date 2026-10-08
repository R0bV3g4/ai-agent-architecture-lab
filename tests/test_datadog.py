import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from datadog_observability import DatadogAuditor, NoRedirect, redact_span


class DatadogTests(unittest.TestCase):
    def auditor(self):
        auditor = DatadogAuditor()
        with patch.dict(os.environ, {"OBSERVABILITY_PROVIDER": "datadog",
                                    "DD_API_KEY": "test-secret", "DD_SITE": "datadoghq.eu",
                                    "OPIK_ENABLED": "false"}):
            auditor.configure("run-1", traces=False)
        return auditor

    def test_logs_allowlist_excludes_private_data(self):
        auditor = self.auditor()
        auditor.record({"evento": "decision_evaluada", "evaluacion": "INCUMPLE",
                        "run_id": "run-1", "caso_id": "rrhh", "event_id": "event-1",
                        "motivo": "SALARIO PRIVADO", "argumentos": {"cuenta": "123"},
                        "solicitud": "secreto", "respuesta": "dato medico"})
        payload = json.dumps(auditor.events)
        for private in ["SALARIO PRIVADO", "123", "secreto", "dato medico"]:
            self.assertNotIn(private, payload)
        self.assertIn("INCUMPLE", payload)
        self.assertIn("event-1", payload)

    def test_send_and_drain_after_acceptance(self):
        auditor = self.auditor()
        auditor.record({"evento": "prueba"})
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 202
        with patch("datadog_observability.request.build_opener", return_value=opener):
            auditor.flush(strict=True)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, "https://http-intake.logs.datadoghq.eu/api/v2/logs")
        self.assertEqual(req.get_header("Dd-api-key"), "test-secret")
        self.assertEqual(auditor.events, [])

    def test_failed_delivery_retains_events_and_hides_response(self):
        auditor = self.auditor()
        auditor.record({"evento": "prueba"})
        opener = MagicMock()
        opener.open.side_effect = HTTPError("url", 403, "secret-body", {}, None)
        with patch("datadog_observability.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                auditor.flush(strict=True)
        self.assertEqual(len(auditor.events), 1)
        self.assertEqual(opener.open.call_count, 1)

    def test_network_failure_has_bounded_retries(self):
        auditor = self.auditor()
        auditor.record({"evento": "prueba"})
        opener = MagicMock()
        opener.open.side_effect = URLError("offline")
        with patch("datadog_observability.request.build_opener", return_value=opener), patch("datadog_observability.time.sleep"):
            with self.assertRaises(RuntimeError):
                auditor.flush(strict=True)
        self.assertEqual(opener.open.call_count, 3)

    def test_redirect_cannot_forward_key(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_span_redaction(self):
        span = SimpleNamespace(input=["secret"], output=["medical"], metadata={"private": "data"})
        self.assertIs(redact_span(span), span)
        self.assertEqual(span.input[0]["content"], "[REDACTED]")
        self.assertEqual(span.output[0]["content"], "[REDACTED]")
        self.assertEqual(span.metadata, {})

    def test_invalid_site_rejected_before_network(self):
        with patch.dict(os.environ, {"OBSERVABILITY_PROVIDER": "datadog", "DD_SITE": "attacker.example", "OPIK_ENABLED": "false"}):
            with self.assertRaises(ValueError):
                DatadogAuditor().configure("run")


if __name__ == "__main__":
    unittest.main()
