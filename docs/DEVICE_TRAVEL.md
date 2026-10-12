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
2. Copiar `scripts/traveler_linux.py`, `scripts/install_traveler_linux.py` a
   `~/.local/share/arfoxia-traveler/`; los módulos `sprites.py` y `pet_motion.py`
   del paquete a `lib/`; el contenido de la variante PMD utilizada a `sprites/`.
   Respetar la licencia/atribución de los recursos del proyecto original.
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

El cliente se oculta ante un fallo de red o al caducar su ventana de cinco
segundos. Windows recupera la mascota después de ocho segundos sin confirmación;
una solicitud que no logra llegar caduca a los veinte segundos. Un heartbeat
atrasado nunca puede ordenar un nuevo viaje por sí solo. Un reinicio del PC
restaura la presencia local. No se viaja automáticamente ni se cambia de
dispositivo sin pulsar el control. Derecha en Linux → **Volver al PC**.

## PS4 con GoldHEN: no implementado como overlay global

FTP no ejecuta un cliente gráfico. El repositorio oficial de plugins GoldHEN
documenta carga en juegos por TitleID; eso no garantiza un plugin universal
para todos los juegos y el shell. Un hook genérico de VideoOut puede colisionar
con el propio overlay de GoldHEN. No se instala un PRX especulativo, no se
modifica `plugins.ini`, juegos, kernel ni firmware.

- [Plugins oficiales y carga por título](https://github.com/GoldHEN/GoldHEN_Plugins_Repository)
- [SDK de hooks PRX](https://github.com/GoldHEN/GoldHEN_Plugins_SDK)
- [Conflicto documentado con VideoOut / Game Overlay](https://github.com/GoldHEN/GoldHEN/issues/130)
- [Capa Wayland compatible con KDE](https://github.com/wmww/gtk-layer-shell)

La superposición PS4 en todos los juegos **y** menú del sistema queda pendiente
de desarrollo específico, acceso a SDK/firmware compatibles y pruebas reales.
No se sustituye silenciosamente por una página del navegador ni se registra
la PS4 como destino operativo si no existe ese cliente.
