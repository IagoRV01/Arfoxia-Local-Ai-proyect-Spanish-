# Modelo de seguridad

## Límites

- La API escucha en localhost por defecto.
- El acceso remoto se publica con Tailscale Serve sobre HTTPS y solo dentro del tailnet.
- Cada llamada privada necesita un token Bearer aleatorio de 256 bits.
- `secrets.json` y `authorization.json` se endurecen con una ACL de archivo para el usuario actual, SYSTEM y administradores.
- El token móvil viaja en el fragmento `#token=`, que el navegador no envía al servidor, y después se guarda en el almacenamiento local del iPhone.
- No hay puertos del router, Funnel ni servidor intermediario público.

## Herramientas

`ActionDispatcher` acepta únicamente nombres y argumentos tipados. `open_app` ejecuta una ruta exacta de configuración y `close_app` solo termina nombres exactos de proceso asociados. `open_target` permite HTTPS de forma inmediata; un ejecutable instalado, una ruta ejecutable o un protocolo de Windows requieren antes una autorización local. Todos se abren con una lista de argumentos exacta u `os.startfile`, nunca con `shell=True`.

Los enlaces HTTPS escritos literalmente por Gori se entregan al navegador predeterminado de Windows. Se rechazan credenciales embebidas, puertos malformados, espacios, barras invertidas y escapes `%` inválidos; las rutas de vídeo conocidas de YouTube también deben contener un identificador con sintaxis válida. Los destinos sugeridos por el modelo solo pueden abrirse si coinciden exactamente con una fuente comprobada durante ese turno. `os.startfile` confirma únicamente que Windows aceptó la solicitud: no permite comprobar que la página terminó de cargar ni imponer si el navegador reutiliza una pestaña o crea otra.

Cerrar aplicaciones, bloquear Windows, apagar/reiniciar, pausar Codex y cualquier modificación de archivos requieren una contraseña introducida exclusivamente en un diálogo enmascarado del PC. El servicio valida primero los argumentos y después crea un identificador aleatorio ligado a una copia profunda de la acción y sus argumentos; caduca a los 90 segundos y se consume antes de ejecutar. Un booleano `confirmed=true` procedente de la API se rechaza y no concede permisos. Las peticiones remotas quedan como botón pendiente —no abren solas el campo— y se limitan a tres por minuto.

El verificador usa scrypt con sal aleatoria y comparación constante. La contraseña nunca se guarda en claro, pasa a Ollama, forma parte de argumentos, se publica en eventos ni se registra en SQLite. Cinco fallos dentro de la ventana aplican 60 segundos de bloqueo. Cambiar la contraseña exige la anterior e invalida desafíos pendientes.

`file_operation` limita el contenido UTF-8 a 1 MiB y ofrece solo crear carpeta, escribir, añadir, copiar, mover, renombrar y enviar a la Papelera. Las escrituras son atómicas, no sobrescriben por defecto y vinculan la versión existente mediante SHA-256 para detectar cambios entre autorización y ejecución. Se rechazan raíces amplias, rutas relativas, dispositivos, flujos alternativos, inicio automático y los archivos internos/código de Arfoxia. No existen lectura arbitraria, shell, PowerShell, CMD, ejecución con argumentos arbitrarios, elevación, instalación, descarga automática, cambios de firewall/antivirus ni borrado permanente.

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

- Cualquiera que obtenga el token puede usar las herramientas permitidas mientras tenga acceso de red al servicio.
- El token remoto no basta para operaciones sensibles: estas necesitan interacción en el PC. Un proceso malicioso que ya ejecute código como el mismo usuario de Windows queda fuera de este límite y podría modificar el programa o capturar teclas.
- Una contraseña corta continúa siendo susceptible a ataque offline si alguien roba el verificador. No reutilices una clave que hayas escrito en una conversación; cámbiala desde el menú local.
- Una captura puede contener información sensible visible en pantalla.
- Terminar un proceso puede perder cambios sin guardar; por eso necesita confirmación.
- Una fuente accesible todavía puede contener información falsa, cambiar después de la comprobación o estar restringida en otra región; Arfoxia muestra las fuentes para poder evaluarlas.
- El protocolo de Codex lee metadatos locales para resolver las tareas, pero la API de Arfoxia solo devuelve título y estado. Quien obtenga el token podría solicitar ese listado reducido.
- Codex no publica una API externa para ordenar animaciones a Eevee. Las interacciones directas se representan desde Arfoxia; Eevee conserva únicamente sus reacciones naturales gestionadas por Codex.
- Los sprites no tienen una licencia comercial uniforme. No distribuyas la carpeta `assets/external` sin revisar cada fuente.
