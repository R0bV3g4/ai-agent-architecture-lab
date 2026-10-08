# Infraestructura efímera en AWS

Para AWS + Datadog sigue [la guía actual](../datadog/README.md).
Las secciones Splunk de este documento describen recursos heredados; el script
actual no realiza envíos HEC directos. Datadog usa HTTPS directo desde Fargate,
con la API key en Secrets Manager y sin sidecar ni Forwarder Lambda.

Desde la raíz del proyecto:

```bash
./lab up       # Construye la imagen, crea AWS y publica en ECR.
./lab run      # Ejecuta los cuatro agentes una vez y espera su resultado.
./lab logs     # Sigue los registros de CloudWatch.
./lab hec-test # Envía un evento sintético a HEC; no necesita AWS ni Anthropic.
./lab down     # Detiene tareas activas y elimina los recursos de este estado.
```

`up` deja el laboratorio listo; cada `run` consume la API de Anthropic. No se
crea un servicio permanente ni un calendario de ejecuciones.

## Configuración inicial

Necesitas Python 3.11 o superior, Terraform >= 1.11 y < 2, AWS CLI v2 y Docker
con el motor iniciado. El lanzador funciona en macOS y Linux; en Windows, usa
WSL. Puede usar el Python de `.venv` o `python3` del PATH. La imagen se construye
para `linux/amd64`, también cuando la máquina local utiliza Apple Silicon.

Instaladores oficiales:

