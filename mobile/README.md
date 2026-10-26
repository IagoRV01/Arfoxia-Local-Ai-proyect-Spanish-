# Arfoxia para Expo Go

Aplicación nativa de Arfoxia para iPhone. Se conecta a la API local del PC a
través del HTTPS privado de Tailscale; no usa Safari ni publica el servicio en
Internet.

## Abrirla en el iPhone

1. Usa Expo Go compatible con **SDK 58** e inicia sesión en la app.
2. En el PC, desde la carpeta `mobile`, ejecuta `npx expo login --browser` e
   inicia sesión con **la misma cuenta**. Solo hace falta repetirlo si caduca
   o se cierra la sesión. No guardes credenciales de Expo en el proyecto.
3. Mantén Tailscale conectado en el PC y en el iPhone.
   Si Expo da tiempo agotado aunque ambos estén conectados, ejecuta una vez
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/configure_expo_firewall.ps1`
   desde PowerShell como administrador
   en la raíz del proyecto. Crea una regla TCP 8081 limitada a Node.js, la
   interfaz Tailscale y sus direcciones privadas, independientemente del perfil
   público/privado de Windows. No abre el puerto en Ethernet/Wi-Fi. Admite
   `-WhatIf`, `-Port` si cambias el puerto y `-Disable` para retirar solo esa regla.
   La política de ejecución se aplica solo a ese proceso; no cambia la de Windows.
4. Abre Arfoxia en el PC. El servidor de Expo se iniciará automáticamente en
   cuanto Tailscale esté listo.
5. Abre el servidor de desarrollo de Arfoxia en Expo Go. Si ha desaparecido
   de recientes, vuelve a abrir su enlace `exp://<MagicDNS-del-PC>:8081` o
   escanea el QR de Expo con la Cámara del iPhone.
6. Si la app aún no está emparejada, pulsa **Escanear QR de Arfoxia**.
7. En el PC, haz clic derecho sobre Arfoxia y elige **Emparejar iPhone**; escanea
   ese segundo QR desde la app.

Arfoxia anuncia Metro mediante el MagicDNS privado de Tailscale y lo reinicia si
se cierra. Expo Go 57 y posteriores en iOS exigen autenticación en ambos dispositivos; el
arranque ya no fuerza el modo `--offline`, para registrar la sesión de
desarrollo con Expo. El tráfico de Arfoxia continúa por Tailscale, sin túnel
público de Expo. El QR de emparejamiento conecta de forma privada la app con la API
de Arfoxia. La clave solo se almacena en SecureStore, que utiliza el llavero
cifrado de iOS.

## Funciones

- Estado, alimentación, caricias, juego, sueño y despertar.
- Chat con el modelo local y fuentes HTTPS.
- Varias conversaciones compartidas con el PC: crear, cambiar, renombrar,
  eliminar y cargar historial antiguo por páginas.
- Sincronización automática al volver a primer plano y conservación del
  historial ya visible cuando el PC queda temporalmente sin conexión.
- Modo explícito de investigación intensiva.
- Envío de hasta cuatro fotos, PDF, texto o archivos de código.
- Adjuntos, fuentes, modelo utilizado y capturas conservados en cada mensaje;
  las imágenes históricas se abren con autenticación privada.
- Conversión de imágenes de iPhone a JPEG compatible antes de subirlas.
- Estado de CPU, RAM, GPU, VRAM, juego detectado y modelo adaptativo.
- Modo manual **Dual · Qwen3.8 27B Extra High** desde la pestaña PC, usando ambas
  GPU: presupuesto de 16 + 5,5 GiB, contexto 32K y avisos cada 20 segundos.
  Hay que liberar el modelo manualmente antes de jugar; no se descarga solo.
  Conserva los otros tres perfiles. Consulta [la configuración Dual](../docs/DUAL_GPU.md).
- Estado de control privado sin contraseña, herramienta PowerShell y permisos
  reales de administrador cuando el propietario los habilita localmente.
- Captura autenticada del monitor, apertura de aplicaciones permitidas y
  liberación manual de VRAM.
- Botón fijo **🎮 Jugar · PC / BC-250** con estado de Sunshine y Tailscale, copia del
  host privado, confirmación segura del PIN de Moonlight y acceso a la app.
- Desemparejamiento que borra la clave del llavero.

### Sunshine de la BC-250

**Jugar · PC / BC-250** permite elegir **Este PC** o **BC-250** antes de consultar
el estado o enviar el PIN de Moonlight. La BC-250 aparece si está registrada con
el identificador `bc250` en Paseo entre dispositivos y su alias OpenSSH funciona.
No se elige un equipo arbitrario por URL ni se cambia de destino automáticamente.

1. En Windows, menú de Arfoxia → **Configurar Sunshine de la BC-250…**, o pulsa
   **Autorizar Sunshine en Windows** desde la app. Introduce la cuenta del panel
   de Sunshine, no la de Bazzite. Se valida por SSH antes de guardarla protegida
   con DPAPI, separada de la cuenta del Sunshine de Windows. No se restablece
   ninguna contraseña ni se modifican los clientes ya vinculados.
2. En Moonlight, selecciona la BC-250 e inicia el emparejamiento. Copia las cuatro
   cifras a Arfoxia → **Jugar · PC / BC-250** → **BC-250** → **Emparejar**.
   Ya no tienes que introducirlas en el panel web de Sunshine. iOS no permite
   leer automáticamente el PIN de otra app: escribirlo en Arfoxia sigue siendo
   necesario. Los clientes ya emparejados no necesitan repetirlo.
