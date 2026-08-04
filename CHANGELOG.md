# Changelog

Todos los cambios relevantes de Arfoxia se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y las versiones del proyecto siguen versionado semántico.

## [Sin publicar]

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
