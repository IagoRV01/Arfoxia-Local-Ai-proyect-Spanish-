# Cliente PS4: investigación del menú ShellUI

Estado: **sonda antigua en cuarentena; callback e hilo gráfico validados;
animación, desplazamiento y poses controladas confirmados; cliente completo en desarrollo**.
La mascota PS4 completa todavía no está validada.
No es un cliente GTK ni una aplicación a pantalla completa disfrazada de overlay.
La prueba está limitada al menú de inicio, sin juegos abiertos. No habilita
viajes a PS4 en la interfaz Windows hasta verificar un cliente estable completo.

## Despacho nuevo: primera prueba en consola superada

`offline_aot.py` analiza el formato x64 AOT v140 observado en las bibliotecas
privadas: exportación de información, límites de segmentos ELF y tabla de
llamadas relativas. Rechaza layouts desconocidos, cuerpos no ejecutables y
tokens fuera de rango. Un método sin cuerpo nativo se marca como provisto por
el runtime, no como prueba de que podamos invocarlo. No ejecuta código Sony.

`dispatch_profile.py` exige los tipos y firmas exactos, los cuerpos AOT del
constructor/contexto PUI y de `Post`, y coincidencia entre GUID AOT y MVID de
metadata. Genera un header **privado y excluido de Git**, sin activar cargas:

```sh
python ports/ps4/dispatch_profile.py \
  --pui RUTA_PUI_PRIVADA --corlib RUTA_CORLIB_PRIVADA \
  --output ports/ps4/build/dispatch_profile.h
```

La prueba de host (`make test-mono`) crea un delegado hacia una función nativa
y lo encola en un `SynchronizationContext` propio. Se verificó ejecución
exactamente una vez en el hilo gestionado propietario, también con JIT
deshabilitado en **full-AOT**, en un contenedor Mono 6.8 aislado. El runtime
de la consola se identifica como PlayStation4 Mono 5.2: **el éxito del host
no valida esa variante ni demuestra que el hilo sea el gráfico de PS4**.

El reemplazo `native/dispatch_probe.c` por defecto no crea widgets; los
experimentos visuales requieren flags y perfiles privados adicionales.
No usa hooks, parches ni desactiva aserciones del hilo principal.
Antes de resolver tokens verifica firmware, proceso y los GUID de ambas
bibliotecas cargadas. Solo consulta el ensamblado PUI ya cargado, sin buscar
clases en todos los ensamblados ni cargar una DLL nueva. Registra fases con
fsync y conserva el módulo/raíces GC después de encolar: no se deben liberar
mientras pueda quedar código pendiente. `module_stop` rechaza una parada tras
el envío; no se debe asumir que esto protege frente a cualquier descarga
externa forzada.

El cargador usa rutas nuevas y un log exclusivo de una sola ejecución;
no puede cargar `arfoxia_probe.prx`, el prototipo que causó el error. Ambos
puntos de entrada nuevos retornan -4 por defecto, comprobado por desensamblado.
Los targets explícitos `build/arfoxia_dispatch_candidate_v1.prx` y
`build/dispatch_loader_candidate.elf` requieren el perfil privado y generan
artefactos distintos de las versiones desactivadas. No forman parte de `all`,
no tienen autoarranque ni un envío automático. Los transportes anteriores
permanecen bloqueados y el PRX fallido sigue conservado con nombre `.disabled`.

Se compilaron los candidatos con OpenOrbis/Clang/LLD y se validó el cargador
PIE sin relocaciones pendientes. Con el menú/BinLoader confirmados por el dueño,
se hizo **un único envío de v1**: `LOAD_RC 0`, `POST_RETURNED 1`, `NULL_STATE 1`
y `CALLBACK_COUNT 1`, sin excepción gestionada. Se conservaron el diagnóstico
bruto de kernel y los logs en almacenamiento privado. El dueño confirmó que
el menú siguió normal y respondió al mando, sin error del sistema.

`DIFFERENT_THREAD 0` no identifica por sí solo al hilo gráfico ni invalida el
despacho. La variante v2 añade identidad pthread no nula y consulta de solo
lectura `Sce.PlayStation.Core.Runtime.Diagnostics.get_IsMainThread(): bool`;
no ejecuta las aserciones `CheckRunningOnMainThread`/`AssertRunningOnMainThread`.
El perfil opcional `--core RUTA_CORE_PRIVADA` exige firma estática, cuerpo AOT y
GUID/MVID coincidentes antes de resolver tokens. Tiene targets, perfil y logs
separados; nunca se sustituye o recarga la instancia v1 pendiente de descarga.
El host también verifica la invocación gestionada anidada y desempaquetado de
un booleano dentro del callback, en Mono normal/full-AOT.

