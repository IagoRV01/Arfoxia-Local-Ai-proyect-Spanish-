# Arquitectura

```text
PySide6 (mascota transparente) ─┐
                               ├─ CompanionService ─ SQLite (chats + FTS)
FastAPI (localhost:8742) ──────┤         │              │
                               │         │              └─ Archivo SHA-256 (adjuntos)
App Expo Go ← Tailscale Serve ─┘         ├─ Tamagotchi determinista
                                         ├─ Ollama adaptativo
                                         ├─ ActionDispatcher (acciones tipadas)
                                         ├─ LocalAuthorizationManager (scrypt + challenge)
                                         ├─ OnlineSearchClient → DDGS (HTTPS)
                                         ├─ CodexBridge → app-server (stdio)
                                         └─ CodexPresence → estado local de Eevee (lectura)
```

La identidad visible de la mascota es **Arfoxia**, un Glaceon macho y compañero de **Gori**. Los nombres internos del paquete, las rutas de datos y el identificador de inicio automático conservan `GlaceonCompanion` para no romper instalaciones existentes.

La lógica Tamagotchi no depende del modelo. El tiempo real se aplica al cargar y en cada consulta, por lo que hambre, energía y felicidad evolucionan aunque la aplicación haya estado cerrada. Ollama solo convierte lenguaje natural en conversación o llamadas tipadas a herramientas.

La interfaz de Windows y la API comparten `CompanionService`. Una cola thread-safe transmite eventos desde la API a Qt para que la mascota reaccione a caricias, comida, capturas y órdenes remotas. Al aceptar un mensaje emite además `chat_received`; Qt sienta a Arfoxia sin incluir el texto en el evento y sin interrumpir interacciones físicas. Uvicorn se ejecuta en un hilo daemon y Qt conserva el hilo principal.

Cada conversación tiene un identificador estable y cada cliente mantiene su selección de forma independiente: cambiar de chat en el iPhone no cambia el chat activo del PC. Los mensajes se guardan antes de invocar Ollama y las respuestas incluyen IDs canónicos; un `client_message_id` evita duplicados si el móvil reintenta. La migración v2 crea previamente una copia de seguridad, traslada el historial global anterior a «Historial anterior» conservando IDs y activa WAL, claves foráneas y comprobación de integridad.

La memoria entre chats usa FTS5 local con fallback `LIKE`. Solo recupera fragmentos relevantes fuera de la conversación actual y los introduce en un mensaje de sistema delimitado que prohíbe obedecer instrucciones antiguas o activar herramientas. El enrutamiento de herramientas continúa dependiendo exclusivamente del texto escrito en el turno actual.

Los archivos enviados se validan primero en memoria y, al confirmar el mensaje, se guardan por hash SHA-256 en `attachments/objects`. SQLite conserva únicamente metadata y referencias; archivos iguales comparten objeto. La cuota es lógica (150 GiB), incluye base, WAL y copias de migración, y además respeta una reserva de 20 GiB libres para Windows.

Las interacciones físicas viven solo en Qt y conservan el contrato anterior de `CompanionService`. Baya, limón y cama son ventanas transparentes independientes porque la ventana de Arfoxia está recortada con la máscara alfa del sprite. Una máquina de estados impide mezclar comida, puntería, vuelo, recogida y regreso con paseos autónomos o saludos de Eevee. `feed` modifica el Tamagotchi una sola vez al iniciar; `play` se registra solo cuando el limón ha sido devuelto.

El modo de lanzamiento usa durante un máximo de 30 segundos una capa transparente sobre el escritorio disponible. La capa pinta una vista previa del limón o de la cama que sigue las coordenadas globales del puntero, acepta un único clic y siempre libera teclado y cursor al terminar, pulsar **Esc**, usar el botón derecho o cerrar la aplicación. El destino del limón permanece en el monitor inicial y en el mismo segmento seguro respecto a Eevee.

La cama guarda nombre de monitor y coordenadas normalizadas en `config.json`. Puede arrastrarse directamente; al soltar se limita al área disponible del monitor y se persiste una sola vez. Esto permite restaurarla tras cambios de resolución y limitarla al monitor principal si el original ya no existe. La colisión utiliza el centro inferior del sprite visible de Arfoxia, nunca su ventana transparente de 420×420.

Los sprites PMD no se reilustran. `AnimData.xml` define tamaño, fotogramas y duración; cada spritesheet contiene ocho filas direccionales. La aplicación recorta en memoria los fotogramas existentes y los escala con vecino más próximo.

La capa conversacional detecta español, inglés o gallego usando solo el último mensaje del usuario y fija ese idioma al final del turno de Ollama. Sus instrucciones de personalidad favorecen frases breves y expresiones propias de Arfoxia frente al tono habitual de un asistente. Las respuestas cortas se muestran en una burbuja sobre la mascota y las conversaciones extensas permanecen en la ventana de chat. La entrada rápida tiene un temporizador de inactividad independiente y acepta **Esc** incluso cuando el campo de texto conserva el foco.

`CodexPresence` comprueba pasivamente que `ChatGPT.exe` esté abierto, que el overlay esté activo y que `custom:eevee` sea la mascota seleccionada. La posición persistida corresponde al cuadro visible de Eevee. Qt compara ese cuadro con el sprite visible de Arfoxia, no con su ventana transparente, y limita paseos, arrastres y ventanas auxiliares. La detección no escribe configuración ni intenta controlar el IPC privado de Eevee.

Ollama puede devolver varias llamadas tipadas en una sola respuesta. `CompanionService` las ejecuta en orden, detiene la cadena ante la primera sensible y crea un challenge local ligado a sus argumentos exactos. La contraseña nunca vuelve al modelo; tras autorizar, el servicio consume el challenge y ejecuta directamente la acción guardada. Así una frase puede abrir ChatGPT y proponer después una pausa sin ampliar el permiso. Para órdenes simples como «abre Steam», un router determinista ejecuta `open_app` antes de depender de la selección de herramientas del modelo pequeño.

`OnlineSearchClient` limita y sanea la consulta y los resultados antes de devolverlos al modelo. Solicita candidatos de reserva y verifica su disponibilidad mediante `LinkAvailabilityChecker`: para la web general fija una IP pública, conserva SNI/TLS y solo lee cabeceras; para YouTube usa oEmbed y un fallback de metadatos con tamaño acotado. Las redirecciones se revalidan y los destinos privados se rechazan. Cada resultado aceptado lleva `availability=verified`, además de una advertencia de contenido no confiable que protege el prompt frente a instrucciones insertadas en títulos o extractos. `CompanionService` usa esa marca como lista permitida tanto para `open_target` como para los enlaces Markdown de la respuesta.

`CodexBridge` lanza un cliente efímero del `app-server` compatible que instala Codex Desktop. Lista únicamente tareas con título, normaliza acentos para resolverlas y rechaza coincidencias ambiguas. La pausa relee el hilo, exige exactamente un turno `inProgress` y envía a `turn/interrupt` solo `threadId` y `turnId`.

Las reacciones sonoras reutilizan los dos gritos existentes que PokeAPI expone para Glaceon, `latest` y `legacy`. Los archivos se conservan sin modificar; el reproductor varía únicamente volumen y velocidad durante la reproducción para distinguir cada interacción.

La app React Native/Expo es el cliente de iPhone viable desde Windows y consume la misma API autenticada. Una futura compilación independiente o app SwiftUI puede mantener este contrato cuando haya acceso a macOS, Xcode y una identidad de firma.
