# Visualizador de proyectos en Expo Go

La pestaña **Visor** lista los resultados existentes dentro de
`workspace_directory` (por defecto `<usuario>\Arfoxia`). Cada subcarpeta es un
proyecto. Se prefiere su `index.html`; los demás HTML, imágenes, PDF y archivos
de texto/código se ofrecen como vistas adicionales. La lista se actualiza al
entrar, al volver a la app y cada 15 segundos mientras la pestaña está abierta.

El chat muestra **Ver resultado** cuando una respuesta contiene herramientas
correctas relacionadas con archivos que existen. También descubre resultados
de respuestas antiguas al leer el historial, sin volver a ejecutar comandos ni
reescribir el archivo de mensajes. En tareas con Python/PowerShell se pueden
descubrir proyectos modificados desde el inicio de la tarea. No se crean chats
adicionales para mostrar un resultado.

## Uso

1. En Expo Go abre Arfoxia y recarga el proyecto para recibir esta versión.
2. Abre **Visor → Ver resultado**, o el botón de resultado dentro del chat.
3. El HTML y las escenas WebGL/Three.js se ejecutan dentro de una WebView nativa.
   Puedes interactuar con los controles propios del proyecto. Las imágenes,
   PDF (visor de iOS) y el código tienen vista de lectura.
4. **Recargar** solicita una nueva vista y lee los archivos actuales del PC.
   **Cerrar** vuelve al chat o a la lista, sin detener el trabajo de Arfoxia.

La ventana del visor tiene su propio proveedor nativo de área segura, que
se mide cada vez que se abre. Título y botones quedan debajo de la barra de
estado/notch; el contenido termina antes del indicador de inicio y respeta
los laterales. Título y acciones usan filas independientes. La WebView no
duplica esos márgenes con ajustes automáticos. El mismo patrón protege las
ventanas de chats, imágenes y Moonlight, siguiendo la
[documentación de SafeAreaProvider](https://appandflow.github.io/react-native-safe-area-context/api/safe-area-provider/).

Arfoxia recibe instrucciones para entregar los proyectos visuales con un
`index.html` y recursos en la misma subcarpeta, usando rutas relativas. No debe
enviar una dirección `localhost` del PC al iPhone ni inventar enlaces internos.
Las bibliotecas HTTPS de `unpkg.com`, `cdn.jsdelivr.net` y
`cdnjs.cloudflare.com` están permitidas y necesitan conexión a Internet.

Un HTML puede existir y, aun así, fallar al ejecutarse. El visualizador muestra
los errores JavaScript y fallos de carga en un aviso **Error del proyecto**,
añadido solo a la respuesta HTTP, sin modificar los archivos. Arfoxia no debe
presentar una lectura de código como una comprobación visual del iPhone.
Los errores del servidor, de conexión y las vistas caducadas tienen avisos
nativos; una página puede requerir adaptaciones específicas de WebKit/WebGL.

## Alcance y privacidad

- El catálogo y la creación de vistas requieren la autenticación de Arfoxia.
  El HTML nunca recibe la clave principal: usa un permiso aleatorio temporal,
  solo de lectura, limitado a la carpeta de su archivo de entrada y sus recursos.
  Los archivos directos en la carpeta base comparten esa carpeta; se recomienda
  una subcarpeta por proyecto para mantener las vistas independientes.
- Cada permiso dura 30 minutos y desaparece al reiniciar Arfoxia o cambiar la
  carpeta de trabajo. Máximo 128 permisos activos; **Recargar** crea otro.
  No compartas una URL temporal: quien la obtenga y tenga acceso a tu Tailscale
  puede leer los recursos permitidos durante ese plazo.
- Solo se sirven formatos conocidos y archivos de hasta 50 MiB; la vista de
  texto admite hasta 2 MiB. El catálogo recorre hasta 5.000 archivos y presenta
  hasta 200 proyectos / 100 entradas por proyecto. La lista móvil muestra hasta
  24 vistas adicionales por tarjeta.
- Se rechazan escapes de carpeta, rutas de dispositivo, archivos ocultos,
  configuraciones privadas conocidas, enlaces simbólicos, uniones, enlaces
  duros y directorios generados como `.git`, `.venv` y `node_modules`.
- CSP con origen aislado, sin formularios, iframes, ventanas nuevas ni acceso a
  las herramientas del PC. WebView sin cookies compartidas, archivos locales,
  contenido HTTP mixto ni puente de mensajes a operaciones nativas. La
  navegación permanece dentro del permiso; no se abren enlaces externos desde
  una página generada. No se envía el permiso como referrer a un CDN.
- No es un intérprete de aplicaciones Windows ni un servidor de desarrollo:
  Python, ejecutables y proyectos que necesitan un backend propio no se ejecutan
  en el iPhone. Sus archivos admitidos se muestran como texto; para obtener una
  vista interactiva hay que entregar un HTML compatible.
- El PC debe permanecer encendido, Arfoxia iniciado y Tailscale conectado.
  Esta función no abre puertos públicos ni activa Tailscale Funnel.

## Validación de esta entrega

- Pruebas Python de catálogo, permisos, expiración, rutas, activos, aislamiento,
  errores HTML, archivos privados, historial antiguo y nuevos resultados.
- Pruebas TypeScript de URL sin clave principal, navegación restringida,
  metadatos de historial y descriptores; comprobación de tipos y bundle iOS.
- Prueba real con el modelo Dual: `read_file` correcto, tarea completada en el
  mismo chat y resultado asociado automáticamente.
- Navegador real por HTTPS privado: escena Three.js del pueblo costero, tamaño
  móvil, pausa y día/noche, importación de módulo/CSS locales y error controlado
  visible. Esto no sustituye una prueba presencial en el iPhone.
- WebView 14.0.1, alineado con Expo Go SDK 58 (migración del 2026-10-23).
  Comprobaciones de tipos, navegación privada, modales/áreas seguras y bundle iOS
  correctas. La auditoría npm conserva cuatro avisos altos en la cadena de firma
  de la CLI de Expo, ninguno en `react-native-webview`; no se aplicó
  `audit fix --force` ni se amplió la navegación permitida del visualizador.
