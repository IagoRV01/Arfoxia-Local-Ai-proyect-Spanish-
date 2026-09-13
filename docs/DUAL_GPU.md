# Modo Dual de Arfoxia

Activación manual desde **GPU → Dual** en Windows o **PC → Modos de IA → Dual**
en Expo Go. Normal sigue siendo el modo predeterminado al arrancar. Cambiar a
otro perfil o pulsar **Liberar toda la VRAM** detiene el servidor Dual. No se
descarga automáticamente al terminar una respuesta y no se reactiva solo tras jugar.

## Perfil

- Modelo oficial `qwen3.8:27b-q4_K_M`, con imágenes, herramientas y razonamiento.
- 32768 tokens de contexto, una petición simultánea, batch 256.
- Flash Attention y caché K/V Q8; temperatura 0,6, top-p 0,95, top-k 20.
- Caché de prompts en RAM y checkpoints de contexto desactivados; el KV activo
  permanece en GPU. Esto puede aumentar el tiempo de reevaluación del historial.
- Hasta 8192 tokens generados (incluye el razonamiento); las respuestas complejas
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
calibrado evita superar el presupuesto en las pruebas; la vigilancia cancela el
proceso si NVIDIA notifica un exceso. No es una garantía contra un pico entre
muestreos o contra otra aplicación que empiece a reservar VRAM simultáneamente.
Se comprueba aproximadamente cada segundo al cargar y cada cinco segundos en uso.

Todas las capas deben cargarse en GPU y se rechaza el fallback del proyector
visual a CPU. Esto no significa cero RAM del sistema: Python, Ollama, buffers de
transferencia, tokenización y cachés del sistema necesitan RAM normalmente.
Si empieza un juego o falla la comprobación, se detiene únicamente el servidor
Dual y sus hijos, se libera la GPU de juego y Arfoxia vuelve al perfil Normal.
No se cierra el juego ni se modifica la configuración global del driver.

## Operación y pruebas

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
