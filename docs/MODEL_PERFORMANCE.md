# Auditoría de rendimiento local — 2026-11-03

## Equipo y restricciones

- Windows, Ollama **0.40.14**, Ryzen 7 5800X3D, 32 GB de RAM.
- RTX 5060 Ti de 16 GB: PCIe 4.0 ×8, pantalla activa y memoria compartida con
  el escritorio. RTX 5060 Ti de 8 GB: PCIe 3.0 ×4, sin pantalla activa.
- Dual conserva el modelo `qwen3.8:27b-q4_K_M`, **32.768 tokens**, caché KV Q8,
  Flash Attention, una petición simultánea y razonamiento nativo `high`
  (extra high de este modelo). No se cambia la cuantización.
- Límites originales: hasta la capacidad de la tarjeta de 16 GB y hasta
  **5.632 MiB en la de 8 GB**, contando también otras aplicaciones. El muestreo
  de producción sigue siendo cada 20 segundos; sus avisos no descargan el modelo.
- No se descargaron modelos nuevos ni se escribieron conversaciones. La IA
  estaba pausada antes de las pruebas y se deja pausada después.

## Hallazgos y configuración elegida

El reparto anterior `86,14` dejaba sin margen suficiente a la tarjeta que
también dibuja Windows. La prueba se detuvo al bajar de 128 MiB libres; no se
aceptó una medición obtenida paginando memoria o superando los límites.
El reparto `80,20` con MTP de cuatro tokens tampoco dejó margen suficiente.

Se selecciona **`75,25`, batch 128 y MTP de un token**. Son proporciones de
capas/pesos, no un porcentaje exacto del uso final de VRAM: hay que sumar KV,
estados recurrentes, proyector visual, buffers de cálculo y escritorio.

Ollama 0.40.14 detecta automáticamente las cabezas MTP de estos modelos y usa
cuatro borradores por defecto. Se fija explícitamente `draft_num_predict=1`
para no depender de un valor cambiante del servidor. Cuatro borradores dieron
resultados más rápidos (hasta 43 tok/s), pero una pasada High volvió a quedar
sin margen suficiente en la tarjeta principal. **No se seleccionó ese pico
como configuración de producción.**

Los servidores propios de una sola GPU ya no heredan variables `LLAMA_ARG_*`,
`GGML_*` u opciones Ollama de otros perfiles. Se conserva la ruta de modelos
compartida; se fijan UUID, caché Q8, Flash Attention y una petición simultánea.
Todos los turnos solicitan las capas en GPU (`num_gpu=999`), sin fallback
silencioso a capas en CPU. Esto no significa cero RAM del proceso: tokenización,
carga, entradas y buffers auxiliares siguen necesitando memoria del sistema.

## Mediciones

Servidor temporal propio en `127.0.0.1:11437`, sin tocar los servidores del
usuario. Se excluye la primera pasada de cada serie de las cifras «en caliente».
Se conserva el contexto configurado de cada perfil. Fórmula de generación:
`eval_count / (eval_duration / 1e9)`.

| Prueba | Configuración | Generación en caliente |
|---|---|---:|
| 4B en tarjeta de IA | 4K, batch 512, MTP 4, sin pensamiento | 57,6 tok/s |
| 4B en tarjeta de juego | 4K, batch 512, MTP 4, sin pensamiento | 59,5 tok/s |
| 9B adaptativo | 32K, batch 512, MTP 4, sin pensamiento | 44,1 tok/s |
| Dual sin MTP | 32K, 75/25, batch 128, sin pensamiento | 20,1–20,8 tok/s |
| **Dual elegido** | **32K, 75/25, batch 128, MTP 1, sin pensamiento** | **33,1–33,2 tok/s** |
| **Dual elegido con High** | **Mismas condiciones, temperatura 1, High** | **30,3–30,8 tok/s** |
| **Dual elegido con High y entrada larga** | **18.758 tokens de entrada, temperatura 1** | **28,7 tok/s** |
| Dual elegido con imagen | MTP 1, imagen local de la mascota | 31,3 tok/s |
| Dual no seleccionado | MTP 4, temperatura 1, High | 43,0 tok/s; otra pasada sin margen |

