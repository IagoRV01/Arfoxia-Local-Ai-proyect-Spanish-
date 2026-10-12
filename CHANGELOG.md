# Changelog

Todos los cambios relevantes de Arfoxia se documentan en este archivo.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y las versiones del proyecto siguen versionado semántico.

## [Sin publicar]

### Añadido — Base de investigación nativa PS4/ShellUI — 2026-10-12

- Sonda propia PRX de metadata Mono/PUI, limitada a `SceShellUI` y GoldHEN SDK
  1.00; registra versión real y firmas de clases, con log acotado. Sin offsets
  de firmware, hooks, parches de hilo principal ni modificación de plugins.
- Cargador BinLoader de una sola ejecución, ruta propia y comprobación explícita
  del syscall/handle; no confunde el envío con una mascota visible.
- Transporte manual FTP con comprobación byte a byte antes de la carga, límite
  de tamaños, rechazo de sobrescrituras/reintentos ciegos y estado de solo lectura.
  Se evita el ping vacío del cargador y el auto-descifrado `.prx` de GoldHEN
  durante la verificación. Sin contraseñas ni configuración persistente nueva.
- Compilación real de PRX y payload con Clang/LLD 18/OpenOrbis y SDK público,
  en contenedor rootless sobre Bazzite; no se instalan capas ni se mueve la IA.
  Once pruebas automatizadas de transporte correctas; suite Python completa:
  775 pruebas correctas.
- Prueba en consola pendiente: PRX subido y verificado en la carpeta propia;
  no se envió el payload porque BinLoader dejó de escuchar tras la comprobación
  TCP. Requiere reactivación manual. Renderizador/mascota PS4 todavía no
  implementados ni registrados como destino de paseo operativo.

### Corregido y ampliado — Paseo en Bazzite — 2026-10-12

- Arrastre estable en Wayland: superficie transparente fija, coordenadas
  lógicas, ancla de pies y pausa de animación durante el gesto. Un arrastre
  que vuelve al punto inicial ya no se interpreta como acariciar.
  El menú se ancla al clic en esa misma superficie, sin coordenadas globales.
- Menú Linux ampliado con dormir/despertar, sentarse/reanudar, limón, cama
  independiente, expresiones, sonidos, estado, captura local y regreso manual
  al PC. Posiciones de mascota/objetos y sonido persistentes en Linux;
  se reutilizan recursos originales sin copiar modelos ni credenciales del dueño.
- Solo las zonas de mascota/objetos reciben entrada; redibujado por daño local,
  sin apropiarse del teclado. Interacciones se envían sin esperar el heartbeat.
- Juego del limón con ida, recogida y regreso, interrumpible al arrastrar y
  respetando sueño/sentado. Destinos acotados a la superficie real de la mascota.
- PS4: diagnóstico de conexión y FTP de solo lectura para la prueba pedida en
  el menú del SO. Sin prueba gráfica: falta un renderizador ShellUI compatible
  con 12.52. No se cargan payloads de otra versión ni se alteran plugins/juegos.
- Validación: 764 pruebas Python correctas; comprobación adicional en GTK real
  sobre KDE Wayland de arrastre, objetos independientes, ida/regreso del limón,
  posiciones persistentes y menú anclado al clic, con capturas revisadas. Los
  gestos de esa prueba se enviaron a los callbacks GTK, no desde un ratón físico.


### Añadido — Paseo de Arfoxia a Linux — 2026-10-12

- Cliente ligero GTK3 para Bazzite/KDE Wayland: sprites originales, expresiones,
  movimiento en ocho direcciones, arrastre e interacciones, con Layer Shell
  OVERLAY y sin apropiarse del teclado. IA, GPU, memoria y chats permanecen
  en el PC; no se instala otro Ollama ni se migra el modelo.
- Control Paseo entre dispositivos en mascota y bandeja, llegada confirmada
  tras dibujar, regreso manual y recuperación por pérdida de conexión.
  Túnel inverso SSH exclusivamente loopback, huellas estrictas y claves.
- Recuperación del túnel propio tras un cierre forzado, comprobando PID, fecha
  de creación y línea de comando exacta; no se terminan conexiones ajenas.
- Permiso independiente restringido a mascota, DPAPI en Windows y fichero
  privado en Linux; sin acceso a herramientas, chats o archivos del dueño.
  Instalador de usuario, sin root ni cambios al sistema inmutable de Bazzite.
