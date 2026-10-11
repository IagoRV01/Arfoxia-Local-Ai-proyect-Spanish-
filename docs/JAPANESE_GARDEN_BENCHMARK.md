# Reto del jardín japonés 3D

Este reto local evalúa una petición de programación visual con el modelo real de
Arfoxia y sus herramientas. No es un benchmark oficial ni una comparación
controlada entre modelos. El prompt completo está en
`scripts/benchmark_japanese_garden.py`; cada ejecución crea una carpeta nueva y
una conversación explícita, manteniendo el modelo seleccionado.

## Condiciones

- Una escena voxel interactiva en Three.js, escrita por Arfoxia en `index.html`.
- Geometría procedural; solo Three.js y OrbitControls pueden venir de un CDN,
  fijando su versión. Sin assets externos ni instalación de paquetes.
- Pagoda, cerezos, faroles, puente, estanque y koi animados, aldeanos y dragón.
- Sombras, ciclo día/noche, cámara orbital, pausa y adaptación al tamaño de pantalla.
- El modelo puede usar hasta seis rondas/24 llamadas; no se edita su código para
  mejorar artificialmente el resultado. Una corrección posterior debe solicitarse
  al propio modelo y registrarse como otra iteración.
- Los límites de VRAM y avisos del perfil siguen activos. No se descarga ni cambia
  de modelo automáticamente para esta prueba.

## Verificación

El script registra tiempo total de la petición, modelo, llamadas, éxitos y si se
creó el archivo. Estos valores no equivalen a tokens por segundo ni FPS.
Después se comprueba la carga real en navegador, la consola, la escena visible y
los controles. El informe debe distinguir lo observado visualmente de lo que solo
figura en el código. Una captura estática no demuestra animación ni rendimiento.

Los archivos generados, respuesta cruda y rutas locales se conservan en una
carpeta independiente fuera del programa, por ejemplo en Documentos/Arfoxia
Benchmarks, fuera de Git. La herramienta de archivos protege el árbol del
programa; el harness rechaza ese destino antes de crear archivos. Los intentos
históricos en `work/` documentados abajo son anteriores a esta corrección.
Las pruebas del repositorio validan las herramientas; no demuestran
por sí mismas que una escena concreta generada por un modelo funcione.

## Recuperación e iteraciones

Dual conserva extra high como razonamiento inicial. Cuando una generación con
herramientas sigue razonando sin texto visible ni llamadas durante 120 segundos
o 8 000 caracteres internos, Arfoxia cierra únicamente esa petición y la
reintenta una vez con `think: false`. Una generación vacía terminada también
puede recuperarse una vez. No cambia modelo/contexto, no descarga el servidor ni
modifica los permisos; las siguientes rondas del flujo recuperado continúan sin
razonamiento. La respuesta registra `execution_recovery` y el motivo, sin guardar
el razonamiento privado. El plazo real también cubre la ausencia de fragmentos
intermedios y se desactiva al recibir texto visible o herramientas.
También se aplica al cierre final de un flujo de herramientas si sigue usando
razonamiento, aunque en esa respuesta ya no haya herramientas habilitadas.
No se reintenta una petición que ya produjo herramientas
o texto visible, ni se ejecuta un flujo truncado.

El mismo harness admite `--followup "error observado" --conversation-id ID`
junto a la carpeta original. Cada corrección crea informes separados con
`guided_iteration: true`, sin abrir otro chat ni sobrescribir el informe inicial.
El ID del chat, el ID único de petición y el prompt se guardan antes de cada
petición larga. Un error de conexión se informa como resultado desconocido, no
como ausencia de acciones ni como permiso para repetir órdenes. Una escena
corregida de esta forma cuenta como resultado iterativo, no como éxito de un
único intento ni puntuación oficial.

Las llamadas ya procesadas conservan sus rutas y resultados, pero omiten del
contexto las fuentes extensas de comandos/Python/archivos. Los argumentos
ejecutados y los archivos se mantienen completos; el modelo puede usar read_file
para verificarlos. Esto evita volver a inyectar scripts rechazados hasta llenar
el contexto. Al terminar las rondas se solicita una respuesta visible final sin
llamadas nuevas, conservando un único mensaje de sistema al principio de la
conversación. Una salida vacía tras herramientas no se presenta como éxito.

