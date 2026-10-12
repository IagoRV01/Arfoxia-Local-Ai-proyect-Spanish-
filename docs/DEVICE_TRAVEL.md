# Paseo entre dispositivos

Arfoxia puede mostrarse en un cliente Linux mientras la IA, herramientas,
conversaciones y memoria continúan en el PC Windows. No se copia un modelo ni
se ejecutan comandos del PC desde el cliente. Este modo se controla con
**Paseo entre dispositivos…** en el menú de la mascota o el icono de la bandeja.
**Volver a este PC** funciona aunque la mascota esté oculta.

## Linux / Bazzite KDE Wayland

- Cliente GTK3/PyGObject/Pillow, mismos sprites PMD, ocho direcciones,
  expresiones, arrastre, clic para acariciar y menú contextual de interacciones.
- Superposición nativa `gtk-layer-shell` en capa OVERLAY, sin capturar teclado
  ni bloquear con una ventana rectangular todo el escritorio. X11 usa una
  ventana transparente siempre encima. El instalador suministrado está
  configurado para KDE Wayland; GNOME Wayland y Gamescope en modo juego no se
  dan por compatibles sin una implementación y prueba adicionales.
- Necesita una sesión gráfica abierta. No puede aparecer en un monitor
  apagado, en el login, ni garantizar superposición sobre una pantalla bloqueada.
- Solo el recuadro de la mascota recibe clics. Es posible arrastrarla; el resto
  de la superficie deja pasar la entrada. Los juegos y el compositor pueden
  limitar una superposición: no se promete compatibilidad con todos los títulos.
- Arrastre en coordenadas lógicas sobre una superficie fija: la ventana no
  cambia sus márgenes durante el gesto. No se usa `x_root` de Wayland. Los
  cambios de animación se pausan mientras se arrastra y no se confunde un
  arrastre de ida y vuelta con un clic. Posición/anclas de pies estables.
- Menú: acariciar, baya, limón, cama, dormir/despertar, sentarse/reanudar,
  ocho expresiones disponibles, sonido, estado, captura local y regreso.
  Cama y limón se arrastran por separado; posiciones y sonido se guardan solo
  en `display.json` privado del cliente. Los recursos originales se reutilizan.
  Al jugar o soltar el limón, Arfoxia va a buscarlo y lo trae al punto de partida
  si está despierto y no está sentado; arrastrar la mascota cancela ese paseo.
  Capturas en `~/Pictures/Arfoxia/` mediante Spectacle; audio con `pw-play`.
  Chat, GPU, emparejamiento móvil y seguridad del dueño siguen en Windows/Expo;
  no se añaden botones ficticios ni se amplían los permisos del cliente.
- Windows abre un túnel inverso OpenSSH: `127.0.0.1:18842` del cliente se conecta
  al puerto local de la API Windows. Solo autenticación por clave ya configurada,
  validación estricta de known_hosts, sin contraseñas embebidas ni puertos LAN.
- Los túneles propios se identifican por PID, fecha de creación y argumentos
  exactos. Se pueden adoptar tras un cierre forzado de la interfaz; no se
  buscan ni terminan sesiones SSH ajenas. Al salir normalmente se cierran.
- La clave de cliente es independiente y solo autoriza estado reducido,
  heartbeat, regreso y siete interacciones Tamagotchi. No autoriza chats,
  archivos, registro de dispositivos ni herramientas del PC. En Windows se
  protege con DPAPI; en Linux `client.json` es privado (0600, carpeta 0700).

## Instalación

1. Configurar manualmente un alias OpenSSH, aceptar su huella tras verificarla
   y comprobar autenticación por clave. El código no inventa usuarios/hosts.
2. Copiar `scripts/traveler_linux.py`, `scripts/traveler_geometry.py` y
   `scripts/install_traveler_linux.py` a
   `~/.local/share/arfoxia-traveler/`; los módulos `sprites.py` y `pet_motion.py`
   del paquete a `lib/`; el contenido de la variante PMD utilizada a `sprites/`.
   Respetar la licencia/atribución de los recursos del proyecto original.
   Opcional: `assets/external/props/{bed,lemon}.png` y su atribución a `props/`,
   y `assets/external/pokeapi/cries/glaceon-latest.ogg` a `sounds/cry.ogg`.
3. Instalar GTK3, PyGObject, Cairo, Pillow y gtk-layer-shell por el mecanismo
   adecuado de la distribución. En Bazzite se puede descargar un RPM de Fedora,
   verificar su firma y extraer biblioteca/tipado a `deps/`, sin capas del SO,
   sudo ni reinicio. No extraer un RPM no verificado.