- PS4/GoldHEN: se documenta la limitación real del overlay universal de juegos
  y menú. No se instala un PRX no validado ni se altera plugins.ini/firmware.
- Pruebas de llegada, timeout, regreso, credenciales, aislamiento API y comandos
  SSH; validación adicional del cliente en la sesión real del PC Linux.
- Validación: 750 pruebas Python correctas; cliente real dibujando en KDE,
  captura de escritorio y superposición sobre una ventana de prueba a pantalla
  completa. Regreso manual y por parada del servicio comprobados. Esto no
  equivale a probar todos los juegos ni el modo Gamescope de Bazzite.

### Corregido — Interfaz de iOS en Expo Go — 2026-10-11

- Las ventanas nativas disponen de su propio SafeAreaProvider/SafeAreaView:
  la jerarquía nativa de un Modal de iOS no hereda el proveedor de la pantalla
  principal. Se protegen los cuatro bordes, incluida la barra de estado, la
  zona del notch/Dynamic Island y el indicador de inicio, sin alturas fijas
  ni métricas de una ventana anterior.
- Componente SafeModal reutilizado por Visor, historial de conversaciones,
  renombrado, imágenes/capturas y el panel de Moonlight. Se mantienen las
  presentaciones de pantalla completa/transparentes y los botones de cierre.
- Título del proyecto separado de Recargar/Cerrar; botones con ajuste de línea
  y títulos largos contenidos para no empujar otros controles. La WebView no
  añade un segundo margen automático sobre el área segura de la ventana.
- Pantalla principal protegida también en los laterales; se sustituye el
  margen fijo de 52 puntos de las capturas por margen normal más insets nativos.
- Pruebas de regresión de la jerarquía de las cinco ventanas emergentes, bordes,
  medición al reabrir, distribución de cabecera y ajustes de WebView. Validación
  de TypeScript y exportación iOS; confirmación visual final en el iPhone por
  el propietario, sin simular que se ha realizado desde el PC.
- Validación: 65 pruebas móviles correctas, TypeScript sin errores y bundle
  iOS generado. Expo/Metro sigue sirviendo el proyecto actualizado en el mismo
  host/puerto; no se cambia el emparejamiento, el modelo ni los archivos 3D.

### Añadido — Visualizador de proyectos en Expo Go — 2026-10-11

- Nueva pestaña Visor, listado de proyectos/archivos y WebView nativa con
  Recargar/Cerrar. HTML y Three.js interactivos, imágenes, PDF de iOS y lectura
  de texto/código. Se conserva el chat activo y los trabajos del PC.
- Botones Ver resultado automáticos tras herramientas relacionadas con archivos
  reales; recuperación de resultados de mensajes antiguos sin reejecutar
  comandos. Prompt de Arfoxia orientado a entregas HTML con recursos relativos,
  sin enlaces localhost inventados ni falsas comprobaciones visuales.
- API privada de catálogo y vistas con permisos aleatorios de 30 minutos,
  limitados a recursos del proyecto. Sin clave principal en WebView, cookies
  compartidas, acceso a archivos del iPhone ni puente a herramientas del PC.
  CSP aislada, CDN permitidos, rechazo de escapes, enlaces/uniones/enlaces duros,
  archivos privados y carpetas generadas. Sin exposición pública/Funnel.
- Aviso visible de errores JavaScript/carga, sin reescribir los archivos fuente.
  Prueba visual real por Tailscale del proyecto 3D, pausa, día/noche, tamaño móvil,
  módulos/CSS locales y error controlado. Se detectó y corrigió localmente una
  función usada antes de inicializarse, conservando copia previa privada.
- WebView 13.16.1 y parches compatibles recomendados para SDK 57. Actualización
  de shell-quote que elimina el aviso crítico previo; quedan 26 avisos npm
  transitivos (9 moderados/17 altos), sin hallazgos en WebView ni cambios mayores
  forzados. Dependencias generadas y proyectos personales no se publican.
- Pruebas automatizadas y prueba real con Dual: lectura correcta, tarea
  completada en el mismo chat y vista asociada. Documentación de formatos,
  permisos y límites en docs/PROJECT_VIEWER.md; pendiente validación en iPhone
  por el propietario, sin presentarla como ya realizada.