Las peticiones de archivos concretos y herramientas locales no se convierten en
búsquedas web por contener «verifica». Tampoco heredan automáticamente un tema
web antiguo. Su flujo conserva las herramientas locales y excluye búsqueda/lectura
web; una petición explícita de documentación en Internet sigue usando búsqueda.
Si una orden positiva que comienza por «Lee»/«Read» y contiene una ruta de archivo
Windows literal recibe solo una promesa, se ejecuta esa lectura exacta y continúa
el flujo con el contenido real. No se deducen escrituras ni comandos, ni se toma
autoridad de un archivo o un adjunto. Las negaciones y rutas ambiguas no activan
este mecanismo. Los errores Python ya no vuelcan el transporte Base64 al contexto;
search_files puede buscar también en un único archivo explícito, sin sus vecinos.

PowerShell comprueba la longitud real UTF-16 de la línea codificada antes de
crear el proceso, además del límite de la fuente. Windows limita esa línea a
32 767 unidades incluyendo terminador. [Referencia de Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw).

## Resultado local — 2026-10-11

- Modelo: `qwen3.8:27b-q4_K_M`, perfil Dual, razonamiento nativo `high` (extra high).
- Contexto: 32 768 tokens. Modelo ya cargado; sin cambiar ni descargar el perfil.
- Tiempo completo de la petición: **896,17 s (14 min 56 s)**.
- El registro del servidor muestra 4 801 tokens de entrada y 16 384 tokens
  generados, con 889,10 s de generación (**18,43 tokens/s**). Esta velocidad incluye
  los tokens generados por el modelo, no solo texto visible o código útil.
- **Cero llamadas a herramientas y ningún `index.html` creado.** La API recibió
  una respuesta visible vacía y la interfaz antigua la sustituyó por un saludo.
- Resultado: **reto no superado**. No se pudo ejecutar la comprobación visual ni
  medir FPS, animaciones o calidad de la escena porque no existe un artefacto.
- El número de tokens coincide con el tope configurado de 16 384; junto a la
  ausencia de salida visible, apunta a agotamiento del presupuesto de generación.
  No se expone ni se conserva el razonamiento privado del modelo en este informe.
- Ollama declaró el modelo íntegramente en VRAM (16,68 GiB). El gestor avisó de
  uso total de la GPU secundaria por encima de 5 632 MiB; una muestra fue
  6 892 MiB. Es uso total de la tarjeta, no una atribución exclusiva al modelo.
  No se descargó automáticamente ni se alteraron los límites para ocultar el aviso.

Las seis herramientas añadidas se comprobaron por separado mediante la API real
(incluidos Python y lectura web). El fallo del reto no se presenta como un fallo
de esas pruebas ni como un éxito de programación. Se ha corregido el saludo
sustitutivo: una generación vacía se informa ahora como tarea no completada.

Una comprobación adicional en el mismo chat, separada del reto, pidió al modelo
calcular `2+2` usando `calculate`. Qwen ejecutó la llamada nativa correctamente y
confirmó `4` en **15,06 s**. Esto verifica que el modelo recibe y puede invocar las
herramientas nuevas, pero no cambia el resultado negativo del jardín.

## Segunda ejecución y diagnóstico — 2026-10-11

El nuevo intento del encargo completo tampoco fue un éxito de un solo turno:
**1 600,38 s (26 min 40 s)** y tres llamadas, sin HTML. Se ejecutó una lectura
de carpeta y se rechazaron dos scripts por superar los límites de entrada
(PowerShell/Python). El historial reincorporaba esas fuentes completas hasta
llenar los 32 768 tokens y truncar la generación. Este diagnóstico motivó la
compactación de llamadas ya procesadas y las instrucciones de escritura incremental.

Se pasó después a fases guiadas en el mismo chat, con código escrito únicamente
por Arfoxia. La primera fase generó un HTML mínimo en **285,45 s** y seis llamadas:
cuatro correctas y dos escrituras rechazadas porque el destino antiguo estaba
dentro del programa protegido. El artefacto se trasladó sin editar su contenido
a una carpeta de benchmark fuera del programa; el harness ya impide ese destino.

