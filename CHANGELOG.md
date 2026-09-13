# Changelog

Todos los cambios relevantes de Arfoxia se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y las versiones del proyecto siguen versionado semántico.

## [Sin publicar]

## [0.13.0] - 2026-09-14

### Añadido

- Modo manual **Dual · Qwen3.8 27B** en el gestor de GPU de Windows y Expo Go,
  manteniendo los perfiles Normal, Potencia y Ligero existentes.
- Servidor Ollama privado en loopback (11436), separado de los modos anteriores,
  que usa ambas GPU por UUID con reparto de capas 86:14, Q4_K_M, contexto 32K,
  Flash Attention, caché KV Q8, razonamiento y residencia indefinida.
- Desactivadas la caché de prompts en RAM y las copias de contexto del servidor
  Dual, conservando el KV activo en GPU.
- Presupuesto máximo conservador de 16 GiB en la GPU de IA y 5,5 GiB en la de
  juego: incluye el consumo ajeno de Windows. Vigilancia durante carga y uso,
  cancelación ante exceso, falta de telemetría, juego activo u offload a CPU.
- Recuperación de procesos propios tras cierre inesperado, liberación manual
  y pruebas de regresión para selección, límites, autenticación y uso de ambas GPU.
- Prueba real reproducible `scripts/smoke_dual_gpu.py` para código, llamada de
  herramienta e imagen, sin escribir chats ni ejecutar las herramientas propuestas.

### Corregido

- La superposición de Epic Online Services ya no se confunde con un juego activo.
- Etiquetas del modelo Dual en chat y telemetría, adjuntos con el presupuesto
  del modelo grande y plazos de espera móviles adecuados para razonamiento local.

## [0.12.1] - 2026-09-10

### Corregido

- Compatibilidad con Expo Go SDK 57 en iPhone: migración desde SDK 54 a Expo
  57.0.21, React Native 0.86.3, React 19.2.3 y módulos nativos compatibles.
- Actualizado el estilo de la máscara del escáner QR y los tipos de desarrollo
  para las APIs actuales de React Native y TypeScript 6.
- Arranque automático de Metro sin `--offline` ni `EXPO_OFFLINE` heredado, para
  permitir el registro de la sesión exigida por Expo Go 57. Se mantiene el host
  privado de Tailscale y la supervisión de reinicios.
- Retiradas opciones nativas obsoletas y documentados el inicio de sesión con
  la misma cuenta en PC/iPhone y la reapertura si el proyecto no sale en recientes.
- Conservados identificador de app, claves de emparejamiento e historial local;
  actualizada la evaluación de dependencias en la documentación de seguridad.

## [0.12.0] - 2026-08-30

### Añadido

- Lanzador permanente **🎮 Jugar en mi PC** en Expo Go, con preparación de
  Sunshine, estado de Tailscale, host privado copiable y guía integrada para
  Moonlight.
- Emparejamiento desde Arfoxia mediante el PIN de cuatro cifras de Moonlight y
  acceso a la app con un Atajo de iOS o su ficha oficial como alternativa.
- Acceso directo a Moonlight también desde la pantalla offline de Arfoxia; un
  equipo ya emparejado se abre con el primer toque en **Jugar en mi PC**.
- Sunshine estable como servicio automático de Windows, captura de la pantalla
  conectada a la RTX 5060 Ti de 8 GB y ViGEmBus para el mando virtual.

### Cambiado

- Separado el plano de control HTTPS de Expo del streaming: la app de Arfoxia
  continúa por Tailscale Serve y Moonlight conecta directamente al host MagicDNS
  o a la IP privada del PC.
- Documentado el primer emparejamiento en la red local y la imposibilidad de
  despertar el PC desde fuera sin un segundo nodo siempre encendido en casa.
- Separados los estados de Sunshine local y conexión remota por Tailscale para
  no anunciar «Listo» cuando la red privada está desconectada; la app refresca
  el estado al volver desde Moonlight y usa áreas táctiles compactas de 44 pt.
- Actualizados los parches compatibles de Expo SDK 54 y sus dependencias no
  disruptivas; `expo-doctor` vuelve a superar todas sus comprobaciones.

### Seguridad

- Las credenciales aleatorias de Sunshine se guardan solo en el almacén local
  con la contraseña cifrada mediante DPAPI y ACL restringida; el guardado falla
  de forma cerrada si Windows no puede protegerlo. Nunca se envían a Expo,
  Ollama, registros ni Git.
- El puente solo puede iniciar el servicio exacto y llamar a la operación de PIN
  en el loopback literal; no expone una consola ni la API administrativa general
  de Sunshine y limita los intentos de emparejamiento a cinco por minuto.
- Cada cliente Moonlight nuevo necesita una autorización local, exacta y de un
  solo uso en el PC antes de que Arfoxia entregue el PIN a Sunshine.
- El panel web de Sunshine queda limitado al PC, sin Funnel ni UPnP, y el estado
  de emparejamiento solo refleja clientes realmente persistidos por Sunshine.
- Las reglas de firewall de Sunshine ya no aceptan cualquier puerto y origen:
  solo permiten sus puertos de streaming desde la LAN o la red privada de
  Tailscale; el panel administrativo no se publica.

## [0.11.4] - 2026-08-29

### Añadido

- Comprobación en vivo y con caché breve de los enlaces encontrados antes de
  entregarlos al modelo, al historial compartido o al navegador.
