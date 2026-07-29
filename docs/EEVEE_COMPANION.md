# Convivencia con Eevee

Cuando Codex Desktop está abierto, su overlay está visible y la mascota seleccionada es `custom:eevee`, Arfoxia reconoce la posición de Eevee. Al detectarlo por primera vez se acerca al lado libre, lo mira, muestra un saludo breve y reproduce una reacción de Glaceon. Mientras ambos sigan visibles puede realizar nuevas interacciones ocasionales, con un intervalo predeterminado de unos dos minutos.

La separación se calcula con los rectángulos de los sprites visibles y 24 píxeles de margen. Los paseos permanecen en el mismo tramo libre para no atravesar a Eevee; si Gori arrastra a Arfoxia encima de él, al soltar se aplica el desplazamiento horizontal mínimo. Las burbujas y la entrada rápida también prueban el lado opuesto para no cubrir la ventana del overlay de Codex.

La detección es pasiva y local. Solo valida el proceso de Codex y lee la preferencia, posición y paquete de Eevee. No se hacen capturas, no se envían teclas, no se mueve Eevee y no se altera la configuración de Codex.

Codex no ofrece una interfaz pública para ordenar a Eevee una animación concreta. Por eso Arfoxia puede reconocerlo y reaccionar a su presencia, mientras que Eevee conserva las reacciones naturales que ya le proporciona Codex. Fingir una respuesta directa de Eevee exigiría manipular IPC privado o automatizar la interfaz, opciones que deliberadamente no usa este proyecto.

Estos valores pueden ajustarse en `%LOCALAPPDATA%\GlaceonCompanion\config.json`:

```json
{
  "eevee_companion_enabled": true,
  "eevee_presence_poll_ms": 2500,
  "eevee_interaction_interval_ms": 120000,
  "eevee_avoidance_padding": 24
}
```
