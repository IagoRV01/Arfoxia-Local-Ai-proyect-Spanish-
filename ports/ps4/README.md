# Cliente PS4: investigación del menú ShellUI

Estado: **sonda en cuarentena tras CE-36329-3; cargas en consola deshabilitadas**.
La mascota/renderizado PS4 todavía no están implementados ni validados.
No es un cliente GTK ni una aplicación a pantalla completa disfrazada de overlay.
La prueba está limitada al menú de inicio, sin juegos abiertos. No habilita
viajes a PS4 en la interfaz Windows hasta verificar un cliente que dibuje.

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
