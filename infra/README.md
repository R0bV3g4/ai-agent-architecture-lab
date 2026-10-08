# Infraestructura efímera en AWS

Para AWS + Datadog sigue [la guía actual](../datadog/README.md).
Datadog usa HTTPS directo desde Fargate,
con la API key en Secrets Manager y sin sidecar ni Forwarder Lambda.

Desde la raíz del proyecto:

```bash
./lab up       # Construye la imagen, crea AWS y publica en ECR.
./lab run      # Ejecuta los cuatro agentes una vez y espera su resultado.
./lab logs     # Sigue los registros de CloudWatch.
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
y CloudWatch. `run` requiere `ecs:RunTask` e
`iam:PassRole` para los roles de la tarea; `down` necesita los permisos de borrado
y detención. La plantilla no modifica el perfil del operador.

Ejecuta `./lab up`. Solicitará `ANTHROPIC_API_KEY` con entrada oculta; también
puedes proporcionarla como variable de entorno. No la escribas en el JSON ni
en Terraform. Con Datadog habilitado, solicitará además `DD_API_KEY`.

La primera configuración queda así:

```json
{
  "aws_account_id": "123456789012",
  "aws_region": "us-east-1",
  "project_name": "crewai-lab",
  "private_network": true,
  "anthropic_model": "claude-sonnet-4-6",
  "observability_provider": "datadog",
  "datadog_site": "datadoghq.com"
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
y no tiene reglas de entrada en su security group. La salida permite HTTPS en 443.
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

Los eventos se conservan en CloudWatch durante la retención de 7 días.

## Eliminación y estado

**`./lab down` ejecuta la eliminación sin otra confirmación.** Detiene las tareas
del clúster y borra imágenes ECR, logs CloudWatch, secretos sin período de
recuperación y la red.
Exporta la evidencia que quieras conservar antes de ejecutarlo; los eventos
pendientes de entrega pueden perderse al eliminar la infraestructura.
No se elimina lo ya enviado a Datadog.

No cambies cuenta, región o nombre antes de destruir el despliegue original.
El estado se guarda localmente en `infra/terraform.tfstate`, excluido de Git.
Conserva ese archivo y su respaldo hasta terminar la eliminación. El archivo
`.terraform.lock.hcl` sí se versiona. El lanzador no elimina archivos de estado
ni imágenes locales de Docker.

Las claves se pasan como variables `ephemeral` a argumentos `secret_string_wo`.
Terraform no guarda sus valores en el estado ni en planes. ECS recibe referencias
a los secretos de Anthropic y Datadog.
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
El despliegue real y la construcción Docker requieren tus
herramientas y cuenta; deben verificarse con la primera ejecución del laboratorio.

Referencias:

- [Tareas independientes de ECS](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/standalone-tasks.html)
- [Secretos que Terraform no guarda en el estado](https://developer.hashicorp.com/terraform/language/manage-sensitive-data)
