# Modo Dual de Arfoxia

Activación manual desde **GPU → Dual** en Windows o **PC → Modos de IA → Dual**
en Expo Go. Normal es el predeterminado si no hay un servidor Dual propio vivo;
reiniciar la interfaz recupera ese servidor sin descargarlo. Cambiar a
otro perfil o pulsar **Liberar toda la VRAM** detiene el servidor Dual. No se
descarga automáticamente al terminar una respuesta y no se reactiva solo tras jugar.

## Perfil

- Modelo oficial `qwen3.8:27b-q4_K_M`, con imágenes, herramientas y razonamiento **Extra High**.
- Ollama 0.34 traduce `think: "high"` al nivel oficial `xhigh` de Qwen3.8.
  No se envía literalmente `think: "xhigh"`, que esa API nativa no admite.
- 32768 tokens de contexto, una petición simultánea, batch 256.
- Flash Attention y caché K/V Q8; muestreo oficial de razonamiento: temperatura
  1,0, top-p 0,95, top-k 20, min-p 0, presence-penalty 0 y repeat-penalty 1.
- Caché de prompts en RAM y checkpoints de contexto desactivados; el KV activo
  permanece en GPU. Esto puede aumentar el tiempo de reevaluación del historial.
- Hasta 16384 tokens generados (incluye el razonamiento); las respuestas complejas
  pueden tardar varios minutos.
- Reparto por capas 86:14 entre los UUID de IA/juego, sin `main_gpu` en la API:
  en Ollama 0.34 ese parámetro fuerza una sola GPU y desactiva el reparto.
- Se solicitan todas las capas en GPU. `fit` automático se desactiva porque no
  aplica los márgenes por tarjeta cuando se fijan explícitamente todas las capas.

## Memoria y protección del juego

Los techos son 16384 MiB y 5632 MiB: suman **21,5 GiB**, no 22. El presupuesto
cuenta toda la VRAM dedicada usada en cada tarjeta, incluido Windows, por lo que
es más conservador que contar solo el modelo. También se exige margen libre.

No existe una cuota dura de VRAM por proceso en este servidor CUDA. El reparto
calibrado evita superar el presupuesto en las pruebas; la vigilancia **avisa**
si NVIDIA notifica un exceso, pero no descarga el modelo. No es una garantía contra un pico entre
muestreos o contra otra aplicación que empiece a reservar VRAM simultáneamente.
Se comprueba cada **20 segundos**, con una ventana compartida por carga, chat y
vigilante para evitar muestreos adicionales al enviar mensajes. La telemetría
informativa al actualizar una pantalla no cambia esa ventana.

Al cargar se exige que todas las capas estén en GPU y se rechaza un proyector
visual ya descargado a CPU. Durante el uso se avisa si se detecta ese fallback.
Esto no significa cero RAM del sistema: Python, Ollama, buffers de
transferencia, tokenización y cachés del sistema necesitan RAM normalmente.
Si empieza un juego o falla la comprobación, se muestra un aviso en PC y móvil.
**Hay que liberar Dual manualmente antes de jugar**: no se cierra el juego, no
se cambia de perfil ni se descarga el modelo por una respuesta fallida o timeout.
Cerrar Arfoxia deja el servidor residente, sin vigilancia mientras la app está
cerrada. Apagar Windows, un fallo del driver/Ollama o una falta de memoria pueden
descargarlo inevitablemente. Una carga inicial fallida se revierte, especialmente
si no cumple el requisito de capas en GPU; no se considera una sesión cargada.

## Operación y pruebas

Verificación de 0.14 (2026-09-17): 447 pruebas Python y 50 móviles correctas,
TypeScript y exportación iOS correctos. Llamada real `think: high` aceptada por
Ollama, con propuesta estructurada de `run_powershell`. Reinicio de la interfaz
a administrador manteniendo los mismos PID de Ollama y del modelo, sin recarga.
En esa prueba: 15084 MiB en IA y 4884 MiB en juego; son medidas, no cuotas duras.

Prueba del 2026-09-14 en las dos RTX 5060 Ti: carga completa de 66/66 capas en
GPU, generación de código Python, llamada estructurada a `web_search` con la
fecha actual e interpretación de una imagen. Picos registrados: 15128 MiB
(14,77 GiB) en IA y 5172 MiB (5,05 GiB) en juego, incluyendo otras aplicaciones.
Generación aproximada: 20 tokens/s. Son medidas de estas pruebas, no un máximo
garantizado para cualquier imagen o carga simultánea del escritorio.
Una prueba adicional con cuatro imágenes de 1600×1000 llegó a 15182 MiB
(14,83 GiB) y 5312 MiB (5,19 GiB), y respondió correctamente sin superar los límites.
La repetición con las cachés opcionales en RAM desactivadas también pasó; el
pico de la GPU de juegos fue 5462 MiB (5,33 GiB), al variar el consumo del escritorio.

Validación: 422 pruebas Python y 49 móviles, TypeScript y exportación iOS
correctos. `expo-doctor` pasa 20/21 comprobaciones: recomienda parches recientes
de SDK 57 para 10 paquetes ya instalados. Esta función no cambia las dependencias
de Expo; queda pendiente esa actualización de mantenimiento.

Requiere Ollama 0.34.0 o una versión compatible con estas opciones de llama.cpp.
El modelo se descarga una sola vez con `ollama pull qwen3.8:27b-q4_K_M`.
Los pesos permanecen en el almacén local compartido de Ollama, nunca en Git.
El servidor escucha solo en `127.0.0.1:11436`; el móvil utiliza la API autenticada
habitual de Arfoxia, no este puerto. No se cambia el Ollama principal ni sus GPU.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_dual_gpu.py tests/test_model_policy.py
.venv\Scripts\python.exe scripts/smoke_dual_gpu.py
```

La prueba real libera los modelos de Arfoxia antes de empezar y el modo Dual al
terminar. No la ejecutes mientras otra conversación esté generando una respuesta.
Los datos de emparejamiento, logs y marcadores de procesos se guardan fuera del
repositorio publicable; no contienen cambios del historial de conversaciones.

Fuentes: [modelo oficial](https://ollama.com/library/qwen3.8:27b-q4_K_M),
[selección de GPU](https://docs.ollama.com/gpu),
[implementación de Ollama 0.34](https://github.com/ollama/ollama/blob/v0.34.0/llm/llama_server.go).

Extra High y muestreo: [ficha oficial de Qwen3.8](https://huggingface.co/Qwen/Qwen3.8-27B),
[mapeo nativo de razonamiento](https://github.com/ollama/ollama/blob/v0.34.0/model/renderers/qwen35.go).