**v2 se ejecutó una sola vez:** `CORE_IS_MAIN_THREAD 1`, sin excepción y con
menú/mando normales confirmados por el dueño. Esta consulta sí identifica el
hilo gráfico; no demuestra todavía dibujo. No descargar módulos a la fuerza
ni eliminar sus logs/marcas para repetir una ejecución.

### Prueba de sprite pasivo y gestor de imágenes propio

`sprite_profile.py` verifica firmas, staticness y cuerpos AOT de los métodos
de aplicación, escena UI2, imagen, widget y geometría. Los tokens solo valen
para las bibliotecas con los GUID verificados. No se publican perfiles Sony.
`native/sprite_preview.h` valida tipo de escena y dimensiones antes de crear
un sprite estático existente, desactiva foco/respuesta táctil y programa su
retirada después de 15 segundos desde un worker independiente. Tanto la
inserción como la limpieza consultan propiedad del hilo UI. Un fallo de
despacho conserva raíces/módulo, no fuerza descarga ni hace llamadas UI
desde el worker. La retirada es best-effort, no una garantía contra fallos.

La primera prueba visual v3 llegó a la escena UI2 y decodificó el PNG 96×96,
pero no creó un widget: el registro identificó un gestor por defecto con
presupuesto cero que rechazaba los 36.864 bytes de imagen. La excepción
gestionada se capturó y la limpieza terminó; se preservó el diagnóstico bruto.
No se debe confundir `LOAD_RC 0` con «Arfoxia visible».

La variante v4 usa un **AssetManager propio de 256 KiB**, constructor
con nombre y presupuesto, comprueba `get_MaxSize` y carga con su propio
`LoadImageAsset(string)`. No reinicializa gestores del sistema ni desactiva
sus límites. La limpieza dispone únicamente el widget y gestor propios.

**v4 se ejecutó una vez en consola:** presupuesto 262.144, PNG 96×96,
inserción/retirada y limpieza completas, sin excepción gestionada. El dueño
confirmó menú/mando normales, pero no estaba mirando la pantalla durante los
15 segundos: **el dibujo visible todavía no está confirmado**. El diagnóstico
registró un aviso de imagen no dispuesta antes del gestor propio.

La variante v5 añade `AssetProxy.Dispose(): void` para liberar explícitamente
la imagen propia después de retirar/disponer el widget y antes de liberar
raíces GC o el gestor. El contrato heredado se verifica offline, sin buscar
clases globalmente ni descargar instancias previas. Usa rutas, logs y targets
nuevos (`build/arfoxia_sprite_candidate_v5.prx`,
`build/dispatch_loader_dispose.elf`); no debe reenviarse v4.

**v5 también se ejecutó una sola vez:** inserción, retirada, disposición
explícita de imagen y gestor completas (`PREVIEW_CLEANED 1`), sin excepciones
gestionadas. El diagnóstico bruto ya no contiene el aviso de imagen pendiente
observado en v4 ni marcadores de fallo Mono. Esto prueba la secuencia de APIs,
no por sí solo que el sprite se haya dibujado sobre el menú visible; se necesita
confirmación física del dueño antes de habilitar una mascota persistente.
El dueño confirmó posteriormente que **v5 sí apareció y desapareció en pantalla**
y el menú/mando permanecieron normales. Era deliberadamente un PNG estático,
no la mascota animada completa.

### Primera animación nativa (v6)

La variante experimental v6 usa `UI2.AnimationImageBox`, derivada de `UI2.Widget`,
con constructor, asignación de imagen, ancho/alto/cantidad de fotogramas,
intervalo, Start/Stop y cuerpos AOT comprobados offline. El perfil sustituye
el ImageBox estático solo en esta variante; no reutiliza tokens de otra clase.
Requiere gestor propio y disposición explícita de la imagen.

Reutiliza **sin modificar** `assets/external/pmd/default/Walk-Anim.png`: hoja
128×320, cuatro fotogramas horizontales de 32×40 y ocho filas de dirección.
El ciclo frontal utiliza el orden Normal por defecto y 166,67 ms por fotograma
(6 fps). La geometría de presentación respeta su proporción 32:40. La hoja
RGBA ocupa 163.840 bytes dentro del presupuesto propio de 256 KiB.
Se delegó el avance al motor del menú: no se hizo un Post nativo por frame,
ni hooks, escrituras de memoria o actualizaciones UI desde el worker.

