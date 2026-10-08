"""Lanzador local de infraestructura. Solo usa la biblioteca estándar de Python."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
CONFIG = INFRA / "lab.tfvars.json"
OPIK = ROOT / ".opik"
OPIK_COMPOSE = OPIK / "deployment" / "docker-compose" / "docker-compose.yaml"
OPIK_PROJECT = "agent-observability"
TF = os.environ.get("TERRAFORM_BIN", "terraform")
ALLOWED_CONFIG = {
    "aws_account_id", "aws_region", "project_name", "private_network",
    "anthropic_model", "splunk_hec_endpoint", "splunk_delivery_mode",
    "splunk_hec_verify_tls",
    "observability_provider", "datadog_site",
}


class LabError(RuntimeError):
    pass


def environment(**extra: str) -> dict[str, str]:
    # Los secretos solo se pasan a Terraform mediante variables efímeras.
    result = {
        key: value for key, value in os.environ.items()
        if key not in {"ANTHROPIC_API_KEY", "SPLUNK_HEC_TOKEN", "DD_API_KEY"}
        and not key.startswith("TF_VAR_")
    }
    result.update({
        "AWS_PAGER": "", "AWS_CLI_AUTO_PROMPT": "off",
        "TF_IN_AUTOMATION": "1", "TF_LOG": "OFF",
        "TF_LOG_PROVIDER": "OFF", "TF_LOG_CORE": "OFF",
    })
    result.update(extra)
    return result


def execute(args: list[str], *, capture: bool = False, input_text: str | None = None,
            env: dict[str, str] | None = None, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd or ROOT, check=True, text=True, input=input_text,
        stdout=subprocess.PIPE if capture else None,
        env=environment() if env is None else env,
    )
    return result.stdout if capture else ""


def require_commands(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise LabError("Faltan comandos: " + ", ".join(missing) + ". Consulta infra/README.md.")


def load_config() -> dict:
    if not CONFIG.exists():
        raise LabError("Copia infra/lab.tfvars.json.example a infra/lab.tfvars.json y configura tu cuenta AWS.")
    config = json.loads(CONFIG.read_text())
    if not isinstance(config, dict):
        raise LabError("lab.tfvars.json debe ser un objeto JSON.")
    unknown = set(config) - ALLOWED_CONFIG
    if unknown:
        raise LabError("Campos no admitidos en la configuración: " + ", ".join(sorted(unknown)))
    if not re.fullmatch(r"[0-9]{12}", str(config.get("aws_account_id", ""))):
        raise LabError("Configura aws_account_id con los 12 dígitos de tu cuenta de laboratorio.")
    if config.get("observability_provider", "none") not in {"none", "datadog"}:
        raise LabError("observability_provider debe ser none o datadog.")
    sys.path.insert(0, str(ROOT))
    from datadog_observability import SITES
    if config.get("datadog_site", "datadoghq.com") not in SITES:
        raise LabError("datadog_site no admitido.")
    if config.get("observability_provider") == "datadog" and config.get("splunk_hec_endpoint"):
        raise LabError("Para migrar a Datadog configura splunk_hec_endpoint como cadena vacía.")
    return {
        "aws_region": "us-east-1", "project_name": "crewai-lab",
        "private_network": True, "anthropic_model": "claude-sonnet-4-6",
        "splunk_hec_endpoint": "", "splunk_delivery_mode": "hec",
        "splunk_hec_verify_tls": True, **config,
    }


def terraform(*args: str, capture: bool = False, env: dict[str, str] | None = None) -> str:
    return execute([TF, f"-chdir={INFRA}", *args], capture=capture, env=env)


def initialize() -> None:
    terraform("init", "-input=false", "-no-color")


def aws(config: dict, *args: str, raw: bool = False) -> dict | str:
    output = execute(
        ["aws", "--region", config["aws_region"], "--no-cli-pager", *args,
         "--output", "text" if raw else "json"], capture=True,
    )
    return output.strip() if raw else json.loads(output or "{}")


def check_account(config: dict) -> None:
    actual = aws(config, "sts", "get-caller-identity")["Account"]
    if actual != config["aws_account_id"]:
        raise LabError(f"El perfil AWS pertenece a {actual}, pero la configuración autoriza {config['aws_account_id']}.")


def outputs(required: bool = True) -> dict:
    result = json.loads(terraform("output", "-json", capture=True))
    lab = result.get("lab", {}).get("value", {})
    if required and not lab:
        raise LabError("No hay infraestructura desplegada en este estado. Ejecuta ./lab up.")
    return lab


def check_state(config: dict, state: dict) -> None:
    if not state:
        return
    cluster_name = state["cluster_arn"].rsplit("/", 1)[-1]
    if (state["account_id"] != config["aws_account_id"]
            or state["region"] != config["aws_region"]
            or cluster_name != config["project_name"]):
        raise LabError("La cuenta, región o nombre no coinciden con el estado. Restaura la configuración original antes de operar.")


def secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value and sys.stdin.isatty():
        value = getpass.getpass(f"{name} (entrada oculta): ").strip()
    if not value:
        raise LabError(f"Falta {name}. Expórtala o ejecuta el comando en una terminal interactiva.")
    return value


def up(config: dict) -> None:
    require_commands("docker")
    execute(["docker", "info"], capture=True)
    api_key = secret("ANTHROPIC_API_KEY")
    hec_token = secret("SPLUNK_HEC_TOKEN") if config["splunk_hec_endpoint"] else ""
    dd_key = secret("DD_API_KEY") if config.get("observability_provider") == "datadog" else ""
    initialize()
    check_state(config, outputs(required=False))
    image_tag = f"run-{int(time.time())}-{uuid4().hex[:8]}"
    local_image = f"{config['project_name']}:{image_tag}"

    print("Construyendo imagen Linux AMD64...", flush=True)
    execute(["docker", "build", "--platform", "linux/amd64", "--tag", local_image, str(ROOT)])
    print("Creando o actualizando recursos de AWS...", flush=True)
    terraform(
        "apply", "-input=false", "-auto-approve", "-no-color",
        f"-var-file={CONFIG}", f"-var=image_tag={image_tag}",
        f"-var=secret_revision={int(time.time())}",
        env=environment(TF_VAR_anthropic_api_key=api_key, TF_VAR_splunk_hec_token=hec_token,
                        TF_VAR_datadog_api_key=dd_key),
    )
    state = outputs()
    repository = state["repository_url"]
    registry = repository.split("/", 1)[0]
    password = aws(config, "ecr", "get-login-password", raw=True)
    # El token temporal no aparece en argv. Se conserva el contexto de Docker
    # seleccionado por el usuario, incluido el de Docker Desktop.
    execute(["docker", "login", "--username", "AWS", "--password-stdin", registry],
            input_text=password + "\n")
    execute(["docker", "tag", local_image, f"{repository}:{image_tag}"])
    execute(["docker", "push", f"{repository}:{image_tag}"])
    print("Infraestructura lista e imagen publicada. Ejecuta ./lab run para iniciar los ocho casos.")


def network_configuration(state: dict) -> str:
    return json.dumps({"awsvpcConfiguration": {
        "subnets": [state["subnet_id"]],
        "securityGroups": [state["security_group_id"]],
        "assignPublicIp": state["assign_public_ip"],
    }})


def publish(config: dict, state: dict) -> None:
    """Actualizar solo la imagen y su tarea, conservando las claves existentes."""
    require_commands("docker")
    execute(["docker", "info"], capture=True)
    saved = json.loads(terraform("show", "-json", capture=True))
    resources = saved.get("values", {}).get("root_module", {}).get("resources", [])
    revisions = {r["values"].get("secret_string_wo_version") for r in resources
                 if r.get("type") == "aws_secretsmanager_secret_version"}
    if len(revisions) != 1 or None in revisions:
        raise LabError("No se pudo conservar la revisión de secretos. Usa ./lab up.")
    revision = revisions.pop()
    tag = f"run-{int(time.time())}-{uuid4().hex[:8]}"
    image = f"{state['repository_url']}:{tag}"
    execute(["docker", "build", "--platform", "linux/amd64", "--tag", image, str(ROOT)])
    password = aws(config, "ecr", "get-login-password", raw=True)
    execute(["docker", "login", "--username", "AWS", "--password-stdin", state["repository_url"].split("/", 1)[0]],
            input_text=password + "\n")
    execute(["docker", "push", image])
    # No solicitar ni leer claves. Mantener la revisión de los atributos write-only
    # y rechazar cualquier plan que pretenda cambiar secretos u otros recursos.
    with tempfile.TemporaryDirectory(prefix="crewai-publish-") as folder:
        plan = str(Path(folder) / "publish.tfplan")
        terraform("plan", "-input=false", "-no-color", f"-out={plan}",
                  f"-var-file={CONFIG}", f"-var=image_tag={tag}",
                  f"-var=secret_revision={revision}", capture=True)
        changes = json.loads(terraform("show", "-json", plan, capture=True))
        unexpected = [r["address"] for r in changes.get("resource_changes", [])
                      if r["change"]["actions"] != ["no-op"]
                      and r["address"] != "aws_ecs_task_definition.lab"]
        if unexpected:
            raise LabError("Se canceló la publicación: el plan también cambia " + ", ".join(unexpected) + ". Revisa ./lab up.")
        terraform("apply", "-input=false", "-no-color", plan)
    print("Imagen actualizada. La próxima misión usará esta versión y las claves ya configuradas.")


def wait_tasks(config: dict, cluster: str, arns: list[str], timeout: int = 1800) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tasks = []
        for start in range(0, len(arns), 100):
            result = aws(config, "ecs", "describe-tasks", "--cluster", cluster,
                         "--tasks", *arns[start:start + 100])
            failures = result.get("failures", [])
            # ECS es eventualmente consistente después de RunTask.
            if any(failure.get("reason") != "MISSING" for failure in failures):
                raise LabError("No se pudieron consultar las tareas: " + json.dumps(failures))
            tasks.extend(result["tasks"])
        if len(tasks) == len(arns) and all(task["lastStatus"] == "STOPPED" for task in tasks):
            return tasks
        time.sleep(10)
    raise LabError("Tiempo de espera agotado. Revisa ./lab logs; las tareas pueden seguir activas.")


def run(config: dict, state: dict, on_started=None, case_ids=None) -> None:
    overrides = []
    if case_ids is not None:
        sys.path.insert(0, str(ROOT))
        from compliance import seleccionar_casos
        selected = seleccionar_casos(case_ids)
        overrides = ["--overrides", json.dumps({"containerOverrides": [{"name": "agents", "environment": [
            {"name": "LAB_CASE_IDS", "value": json.dumps([c.id for c in selected])}
        ]}]})]
    # Un apply incompleto o un push fallido no debe lanzar una tarea sin imagen.
    aws(config, "ecr", "describe-images", "--repository-name", config["project_name"],
        "--image-ids", f"imageTag={state['image_tag']}")
    result = aws(
        config, "ecs", "run-task", "--cluster", state["cluster_arn"],
        "--task-definition", state["task_definition_arn"], "--launch-type", "FARGATE",
        "--platform-version", "LATEST", "--count", "1",
        "--network-configuration", network_configuration(state),
        "--started-by", "crewai-lab-cli", "--propagate-tags", "TASK_DEFINITION",
        *overrides,
    )
    if result.get("failures") or len(result.get("tasks", [])) != 1:
        raise LabError("ECS no pudo iniciar la prueba: " + json.dumps(result.get("failures", [])))
    arn = result["tasks"][0]["taskArn"]
    if on_started is not None:
        on_started(arn)
    print(f"Tarea iniciada: {arn}\nEsperando resultado; puedes ver ./lab logs en otra terminal.", flush=True)
    task = wait_tasks(config, state["cluster_arn"], [arn])[0]
    containers = task.get("containers", [])
    if not containers or any(container.get("exitCode") != 0 for container in containers):
        reason = task.get("stoppedReason", "Error de ejecución")
        raise LabError(f"La prueba falló: {reason}. Consulta ./lab logs.")
    print("La ejecución terminó con código 0. Revisa CloudWatch y tu plataforma de observabilidad; esto no confirma cumplimiento ni entrega de telemetría.")


def down(config: dict, state: dict) -> None:
    if state:
        result = aws(config, "ecs", "list-tasks", "--cluster", state["cluster_arn"],
                     "--desired-status", "RUNNING")
        arns = result.get("taskArns", [])
        for arn in arns:
            aws(config, "ecs", "stop-task", "--cluster", state["cluster_arn"],
                "--task", arn, "--reason", "Eliminación del laboratorio con ./lab down")
        if arns:
            wait_tasks(config, state["cluster_arn"], arns)
    print("Eliminando los recursos administrados, incluidas imágenes, secretos y evidencia almacenada en AWS...", flush=True)
    terraform("destroy", "-input=false", "-auto-approve", "-no-color", f"-var-file={CONFIG}")
    print("Recursos de Terraform eliminados. El estado local y los datos ya enviados a Datadog/Splunk permanecen fuera de esta eliminación.")


def datadog_test():
    """Enviar un log sintético sin levantar AWS ni consumir Anthropic."""
    sys.path.insert(0, str(ROOT))
    from datadog_observability import DatadogAuditor
    config = load_config()
    os.environ.update(OBSERVABILITY_PROVIDER="datadog",
                      DD_SITE=config.get("datadog_site", "datadoghq.com"),
                      DD_API_KEY=secret("DD_API_KEY"), OPIK_ENABLED="false")
    auditor = DatadogAuditor()
    event_id = str(uuid4())
    auditor.configure(event_id, traces=False)
    auditor.record({"evento": "datadog_prueba", "event_id": event_id,
                    "run_id": event_id, "simulado": True})
    try:
        auditor.flush(strict=True)
    except RuntimeError as exc:
        raise LabError(str(exc)) from None
    print(f"Datadog Logs aceptó el evento. Confirma su indexación: service:{auditor.service} @event_id:{event_id}")
    print("Esta prueba valida Logs; las trazas se comprueban con ./lab run.")


def hec_test() -> None:
    """Enviar un único evento sintético antes de desplegar o consumir el LLM."""
    sys.path.insert(0, str(ROOT))
    from splunk_hec import HECClient, HECError

    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    endpoint = os.environ.get("SPLUNK_HEC_URL", "").strip() or config.get("splunk_hec_endpoint", "")
    if not endpoint:
        raise LabError("Configura splunk_hec_endpoint o exporta SPLUNK_HEC_URL con la URL base HTTPS de tu trial.")
    event_id = str(uuid4())
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "level": "INFO",
        "run_id": str(uuid4()), "event_id": event_id,
        "evento": "prueba_conexion", "simulado": True,
    }
    try:
        verify_value = os.environ.get("SPLUNK_HEC_VERIFY_TLS")
        verify_tls = config.get("splunk_hec_verify_tls", True) if verify_value is None else verify_value.lower() != "false"
        HECClient(endpoint, secret("SPLUNK_HEC_TOKEN"), verify_tls=verify_tls).send(event)
    except HECError as error:
        raise LabError(str(error)) from None
    print(f'HEC aceptó el evento. Confirma su indexación buscando en Splunk: index=* event_id="{event_id}"')


def opik_compose(*args: str) -> None:
    if not OPIK_COMPOSE.is_file():
        raise LabError("No se encontró el instalador de Opik. Ejecuta ./lab opik-up primero.")
    # El instalador upstream construye un comando de shell sin entrecomillar la
    # ruta del compose. Docker recibe los argumentos por separado aquí, por lo
    # que funciona aunque el directorio del proyecto tenga espacios.
    execute([
        "docker", "compose", "-p", OPIK_PROJECT, "-f", str(OPIK_COMPOSE),
        "--project-directory", str(OPIK_COMPOSE.parent), "--profile", "opik", *args,
    ])


def opik_up() -> None:
    """Descargar una copia aislada de Opik y levantarla localmente con Docker."""
    require_commands("docker", "git")
    execute(["docker", "info"], capture=True)
    memory = int(execute(["docker", "info", "--format", "{{.MemTotal}}"], capture=True) or "0")
    minimum = 6 * 1024 ** 3
    if memory < minimum:
        assigned = round(memory / 1024 ** 3, 1)
        raise LabError(
            f"Docker Desktop tiene {assigned} GB asignados; Opik local requiere al menos 6 GB y funciona mejor con 8 GB. "
            "En Docker Desktop abre Settings > Resources, aumenta Memory y vuelve a ejecutar ./lab opik-up."
        )
    if not OPIK.exists():
        execute(["git", "clone", "--depth", "1", "https://github.com/comet-ml/opik.git", str(OPIK)])
    # Las imágenes oficiales se descargan una vez. Evitar builds locales reduce
    # el uso de CPU, memoria y disco de Docker Desktop.
    # El servicio `mc` inicializa MinIO y termina correctamente; por eso no
    # usamos `--wait`, que Compose considera erróneamente un fallo al verlo salir.
    opik_compose("up", "--detach", "--no-build")
    print("Opik está listo en http://127.0.0.1:5173\n"
          "Para registrar una misión local: OPIK_ENABLED=true OPIK_URL_OVERRIDE=http://127.0.0.1:5173/api python laboratorio_empresa.py")


def opik_down() -> None:
    """Detener Opik sin eliminar sus volúmenes ni las trazas guardadas."""
    opik_compose("down")
    print("Opik se detuvo. Tus trazas locales se conservan para el siguiente ./lab opik-up.")


def opik_status() -> None:
    opik_compose("ps")


def opik_run() -> None:
    """Ejecutar el crew desde este equipo y enviar las trazas a Opik local."""
    if not OPIK_COMPOSE.is_file():
        raise LabError("Inicia Opik antes con ./lab opik-up.")
    api_key = secret("ANTHROPIC_API_KEY")
    local_env = os.environ.copy()
    local_env.update({
        "ANTHROPIC_API_KEY": api_key,
        "OPIK_ENABLED": "true",
        "OBSERVABILITY_PROVIDER": "none",
        "OPIK_URL_OVERRIDE": "http://127.0.0.1:5173/api",
        "OPIK_PROJECT_NAME": local_env.get("OPIK_PROJECT_NAME", "agent-compliance-lab"),
        "OPIK_ENVIRONMENT": "laboratorio-local",
        "SPLUNK_HEC_URL": "",
        "SPLUNK_HEC_TOKEN": "",
    })
    print("Ejecutando los ocho casos localmente. Esta misión consume tokens de Anthropic.")
    execute([sys.executable, str(ROOT / "laboratorio_empresa.py")], env=local_env)


def main() -> None:
    parser = argparse.ArgumentParser(description="Crear, ejecutar y eliminar el laboratorio de CrewAI en AWS.")
    parser.add_argument("command", choices=["up", "publish", "run", "down", "logs", "hec-test", "datadog-test", "validate", "dashboard", "opik-up", "opik-down", "opik-status", "opik-run"])
    parser.add_argument("--port", type=int, default=8765, help="Puerto local del dashboard (8765).")
    args = parser.parse_args()
    if args.command == "datadog-test":
        datadog_test()
        return
    if args.command == "hec-test":
        hec_test()
        return
    if args.command == "dashboard":
        from dashboard import serve
        serve(args.port)
        return
    if args.command == "opik-up":
        opik_up()
        return
    if args.command == "opik-down":
        opik_down()
        return
    if args.command == "opik-status":
        opik_status()
        return
    if args.command == "opik-run":
        opik_run()
        return
    require_commands(TF)
    if args.command == "validate":
        initialize()
        terraform("fmt", "-check", "-recursive")
        terraform("validate", "-no-color")
        terraform("test", "-no-color")
        return
    require_commands("aws")
    config = load_config()
    check_account(config)
    if args.command == "up":
        up(config)
        return
    if args.command == "down":
        initialize()
    state = outputs(required=args.command != "down")
    check_state(config, state)
    if args.command == "publish":
        publish(config, state)
    elif args.command == "run":
        run(config, state)
    elif args.command == "down":
        down(config, state)
    elif args.command == "logs":
        execute(["aws", "--region", config["aws_region"], "--no-cli-pager",
                 "logs", "tail", state["log_group"], "--follow", "--since", "1h", "--format", "short"])


if __name__ == "__main__":
    try:
        main()
    except (LabError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        print(f"Falló {Path(error.cmd[0]).name} (código {error.returncode}). Si up quedó incompleto, puedes repetirlo o usar ./lab down.", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nComando interrumpido. Los recursos o tareas iniciados pueden seguir activos; usa ./lab down para eliminarlos.", file=sys.stderr)
        sys.exit(130)