- Validación final: 733 pruebas Python, 59 pruebas móviles, TypeScript sin
  errores, exportación iOS correcta y 21/21 comprobaciones de Expo Doctor.

### Añadido — Carpeta de proyectos predeterminada — 2026-10-11

- Carpeta local persistente `workspace_directory`, por defecto `Arfoxia` dentro
  de la carpeta del usuario (en este PC `C:\Users\Iago\Arfoxia`). Se crea si falta
  y se conserva una ruta personalizada al migrar configuraciones existentes.
- El modelo recibe la ubicación decidida por el propietario y puede crear
  subcarpetas descriptivas por proyecto sin preguntar de nuevo dónde guardarlo;
  debe consultar nombres libres y continuar los proyectos sin sobrescribirlos.
- Archivos, lectura y búsqueda resuelven rutas relativas dentro de la carpeta
  base. Python/PowerShell usan esa base cuando se omite `working_directory`,
  fijada antes de la autorización. No se cambia el cwd global de Arfoxia/Expo.
- Las rutas relativas no pueden escapar mediante `..`, unidades parciales ni
  enlaces hacia fuera. Se mantienen contraseñas/permisos locales, validaciones
  de rutas explícitas, archivos del programa protegidos y control de sobrescritura.
  La ubicación predeterminada no se presenta como sandbox de comandos.
- Pruebas de migración, prompt, subcarpetas, lectura/escritura relativa, cwd,
  autorización, escape de rutas/enlaces y proyecto continuo en el mismo chat.
- Validación: 700 pruebas Python correctas y prueba real con el perfil Dual
  conservado. Creó una subcarpeta en la base sin preguntar la ruta, recuperó
  llamadas de archivo inválidas mediante PowerShell con el cwd correcto y
  comprobó el archivo con read_file antes de cerrar. La comprobación acepta
  texto UTF-8 con BOM de Windows PowerShell, como la herramienta de lectura;
  los informes y archivos de prueba permanecen únicamente en el PC.

### Añadido — Trabajo continuo — 2026-10-11

- Motor de tareas en segundo plano para PC, Expo Go y web, en el mismo chat,
  con estado/progreso compartidos y botón Detener trabajo. El móvil consulta
  con peticiones cortas: cerrar Expo Go o perder conexión no cancela al PC.
- Cierre explícito con resumen y comprobación real posterior a las escrituras;
  las promesas no cuentan como tareas terminadas. Preguntas importantes con
  motivo concreto, sin el habitual «¿quieres que siga?»; respuestas habituales
  retoman el objetivo pendiente en el mismo chat.
- Se supera el antiguo límite de seis rondas conservando el objetivo y grupos
  recientes de herramientas. Guardas de tres pasos idénticos/sin progreso,
  escritura duplicada y emergencia a dos horas/240 llamadas: nunca se informa
  éxito al activarse una guarda. Máximo cuatro trabajos activos/en cola.
- Identidad idempotente, progreso privado persistente sin código/credenciales,
  cancelación cooperativa y recuperación de resultados guardados. Tras reinicio
  se marca la interrupción, sin repetir órdenes automáticamente. Un registro
  dañado se conserva y bloquea nuevos encargos hasta revisarlo.
- API autenticada de tareas y consulta/detención; contrato síncrono anterior
  mantenido. No se amplían permisos ni se habilita ejecución del PC desde una
  búsqueda web/adjunto. Se mantiene el modelo elegido, sin descargarlo por una
  generación cancelada ni hacer fallback automático en trabajo continuo.
- Pruebas de más de seis rondas, comprobación posterior, promesas, permisos,
  decisiones, cancelación durante generación/herramienta, límites, corrupción,
  deduplicación y reinicio. TypeScript comprueba los clientes y prueba el sondeo
  sin reenvíos. Revisión de caché web 11 para cargar la interfaz nueva.
- La prueba con el modelo local detectó y corrigió el enrutamiento de
  «comprueba con calculate»: ya no fuerza una búsqueda web. Un fallo de
  herramienta invalida la comprobación anterior y exige verificar de nuevo,
  evitando cerrar con éxito después de una acción fallida. «Hazme», «créame»,
  «necesito que» y encargos de configuración también activan la continuidad.