Las series cortas usan 128 tokens de salida con temperatura 0 y semilla 42;
High usa 256 tokens con temperatura 1. La imagen no contiene datos personales.
Cada número corresponde a su propia carga: no se comparan como si fueran el
mismo prompt. El conteo de High incluye los tokens internos de razonamiento,
no solo las palabras visibles. No representa tiempo de búsqueda web/herramientas.

La entrada de 18.758 tokens tardó 25,7 segundos en procesarse. La pasada en
caliente duró 34,9 segundos en total, pese a generar a 28,7 tok/s. La primera
pasada añadió unos 19,5 segundos de carga del modelo (54,1 segundos en total).
Los máximos muestreados de la configuración elegida fueron 15.831 MiB en la
tarjeta de 16 GB y 5.407 MiB en la de 8 GB, incluyendo el resto del escritorio.
El muestreo no equivale a un límite físico continuo de asignación de memoria.

Con MTP 4 se comprobó además una entrada sintética de 8.620 tokens: 35,0–37,3
tok/s de generación y unos 11 segundos para procesar la entrada. No se usa esa
serie para atribuir una mejora a la configuración finalmente elegida.

Los registros anteriores contenían respuestas de 11–14 tok/s con cerca de
18.500 tokens de entrada. No constituyen un A/B equivalente: difieren el prompt,
la longitud y el estado de memoria. Tampoco es correcto prometer 20–35 tok/s
para cualquier consulta basándose en una estimación de otro chat.

### Potencia: límite pendiente de hardware/memoria disponible

`qwen3.6:27b-q4_K_M` con 8K en la tarjeta principal, tal como está configurado
ese perfil, agotó el margen libre. También se probó batch 128 sin MTP: no bastó.
No se aceptó offload a CPU ni se cambió a otro modelo para fabricar una cifra.
Su error de falta de memoria ahora recomienda liberar VRAM o seleccionar Dual,
sin hacer esos cambios automáticamente.

Windows sigue usando la tarjeta de 16 GB. Mover físicamente las conexiones de
pantalla a otra tarjeta podría liberar memoria allí, pero **obligaría a volver
a medir el reparto Dual**: el escritorio pasaría a consumir parte del límite
de 5,5 GiB de la otra tarjeta. No se cambiaron conexiones, controladores, BIOS,
frecuencias, voltajes ni configuraciones de seguridad.

## Repetir las pruebas

Usar el Python del proyecto desde su raíz. Pausar la IA y cerrar manualmente
sus modelos residentes primero. El script se niega a ejecutarse con un juego,
trabajo activo, otro modelo residente o puerto ocupado. Solo detiene el proceso
de benchmark cuya identidad y entorno ha comprobado.

```powershell
.venv\Scripts\python.exe scripts/benchmark_local_models.py --profile dual --variant high --think high --temperature 1 --tokens 256
.venv\Scripts\python.exe scripts/benchmark_local_models.py --profile dual --variant vision --vision
.venv\Scripts\python.exe scripts/benchmark_local_models.py --profile dual --variant long --long --prompt-paragraphs 480 --think high --temperature 1 --tokens 256 --samples 1
.venv\Scripts\python.exe scripts/benchmark_local_models.py --profile normal --variant normal --batch 512 --draft 4
```

Los resultados JSON y logs se guardan en `work/`, ignorado por Git; no deben
publicarse sin revisar rutas y otros datos locales. Las pruebas no llaman
herramientas del modelo ni ejecutan su texto.

## Fuentes técnicas

- [Ollama: opciones y valor predeterminado de borradores, versión 0.40.14](https://github.com/ollama/ollama/blob/v0.40.14/api/types.go).
- [Ollama: detección MTP y argumentos del runner](https://github.com/ollama/ollama/blob/v0.40.14/llm/llama_server.go).
- [Ollama: GPU, contexto, Flash Attention y caché](https://docs.ollama.com/faq).

Estas fuentes describen el funcionamiento; las velocidades de arriba son
mediciones locales, no cifras tomadas de las fuentes ni garantías comerciales.
