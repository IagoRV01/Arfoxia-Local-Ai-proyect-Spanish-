# Arfoxia para Expo Go

Aplicación nativa de Arfoxia para iPhone. Se conecta a la API local del PC a
través del HTTPS privado de Tailscale; no usa Safari ni publica el servicio en
Internet.

## Abrirla en el iPhone

1. Mantén Tailscale conectado en el PC y en el iPhone.
2. Abre Arfoxia en el PC. El servidor de Expo se iniciará automáticamente en
   cuanto Tailscale esté listo.
3. Abre el proyecto reciente de Arfoxia en Expo Go.
4. Dentro de la app, pulsa **Escanear QR de Arfoxia**.
5. En el PC, haz clic derecho sobre Arfoxia y elige **Emparejar iPhone**; escanea
   ese segundo QR desde la app.

Arfoxia anuncia Metro mediante el MagicDNS privado de Tailscale y lo reinicia si
se cierra. `Iniciar Arfoxia movil.cmd` queda disponible como arranque manual de
emergencia. El QR de emparejamiento conecta de forma privada la app con la API
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
- Captura autenticada del monitor, apertura de aplicaciones permitidas y
  liberación manual de VRAM.
- Desemparejamiento que borra la clave del llavero.

## Comprobaciones de desarrollo

```powershell
npm run typecheck
npm test
npx expo-doctor@latest
npx expo export --platform ios
```

Expo SDK 54 se mantiene deliberadamente mientras sea la versión admitida por
Expo Go en iPhone. Una app iOS independiente requerirá más adelante una cuenta
del Apple Developer Program y una compilación EAS/TestFlight.