- Verificación específica de vídeos mediante oEmbed y el estado oficial de
  reproducción de YouTube, incluida la distinción entre un vídeo eliminado y
  uno válido que simplemente no permite incrustación.

### Cambiado

- Las peticiones explícitas como «pásame enlaces», «dame la fuente» o
  «recomiéndame vídeos» fuerzan una búsqueda actual y solicitan candidatos de
  reserva para sustituir resultados rotos.
- Los resultados de YouTube se deduplican por identificador real de vídeo y,
  si ninguno sigue disponible, Arfoxia abre la búsqueda canónica sin inventar
  un destino `watch`.

### Corregido

- Descartados enlaces con respuesta 404/410/451 y vídeos eliminados, privados,
  restringidos o no reproducibles antes de mostrarlos como fuentes válidas.
- Impedido que el modelo vuelva a insertar en Markdown o intente abrir una URL
  que no fue escrita por Gori ni verificada en la búsqueda del turno actual,
  incluso si disfraza el destino con escapes, entidades HTML o referencias.

### Seguridad

- Las comprobaciones web generales fijan una IP pública validada, conservan
  SNI y certificado TLS, revalidan cada redirección HTTPS y bloquean destinos
  locales, privados, credenciales, puertos alternativos y DNS mixto.
- Los sondeos usan límites estrictos de tiempo, concurrencia, redirecciones y
  cabeceras; no descargan cuerpos genéricos ni ejecutan contenido remoto.

## [0.11.3] - 2026-08-04

### Añadido

- Reloj local inmutable por turno en `Europe/Madrid`, con fecha, hora, ayer,
  mañana y límites de la semana disponibles para el modelo.
- Búsqueda específica de noticias con ventana diaria o semanal, fecha de
  referencia y metadatos verificables de publicación y fuente.

### Cambiado

- Documentado el repositorio canónico y el flujo obligatorio para acompañar
  cada cambio con changelog, pruebas, commit y subida a GitHub.
- Las expresiones «hoy», «ayer», «mañana» y «esta semana» se transforman en
  fechas ISO dentro de la consulta, por lo que la caché cambia cada día.
- Los recuerdos de otros chats muestran su fecha para evitar que un «hoy»
  antiguo compita con el reloj actual.

### Corregido

- Impedido que el modelo sustituya una consulta temporal determinista por una
  consulta antigua o sin fecha.
- Las noticias sin fecha verificable o fuera del periodo solicitado ya no se
  presentan como noticias actuales.
- Las fechas históricas escritas por Gori se respetan y no se sustituyen por
  «hoy»; las búsquedas de texto como el tiempo tampoco se filtran como noticias.
- Las consultas de noticias usan una frase breve y una fecha ISO natural; si
  el proveedor etiqueta mal el día, también se valida la fecha explícita de la
  URL antes de descartar una noticia vigente.

## [0.11.2] - 2026-07-29

### Añadido

- Mascota local animada para Windows con estado persistente, interacciones,
  cama, comida, juego y convivencia visual con Eevee de Codex.
- Conversaciones múltiples y memoria compartida entre el escritorio y Expo Go,
  con adjuntos, Markdown e historial local de hasta 150 GiB.
- Gestor de las dos GPU y perfiles Normal, Potencia y GPU de juego, con Ollama
  aislado por UUID y controles equivalentes desde el móvil.
- Búsqueda web normal e intensiva con fuentes, límites de resultados y
  tratamiento del contenido remoto como no confiable.
- Herramientas tipadas para aplicaciones, archivos, estado del PC y puente
  local con tareas de Codex.

### Cambiado

- Las órdenes de YouTube se resuelven mediante un enrutador determinista: los
  títulos y temas abren búsquedas canónicas y las órdenes contextuales pueden
  reutilizar el último tema escrito por Gori.
- Arfoxia mantiene separados los resultados de búsqueda de las sugerencias del
  modelo y comunica que Windows aceptó la apertura sin afirmar que la página
  terminó de cargar.

### Corregido

- Impedido que enviar un mensaje cree una conversación nueva de forma
  automática en escritorio o móvil.
- Corregidos el reinicio supervisado de Ollama y Expo Go, la visualización de
  tablas Markdown en móvil y la posición persistente de la cama y el limón.
- Bloqueados los identificadores de vídeo de YouTube inventados o no
  verificados.
- Respetadas órdenes negativas como «no abras», «nunca abras» y «búscalos, pero
  no los abras».

### Seguridad

- Los vídeos solo pueden abrirse si la URL fue escrita por Gori o devuelta por
  una búsqueda de ese mismo turno.
- Validación estricta de destinos HTTPS y rutas de YouTube antes de entregarlos
  al navegador predeterminado.
- Exclusión preventiva de tokens, autorizaciones, bases de datos, registros y
  archivos de entorno en las publicaciones del repositorio.
- Reglas explícitas para normalizar archivos de texto y conservar los recursos
  multimedia como binarios en Git.

[0.11.2]: https://github.com/IagoRV01/Arfoxia-Local-Ai-proyect-Spanish-/releases/tag/v0.11.2
[0.11.3]: https://github.com/IagoRV01/Arfoxia-Local-Ai-proyect-Spanish-/releases/tag/v0.11.3
[0.11.4]: https://github.com/IagoRV01/Arfoxia-Local-Ai-proyect-Spanish-/releases/tag/v0.11.4
[0.12.0]: https://github.com/IagoRV01/Arfoxia-Local-Ai-proyect-Spanish-/releases/tag/v0.12.0
