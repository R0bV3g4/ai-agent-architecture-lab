# AWS + Datadog: puesta en marcha

## Misiones con selección de casos

Publica la versión nueva con `./lab publish` y reinicia `./lab dashboard`.
El frontend permite elegir todo el equipo, un agente o un escenario del catálogo,
y repetir esa selección entre 1 y 10 sesiones. Muestra la solicitud y decisión esperada.
El catálogo actual conserva los ocho casos evaluables; no es un editor de prompts libres.
Cada sesión ejecuta exactamente la selección usando `LAB_CASE_IDS` en el override ECS.
`./lab run` sin selección conserva los ocho casos. El botón Parar termina la sesión actual.

Las misiones parciales no requieren ocho evaluaciones: consulta `casos_seleccionados`
en `inicio_laboratorio` y compáralo con los casos completados del mismo `run_id`.
Las notas de dashboards antiguos que exigen siempre ocho casos solo aplican a misiones
completas. Los agentes excluidos del plan se muestran como No participa.

El código está integrado; la recepción real requiere tu API key, organización
Datadog y una misión AWS. No se provisionan productos, monitores ni dashboards
en tu cuenta Datadog mediante Terraform. Activa Agent/LLM Observability y Logs.

## 1. Configuración

Edita `infra/lab.tfvars.json`, conservando tu cuenta y región AWS:

```json
"observability_provider": "datadog",
"datadog_site": "datadoghq.com"
```

Sitios admitidos: `datadoghq.com` (app.datadoghq.com), `us3.datadoghq.com`,
`us5.datadoghq.com`, `datadoghq.eu` (app.datadoghq.eu), `ap1.datadoghq.com`,
`ap2.datadoghq.com`. El sitio debe coincidir con tu organización y API key.
Se dejó US1 como valor inicial, pendiente de confirmarlo en tu cuenta.
No pongas claves en este JSON. Usa una API key, no una Application Key.

## 2. Comprobar Logs sin AWS ni Anthropic

```bash
./lab datadog-test
```

Solicita `DD_API_KEY` con entrada oculta. Un HTTP 202 solo significa aceptación:
busca el `event_id` impreso en Logs Explorer, periodo últimos 15 minutos.
No valida trazas ni activa Cloud SIEM. Un 403 suele indicar sitio/clave incorrectos;
si se acepta pero no aparece, revisa filtros, índices y disponibilidad de Logs.

## 3. Crear AWS y ejecutar

```bash
aws login
aws sts get-caller-identity
docker info
./lab up
./lab run
```

`up` solicita ANTHROPIC_API_KEY y DD_API_KEY, construye/publica la imagen y aplica
Terraform. Las claves se pasan mediante variables efímeras y secretos write-only;
no se incluyen en argumentos, imagen ni estado de Terraform.
Cada `run` ejecuta los ocho casos una vez, consume Fargate y Anthropic, y termina.
`./lab dashboard` conserva el botón Iniciar misión y la lectura de CloudWatch;
la nueva definición ECS hace que esas misiones también envíen datos a Datadog.
Tras la primera migración, `./lab publish` actualiza solo el código conservando secretos.

## 4. Verificar evidencia

En Agent/LLM Observability selecciona `agent-compliance-lab`. Busca la misión por
el tag `run_id`: debe incluir Crew, ocho tareas, agentes, herramientas y llamadas
Anthropic con métricas reales. El nombre de cada span de tarea es su `caso_id`.
El número de llamadas/herramientas puede variar según las decisiones del modelo.

En Logs Explorer:

```text
service:agent-compliance-lab @evento:decision_evaluada
service:agent-compliance-lab @evaluacion:INCUMPLE
service:agent-compliance-lab @agente:rrhh
service:agent-compliance-lab @run_id:TU_RUN_ID
```

Campos reales: `agente`, `caso_id`, `evaluacion` (CUMPLE/INCUMPLE/REVISAR),
`decision`, `operaciones`, `rechazo_correcto`, `operacion_permitida`, `evidencia_ids`.
No son `compliance_result:PASS` ni nombres de agentes con espacios.
Una misión completa debe tener ocho `decision_evaluada`, no necesariamente ocho CUMPLE.
Un rechazo correcto cuenta como CUMPLE; un rechazo indebido puede ser INCUMPLE.

Las trazas usan envío periódico del SDK. Los logs se agrupan al terminar la misión
(también ante error) para evitar esperas HTTP en cada acción. El dashboard local
sigue mostrando la actividad desde CloudWatch durante la ejecución.
Si hay fallos de envío, CloudWatch registra `datadog_envio_fallido`; un exit code 0
no prueba entrega ni cumplimiento. Los reintentos pueden duplicar logs: usa `event_id`.
No hay cola persistente ni garantía de entrega después de finalizar el contenedor.

## Instrumentación y privacidad

Se utiliza `LLMObs.enable()` antes de ejecutar CrewAI, con integración automática
en modo agentless. Por eso el Dockerfile conserva `python laboratorio_empresa.py`:
no hace falta `ddtrace-run` ni configurar `DD_LLMOBS_ENABLED` por separado.
No habilites ambos mecanismos: el procesador de redacción se registra al iniciar.
APM y telemetría del instalador se desactivan. Opik y Datadog no se activan juntos.

Inputs/outputs de spans se reemplazan por `[REDACTED]` y se limpian metadatos libres.
Los logs exportan solo campos permitidos; excluyen solicitud, respuesta, motivo,
argumentos y resultados con datos médicos/bancarios. Las definiciones de agentes,
herramientas y diagnósticos internos del SDK pueden seguir apareciendo en trazas;
esta configuración está validada para los datos sintéticos del laboratorio, no
como solución general de DLP. CloudWatch conserva la auditoría original del lab.

## Apagar

```bash
./lab down
```

Elimina los recursos AWS de este estado (incluidos logs y secretos), pero no datos
ni suscripciones Datadog. Retención y facturación Datadog se administran allí.
Aunque Fargate termine, recursos como NAT (si se habilita), secretos e imágenes
pueden seguir generando costos hasta eliminar el laboratorio.

## Pruebas sin servicios reales

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=. .venv/bin/python tests/check_datadog_telemetry.py
./lab validate
```

La prueba integrada captura la salida del SDK sin enviarla: ocho casos, llamadas
Anthropic simuladas, tokens, herramientas y redacción. Terraform utiliza mock_provider
AWS; no crea infraestructura real en estas pruebas.

Referencias: [CrewAI](https://docs.datadoghq.com/llm_observability/guide/crewai_guide/),
[SDK](https://docs.datadoghq.com/llm_observability/instrument/sdk/),
[Logs API](https://docs.datadoghq.com/api/latest/logs/).