- [Terraform](https://developer.hashicorp.com/terraform/install)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Docker](https://docs.docker.com/get-started/get-docker/)

Configura un perfil AWS de tu cuenta de laboratorio. Por ejemplo, si utilizas
IAM Identity Center y ya configuraste el perfil `laboratorio`:

```bash
aws sso login --profile laboratorio
export AWS_PROFILE=laboratorio
cp infra/lab.tfvars.json.example infra/lab.tfvars.json
```

Edita `infra/lab.tfvars.json`: indica tu cuenta de 12 dígitos, región y nombre.
El perfil necesita permisos para administrar VPC, ECS, ECR, IAM, Secrets Manager
y CloudWatch; con el modo Firehose, también Firehose y S3. `run` requiere `ecs:RunTask` e
`iam:PassRole` para los roles de la tarea; `down` necesita los permisos de borrado
y detención. La plantilla no modifica el perfil del operador.

Ejecuta `./lab up`. Solicitará `ANTHROPIC_API_KEY` con entrada oculta; también
puedes proporcionarla como variable de entorno. No la escribas en el JSON ni
en Terraform. Si habilitas Splunk, solicitará además `SPLUNK_HEC_TOKEN`.

La primera configuración queda así:

```json
{
  "aws_account_id": "123456789012",
  "aws_region": "us-east-1",
  "project_name": "crewai-lab",
  "private_network": true,
  "anthropic_model": "claude-sonnet-4-6",
  "splunk_hec_endpoint": "",
  "splunk_delivery_mode": "hec"
}
```

El ID es un ejemplo; debes sustituirlo. El lanzador y el proveedor comprueban la
cuenta. Si ya existe un despliegue, el lanzador también comprueba nombre y región
contra el estado antes de actualizar, ejecutar o destruir.

## Recursos y red

Se crea una VPC propia, subred pública y, por defecto, subred privada con NAT;
un repositorio ECR; un clúster y definición de tarea Fargate; dos roles de ECS;
el secreto de Anthropic; y un grupo de CloudWatch con retención de 7 días.
La tarea utiliza 1 vCPU y 2 GiB, ejecuta el contenedor con usuario sin privilegios
y no tiene reglas de entrada en su security group. La salida permite HTTPS en
443 y, en modo HEC directo, el puerto adicional del endpoint (por ejemplo 8088).
Las herramientas siguen siendo mocks sin permisos para modificar recursos AWS.

`private_network = true` conserva la arquitectura con NAT. **El NAT y otros
servicios pueden seguir generando cargos aunque no haya agentes ejecutándose.**
Si quieres reducir el costo fijo de este laboratorio, establece
`private_network = false`: se usa la subred pública, con IP pública mientras
la tarea está activa y sin puertos de entrada. Se eliminan NAT, EIP y subred
privada. No se filtran dominios de salida: HTTPS puede alcanzar Internet.

`up` construye primero la imagen y después aplica Terraform y la publica. Cada
despliegue usa una etiqueta nueva e inmutable. Si una fase falla después del
apply, pueden quedar recursos facturables: repite `up` o ejecuta `down`.
La publicación usa `docker login` y el almacenamiento de credenciales configurado
en Docker para el token temporal de ECR. `run` comprueba que exista la imagen
antes de iniciar ECS. Un código 0 significa
que el script terminó; no certifica que los agentes hayan cumplido las políticas.

## Splunk opcional

Esta plantilla conecta una instancia existente de Splunk Enterprise o Splunk
Cloud mediante HEC. No instala ni licencia un servidor Splunk.

### Splunk Cloud trial: modo HEC directo

El modo predeterminado es `"splunk_delivery_mode": "hec"`. El contenedor envía
cada evento directamente a `/services/collector/event` y conserva primero una
copia en CloudWatch. No crea Firehose ni su bucket S3.

La documentación de Splunk distingue las capacidades del trial y de una
suscripción. HEC estándar está disponible, pero la integración de Firehose
requiere habilitación y soporte de ACK. El API REST de administración tampoco
está disponible en el free trial; crea el índice y el token desde Splunk Web.

Prepara en la interfaz de tu trial:

1. Un índice, por ejemplo `agentes_lab`.
2. Un token HEC con ese índice predeterminado y `sourcetype = _json`.
3. Deja **Enable indexer acknowledgment desmarcado** para el envío directo.
4. Obtén la URL HEC exacta de tu trial. No uses automáticamente la URL de login:
   el hostname de ingesta y su puerto pueden ser diferentes.

Escribe la **URL base**, sin `/services/collector`, en la configuración:

```json
"splunk_hec_endpoint": "https://TU-ENDPOINT-HEC:8088",
"splunk_delivery_mode": "hec"
```

El hostname anterior es un marcador, no una dirección real. Las páginas de
Splunk muestran distintas convenciones de hostname según el despliegue; confirma
la dirección de tu instancia y verifica TLS. No desactives la validación TLS.

Antes de desplegar, ejecuta `./lab hec-test`. Pedirá el token de forma oculta o
lo tomará de `SPLUNK_HEC_TOKEN`, enviará un evento y mostrará su `event_id` para
buscarlo en Splunk. No crea recursos ni llama al LLM. Si aún no has configurado
AWS, puedes exportar solo `SPLUNK_HEC_URL` con la URL base y ejecutar la prueba.

Una respuesta HEC exitosa confirma aceptación, no indexación: verifica el evento
en Search & Reporting. Después utiliza `./lab up` y `./lab run` normalmente.
El token se guarda en Secrets Manager y ECS lo inyecta al contenedor al arrancar.
No se automatiza la creación del token ni se requiere el API administrativo 8089.

El cliente conserva la validación TLS, rechaza redirecciones y reintenta hasta
tres veces errores de red, HTTP 429 y errores HTTP de servidor. Los reintentos
conservan `event_id`; usa `dedup event_id` si aparecen duplicados. Un fallo de
entrega genera `envio_splunk_fallido` en CloudWatch y la simulación continúa.
No hay una cola persistente ni reproducción automática de eventos pendientes.
El envío es síncrono y añade latencia; los tiempos medidos incluyen esa latencia.

### Modo Firehose, para una instancia que lo tenga habilitado

Con `"splunk_delivery_mode": "firehose"`, prepara un token HEC **con ACK** y
confirma con Splunk que la instancia acepta Amazon Data Firehose. En Splunk
Cloud puede requerir habilitación por soporte. No presupongas que un trial tiene
esa integración disponible. El endpoint debe tener un certificado válido y ser
accesible desde Firehose.

`./lab up` creará el secreto HEC, Firehose, el bucket de respaldo, sus roles y
una suscripción de CloudWatch. El contenedor no enviará directamente a HEC en
este modo. No uses `hec-test` con un token que requiere ACK; esa prueba utiliza
HEC estándar.

La suscripción selecciona solo eventos JSON con `run_id` y `evento`. Firehose
descomprime el envoltorio de CloudWatch y extrae los mensajes para enviarlos al
endpoint HEC Raw. Respalda todos los eventos en S3 y registra errores de entrega
en `/lab/<nombre>/firehose`. El buffer está configurado en 60 segundos, por lo
que la llegada a Splunk no es instantánea; los reintentos pueden aumentarla.

### Consultas de comprobación para ambos modos

Valida la llegada después de `./lab run`:

```spl
index=agentes_lab
| spath
| stats count by run_id evento herramienta
```

Para contar también eventos sin herramienta:

```spl
index=agentes_lab
| spath
| stats count by run_id evento
```

Dejar el endpoint vacío mantiene CloudWatch y omite todos los recursos de
integración con Splunk. Cambiar desde Firehose a HEC directo o desactivar Splunk
mediante `up` elimina el bucket de respaldo de Firehose si existía. El modo
directo conserva la copia de CloudWatch durante la retención de 7 días.

## Eliminación y estado

**`./lab down` ejecuta la eliminación sin otra confirmación.** Detiene las tareas
del clúster y borra imágenes ECR, logs CloudWatch, secretos sin período de
recuperación, red y, si está habilitado, Firehose y el bucket con sus objetos.
Exporta la evidencia que quieras conservar antes de ejecutarlo; los eventos
pendientes de entrega pueden perderse al eliminar la infraestructura.
No se elimina la instancia de Splunk ni lo que ya haya indexado.

No cambies cuenta, región o nombre antes de destruir el despliegue original.
El estado se guarda localmente en `infra/terraform.tfstate`, excluido de Git.
Conserva ese archivo y su respaldo hasta terminar la eliminación. El archivo
`.terraform.lock.hcl` sí se versiona. El lanzador no elimina archivos de estado
ni imágenes locales de Docker.

Las claves se pasan como variables `ephemeral` a argumentos `secret_string_wo`.
Terraform no guarda sus valores en el estado ni en planes. Firehose o ECS
reciben una referencia al secreto HEC, según el modo, y ECS recibe una referencia
al secreto de Anthropic.
`down` no requiere ninguna de esas claves; sí requiere autenticación AWS.
Para un equipo que opere desde varias máquinas, cambia a un backend remoto
con cifrado y bloqueo antes de compartir la administración.

## Validación

```bash
./lab validate
python3 -m unittest discover -s tests -v
```

`validate` descarga el proveedor fijado en el lockfile, comprueba la configuración
y ejecuta `terraform test` con un proveedor AWS simulado. No utiliza credenciales
AWS ni crea recursos. Las pruebas Python verifican el manejo de cuentas, secretos,
fallos de ejecución y orden de detención/borrado.

Se ha validado localmente la configuración y el ciclo de vida con simulaciones.
El despliegue real, la construcción Docker y la entrega a tu HEC requieren tus
herramientas y cuenta; deben verificarse con la primera ejecución del laboratorio.

Referencias:

- [Diferencias del trial de Splunk Cloud](https://help.splunk.com/en/splunk-cloud-platform/administer/admin-manual/10.3.2512/get-started-managing-splunk-cloud-platform/splunk-cloud-platform-deployment-types)
- [HEC en Splunk Cloud y requisitos de Firehose](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/10.2/get-data-with-http-event-collector/set-up-and-use-http-event-collector-in-splunk-web)
- [Tareas independientes de ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/standalone-tasks.html)
- [Secretos que Terraform no guarda en el estado](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
- [Formato del secreto HEC para Firehose](https://docs.aws.amazon.com/firehose/latest/dev/secrets-manager-whats-secret.html)
- [CloudWatch Logs hacia Firehose](https://docs.aws.amazon.com/firehose/latest/dev/writing-with-cloudwatch-logs.html)
