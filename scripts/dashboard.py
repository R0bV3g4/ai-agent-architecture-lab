"""Panel local: eventos reales de CloudWatch y ejecuciones limitadas de ECS.

Solo biblioteca estándar. No consulta Secrets Manager ni guarda claves en el navegador.
"""
from __future__ import annotations

from datetime import datetime, timezone
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

import lab
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compliance import CASOS, seleccionar_casos

WEB = Path(__file__).resolve().parents[1] / "dashboard"
TOOLS = {
    "procesar_pago_factura": "finanzas", "emitir_reembolso": "soporte",
    "consultar_base_rrhh": "rrhh", "aprobar_orden_compra": "compras",
}


def parse_events(rows):
    """Ignorar el texto libre del SDK; conservar solo el esquema de auditoría."""
    events, seen = [], set()
    for row in rows:
        try:
            item = json.loads(row.get("message", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(item, dict) or not all(item.get(k) for k in ("run_id", "event_id", "evento")):
            continue
        if item["event_id"] in seen:
            continue
        seen.add(item["event_id"])
        item = dict(item)
        item.setdefault("timestamp", datetime.fromtimestamp(row["timestamp"] / 1000, timezone.utc).isoformat())
        item.setdefault("agente", TOOLS.get(item.get("herramienta")) or str(item.get("tarea", "")).split("_", 1)[0])
        events.append(item)
    return sorted(events, key=lambda e: e["timestamp"])


def summarize_usage(rows, events):
    """Métricas reales; las versiones antiguas no registraban todas las respuestas."""
    records = {}
    for event in events:
        if event["evento"] == "llm_respuesta":
            records.setdefault(event.get("response_id") or event["event_id"], {
                "input_tokens": event.get("tokens_entrada", 0),
                "output_tokens": event.get("tokens_salida", 0),
            })
    modern = any(e.get("telemetria_version", 0) >= 3 for e in events) or bool(records)
    http_calls = sum('POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"' in row.get("message", "") for row in rows)
    if not modern:
        for index, row in enumerate(rows):
            message = row.get("message", "")
            prefixes = ("Anthropic API usage: ", "Anthropic API tool conversation usage: ")
            prefix = next((p for p in prefixes if message.startswith(p)), None)
            if prefix and len(message) < 2000:
                try:
                    value = ast.literal_eval(message[len(prefix):])
                    if isinstance(value, dict):
                        records[str(index)] = value
                except (ValueError, SyntaxError):
                    pass
    def count(value):
        return value if type(value) is int and value >= 0 else 0
    input_tokens = sum(count(r.get("input_tokens")) for r in records.values())
    output_tokens = sum(count(r.get("output_tokens")) for r in records.values())
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens if records else None,
            "calls": max(http_calls, len(records)), "measured_calls": len(records),
            "partial": not modern or len(records) < http_calls,
            "source": "provider_events" if modern else "legacy_sdk_logs"}


class Dashboard:
    def __init__(self):
        lab.require_commands(lab.TF, "aws")
        self.config = lab.load_config()
        lab.check_account(self.config)
        self.state = lab.outputs()
        lab.check_state(self.config, self.state)
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.stop_poll = threading.Event()
        self.stop_batch = threading.Event()
        self.batch_active = False
        self.batch = {"total": 0, "completed": 0, "status": "idle", "message": "Sin lote activo"}
        self.task_arn = None
        self.snapshot = {"events": [], "runs": [], "running": 0, "pending": 0,
                         "last_sync": None, "error": None, "task_status": None}
        self.cache = {}
        self.last_discovery = 0
        self.stream_names = []

    def api(self, *args):
        # aws CLI mantiene el inicio de sesión temporal del usuario en el servidor.
        return lab.aws(self.config, *args)

    def refresh(self):
        cluster = self.api("ecs", "describe-clusters", "--clusters", self.state["cluster_arn"])
        if cluster.get("failures") or not cluster.get("clusters"):
            raise lab.LabError("No se encontró el clúster; comprueba si ejecutaste ./lab down.")
        info = cluster["clusters"][0]
        with self.lock:
            target = self.task_arn
        task_status = None
        if target:
            tasks = self.api("ecs", "describe-tasks", "--cluster", self.state["cluster_arn"], "--tasks", target)
            if tasks.get("tasks"):
                task_status = tasks["tasks"][0]["lastStatus"]
        # Descubrir las últimas 12 ejecuciones; consultar el resto de páginas de cada
        # stream por token para no omitir eventos que lleguen durante el sondeo.
        if time.monotonic() - self.last_discovery > 15 or not self.stream_names:
            result = self.api("logs", "describe-log-streams", "--log-group-name", self.state["log_group"],
                              "--order-by", "LastEventTime", "--descending", "--limit", "12", "--no-paginate")
            self.stream_names = [s["logStreamName"] for s in result.get("logStreams", [])]
            self.last_discovery = time.monotonic()
        names = list(self.stream_names)
        if target:
            target_stream = "lab/agents/" + target.rsplit("/", 1)[-1]
            if target_stream not in names:
                # El stream puede no existir todavía mientras ECS descarga la imagen.
                found = self.api("logs", "describe-log-streams", "--log-group-name", self.state["log_group"],
                                 "--log-stream-name-prefix", target_stream)
                if found.get("logStreams"):
                    names.insert(0, target_stream)
        for i, name in enumerate(names):
            cached = self.cache.setdefault(name, {"rows": [], "token": None, "done": False, "truncated": False})
            if cached["done"] and i > 0 and name != ("lab/agents/" + target.rsplit("/", 1)[-1] if target else None):
                continue
            args = ["logs", "get-log-events", "--log-group-name", self.state["log_group"],
                    "--log-stream-name", name, "--start-from-head", "--limit", "2000", "--no-paginate"]
            if cached["token"]:
                args.extend(["--next-token", cached["token"]])
            page = self.api(*args)
            rows = page.get("events", [])
            if page.get("nextForwardToken") != cached["token"]:
                cached["rows"].extend(rows)
            cached["token"] = page.get("nextForwardToken")
            if len(cached["rows"]) > 10000:
                cached["rows"] = cached["rows"][-10000:]
                cached["truncated"] = True
            events = parse_events(cached["rows"])
            # Una página vacía confirma que alcanzamos el final observado; seguimos
            # consultando el stream más reciente por posibles entregas tardías.
            cached["done"] = not rows and any(e["evento"] in ("fin_laboratorio", "error_laboratorio") for e in events)
        runs = []
        for name in names:
            cached = self.cache[name]
            events = parse_events(cached["rows"])
            if not events:
                continue
            runs.append({"stream": name, "run_id": events[0]["run_id"], "events": events,
                         "timestamp": events[0]["timestamp"], "truncated": cached["truncated"],
                         "usage": summarize_usage(cached["rows"], events)})
        runs.sort(key=lambda r: r["timestamp"], reverse=True)
        with self.lock:
            # Si el usuario inició otra ronda mientras se consultaba AWS, conservar
            # el destino nuevo y no volver a mostrar la ronda anterior.
            if target != self.task_arn:
                target = self.task_arn
                task_status = self.snapshot.get("task_status")
            self.snapshot = {"runs": runs, "running": info["runningTasksCount"],
                             "pending": info["pendingTasksCount"], "task_status": task_status,
                             "target_stream": "lab/agents/" + target.rsplit("/", 1)[-1] if target else None,
                             "last_sync": datetime.now(timezone.utc).isoformat(), "error": None}

    def poll(self):
        while not self.stop_poll.is_set():
            try:
                self.refresh()
            except Exception:
                with self.lock:
                    self.snapshot["error"] = "No se pudo actualizar AWS. Los datos visibles son la última lectura; revisa la terminal y tu sesión de AWS."
                print("No se pudo actualizar el dashboard. Comprueba aws sts get-caller-identity y la existencia del laboratorio.", flush=True)
            self.stop_poll.wait(2)

    def view(self):
        with self.lock:
            return {**self.snapshot, "batch": dict(self.batch), "batch_active": self.batch_active,
                    "csrf_token": self.token, "region": self.config["aws_region"],
                    "model": self.config["anthropic_model"], "project": self.config["project_name"]}

    def start(self, count, case_ids=None):
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError("Elige entre 1 y 10 rondas.")
        selected = seleccionar_casos(case_ids)
        with self.lock:
            if self.batch_active:
                raise ValueError("Ya existe un lote en ejecución.")
            self.batch_active = True
            self.task_arn = None
            self.snapshot.update(target_stream=None, task_status=None)
            self.stop_batch.clear()
            self.batch = {"total": count, "completed": 0, "status": "starting", "message": "Comprobando AWS…",
                          "cases": [c.metadata() for c in selected]}
        threading.Thread(target=self.run_batch, args=(count, [c.id for c in selected]), daemon=True).start()

    def started(self, arn):
        with self.lock:
            self.task_arn = arn
            self.snapshot.update(target_stream="lab/agents/" + arn.rsplit("/", 1)[-1], task_status="PROVISIONING")
            self.batch["status"] = "running"
            self.batch["message"] = f"Sesión {self.batch['completed'] + 1} de {self.batch['total']} · {len(self.batch.get('cases', CASOS))} casos en un contenedor"
            self.last_discovery = 0

    def run_batch(self, count, case_ids=None):
        try:
            # Releer outputs permite observar una nueva imagen publicada con ./lab up.
            lab.check_account(self.config)
            state = lab.outputs()
            lab.check_state(self.config, state)
            with self.lock:
                self.state = state
            for _ in range(count):
                if self.stop_batch.is_set():
                    break
                existing = self.api("ecs", "list-tasks", "--cluster", state["cluster_arn"], "--desired-status", "RUNNING")
                if existing.get("taskArns"):
                    raise lab.LabError("El clúster ya tiene una tarea activa. Espera a que termine.")
                lab.run(self.config, state, on_started=self.started, case_ids=case_ids)
                with self.lock:
                    self.batch["completed"] += 1
            with self.lock:
                self.batch.update(status="completed", message=f"Lote detenido tras {self.batch['completed']} rondas" if self.stop_batch.is_set() else "Lote finalizado")
        except Exception:
            with self.lock:
                self.batch.update(status="error", message="No se completó el lote. Revisa ./lab logs y tu sesión AWS. Una tarea enviada puede seguir activa.")
            print("Error en el lote del dashboard. Consulta ./lab logs y aws sts get-caller-identity.", flush=True)
        finally:
            with self.lock:
                self.batch_active = False


def handler_for(dashboard, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {"http://" + host for host in hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def trusted(self):
            return self.headers.get("Host") in hosts and self.headers.get("Origin", "") in origins | {""}

        def respond(self, code, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.trusted():
                self.respond(403, {"error": "Origen no permitido"})
                return
            path = urlsplit(self.path).path
            if path == "/api/state":
                self.respond(200, dashboard.view())
                return
            if path == "/api/cases":
                self.respond(200, [{**c.metadata(), "solicitud": c.solicitud,
                                    "decision_esperada": "APROBAR" if c.permitido else "RECHAZAR"} for c in CASOS])
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/state.js": ("state.js", "application/javascript; charset=utf-8"),
                     "/app.js": ("app.js", "application/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path not in files:
                self.respond(404, {"error": "No encontrado"})
                return
            filename, mime = files[path]
            self.respond(200, (WEB / filename).read_bytes(), mime)

        def do_POST(self):
            if (not self.trusted() or self.headers.get("Origin") not in origins
                    or not secrets.compare_digest(self.headers.get("X-Lab-Token", ""), dashboard.token)):
                self.respond(403, {"error": "Recarga el panel para autorizar esta acción local."})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024:
                    raise ValueError("Solicitud no válida")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Solicitud no válida")
                if self.path == "/api/run":
                    dashboard.start(data.get("rounds", 1), data.get("case_ids"))
                elif self.path == "/api/stop":
                    dashboard.stop_batch.set()
                    with dashboard.lock:
                        dashboard.batch["message"] = "Se completará la ronda actual; las siguientes quedan canceladas."
                else:
                    self.respond(404, {"error": "No encontrado"})
                    return
                self.respond(202, {"ok": True})
            except (ValueError, TypeError) as error:
                self.respond(400, {"error": str(error)})

    return Handler


def serve(port=8765):
    if not 1024 <= port <= 65535:
        raise ValueError("El puerto debe estar entre 1024 y 65535.")
    dashboard = Dashboard()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_for(dashboard, port))
    threading.Thread(target=dashboard.poll, daemon=True).start()
    print(f"Oficina de agentes: http://127.0.0.1:{port}\nSolo acceso local. Los botones ejecutan rondas en AWS y consumen créditos de Anthropic.\nCtrl+C cierra el panel y cancela las rondas pendientes; una tarea AWS ya iniciada sigue hasta terminar.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop_batch.set()
        dashboard.stop_poll.set()
        server.server_close()