3. Arfoxia envía el PIN por SSH al servicio local de la BC-250; no abre su panel
   en Internet ni almacena PINs. Si está activada la protección local de acciones,
   la solicitud se autoriza en Windows con el destino exacto; respeta también la
   opción local del propietario que desactiva esa confirmación.

El contador de clientes es el total guardado por Sunshine, no una afirmación de
que el móvil actual esté emparejado. Un PIN aceptado exige comprobar la conexión
en Moonlight; un error al refrescar el estado no vuelve a enviar el PIN.
Sunshine debe estar activo en la BC-250: el botón no reinicia ni reconfigura su
servicio. Para jugar fuera de casa, Tailscale debe estar conectado también allí;
sin esa conexión se muestra la dirección de la LAN y una advertencia. El PC de
Arfoxia debe permanecer encendido para actuar como puente de control.

## Jugar con Sunshine y Moonlight

1. Instala la app oficial
   [Moonlight Game Streaming](https://apps.apple.com/es/app/moonlight-game-streaming/id1000551566).
2. La primera vez, usa el iPhone en la misma Wi‑Fi que el PC. Pulsa
   **🎮 Jugar · PC / BC-250**, elige **Este PC**, copia el host que muestra Arfoxia y añádelo con **+**
   dentro de Moonlight.
3. Escribe en Arfoxia las cuatro cifras que enseña Moonlight. El PIN viaja a la
   API autenticada de Arfoxia; las credenciales administrativas de Sunshine no
   salen del PC. La primera vinculación exige además aprobar la solicitud
   privada en Windows; después no hay que repetirla para jugar.
4. Crea en la app Atajos un atajo llamado exactamente **Abrir Moonlight** con
   la acción **Abrir app → Moonlight**. El botón **Abrir con Atajo** podrá
   ejecutarlo desde Expo Go. Si no existe, usa **Instalar / abrir Moonlight** y
   pulsa **Abrir** en la ficha oficial.

Moonlight para iOS no publica un enlace profundo que permita a Expo Go abrir un
equipo o juego concreto. Por eso la selección final del PC o de **Desktop/Steam
Big Picture** se realiza dentro de Moonlight. Fuera de casa, conecta Tailscale y
usa el mismo host ya emparejado. Encender un PC apagado desde otra red requiere
un segundo dispositivo siempre activo en casa que haga de relé Wake-on-LAN.
Si Arfoxia queda temporalmente sin conexión, la pantalla offline conserva el
botón **Abrir Moonlight** para entrar al cliente ya emparejado.

## Visualizador de resultados

La pestaña **Visor** muestra los proyectos guardados en la carpeta Arfoxia del PC.
El chat añade **Ver resultado** tras herramientas correctas relacionadas con
archivos existentes. La vista nativa admite HTML/Three.js interactivo, imágenes,
PDF en iOS y lectura de texto/código. **Recargar** obtiene los archivos actuales;
**Cerrar** vuelve sin crear otra conversación ni detener trabajos.

Usa HTTPS privado de Tailscale, con permisos de lectura de 30 minutos que no
exponen la clave de la API. No ejecuta programas Windows ni backends Python en
el iPhone. Los proyectos con bibliotecas CDN requieren Internet. Consulta
[formatos, límites y seguridad](../docs/PROJECT_VIEWER.md).

## Comprobaciones de desarrollo

```powershell
npm run typecheck
npm test
npx expo-doctor@latest
npx expo export --platform ios
```

La app utiliza Expo SDK 58, React Native 0.88 y React 19.3. Una actualización
futura de Expo Go puede exigir otra migración de SDK; actualizar la app de
Expo Go no modifica por sí solo este proyecto. La migración no borra
los chats del PC ni cambia el identificador de la app o sus claves SecureStore.
Una app iOS independiente requerirá más adelante una cuenta del Apple Developer
Program y una compilación EAS/TestFlight.

## Mantenimiento automático en el PC del propietario

Se ha configurado una automatización local de Codex, **Mantener Arfoxia compatible
con Expo Go**, que revisa cada seis horas las versiones estables y el soporte
oficial del cliente iPhone. Migra las dependencias, corrige incompatibilidades y
solo publica tras superar tipos, tests, Expo Doctor y exportación iOS. Reinicia
únicamente el Metro identificado de este proyecto, sin reiniciar modelos ni
alterar chats, emparejamiento o Tailscale. Avisa al completar una migración o
cuando encuentra un problema que necesita atención; no envía avisos sin novedades.

Requiere este PC encendido, acceso a Internet y Codex abierto. No detecta
instantáneamente la versión instalada en el iPhone ni puede garantizar soporte
desde el segundo exacto de una actualización de la tienda. La automatización
pertenece al Codex del propietario y no se instala al clonar este repositorio.
Puede gestionarse desde las automatizaciones de Codex.

Para una migración manual, sigue la
[guía oficial de Expo](https://docs.expo.dev/workflow/upgrading-expo-sdk-walkthrough/),
alinea dependencias con `npx expo install --fix` y ejecuta las comprobaciones
anteriores antes de reiniciar Metro. No uses `npm audit fix --force`, no copies
`node_modules`, `.expo`, credenciales ni datos del PC al repositorio público.

Requisito oficial de sesión:
https://expo.dev/changelog/expo-go-57-login
