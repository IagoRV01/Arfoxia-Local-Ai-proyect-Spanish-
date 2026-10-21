# Agente de código de Arfoxia · Qwen 3.8 27B

El modo Dual añade un perfil automático de agente para encargos explícitos de
programación con `qwen3.8:27b-q4_K_M`. No cambia los pesos, entrena el modelo,
descarga otro modelo ni delega código a un servicio en la nube. Usa el motor
de tareas y herramientas de Arfoxia, compartido entre Windows y Expo Go.

## Uso

Reinicia la interfaz de Arfoxia para cargar esta versión y activa **Dual** desde
Windows o Expo Go. Ejemplo: «Crea una calculadora en Python, escribe tests y
corrige los errores hasta que pasen». Los proyectos nuevos usan la carpeta de
trabajo configurada y una subcarpeta propia; no se pide otra ubicación por defecto.

Se reconoce creación/reparación de programas, aplicaciones, webs, scripts,
repositorios y tests. Una pregunta como «¿Qué es Python?» no inicia un trabajo
de programación ni recibe permiso implícito para modificar archivos. Otros
modelos conservan su flujo actual. Una continuación de una tarea pendiente
mantiene el objetivo original del propietario.

## Herramientas y ciclo

- Inspección: carpetas, búsqueda de texto y lectura UTF-8 paginada con SHA-256.
- Cambios: crear archivos y `file_operation` → `replace_text`, con ancla única,
  texto nuevo y `expected_sha256` de la lectura. Si cambió el archivo o el ancla
  es ambigua, se rechaza sin sobrescribir. Conserva BOM y saltos CRLF al editar.
  El código de origen/reemplazo no se incluye en el registro de auditoría.
- Ejecución: Python y PowerShell con el entorno/runner del proyecto; Git,
  Node/npm y herramientas ya instaladas pueden usarse por comandos. Dependencias
  necesarias del proyecto, solo en su entorno local; no instalaciones globales.
- Documentación: buscar y leer fuentes sin perder las herramientas locales al
  consultar la web. Los documentos/adjuntos siguen siendo datos, no permisos.
  Un encargo explícito de implementar código a partir de adjuntos puede usar
  herramientas; resumir un adjunto no autoriza cambios.
- Interfaces: abrir un artefacto del encargo, capturar pantalla y consultar el
  sistema cuando proceda. Solo la última captura de herramienta se reenvía al
  modelo; las anteriores y adjuntos originales no se borran del historial.
- Cierre: `finish_task` exige una ejecución correcta posterior a las ediciones.
  Leer un archivo, listar carpetas o calcular no satisface esa comprobación.
  Un comando fallido sigue pendiente aunque luego se lea un archivo.

El registro acotado de rutas modificadas y comprobaciones se conserva en el
contexto aunque salgan de las últimas seis rondas de herramientas. No contiene
código completo, razonamiento privado ni nuevas autorizaciones. El plan debe
ser breve; el resultado es el proyecto guardado y comprobado, no solo un plan
o un bloque de código en el chat.

## Rendimiento y límites

No se sube el contexto ni cambia el reparto de GPU: se mantienen los parámetros
del [modo Dual](DUAL_GPU.md), sus límites de 16 GiB + 5,5 GiB, caché Q8, capas en
GPU, residencia manual y vigilancia a intervalos de 20 segundos. No se habilita
offload de pesos a RAM. Esto no elimina el uso normal de RAM de Python/Ollama.

El primer intento sigue usando `think: high`. Para código, la recuperación por
falta de progreso concede hasta 300 segundos o 24.000 caracteres de razonamiento
sin respuesta/llamada, frente a 120 segundos/8.000 en otros flujos. No expone ese
razonamiento. Si se agota, conserva la recuperación existente sin razonamiento
para intentar actuar, sin descargar ni cambiar de modelo. La generación máxima
y el contexto no se amplían para conseguir este margen.

Se mantienen Cancelar, límite por comando (120 s), límite por tarea (2 h/240
llamadas), comprobaciones de autorización y detención por bucles sin progreso.
Los archivos internos de Arfoxia y las acciones destructivas no reciben nuevas
excepciones. Un código de salida 0 no prueba por sí solo todos los requisitos;
el agente debe elegir tests pertinentes y comunicar qué no comprobó.

## Validación

Pruebas de perfil, herramientas, hashes obsoletos/anclas ambiguas, auditoría,
protecciones, continuidad, fuentes web, evidencia de ejecución y parámetros GPU
sin cambios. Un test de integración usa **PowerShell/Python reales**: crea una
calculadora, ve fallar `unittest`, aplica `replace_text` y repite hasta pasar.
La selección/respuestas del modelo se simulan en ese test; no es un benchmark
de la capacidad de Qwen ni una medición nueva de VRAM durante inferencia.
La batería completa supera 1.101 pruebas Python.

La instalación local se comprobó por metadatos de Ollama (27.3B Q4_K_M,
herramientas/visión/razonamiento). No se cargó el modelo para un benchmark nuevo
ni se liberaron otras aplicaciones para hacer sitio.

Referencia de protocolo: [herramientas y bucle de agente de Ollama](https://docs.ollama.com/capabilities/tool-calling).
