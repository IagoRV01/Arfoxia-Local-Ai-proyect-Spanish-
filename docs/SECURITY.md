# Modelo de seguridad

## Límites

- La API escucha en localhost por defecto.
- El acceso remoto se publica con Tailscale Serve sobre HTTPS y solo dentro del tailnet.
- Cada llamada privada necesita un token Bearer aleatorio de 256 bits.
- `secrets.json` y `authorization.json` se endurecen con una ACL de archivo para el usuario actual, SYSTEM y administradores.
- El token móvil viaja en el fragmento `#token=`, que el navegador no envía al servidor, y después se guarda en el almacenamiento local del iPhone.
- No hay puertos del router, Funnel ni servidor intermediario público.

## Herramientas

### Control privado sin contraseña (opcional, desde 0.14)

La configuración local permite `require_action_password: false` y
`pc_command_enabled: true`. El propietario ha elegido este perfil en su PC.
**El repositorio mantiene por defecto contraseña obligatoria y PowerShell
desactivado**. No existe un endpoint para cambiar estas opciones. Para revertir
el perfil, usa `true` y `false`, respectivamente, en el `config.json` del directorio
de datos local y reinicia Arfoxia. El verificador de contraseña no se borra.

Sin contraseña, las acciones siguen validando argumentos pero no crean desafíos;
PC y móvil autenticado usan la misma política. `run_powershell` ofrece ejecución
general con los permisos del proceso: consultar/editar archivos, programar,
ejecutar scripts y gestionar programas. Cada ejecución tiene un máximo de 120
segundos y 24000 bytes de salida capturada; se interrumpe su árbol al agotar el
plazo y se redacta el script del registro de auditoría. La salida sí se entrega
al modelo/chat; no deben solicitarse secretos.

**Este perfil amplía mucho la confianza**: quien posea el token y acceso al
tailnet puede ejecutar comandos sin interacción local. Un error del modelo
puede afectar archivos/programas. Las instrucciones contra inyección desde
webs/adjuntos no garantizan inmunidad; las restricciones de la herramienta tipada
de archivos no son un sandbox para PowerShell. Protege el token, el móvil y tus
copias de seguridad; no publiques el servicio.

### Administrador de Windows (opcional)

`run_as_administrator: true` solicita ejecución elevada del proceso completo.
El instalador `scripts/install_admin.ps1`, ejecutado mediante el aviso normal de
UAC, registra **Arfoxia Companion (Administrador)**: tarea interactiva del usuario
actual, al iniciar sesión, con nivel `Highest` y sin contraseña guardada.
Solo retira la entrada antigua de inicio de Arfoxia si coincide exactamente.
El lanzador reutiliza esa tarea si su ejecutable/argumentos corresponden al
proyecto; en caso contrario solicita UAC. Cancelarlo no inicia una falsa sesión
de administrador. No se desactiva UAC, Defender ni el firewall.

Las herramientas y procesos hijos heredan la elevación: combinada con el modo
sin contraseña, el móvil emparejado dispone de ejecución administrativa. La API
sigue en loopback/Tailscale con Bearer; este es un perfil de alta confianza.
Windows mantiene restricciones adicionales como TrustedInstaller y procesos
protegidos: «administrador» no significa acceso ilimitado a todo.

Para revertirlo, cambia `run_as_administrator` a `false`, ejecuta el instalador
elevado con `-Disable` y reinicia Arfoxia. Esto elimina solo su tarea y restaura
su inicio normal por usuario. No cambia ninguna cuenta ni pertenencia a grupos.

### Política predeterminada con contraseña

`ActionDispatcher` acepta únicamente nombres y argumentos tipados. `open_app` ejecuta una ruta exacta de configuración y `close_app` solo termina nombres exactos de proceso asociados. `open_target` permite HTTPS de forma inmediata; un ejecutable instalado, una ruta ejecutable o un protocolo de Windows requieren antes una autorización local. Todos se abren con una lista de argumentos exacta u `os.startfile`, nunca con `shell=True`.

Los enlaces HTTPS escritos literalmente por Gori se entregan al navegador predeterminado de Windows. Se rechazan credenciales embebidas, puertos malformados, espacios, barras invertidas y escapes `%` inválidos; las rutas de vídeo conocidas de YouTube también deben contener un identificador con sintaxis válida. Los destinos sugeridos por el modelo solo pueden abrirse si coinciden exactamente con una fuente comprobada durante ese turno. `os.startfile` confirma únicamente que Windows aceptó la solicitud: no permite comprobar que la página terminó de cargar ni imponer si el navegador reutiliza una pestaña o crea otra.