Se prueba caminar **en el sitio**, todavía sin desplazamiento por el escritorio,
menús de interacción o viajes persistentes. Tras 15 segundos, el callback UI
detiene la animación antes de retirar/disponer widget, imagen y gestor propios.
Los targets `build/arfoxia_sprite_candidate_v6.prx` y
`build/dispatch_loader_animation.elf` tienen rutas/logs nuevos y quedan fuera
de `all` y autoarranque. El generador usa `--animated` junto a las opciones de
gestor/limpieza y escribe el perfil privado
`ports/ps4/build/dispatch_sprite_animation_profile.h`. La animación visual
requiere otra confirmación física; el sprite estático validado no la demuestra.
En consola v6 se envió una sola vez y registró hoja 128×320, configuración,
Start, Stop, retirada y limpieza completas sin excepción. El diagnóstico bruto
no contiene nuevos marcadores fatales de Mono o imágenes sin disponer. Estos
registros no sustituyen la comprobación visual de que los frames avanzaron.
El dueño confirmó después que **v6 no se animó visualmente**, aunque se retiró
y el menú/mando siguieron normales. No se considera esta vía validada. El
Update del elemento depende del ciclo/tiempo del menú; los registros no aíslan
cuál de esos mecanismos no avanzó. No se fuerza `Application.Update` ni se
parchea el reloj global para corregirlo.

### Fotogramas controlados y acotados (v7)

v7 vuelve al ImageBox estático que ya dibujó en consola. `frame_assets.py`
extrae los cuatro fotogramas frontales de Walk preservando sus píxeles,
sin tocar la hoja original, y escribe PNG/manifiesto en una carpeta nueva
exclusiva. Comprueba dimensiones, fotogramas distintos y conserva SHA256.
Los cuatro frames RGBA suman 20.480 bytes dentro del gestor propio de 256 KiB.

El worker adjunto a Mono solo encola hasta 90 cambios a intervalos de 166,67 ms
(15 segundos), con **un único callback pendiente** por guarda atómica. Si el
menú se retrasa, se salta ese slot; no se acumula una cola de animación.
Cada callback consulta propiedad del hilo UI y cambia únicamente la imagen
del widget propio. Error o hilo incorrecto detienen los cambios. La limpieza
activa parada antes de retirar el widget y dispone cada fotograma antes del
gestor. Callbacks tardíos se vuelven no-op; se retienen raíces de delegado y
PRX para evitar descargar código pendiente. No se llama el ciclo global UI.

Los targets nuevos son `build/arfoxia_sprite_candidate_v7.prx` y
`build/dispatch_loader_scheduled.elf`. El perfil privado usa
`--scheduled-frames --own-image-manager --dispose-image-asset` y salida
`build/dispatch_sprite_scheduled_profile.h`; rechaza combinarlo con `--animated`.
El fixture propio de host verificó 91 callbacks con reencolado acotado y
consultas/argumentos dentro del hilo propietario, normal y full-AOT.
El éxito del host no demuestra animación visible ni compatibilidad Sony.
v7 se ejecutó una vez: cuatro imágenes cargadas, **90 cambios de imagen** en
callbacks del hilo UI, retirada y disposición de todos los frames/gestor sin
excepción. El dueño confirmó estabilidad, pero no estaba mirando el monitor;
el movimiento sigue sin confirmación visual.

Para facilitar esa comprobación, v8 mantiene la misma cola acotada pero durante
**60 segundos / 360 slots**. Usa `ImageBox.set_ImageScaleType(AspectInside)`
(valor 2 verificado en la biblioteca privada) para ampliar las imágenes al
área 192×240 preservando proporción; no modifica sus píxeles ni el presupuesto.
Tiene rutas/logs y targets distintos (`build/arfoxia_sprite_candidate_v8.prx`,
`build/dispatch_loader_visible.elf`); el perfil privado añade `--visible-test`
y se guarda como `build/dispatch_sprite_visible_profile.h`. No forma parte
de `all` ni convierte el experimento en mascota persistente. Solo se envía
tras confirmar que el dueño está observando la PS4 en el menú, sin juegos.

