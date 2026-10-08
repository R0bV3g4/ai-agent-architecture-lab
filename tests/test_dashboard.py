"""Verificación del observador y controles sin crear tareas en AWS."""
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dashboard as panel

CONFIG = {"aws_account_id": "123456789012", "aws_region": "us-east-1", "project_name": "crewai-lab", "anthropic_model": "test"}
STATE = {"cluster_arn": "cluster", "log_group": "logs"}


def make_panel():
    with patch.object(panel.lab, "require_commands"), patch.object(panel.lab, "check_account"), \
         patch.object(panel.lab, "load_config", return_value=CONFIG), patch.object(panel.lab, "outputs", return_value=STATE), \
         patch.object(panel.lab, "check_state"):
        return panel.Dashboard()


class DashboardTests(unittest.TestCase):
    def test_legacy_usage_is_partial_and_missing_usage_is_not_zero(self):
        rows = [{"message": 'HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"'},
                {"message": 'HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"'},
                {"message": "Anthropic API usage: {'input_tokens': 20, 'output_tokens': 10}"}]
        result = panel.summarize_usage(rows, [])
        self.assertEqual((result["total_tokens"], result["calls"], result["measured_calls"]), (30, 2, 1))
        self.assertTrue(result["partial"])
        self.assertIsNone(panel.summarize_usage([], [])["total_tokens"])

    def test_provider_events_deduplicate_and_do_not_double_count_sdk_logs(self):
        event = {"evento": "llm_respuesta", "event_id": "e", "response_id": "msg", "tokens_entrada": 50, "tokens_salida": 12}
        rows = [{"message": "Anthropic API usage: {'input_tokens': 50, 'output_tokens': 12}"}]
        result = panel.summarize_usage(rows, [event, {**event, "event_id": "retry"}])
        self.assertEqual(result["total_tokens"], 62)
        self.assertEqual(result["measured_calls"], 1)
        self.assertFalse(result["partial"])

    def test_start_clears_previous_target_before_new_task_exists(self):
        model = make_panel()
        model.task_arn = "old"
        model.snapshot.update(target_stream="lab/agents/old", task_status="STOPPED")
        with patch.object(panel.threading, "Thread"):
            model.start(1)
        self.assertIsNone(model.task_arn)
        self.assertIsNone(model.view()["target_stream"])

    def test_filters_sdk_logs_deduplicates_and_maps_legacy_tools(self):
        event = {"timestamp": "2026-09-30T12:00:00+00:00", "run_id": "r", "event_id": "e", "evento": "herramienta_ejecutada", "herramienta": "aprobar_orden_compra"}
        row = {"message": json.dumps(event), "timestamp": 0}
        result = panel.parse_events([row, row, {"message": "SDK output"}, {"message": "null"}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["agente"], "compras")

    def test_rejects_unbounded_or_concurrent_batches(self):
        model = make_panel()
        for count in (0, 11, True, "3"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                model.start(count)
        model.batch_active = True
        with self.assertRaises(ValueError):
            model.start(1)

    def test_stop_finishes_current_round_and_cancels_remainder(self):
        model = make_panel()
        model.batch_active = True
        model.batch["total"] = 3
        with patch.object(panel.lab, "check_account"), patch.object(panel.lab, "outputs", return_value=STATE), \
             patch.object(panel.lab, "check_state"), patch.object(model, "api", return_value={"taskArns": []}), \
             patch.object(panel.lab, "run", side_effect=lambda *a, **k: model.stop_batch.set()) as run:
            model.run_batch(3)
        run.assert_called_once()
        self.assertEqual(model.batch["completed"], 1)
        self.assertFalse(model.batch_active)

    def test_existing_task_prevents_new_round(self):
        model = make_panel()
        with patch.object(panel.lab, "check_account"), patch.object(panel.lab, "outputs", return_value=STATE), \
             patch.object(panel.lab, "check_state"), patch.object(model, "api", return_value={"taskArns": ["other"]}), \
             patch.object(panel.lab, "run") as run:
            model.run_batch(1)
        run.assert_not_called()
        self.assertEqual(model.batch["status"], "error")

    def test_pagination_does_not_duplicate_forward_token(self):
        model = make_panel()
        event = {"timestamp": "2026-09-30T12:00:00+00:00", "run_id": "r", "event_id": "e", "evento": "inicio_laboratorio"}
        calls = []
        def fake(*args):
            calls.append(args)
            if args[1] == "describe-clusters":
                return {"clusters": [{"runningTasksCount": 0, "pendingTasksCount": 0}]}
            if args[1] == "describe-log-streams":
                return {"logStreams": [{"logStreamName": "stream"}]}
            return {"nextForwardToken": "token", "events": [{"message": json.dumps(event), "timestamp": 0}]}
        with patch.object(model, "api", side_effect=fake):
            model.refresh()
            model.refresh()
        self.assertEqual(len(model.cache["stream"]["rows"]), 1)
        self.assertIn("--next-token", calls[-1])


class HTTPTests(unittest.TestCase):
    def test_run_requires_same_origin_and_session_token(self):
        model = make_panel()
        server = ThreadingHTTPServer(("127.0.0.1", 0), panel.handler_for(model, 0))
        port = server.server_port
        server.RequestHandlerClass = panel.handler_for(model, port)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(model, "start") as start:
                for headers, expected in [
                    ({}, 403),
                    ({"Origin": "https://outside.example", "X-Lab-Token": model.token}, 403),
                    ({"Origin": f"http://127.0.0.1:{port}", "X-Lab-Token": model.token}, 202),
                ]:
                    connection = http.client.HTTPConnection("127.0.0.1", port)
                    connection.request("POST", "/api/run", '{"rounds":1}', headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                    connection.close()
                start.assert_called_once_with(1, None)
                connection = http.client.HTTPConnection("127.0.0.1", port)
                connection.request("GET", "/api/state", headers={"Host": f"attacker.example:{port}"})
                self.assertEqual(connection.getresponse().status, 403)
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()