Una ampliación inicial tardó **94,36 s** e hizo una búsqueda web en vez de editar
el archivo. «Verifica el archivo» estaba forzando el enrutamiento web y ocultando
las herramientas locales. No produjo cambios y se registra como fase fallida.
Tras corregir ese enrutamiento, la ampliación de cerezos, faroles, puente y
control día/noche tardó **317,25 s**, con **seis llamadas correctas**. Se comprobó
su carga en navegador, sin errores de consola, y que la cámara siguiera funcionando
durante la pausa. Estos pasos no se presentan como un benchmark one-shot superado.

La primera ampliación de entidades tardó **326,38 s**, con seis llamadas (cuatro
correctas). Un parche falló por un anclaje con espacios incorrectos y el modelo
gastó sus rondas diagnosticándolo sin llegar a escribir: no cambió el HTML.
Tras limpiar las trazas y acotar la siguiente petición, Arfoxia añadió cinco koi,
tres aldeanos y un dragón en **297,11 s**, con cinco llamadas (cuatro correctas;
una lectura rechazó max_lines fuera de límite). La sintaxis y carga se validaron
sin errores. La pausa conservó dos fotogramas idénticos y el movimiento se observó
antes y después de reanudar. Una pasada de acabado posterior tardó **134,07 s**
pero no llamó herramientas ni editó el archivo: se registra como fallo, y motivó
la recuperación de lecturas explícitas sin llamada nativa.

## Validación del artefacto final — 2026-10-11

La última iteración guiada tardó **358,91 s**, con ocho llamadas (siete correctas).
Arfoxia guardó el acabado de interfaz, puente, reloj con delta real y ciclo
automático. El HTML final tiene 12 783 bytes y sintaxis JavaScript válida.
Su respuesta final prometió revisar un detalle de los koi, pero no ejecutó una
corrección adicional: esa promesa no se contabiliza como trabajo realizado.

En un navegador Chromium real se comprobó:

- Carga de la escena sin errores ni advertencias de consola.
- Presencia de pagoda, cinco cerezos, cuatro faroles, puente, estanque con cinco
  koi, tres aldeanos, dragón voxel y sombras; movimiento de koi, aldeanos y dragón.
- Pausa/reanudación: dos capturas durante pausa fueron idénticas. La cámara y
  el zoom siguieron operativos mientras el reloj y las entidades estaban detenidos.
- Cambio manual día/noche y cambio automático de noche a día tras reanudar.
  Los 20 segundos por fase se verificaron en el código, no se cronometraron como
  una medición de rendimiento. Las luces nocturnas se ven en el suelo.
- Adaptación a 390 × 844: lienzo del tamaño de pantalla, sin desbordamiento
  horizontal de documento, y botones dentro del viewport. Se restauró el tamaño
  original. No se probó el gesto táctil en un iPhone físico.

Resultado: **funcionamiento básico superado mediante iteraciones guiadas**.
No es un éxito de un solo intento, una puntuación oficial ni una aprobación del
detalle artístico. El jardín es voxel muy sencillo: la pagoda y el dragón tienen
poco detalle, las llamas siguen ocultas por la carcasa opaca del farol, y el
balanceo vertical de los koi usa delta de frame en lugar del reloj acumulado.
La natación horizontal funciona. Estos defectos quedan documentados, no se
disimulan mediante cambios manuales al HTML ni una calificación inventada.
En pantallas estrechas puede ser necesario alejar la cámara. No se midieron FPS.

El modelo que generó todas las fases registradas fue Qwen 27B/Dual. Al retomar
la validación estaba seleccionado Normal y Dual apagado; se respetó ese estado
sin volver a cargar el modelo ni utilizar la GPU de juegos para otra generación.
Los informes crudos, capturas y artefacto permanecen fuera de Git. Solo se publica
este resumen y las correcciones de Arfoxia. Suite final: **654 pruebas correctas**,
una advertencia de dependencia.