**v8 validada visualmente por el dueño:** Arfoxia ampliada y animada, retirada
al terminar el minuto, menú/mando normales. Registros: presupuesto propio
262.144, cuatro imágenes 32×40, AspectInside 2, 360 cambios de imagen y
disposición de widget/cuatro frames/gestor completas, sin excepción. El
diagnóstico bruto no contiene nuevos marcadores fatales de Mono o imagen
pendiente. Se preservan PRX/raíces de callback y logs; no se recarga/descarga
el módulo para repetir la prueba. La validación cubre caminar en el sitio
durante un minuto, **no desplazamiento, interacciones, viajes/autoarranque,
permanencia ni aparición en juegos**.

### Sesión controlada desde el PC (v9)

v9 añade caminar con desplazamiento en dos ejes, sentarse, quedarse quieta y
retirarse. Se mantienen el foco/respuesta táctil desactivados y el hilo UI
verificado antes de cambiar imágenes o posición. La trayectoria rebota dentro
de los límites comprobados del monitor y de una franja inferior; diez imágenes
precargadas (derecha/izquierda/sentarse/quieta) ocupan 51.200 bytes RGBA,
todavía dentro del gestor propio de 256 KiB. La pose de sentarse conserva sus
píxeles en una celda transparente alineada por abajo.

El panel de PC `lease_control.py` tiene botones Caminar, Sentarse, Quieta y
Retirar. No envía payloads, instala plugins, lee chats ni exporta herramientas
del PC: solo actualiza `control-v9.txt` por el FTP ya habilitado. El protocolo
ASCII es acotado (22 bytes), admite únicamente cuatro modos y exige contador
creciente. El escritor verifica bytes antes de reemplazar atómicamente este
archivo propio; conserva archivos desconocidos o temporales interrumpidos.

La señal se renueva cada dos segundos y el cliente se retira cuando caduca
(aproximadamente diez segundos), llega Stop, hay datos inválidos o cambia la
identidad de la escena raíz. La prueba tiene además un máximo de cinco minutos.
El detector de escena **no demuestra detección fiable de un juego en primer
plano**: solo se usa con menú confirmado y sin juegos; retirar antes de jugar.
No se inventan firmas de APIs de foreground ni se aplican hooks/autoarranque.

```sh
python -m ports.ps4.lease_control --host IP_PRIVADA_PS4 --panel
# Demostración de un minuto: caminar, sentarse, quieta, caminar y Stop.
python -m ports.ps4.lease_control --host IP_PRIVADA_PS4 --panel --demo
```

El panel requiere un cliente ya cargado. **Por sí solo no instala ni reinicia
la mascota**, y su indicación «señal enviada» no confirma dibujo. v9 es una
prueba de una sesión: tras Stop/caducidad termina el worker y se conserva el
PRX por seguridad; no recargarlo o borrar marcas para reiniciar. Los botones
se deshabilitan al acabar. Cerrar el panel intenta Stop, con caducidad como
respaldo. Reanudación, sesiones repetidas y botón Viajar de Windows siguen
pendientes. No se habilita un destino PS4 permanente en `TravelManager`.

Los targets `build/arfoxia_sprite_candidate_v9.prx` y
`build/dispatch_loader_resident.elf` requieren un perfil privado generado con
`--resident-client` además de los flags de v8. `frame_assets.py --client-assets`
prepara las diez imágenes sin modificar las fuentes. Los tests C usan la
implementación real de lease con kernel simulado: renovación, replay, archivo
ausente/inválido, caducidad y Stop; el movimiento pasó 300.000 pasos acotados.

**v9 validada visualmente:** el dueño vio desplazamiento, sentarse, quieta y
retirada, con menú/mando normales. Registros de las órdenes 1→2→3→1→0, limpieza
de las diez imágenes/gestor y ausencia de excepciones. Diagnóstico bruto privado
sin nuevos marcadores fatales/imagen pendiente. Se conservaron los artefactos
exactos enviados; el helper de lease se aisló después para pruebas de fallo,
sin volver a enviar una instancia. Esta evidencia no convierte la sesión de
prueba en cliente persistente para juegos o arranque automático.

```sh
python ports/ps4/sprite_profile.py \
  --pui RUTA_PUI_PRIVADA --corlib RUTA_CORLIB_PRIVADA --core RUTA_CORE_PRIVADA \
  --own-image-manager --output ports/ps4/build/dispatch_sprite_manager_profile.h
```

Para v5 se añade `--dispose-image-asset` y la salida privada es
`ports/ps4/build/dispatch_sprite_dispose_profile.h`.

