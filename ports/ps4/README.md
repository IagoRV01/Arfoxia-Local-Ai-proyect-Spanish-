# Cliente PS4: investigación del menú ShellUI

Estado: **sonda antigua en cuarentena; callback e hilo gráfico validados;
prueba temporal de imagen preparada, renderizado visible todavía pendiente**.
La mascota PS4 completa todavía no está validada.
No es un cliente GTK ni una aplicación a pantalla completa disfrazada de overlay.
La prueba está limitada al menú de inicio, sin juegos abiertos. No habilita
viajes a PS4 en la interfaz Windows hasta verificar un cliente que dibuje.

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
La mascota visible, las animaciones y la integración persistente siguen
pendientes; no se habilitan viajes a PS4 ni pruebas en juegos.

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