- Validación real en Normal (Qwen 3.5 9B): dos llamadas correctas a calculate
  para obtener 60 y 12, cierre explícito y petición duplicada sin duplicar
  ejecución, en el mismo chat. Se conserva el informe del intento inicial
  fallido y el del reintento corregido únicamente en el PC, fuera del repositorio.
- Recuperación web instalada una sola vez al iniciar, también tras recargar
  la página sin enviar otro mensaje. El PC bloquea y libera el editor también
  si la tarea se inició desde el móvil. Validación: 687 pruebas Python, 55 pruebas
  móviles, TypeScript y sintaxis JavaScript correctos.

### Corregido — 2026-10-11

- Recuperación de generaciones Dual vacías o atascadas en razonamiento: se
  observa el flujo nativo y se reintenta una sola vez sin razonamiento cuando
  no hay salida ni herramientas tras 8 000 caracteres internos o 120 segundos.
  El modo extra high sigue siendo el predeterminado; la recuperación solo
  afecta a la ejecución bloqueada y sus rondas de herramientas.
- El reintento mantiene modelo, contexto, opciones de GPU y residencia
  indefinida. No ejecuta acciones dos veces, no descarga Ollama ni cambia
  permisos; el chat registra que hubo recuperación sin exponer razonamiento.
- Un flujo interrumpido o malformado no puede ejecutar llamadas parciales.
  Pruebas de agregación de fragmentos, recuperación finita, conversación única
  y conservación de opciones/permisos.
- El plazo también cubre servidores que no envían fragmentos mientras preparan
  una llamada grande. Se desactiva al recibir texto visible o herramientas;
  el flujo recuperado conserva el motivo hasta la respuesta final.
- El harness registra las correcciones como iteraciones en el mismo chat,
  con informes separados y el ID guardado antes de cada petición larga.
- Las instrucciones de programación piden guardar primero una versión mínima
  ejecutable y ampliarla en escrituras pequeñas, evitando proyectos enteros
  que agotan la generación antes de crear el primer archivo.
- El benchmark detectó además que los scripts extensos rechazados llenaban el
  contexto de 32 768 tokens. Su contenido se resume únicamente en el historial
  de llamadas ya procesadas; la herramienta recibe siempre los argumentos
  completos y los archivos no se recortan. El modelo puede releer los archivos
  reales. Un cierre vacío tras herramientas se informa como tarea incompleta.
- La carpeta del benchmark debe estar fuera del programa, protegido por la
  herramienta de archivos. Se corrigen el harness y su documentación en lugar
  de permitir al modelo modificar Arfoxia. Se pide un cierre visible explícito
  cuando terminan las herramientas, sin más llamadas ni éxito inventado.
  Ese cierre conserva el orden nativo de Qwen: un único mensaje de sistema,
  sin insertar nuevas instrucciones de sistema entre resultados de herramientas.
  Si ese cierre todavía usa razonamiento extra high, también tiene el plazo de
  recuperación por falta de progreso, aunque ya no permita llamadas nuevas.
- «Verifica el archivo», búsquedas en rutas locales y menciones a herramientas
  de programación ya no fuerzan una consulta web ni ocultan las herramientas
  de archivos. Un tema web anterior no puede sustituir una nueva tarea local.
  Estas tareas usan un conjunto local acotado, sin búsqueda/lectura web; las
  peticiones explícitas de documentación en Internet conservan su búsqueda.
- El reto detectó un comando PowerShell demasiado largo: se mantiene su límite
  seguro y el error indica usar write_text/append_text para archivos extensos,
  en lugar de repetir un comando que Windows no puede aceptar.
- La misma guía se aplica a Python demasiado extenso. Ambos rechazos mantienen
  sus límites y confirman que no se ejecutó el contenido; el harness conserva
  también un ID de petición único para evitar duplicados al recuperar resultados.
- La ejecución comprueba también el tamaño UTF-16 de la línea codificada antes
  de crear un proceso, evitando el error de Windows por longitud aun cuando el
  texto original no supera 16 000 caracteres. No se cambian políticas del sistema.
- Los errores de Python conservan la excepción y las líneas útiles sin volcar
  el transporte Base64 ni miles de indicadores de columna al contexto del modelo.
  search_files admite también un único archivo explícito sin recorrer sus vecinos;
  conserva límites de tamaño, resultados y exclusión de binarios.