Los targets `build/arfoxia_sprite_candidate_v4.prx` y
`build/dispatch_loader_manager.elf` son explícitos y ajenos a `all`/autoarranque.
Tienen rutas/logs nuevos y exclusivos. El host prueba argumentos float, bool,
string/referencia y un segundo callback desde un worker Mono adjunto, también
en full-AOT. Esto **no valida el renderer PS4**. Cada prueba física requiere
menú operativo confirmado, BinLoader activo y un único envío sin reintentos.
El sprite estático temporal sí se vio; las animaciones completas y la integración
persistente siguen pendientes. No se habilitan viajes a PS4 ni pruebas en juegos.

### Sesiones repetibles (v10/v11, repetición visual confirmada)

v10 separa **Retirar** de finalizar el cliente. Un único widget y las diez
imágenes ya verificadas se crean una vez; Retirar/caducidad lo oculta sin
recargar PRX, disponer y recrear objetos, ni cambiar callbacks entre sesiones.
Solo **Mostrar / Iniciar nueva sesión** puede abrir un identificador mayor.
Un heartbeat de una sesión retirada o caducada nunca la vuelve a mostrar.
**Finalizar prueba / Liberar recursos** termina el worker y solicita la limpieza
definitiva, incluso estando oculta; cerrar el panel también la solicita para la
última sesión propia. Una sesión de otro controlador no puede finalizarse.
La posición se conserva entre sesiones y no se aumenta el presupuesto de imagen.

El cliente arranca oculto. La primera orden válida establece una referencia
sin activarlo, incluso si un archivo antiguo pedía caminar. El protocolo nuevo
`ARFOXIA10` contiene secuencia, sesión y modo en exactamente 34 bytes; no acepta
rutas, comandos ni acciones arbitrarias. Datos inválidos finalizan la prueba;
archivo ausente deja caducar la señal. El modo adicional `finish` solo solicita
limpieza propia; no es un comando arbitrario. Otra sesión sustituida no puede ser
sobrescrita por el panel anterior. El panel empieza sin enviar órdenes, comprueba
el log propio de disponibilidad y exige acuse del identificador de sesión nuevo
antes de mantener su señal. Un log histórico o FTP operativo no basta. Si falta
acuse, no envía heartbeats y deja caducar la orden, sin reenvío automático.
No intenta recargar ni reconectar tras un fallo.
La disponibilidad y «orden enviada» **no son prueba de dibujo en el televisor**.

```sh
python -m ports.ps4.repeat_control --host IP_PRIVADA_PS4 --panel
# Solo tras una carga v10 independiente, controlada y confirmada en el menú.
```

Cada sesión sigue limitada a 1.800 slots (~5 minutos), lease de 60 slots
(~10 segundos); el cliente entero a 5.400 slots (~15 minutos desde cargarlo,
incluida la espera oculto). Son tiempos nominales a 6 Hz, no un reloj de tiempo
real garantizado. Al finalizar se retiran/disponen los recursos gráficos propios;
el módulo y las raíces de callbacks se conservan por seguridad. No hay una nueva
carga automática al llegar al límite. La nueva variante usa rutas/logs v10 y
no altera los artefactos ni las marcas de las pruebas anteriores.

Se mantiene la comprobación del hilo gráfico y de identidad de la escena antes
de mostrar/ocultar/mover. **No es detección de juego en primer plano**: sigue
siendo solo para menú sin juegos, sin autoarranque ni integración Viajar.
El target explícito `build/arfoxia_sprite_candidate_v10.prx` y su cargador
requieren `dispatch_sprite_repeatable_profile.h`, generado con las mismas opciones
de `sprite_profile.py` de v9 (`--resident-client` y dependencias); no hay nuevas
firmas de API ni reflexión de sistema. El flag `ARFOXIA_PS4_REPEATABLE_CLIENT`
está desactivado en compilaciones normales.

Validación offline: tests C del mismo motor de sesiones (referencia inicial,
replay, retirada, caducidad, reinicio explícito, límites, datos inválidos y
10.000 ciclos de 99 inicios/retiradas, finalización manual oculta/activa),
tests Python de formato/FTP, acuse nuevo frente a log histórico y compilación
con OpenOrbis/Clang/LLD y cargador PIE. 1.050 pruebas Python pasan.

**v10 enviada una sola vez:** dos sesiones aceptadas con la misma carga;
el log del hilo UI registra mostrar→ocultar→mostrar→ocultar. La orden Finalizar
terminó el worker y se dispusieron widget, diez imágenes y gestor propio, sin
excepción gestionada. Se conserva el diagnóstico privado y no se recarga la
instancia terminada. El dueño no estaba mirando la pantalla: **no hay aún
validación visual de las dos sesiones ni confirmación física posterior de
estabilidad para esta versión**. No confundir los registros con esa confirmación.

