# Changelog

Todos los cambios relevantes de Arfoxia se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y las versiones del proyecto siguen versionado semántico.

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