- Una orden positiva explícita «Lee C:\\...archivo» que el modelo conteste
  solo con una promesa ejecuta esa lectura concreta y continúa con el contenido
  real. Es una recuperación de solo lectura: no inventa rutas, no escribe ni
  ejecuta código automáticamente, y no se activa por adjuntos o negaciones.

### Añadido — 2026-10-11

- Resultado final guiado del jardín: HTML real creado por Qwen 27B/Dual, carga
  sin errores, entidades animadas, pausa, cámara/zoom, ciclo día/noche y controles
  a 390 × 844 comprobados en Chromium. Se registra como funcionamiento básico
  iterativo, no one-shot ni puntuación oficial; incluye limitaciones visuales y
  dos defectos residuales del artefacto, sin corregirlo manualmente ni ocultarlos.
  La última fase tardó 358,91 s con siete de ocho llamadas correctas. Suite final
  de las correcciones de Arfoxia: 654 pruebas aprobadas, una advertencia.
- Seis herramientas útiles para trabajo local y programación: listar carpetas,
  leer texto con números de línea, buscar texto en un árbol de trabajo acotado,
  calculadora sin ejecución arbitraria, Python con salida/tiempo limitados y
  lectura de páginas públicas con TLS, IP fijada y filtros de redirecciones.
- Flujos de hasta seis rondas y 24 llamadas para crear, comprobar y corregir
  archivos dentro del mismo chat. Mantienen permisos locales, autenticación,
  protección de adjuntos y límites; Python sigue la política de PowerShell.
- Script reproducible del reto de programación del jardín japonés 3D mediante
  el modelo y herramientas reales de Arfoxia, con carpeta aislada y resultados
  locales. No cambia ni descarga modelos; no asigna puntuaciones oficiales.
- Pruebas de lectura, límites numéricos, Python desactivado, redacción de código,
  páginas públicas/redirecciones privadas, autorización en rondas posteriores,
  continuidad de conversaciones y límite de rondas.
- Resultado real del jardín japonés con Dual/27B: 896,17 s, 16 384 tokens,
  18,43 tokens/s de generación, ninguna llamada ni archivo creado. Se documenta
  como reto no superado, sin atribuir una puntuación oficial ni esconder el
  aviso de VRAM secundaria. Las generaciones vacías ya no simulan un saludo
  satisfactorio: informan que la tarea no se completó.
- Las seis herramientas nuevas se validaron por la API real; una prueba nativa
  con Qwen/Dual invocó `calculate` y confirmó el resultado en 15,06 s. Suite
  completa: 616 pruebas correctas. El servidor Dual se conservó durante ambas
  recargas de interfaz, sin descargar el modelo residente.

### Corregido — 2026-10-10

- Fallos intermitentes de búsqueda: reintentos acotados con motores independientes
  cuando la selección automática de DDGS falla, queda vacía o agota su tiempo.
  La consulta, idioma, tipo de búsqueda y filtros temporales se conservan.
- Diagnóstico por consulta: diferencia errores del proveedor, resultados vacíos,
  filtrado por fechas y enlaces que no pudieron verificarse. Las investigaciones
  conservan resultados parciales y no exponen detalles privados de excepciones.
- Arfoxia recibe el diagnóstico real y la descripción de DDGS como búsqueda en
  índices públicos, sin API key. Se le indica que un intento fallido no demuestra
  una caída permanente; no debe inventar causas de red, claves o configuración.
- Las consultas conversacionales largas eliminan introducciones y peticiones de
  formato, conservando tema y fechas. Sigue activa la comprobación de enlaces y
  el rechazo de URLs privadas, retiradas o no verificadas.
- Regresiones de recuperación, límites de espera, noticias fechadas, protección
  de excepciones y transmisión del diagnóstico a las herramientas. Pruebas reales
  de texto e investigación con enlaces verificados, sin crear chats de prueba.

### Añadido — 2026-10-04

- Paseos de Arfoxia en ocho direcciones: arriba, abajo, laterales y diagonales,
  con la fila de sprites orientada al desplazamiento y velocidad diagonal
  normalizada. Trayectos cortos dentro del monitor actual, con margen para
  saltos/gestos, comprobación de obstáculos y parada ante Eevee o los bordes.
- Ocho gestos en el menú contextual «Expresiones»: curiosidad, saludo, cola
  contenta, saltito, estiramiento, respiración, pose y giro. Reutilizan las
  animaciones PMD incluidas; los gestos cortos se repiten brevemente para verse.