4. Con la API del dueño autenticada: POST `/api/travel/register` con `device_id`,
   `label`, `ssh_alias`. Enviar el `client_token` devuelto **por stdin de SSH**
   al instalador, como JSON con `token` y `url: http://127.0.0.1:18842`. Nunca
   ponerlo en argv, logs, capturas o Git. Registrar de nuevo rota el permiso.
5. El instalador crea un servicio systemd del usuario, ligado a la sesión
   gráfica. Está oculto hasta que Windows abre el túnel y solicita el viaje.

## Llegada, regreso y cortes

El PC conserva la mascota visible mientras el cliente confirma que puede
dibujar un frame. El heartbeat del cliente tarda normalmente dos segundos.
Al confirmar, Windows oculta su mascota y pausa su movimiento local, pero
deja abiertos los chats y el modelo. No se duermen ni se reinician las GPU.
La preparación puede mostrarla brevemente en ambos dispositivos durante el
traspaso; no es sincronización de vídeo instantánea.
Al regresar el cliente queda oculto y su servicio sigue disponible para viajes
posteriores; no se apaga la IA del dueño desde el menú del cliente.

El cliente se oculta ante un fallo de red o al caducar su ventana de cinco
segundos. Windows recupera la mascota después de ocho segundos sin confirmación;
una solicitud que no logra llegar caduca a los veinte segundos. Un heartbeat
atrasado nunca puede ordenar un nuevo viaje por sí solo. Un reinicio del PC
restaura la presencia local. No se viaja automáticamente ni se cambia de
dispositivo sin pulsar el control. Derecha en Linux → **Volver al PC**.

## PS4 con GoldHEN: cliente nativo en investigación

FTP no ejecuta un cliente gráfico. El repositorio oficial de plugins GoldHEN
documenta carga en juegos por TitleID; eso no garantiza un plugin universal
para todos los juegos y el shell. Un hook genérico de VideoOut puede colisionar
con el propio overlay de GoldHEN. No se instala un renderizador especulativo, no se
modifica `plugins.ini`, juegos, kernel ni firmware.

- [Plugins oficiales y carga por título](https://github.com/GoldHEN/GoldHEN_Plugins_Repository)
- [SDK de hooks PRX](https://github.com/GoldHEN/GoldHEN_Plugins_SDK)
- [Conflicto documentado con VideoOut / Game Overlay](https://github.com/GoldHEN/GoldHEN/issues/130)
- [Capa Wayland compatible con KDE](https://github.com/wmww/gtk-layer-shell)

La superposición PS4 en todos los juegos **y** menú del sistema queda pendiente
de desarrollar y verificar el renderizador específico y su ejecución real.
No se sustituye silenciosamente por una página del navegador ni se registra
la PS4 como destino operativo si no existe ese cliente.

### Prueba limitada al menú del SO (12.52 / GoldHEN 2.4b18.7)

La comprobación del 12-10-2026 confirma FTP GoldHEN v2.2 y disponibilidad inicial
de BinLoader. La investigación continúa con una sonda PRX propia de metadata
Mono/PUI y un cargador limitado a `SceShellUI`: ambos compilados con SDKs
públicos en un contenedor aislado del cliente Bazzite. El PRX se ha subido a
la carpeta propia y verificado byte a byte, sin modificar plugins existentes.
Tras reactivar BinLoader, GoldHEN confirmó recepción y lanzamiento del cargador.
Se detectó un fallo en `initKernel` debido al enlace ET_EXEC del SDK: una
referencia interna se convirtió en una dirección absoluta. No llegó a solicitar
la carga del PRX. Corregido con enlace PIE y empaquetador que verifica el ELF,
rechaza relocaciones/dependencias y materializa la BSS. Ajustada la entrada al
SDK oficial y comprobado `RAW 256 CARRY 1`: se acepta solo la firma exacta de
versión 1.00, sin aceptar errores arbitrarios. La sonda llegó a `SceShellUI`,
confirmó firmware `12520001` y recogió nombres de ensamblados.

La enumeración no terminó: el registro muestra un fallo de Mono y el dueño
confirmó **CE-36329-3**. Causa concreta de la llamada de metadata aún sin demostrar.
Se han detenido las pruebas y bloqueado cargas/staging antes de conectar a la
consola; los puntos de entrada nativos también están deshabilitados. Solo se
conservan compilación offline y consulta acotada de estado. No se cambian plugins,
firmware, juegos ni datos del usuario para intentar solventarlo. No hubo prueba
gráfica: la sonda no es una mascota y no se considera cliente funcional.
El archivo exacto que falló se conservó mediante renombrado recuperable a
`arfoxia_probe.failed.disabled`; los cargadores antiguos ya no encuentran su
ruta PRX original. Logs y respaldos propios conservados.
No se instala Orbis-Toolbox antiguo ni se registra la PS4 como destino operativo.
Detalles, límites, compilación y comandos explícitos en
[ports/ps4/README.md](../ports/ps4/README.md).
