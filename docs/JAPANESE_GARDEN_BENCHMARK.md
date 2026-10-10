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

Los archivos generados, respuesta cruda y rutas locales se conservan en `work/`,
fuera de Git. Las pruebas del repositorio validan las herramientas; no demuestran
por sí mismas que una escena concreta generada por un modelo funcione.

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