- Más variedad automática cada 12–22 segundos, sin repetir el último gesto y
  con reacciones tranquilas cuando tiene hambre o poca energía. Se mantienen
  el modo sentado, sueño, arrastre, comida y las rutas horizontales del limón.
- Pruebas de orientación, destinos 2D, velocidad, obstáculos, monitores con
  coordenadas negativas, expresiones, descanso y compatibilidad con el limón;
  revisión visual de los sprites existentes en las ocho direcciones.
- Los temporizadores de paseo, comportamiento y animación se detienen al
  cerrar la mascota, evitando llamadas a una base de datos ya cerrada.

### Corregido — 2026-10-02

- Enter y Enter numérico envían una sola vez al chat seleccionado. Se desactiva
  el botón predeterminado implícito de Qt que también pulsaba «+ Nueva» al enviar;
  la creación sigue disponible únicamente mediante la acción manual.
- Las imágenes adjuntas ahora se muestran como miniaturas dentro del chat de PC,
  antes de recibir respuesta y al cargar mensajes guardados. Los adjuntos se
  resuelven por identificador y conversación; no se habilitan imágenes remotas
  ni rutas locales procedentes del texto del modelo.
- Miniaturas con límites de tamaño, proporción y orientación conservadas;
  los archivos ausentes o dañados conservan su nombre sin romper el historial.
  Previsualizar no consume el adjunto destinado al modelo. Al copiar una imagen
  del historial se incluye su nombre, no una referencia interna inservible.
- Regresión reproducida con pulsaciones reales de Enter, prueba de creación
  manual, aislamiento entre chats, almacenamiento real, copiado y formatos
  inválidos; comprobación visual de las imágenes en la conversación.

### Añadido — 2026-10-02

- Botón «Activar Dual» junto a Potencia en la cabecera del chat de PC, conectado
  al selector Dual existente: carga manual en ambas GPU con las mismas
  comprobaciones de juego, instalación y VRAM. No cambia los límites ni la
  permanencia del modelo en memoria.
- Indicadores «Cargando Dual…» y «Dual activo», bloqueo de cambios simultáneos
  y actualización del estado al cambiar desde otros controles. El botón
  «Volver a Normal» permite salir de Dual; los errores se muestran sin crear chats.
- Pruebas del botón, doble clic, regreso a Normal, errores y sincronización
  del modo; comprobación visual de los tres controles en la cabecera.

## [0.15.1] - 2026-09-26

### Corregido

- Fórmulas LaTeX visibles como texto en «Hablar con Arfoxia» (PC): renderizado
  local de raíces, fracciones, exponentes, operadores y resultados enmarcados
  `\boxed{...}` de nivel superior, también dentro de tablas y chats antiguos.
  Admite delimitadores `$...$`, `$$...$$`, `\(...\)` y `\[...\]`.
- El portapapeles recupera el LaTeX original; no se modifica el historial.
  Código, importes monetarios y nombres de adjuntos conservan su formato.
- Recursos matemáticos generados en memoria con Matplotlib, sin procesos TeX,
  descargas ni acceso a imágenes externas. Límites de tamaño, complejidad y
  fórmulas por mensaje; caché acotada y texto de respaldo para sintaxis no
  compatible. No se habilita HTML ni se altera el visor de Expo Go.
- Pruebas de regresión de la captura original, tablas, copiado, delimitadores,
  código literal, entradas inválidas, límites y seguridad de recursos. Revisión
  visual de barras de raíces y escalado suave según los píxeles de la pantalla.

## [0.15.0] - 2026-09-25

### Corregido

- Acceso de Expo Go por Tailscale cuando Windows clasifica la VPN como privada
  y las reglas existentes de Node.js solo admiten redes públicas. Nuevo script
  idempotente `configure_expo_firewall.ps1`: TCP 8081, ejecutable Node.js exacto,
  interfaz Tailscale y rangos privados de la VPN; no desactiva el firewall ni
  modifica otras reglas. Incluye simulación `-WhatIf` y retirada `-Disable`.
- Guía de diagnóstico del tiempo agotado sin borrar el emparejamiento móvil.

### Añadido

- Modo manual «Quedarse sentado (sin dormir)» en el menú de Arfoxia, la bandeja
  de Windows y Expo Go. Detiene paseos, acercamientos a Eevee y juegos físicos
  activos; mantiene a Arfoxia sentado y despierto incluso con energía baja.