Cerrar aplicaciones, bloquear Windows, apagar/reiniciar, pausar Codex y cualquier modificación de archivos requieren una contraseña introducida exclusivamente en un diálogo enmascarado del PC. El servicio valida primero los argumentos y después crea un identificador aleatorio ligado a una copia profunda de la acción y sus argumentos; caduca a los 90 segundos y se consume antes de ejecutar. Un booleano `confirmed=true` procedente de la API se rechaza y no concede permisos. Las peticiones remotas quedan como botón pendiente —no abren solas el campo— y se limitan a tres por minuto.

El verificador usa scrypt con sal aleatoria y comparación constante. La contraseña nunca se guarda en claro, pasa a Ollama, forma parte de argumentos, se publica en eventos ni se registra en SQLite. Cinco fallos dentro de la ventana aplican 60 segundos de bloqueo. Cambiar la contraseña exige la anterior e invalida desafíos pendientes.

`file_operation` limita el contenido UTF-8 a 1 MiB y ofrece solo crear carpeta, escribir, añadir, copiar, mover, renombrar y enviar a la Papelera. Las escrituras son atómicas, no sobrescriben por defecto y vinculan la versión existente mediante SHA-256 para detectar cambios entre autorización y ejecución. Se rechazan raíces amplias, rutas relativas, dispositivos, flujos alternativos, inicio automático y los archivos internos/código de Arfoxia. PowerShell general y el inicio elevado están desactivados por defecto y se rigen por las opciones locales descritas arriba.

## Streaming de juegos

- Los endpoints de juego requieren el mismo Bearer aleatorio que el resto de la
  API privada y solo permiten consultar estado, iniciar el servicio exacto de
  Sunshine o enviar un PIN ASCII de cuatro cifras.
- No se expone un proxy genérico a la API administrativa de Sunshine ni se
  añade esta capacidad a las herramientas que Ollama puede seleccionar.
- La contraseña aleatoria de Sunshine permanece cifrada con DPAPI para el
  usuario actual dentro de `secrets.json`, que conserva además la ACL local
  endurecida. Si la ACL no puede aplicarse, el guardado falla de forma cerrada.
  Nunca se incluye en configuración pública, respuestas, registros, QR ni
  solicitudes del móvil.
- La excepción al certificado autofirmado está limitada en código a
  `https://127.0.0.1:<puerto>` y no acepta un host configurable, DNS ni proxy del
  entorno. El panel web de Sunshine continúa limitado al propio PC.
- Cada cliente nuevo exige un challenge local de un solo uso y la contraseña se
  introduce solo en el PC. Los intentos de PIN se limitan además a cinco por
  minuto y el resultado no se marca como emparejado hasta que Sunshine devuelve
  un cliente habilitado en su API autenticada.
- Tailscale Serve publica la API de Arfoxia, no el vídeo. Moonlight accede
  directamente a los puertos de Sunshine mediante la IP privada o MagicDNS del
  PC; no se abre Funnel ni se configura UPnP.
- Las reglas entrantes de Windows se limitan a TCP `47984`, `47989`, `48010` y
  UDP `47998-48000`, con origen en la subred local o en `100.64.0.0/10`. El panel
  `47990` queda fuera de esas reglas y solo se usa por loopback en el PC.

El host de captura está fijado en este equipo a la pantalla física conectada a
la RTX 5060 Ti de 8 GB, dejando la tarjeta de 16 GB para IA. ViGEmBus proporciona
el mando virtual. La primera vinculación de Moonlight para iOS se realiza en la
misma LAN y, después, el certificado del host emparejado protege la conexión.

No se anuncia un falso encendido remoto: cuando el PC está apagado tampoco puede
atender su propia API. Tailscale necesita otro nodo siempre activo en la LAN para
emitir Wake-on-LAN; hasta que exista, la app muestra esa limitación y no ofrece
un botón que simule poder despertar el equipo.

## Interacciones de escritorio

La vista previa del limón y la colocación de la cama se implementan dentro de Qt, sin inyectar entrada en otras aplicaciones. La capa temporal solo observa movimiento y el clic que completa la acción, se cancela a los 30 segundos y libera cualquier captura de teclado al cerrarse. Los objetos animados siguen siendo transparentes a la entrada; la cama solo recibe el ratón dentro de su máscara visible para poder arrastrarla y nunca toma el foco del teclado.

La posición normalizada de la cama es el único dato nuevo que se persiste. No se guarda el recorrido del ratón ni la posición de cada lanzamiento. El botón remoto `play` conserva la reacción inmediata anterior y nunca activa una capa de captura en el PC.

## Información online