El dueño solicitó repetirla al no haber visto v10. Se preparó **v11 con el
mismo motor**, rutas/marcas independientes y revisión de compilación explícita
(`ARFOXIA_TRIAL_REVISION=11`); no se recargó ni se borró el estado de v10.
Las rutas de PRX, control y ambos logs se comprueban en tests C para v10/v11.
Tras confirmar de nuevo menú/BinLoader y presencia ante la pantalla, hubo un
único envío: dos sesiones aceptadas, mostrar→ocultar→mostrar→ocultar, finalización
y disposición completa del widget, diez imágenes y gestor, sin excepción.
**El dueño confirmó las dos apariciones, retirada final y menú/mando normales.**
No equivale todavía a cliente permanente, autoload o compatibilidad con juegos.
El panel usa las rutas v10 por defecto. `--revision 11` selecciona únicamente
los archivos de control de la prueba v11; no prepara, carga ni repite payloads.

### Acceso desde la ventana Paseo de Windows

«Paseo entre dispositivos» incluye **PS4 · GoldHEN · menú experimental**.
Seleccionarla ofrece **Abrir control experimental de PS4**, no el envío SSH de
Bazzite. Una ventana explica los requisitos y permite introducir la IPv4 privada
de la consola y elegir el cliente revisado v10/v11. La IP y revisión se guardan
en `ps4-menu-control.json` dentro de los datos locales de Arfoxia; no se publican.

El clic explícito abre el panel de sesiones, inicialmente sin emitir órdenes.
Requiere un cliente cargado y todavía activo: **no reinicia las pruebas ya
finalizadas ni envía payloads**, y no establece una lease en `TravelManager`,
oculta la mascota del PC o anuncia una conexión por el mero hecho de seleccionar
la entrada. No equivale todavía a «viajar a PS4» permanentemente. El botón
«Volver a este PC» sigue siendo el retorno del viaje SSH; para retirar de la
prueba PS4 se usa Retirar/Finalizar en su panel independiente.

## Investigación offline después del fallo

La consola volvió al menú y responde al mando, según confirmó el dueño.
Se han analizado copias privadas de las bibliotecas de **su propia consola**
por FTP de solo lectura, sin enviar otro payload ni modificar el sistema.
Esas bibliotecas y los informes completos no se publican.

La búsqueda de clases/métodos se ha trasladado a `offline_metadata.py`: lee
metadata ECMA-335 embebida en un archivo local, sin Mono, dependencias externas,
ejecución de bibliotecas ni conexiones de red. Limita archivo, streams, tablas,
cadenas, firmas y profundidad; rechaza raíces ambiguas y marca las firmas no
soportadas como desconocidas en lugar de inventarlas. Los tokens corresponden
al archivo analizado, **no son offsets de memoria ni contratos universales**.

```sh
python ports/ps4/offline_metadata.py RUTA_BIBLIOTECA_PRIVADA
python ports/ps4/offline_metadata.py RUTA_BIBLIOTECA_PRIVADA --type NAMESPACE.CLASE
```

Comprobaciones offline en firmware 12.52:

| Biblioteca | Clase existente | Firma relevante |
| --- | --- | --- |
| PUI | `Sce.PlayStation.PUI.Application` | `get_Instance()` estático; `get_RootScene()` de instancia |
| PUI | `Sce.PlayStation.PUI.UISynchronizationContext` | `Post(System.Threading.SendOrPostCallback, object)` de instancia |
| app | `Sce.Vsh.ShellUI.AppSystem.LayerManager` | `FindContainerSceneByPath(string)` estático |

También existen `UI2.Widget`, `UI2.Panel` y `UI2.ImageBox`. No aparece
`UI2.ImageAsset` en la tabla TypeDef de PUI analizada: no se presume su
existencia en ese namespace. La existencia de `Post` **no demuestra todavía**
que podamos capturar el contexto UI correcto ni crear un callback compatible
con el runtime AOT. El texto de una cadena suelta tampoco demuestra que sea
un método público invocable.

La sonda nativa conserva su retorno inmediato de cuarentena. Se retiraron
por completo `mono_class_from_name`, enumeración de métodos y generación de
firmas dentro del callback de `mono_assembly_foreach`. El código restante es
solo un inventario limitado, con checkpoints sincronizados a disco; no se ha
vuelto a cargar. Los helpers FTP directos también rechazan staging/verificación
con renombrado mientras siga la cuarentena, no solo la CLI y el envío TCP.