- Órdenes de chat «siéntate», «quédate sentado mientras juego» y «vuelve a
  pasear», ejecutadas directamente sin cargar ni consultar el modelo.
- Estado sentado persistente en SQLite y compartido entre PC/móvil. Descansa
  despierto recuperando energía lentamente; no cambia modelos ni gestión de GPU.
  Comer, acariciar o conversar conservan el modo; jugar, dormir o «Volver a
  pasear» lo desactivan. Se puede seguir arrastrando sin dormirse al pasar por la cama.
- Pruebas de persistencia, compatibilidad con estados antiguos, API autenticada,
  órdenes explícitas sin Ollama, energía baja, animaciones, comida y limón.

## [0.14.1] - 2026-09-18

### Corregido

- El filtro de fuentes conserva literalmente bloques y fragmentos de código
  CommonMark, incluidos imports HTTPS, sangría, cercas anidadas y saltos de línea.
  Las citas fuera del código siguen limitadas a destinos comprobados o escritos
  por el usuario; no se ejecuta ni se abre automáticamente el código mostrado.
- Los enlaces verificados con paréntesis equilibrados ya no se recortan; los
  resultados que redirigen al mismo artículo se muestran una sola vez.
- «Vuelve a intentarlo», «los enlaces no funcionan» y seguimientos sobre máximas
  y mínimas retoman el tema del mismo chat y consultan fuentes de nuevo. Se
  eliminan saludos y relleno de la consulta; no se buscan literalmente las
  frases de reintento ni se recuperan temas de otro chat.
- Los resultados recuerdan al modelo que una página accesible y un extracto
  indexado no garantizan actualidad ni justifican inventar datos meteorológicos.
- En Windows, tablas/listas/código no contaminan el formato del siguiente
  mensaje; los enlaces tienen contraste sobre el fondo oscuro.
- En Expo Go, código monoespaciado seleccionable, desplazamiento horizontal y
  botón Copiar; las cercas de código largas no se confunden con tablas.

### Pruebas

- Regresiones de código literal, enlaces, contenedores Markdown, contexto de
  búsquedas, redirecciones y consultas meteorológicas encadenadas; comprobación
  Qt, pruebas móviles y exportación iOS de Expo. Los historiales existentes no
  se reescriben: el código ya dañado debe regenerarse.

## [0.14.0] - 2026-09-17

### Cambiado

- Modo Dual Qwen3.8 27B en Extra High (`think: high` en Ollama 0.34, equivalente
  oficial a `xhigh`), muestreo recomendado y hasta 16384 tokens de generación.
- Vigilancia compartida de límites cada 20 segundos, con avisos en PC y Expo Go;
  no descarga automática por juego, telemetría, timeout o error de respuesta.
- Residencia indefinida y recuperación del servidor propio tras reiniciar/cerrar
  la interfaz; descarga mediante Liberar VRAM o cambio manual de perfil. Una
  carga inicial inválida se revierte y los cierres de Windows/driver no son evitables.
- PC y móvil muestran Extra High, descarga manual y política privada de acciones.
  El plazo de respuesta Dual aumenta a 30 minutos para razonamiento prolongado.

### Añadido

- Política local opcional para ejecutar acciones sin contraseña de Arfoxia,
  sin retirar el token de emparejamiento ni Tailscale privado.
- Herramienta PowerShell opcional para tareas del PC, con validación, salida
  acotada, plazo máximo y redacción del script en auditoría.
- Inicio como administrador solicitado por el propietario: instalador mediante
  UAC y tarea interactiva `Highest`, sin guardar contraseñas ni desactivar UAC;
  estado real de elevación en PC y móvil y retirada reversible del inicio elevado.
- Valores seguros por defecto en el repositorio (contraseña activa, PowerShell
  y administrador desactivados); el perfil privado se activa solo localmente.
- Pruebas de residencia, muestreo, razonamiento, recuperación de procesos,
  autenticación, permisos, comandos Unicode, salida limitada, timeout y elevación.
- Verificación real: Arfoxia y su herramienta ejecutan como administrador; las
  peticiones sin Bearer siguen devolviendo 401. Qwen3.8 acepta Extra High y
  propone una llamada válida; mantiene los mismos procesos/modelo al reiniciar.

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