- Solo se permite búsqueda de texto con SafeSearch moderado y un máximo de cinco resultados.
- Las consultas se truncan a 240 caracteres y no se guardan completas en el registro de auditoría.
- Se descartan URLs HTTP, locales, privadas, con credenciales, malformadas o no disponibles en el momento de la consulta.
- Cada destino general se comprueba con la IP pública fijada, TLS con SNI, redirecciones revalidadas y peticiones HEAD/GET de cabeceras acotadas. No se descarga el cuerpo ni se ejecuta contenido.
- Los vídeos se validan contra oEmbed de YouTube y contra una lectura limitada del estado de reproducción de la página oficial; así se distingue la mera existencia de metadatos de la reproducción real desde el PC.
- El modelo recibe únicamente título, extracto y URL comprobada; cualquier otra URL escrita en su respuesta se elimina antes de guardarla o enviarla a los clientes.
- Todo resultado lleva una advertencia de contenido no confiable. Una página no puede conceder permisos ni cambiar las reglas de Arfoxia.

## Codex y Eevee

El puente JSONL usa `codex app-server` por `stdio`, sin puerto de red. Rechaza cualquier solicitud iniciada por el servidor y nunca autoaprueba permisos. Los títulos deben coincidir de forma única; una ambigüedad cancela la acción.

La pausa relee el hilo y solo llama a `turn/interrupt` cuando aparece exactamente un turno activo. No mata procesos, no envía teclas y no automatiza la interfaz de ChatGPT/Codex. Como Codex Desktop conserva el estado vivo en su propio proceso, el puente puede limitarse a abrir la tarea mediante el protocolo `codex://` para que el usuario pulse **Detener**.

La convivencia visual con Eevee es de solo lectura. Consulta el indicador del overlay en `.codex-global-state.json`, la mascota seleccionada y su ancho en `config.toml`, y el identificador del paquete local `pets/eevee/pet.json`. No lee conversaciones para este fin, no modifica ninguno de esos archivos, no inyecta IPC y no automatiza la interfaz. Si las señales no se pueden validar, Arfoxia simplemente se comporta como si Eevee no estuviera visible.

## Capturas

Se reducen a un máximo de 1600×1000, se guardan como WebP con un identificador aleatorio y se eliminan después del plazo configurado (24 horas por defecto). Solo se sirven tras autenticar el token.

## Riesgos restantes

- El modo Dual usa solo un servidor propio en loopback y no expone Ollama al
  móvil. Su reparto de VRAM es calibrado y vigilado, no una cuota dura de CUDA:
  pueden existir picos entre comprobaciones, especialmente si otra app reserva
  VRAM. Ante juego, exceso o pérdida de telemetría se avisa cada 20 segundos;
  el propietario debe liberar el modelo manualmente. Véase [Modo Dual](DUAL_GPU.md).
- Cualquiera que obtenga el token puede usar las herramientas permitidas mientras tenga acceso de red al servicio.
- Con la política predeterminada, el token remoto no basta para operaciones sensibles: necesitan interacción en el PC. En el perfil sin contraseña **sí basta**. Un proceso malicioso del mismo usuario queda fuera de este límite.
- Una contraseña corta continúa siendo susceptible a ataque offline si alguien roba el verificador. No reutilices una clave que hayas escrito en una conversación; cámbiala desde el menú local.
- Una captura puede contener información sensible visible en pantalla.
- Terminar un proceso puede perder cambios sin guardar; por eso necesita confirmación.
- Una fuente accesible todavía puede contener información falsa, cambiar después de la comprobación o estar restringida en otra región; Arfoxia muestra las fuentes para poder evaluarlas.
- El protocolo de Codex lee metadatos locales para resolver las tareas, pero la API de Arfoxia solo devuelve título y estado. Quien obtenga el token podría solicitar ese listado reducido.
- Codex no publica una API externa para ordenar animaciones a Eevee. Las interacciones directas se representan desde Arfoxia; Eevee conserva únicamente sus reacciones naturales gestionadas por Codex.
- Los sprites no tienen una licencia comercial uniforme. No distribuyas la carpeta `assets/external` sin revisar cada fuente.
- Quien obtenga el token también podría consultar el estado de Sunshine, iniciar
  su servicio o gastar los intentos limitados de PIN, aunque nunca recibe sus
  credenciales administrativas.
- Una ruta Tailscale indirecta mediante DERP puede añadir demasiada latencia para
  jugar; conviene verificar que PC e iPhone establecen una conexión directa.
- Expo SDK 57 conserva 11 avisos moderados de `npm audit` (sin altos ni críticos,
  comprobado el 2026-09-10), derivados de `uuid` a través de `xcode` y las
  herramientas de configuración/prebuild. No se fuerza la degradación a Expo
  46 que propone npm ni se procesan proyectos Xcode de terceros. Se revisará
  la corrección compatible cuando la publiquen estas dependencias.
- Expo Go 57 en iOS requiere una sesión de Expo en el PC y en el móvil. La CLI
  registra el servidor de desarrollo con Expo, pero la API y los chats siguen
  alojados en el PC y accesibles por Tailscale. Las credenciales de Expo son
  locales al usuario y no se incluyen en el repositorio.