El fallo exacto de Mono sigue sin backtrace conservado que permita atribuirlo
a una llamada concreta. Esta revisión elimina una ruta de inspección arriesgada,
pero **no establece que el error esté resuelto en consola**. Antes de renderizar
se necesita validar el despacho al hilo UI sin desactivar sus comprobaciones,
y una prueba visual real del overlay. No hay mascota PS4 operativa todavía.

Formato de metadata: [ECMA-335, partición II](https://ecma-international.org/publications-and-standards/standards/ecma-335/).
El runtime AOT conserva metadata/cache además de código precompilado, según
la [documentación de Mono](https://www.mono-project.com/docs/advanced/runtime/docs/aot/).

## Arquitectura propuesta

GoldHEN permite cargar un PRX propio en `SceShellUI` mediante su SDK publicado.
ShellUI utiliza Mono y widgets PUI: antes de portar el renderizador se consultan
los nombres y firmas de las clases disponibles en la consola concreta.
No se asumen direcciones de otro firmware ni se anula la comprobación del hilo
principal de PUI. El futuro renderizador necesita un mecanismo real de despacho
al hilo UI y confirmación visual, no solo un identificador de módulo cargado.

`native/probe.c` enumera metadata Mono y escribe como máximo 128 KiB en
`/user/data/Arfoxia/probe.txt`. Solo funciona dentro de `SceShellUI`, con ABI
GoldHEN SDK 1.00. No crea widgets, no hace hooks ni escribe memoria de código.
`native/loader.c` carga exclusivamente `/data/Arfoxia/arfoxia_probe.prx` en ese
proceso y guarda `load.txt`; comprueba tanto el resultado del syscall como el
handle, inicialmente marcado como inválido. No ejecuta el comando jailbreak.

**Experimental:** cargar código en ShellUI puede bloquear el menú o requerir
reiniciar la consola. No se instala como plugin persistente, no se prueba en
juegos y no se cambia `plugins.ini`. No debe reenviarse mientras siga cargado.
La disponibilidad de FTP/BinLoader no demuestra compatibilidad del overlay.

## Compilación aislada en Linux

Dependencias externas, fuera del repositorio:

- [OpenOrbis PS4 Toolchain](https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain),
  release v0.5.4, archivo `toolchain-llvm-18.tar.gz`. SHA256 publicado y verificado:
  `3c7cd5bb593ca74fa1c13fd59f3938dc0fc07985167f7275063019e63abe4526`.
- [GoldHEN Plugins SDK](https://github.com/GoldHEN/GoldHEN_Plugins_SDK),
  revisión probada `bcea3c7ef01dac6d7f9f49ebf9e90fe66d86f5f7`. Solo se usa su CRT
  y el ABI de carga; no se enlaza el motor de hooks.
- [Scene-Collective payload SDK](https://github.com/Scene-Collective/ps4-payload-sdk),
  revisión probada `b7326416c23ce14639e9180a24093bdc5eedb579`.
- Clang/LLD 18, GCC, GNU make, binutils y Python 3. Compilación validada en un contenedor rootless
  Ubuntu 24.04, sin instalar compiladores ni capas en el SO inmutable Bazzite.

```sh
make -C /ruta/ps4-payload-sdk/libPS4
make -C ports/ps4 \
  OO_PS4_TOOLCHAIN=/ruta/OpenOrbis/PS4Toolchain \
  PAYLOAD_SDK=/ruta/ps4-payload-sdk \
  GOLDHEN_SDK=/ruta/GoldHEN_Plugins_SDK
```

Genera `build/arfoxia_probe.prx` y `build/arfoxia_probe_loader.bin`.
El cargador se enlaza como PIE sin intérprete dinámico. `pack_payload.py`
rechaza ET_EXEC, relocaciones pendientes, dependencias compartidas, solapamientos
y tamaños inválidos; materializa BSS a cero antes de generar el binario plano.
En la prueba de construcción aislada, Python 3 del host hizo este último paso:
`python3 pack_payload.py build/loader.elf build/arfoxia_probe_loader.bin`.
No publicar SDKs, bibliotecas propietarias, directorios `.git`, binarios de
desarrollo ni logs de una consola. `build/` está excluido de Git.

## Transporte deshabilitado; estado de solo lectura

`stage` y `send` están bloqueados **antes de abrir cualquier conexión**, también
en la función de envío directa. No hay opción `--force`. Los puntos de entrada
de PRX y BIN retornan antes de llamar al SDK/Mono (`ARFOXIA_PS4_PROBE_QUARANTINED`).
No cargar binarios anteriores: la lectura de metadata provocó un fallo del
software del sistema. La compilación actual es solo para investigación offline.
El comando `status` conserva lectura acotada de los logs propios por FTP.

### Protocolo histórico de prueba (no ejecutar stage/send)

Activar FTP y BinLoader en GoldHEN y dejar la consola en el menú de inicio.
`--host` debe ser la dirección verificada del dispositivo del dueño.

```sh
python ports/ps4/probe_transport.py stage --host DIRECCION_PS4
python ports/ps4/probe_transport.py send --host DIRECCION_PS4 --home-menu
python ports/ps4/probe_transport.py status --host DIRECCION_PS4
```

- `stage`: solo carpeta propia `/data/Arfoxia`; nunca sobreescribe un archivo
  existente. Verifica bytes antes de renombrar a `.prx`, ya que GoldHEN puede
  auto-descifrar PRX/SELF en una descarga FTP normal.
- `send`: verifica nuevamente el archivo y abre **una sola conexión** al puerto
  9090, con el payload real. No hace un ping vacío ni reintentos automáticos.
  Rechaza una carga si ya hay un log o una verificación interrumpida. La marca
  `--home-menu` declara la comprobación física; no detecta por sí sola un juego.
- `status`: FTP de solo lectura para los dos logs propios, con límites de tamaño.
  Nunca abre BinLoader; «enviado» no equivale a «ejecutado» ni a «mascota visible».

Si una conexión vacía hace que el cargador deje de escuchar, desactivar y
reactivar BinLoader en la consola antes del envío real. No intentar solventarlo
instalando plugins ajenos, cambiando offsets o alterando configuraciones.

### Resultado de diagnóstico en consola (12-10-2026)

GoldHEN confirmó recepción y lanzamiento del primer BIN. El log de kernel
registró un fallo de lectura en `0x1520`: correspondía exactamente a la variable
`libKernelHandle` del SDK. El enlace ET_EXEC había relajado la referencia PIC a
un inmediato absoluto. No hubo `load.txt` ni `probe.txt`: el fallo estaba en
`initKernel`, antes de pedir la carga del PRX en ShellUI.

Corregido el enlace a ET_DYN/PIE, el desensamblado confirmó referencias relativas
RIP y ausencia de relocaciones pendientes. El registro se escribe primero en
`/user/data/Arfoxia/`, con fallback `/data/`. Ajustado el helper a la entrada
indirecta del SDK: `RAX=0, RDI=500, RSI=comando, RDX=datos`.

En consola se confirmó `RAW 256 CARRY 1`: la versión exacta SDK 1.00 llega con
carry activado. Solo esa firma en comando 0 se acepta como versión; no se
convierten arbitrariamente errores de otros comandos en éxito. El cargador
registró `LOAD_RC 0 HANDLE 0`, y la sonda confirmó proceso `SceShellUI` y firmware
`12520001` (12.52). Recogió nombres de ensamblados, pero no terminó: el registro
de kernel mostró un fallo de Mono y el dueño observó **CE-36329-3**. No se ha
demostrado todavía qué llamada concreta de metadata falla. No hubo renderizado.

Se detuvieron las cargas y se puso el prototipo en cuarentena. No se modificaron
plugins.ini, juegos, firmware ni datos de usuario; solo la carpeta propia de
diagnóstico. Los logs y versiones anteriores propios se conservaron como
respaldo. No se aplican actualizaciones ni inicialización/restablecimiento de
la consola como solución al fallo causado por la sonda.
El PRX exacto de la prueba se renombró, con verificación SHA256, a
`/data/Arfoxia/arfoxia_probe.failed.disabled`. No se borró y ya no existe la ruta
`arfoxia_probe.prx` que intentaban cargar los BIN anteriores.

## Referencias y licencias

La vía Mono/PUI se investigó a partir de
[ps4-thumbgrid-ime](https://github.com/Zenalios/ps4-thumbgrid-ime), revisión
`9e4fbc9f39f207ce4f08f1ec635bca5fa5bb90f1` (MIT). No se incorpora su parche a
`CheckRunningOnMainThread`: no es un despacho UI seguro.

Las dependencias conservan sus licencias en sus repositorios originales.
No se incluyen recursos Sony ni SDKs completos en este directorio. La atribución
del diseño de estructuras ABI está en [NOTICE.md](NOTICE.md).
