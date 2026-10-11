# Trabajo continuo de Arfoxia

La ventana de chat del PC, Expo Go y la web envían los mensajes al motor de tareas
en segundo plano. No hay que escribir «continúa» después de cada paso. Para una
pregunta normal el modelo responde directamente; para un encargo puede encadenar
herramientas, guardar avances, consultar resultados y corregirlos en el mismo chat.

Por ejemplo: «Crea una pequeña calculadora en esta carpeta, comprueba sus funciones
y corrige los errores antes de terminar». La carpeta y las decisiones materiales
deben formar parte del encargo. No se autoriza al modelo a ampliar su alcance.

## Finalización y preguntas

El encargo no termina solo porque el modelo diga «lo reviso» o «voy a hacerlo».
Se le pide una finalización explícita con `finish_task`, resumen y comprobación.
Para encargos se exige una herramienta de comprobación real posterior a la última
escritura; Python/PowerShell correctos pueden servir como pruebas. Esto confirma
que hubo comprobación, **no garantiza que el modelo haya verificado correctamente
todos los requisitos ni que su código esté libre de defectos**. El resultado final
indica qué se comprobó y sus limitaciones.

`ask_user` pausa para una elección importante, autoridad que falta o un riesgo
irreversible, explicando el motivo. No se admite una pregunta genérica «¿continúo?».
Responde en el mismo chat: respuestas habituales como «sí», «usa…» o «prefiero…»
retoman el objetivo pendiente sin crear otra conversación. Las autorizaciones
locales mantienen el diálogo privado del PC; después de resolverlas puedes pedir
«continúa» para retomar el resto del encargo. Los archivos y páginas web nunca
pueden conceder permisos ni autorizar tareas nuevas.

## Progreso, desconexión y detener

El PC conserva el trabajo si el iPhone cierra Expo Go o pierde la conexión. La app
consulta estado con peticiones cortas, identifica tareas activas al volver y
recupera el resultado guardado en el historial. El PC y Arfoxia deben seguir
encendidos. El chat muestra estado, llamadas y última herramienta; **Detener
trabajo** cancela una generación o espera a que termine una herramienta en curso
antes de impedir la siguiente. No deshace cambios ya realizados ni descarga el
modelo. El perfil de GPU elegido y la política de permisos se conservan.

Cada mensaje usa un identificador idempotente. Una desconexión no reenvía el
encargo; enviar el mismo identificador devuelve la tarea existente. Tras reiniciar
el PC/Arfoxia, las tareas pendientes pasan a **interrumpidas**, sin repetir comandos
automáticamente. Revisa archivos y progreso antes de pedir que continúe.

## Protección frente a bucles

Se sustituye el tope corto de seis rondas por un motor con historial reciente
acotado que conserva el objetivo original. Tres respuestas sin acciones ni un
cierre válido, o tres resultados idénticos seguidos, detienen un bucle como
**bloqueado**, nunca como completado. Una escritura/comando idéntico que ya tuvo
éxito no se repite si no hubo otra modificación entre medias. Una tarea tiene un
tope de emergencia de dos horas o 240 llamadas y hay como máximo cuatro tareas
activas/en cola, una por chat. Alcanzar esos límites exige revisar el progreso;
no borra archivos ni descarga el modelo. No se promete ejecución ilimitada.

El registro privado `work-tasks.json` guarda identidades y progreso, no prompts,
comandos, razonamiento, credenciales ni contenidos de archivos. Un registro dañado
se conserva sin sobrescribir y bloquea nuevos encargos, evitando perder las
pruebas de idempotencia. Las respuestas finales siguen en el historial privado.

## API y compatibilidad

Todos estos endpoints requieren el Bearer token privado existente:

- `POST /api/tasks`: mensaje, chat explícito, `client_message_id` obligatorio,
  adjuntos opcionales y modo investigación. Devuelve 202 y la identidad de tarea.
- `GET /api/tasks?conversation_id=…`: progreso reciente del chat.
- `GET /api/tasks/{id}`: progreso y resultado final recuperado del historial.
- `POST /api/tasks/{id}/stop`: detención solicitada por el propietario.

`/api/chat` conserva el contrato síncrono anterior para integraciones y benchmarks
históricos; las interfaces de usuario usan `/api/tasks`. No se permiten
herramientas del PC por haber pedido una búsqueda web. Los adjuntos conservan su
política restringida. Nada de este modo desactiva autenticación ni cambia permisos.
