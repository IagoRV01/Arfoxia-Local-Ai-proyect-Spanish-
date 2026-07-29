# Puente Arfoxia → Codex/Eevee

Eevee es la mascota visual integrada en Codex. No mantiene una conversación ni posee herramientas propias, por lo que Arfoxia se comunica con el motor local de Codex y Eevee refleja visualmente la actividad de la aplicación.

## Operaciones permitidas

1. `codex_list_tasks`: lista o busca tareas con título. Es de solo lectura.
2. `codex_open_task`: resuelve un título único y abre `codex://threads/<threadId>`.
3. `codex_pause_task`: tras una autorización local de un solo uso, relee la tarea y solicita `turn/interrupt` únicamente si hay exactamente un turno `inProgress`.

No existe una operación genérica de RPC, terminal, teclado o ratón. Las coincidencias parciales solo se aceptan si identifican una única tarea.

## Límite de Codex Desktop

En Windows, Codex Desktop ejecuta su `app-server` sobre tuberías `stdio` privadas. Arfoxia puede abrir otra instancia compatible y leer las tareas persistidas, pero esa instancia no comparte necesariamente el estado vivo del turno que posee Desktop. Por ello:

- Si el servidor que recibe la orden conoce el turno activo, la pausa se completa después de autorizarla con la contraseña local.
- Si no lo conoce, Arfoxia no afirma que lo haya pausado: abre la tarea exacta y solicita el clic manual en **Detener**.

Compartir un `app-server` por WebSocket permitiría controlar el mismo estado, pero el transporte está marcado como experimental y no ofrece aquí una autenticación adecuada. Esta versión no lo habilita para evitar exponer un canal local de control.

Documentación primaria: [Codex App Server](https://learn.chatgpt.com/docs/app-server) y [README del app-server en OpenAI Codex](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md).
