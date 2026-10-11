"""Reproducible local coding challenge, not an official standardized benchmark.

Runs the real Arfoxia API and tools. Keeps generated files and raw replies local.
No model changes, unloads, dependency installs or elevated-permission changes.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx

from glaceon_companion.config import ConfigStore, PROJECT_ROOT

BRIEF = (
    "Ejecuta el reto de programación del jardín japonés 3D. Crea tú el código completo "
    "de index.html en la carpeta absoluta indicada abajo usando tus herramientas, no solo "
    "un bloque de código en el chat. Jardín voxel interactivo en Three.js, con pagoda "
    "japonesa detallada, cerezos, faroles, puente, estanque con peces koi animados que "
    "permanezcan dentro del agua, pequeños aldeanos y un dragón volando. Incluye sombras, "
    "ciclo día/noche, cámara orbital con ratón/táctil, botón pausa y diseño adaptable. "
    "Todos los objetos deben ser geometría procedural, sin imágenes ni modelos externos; "
    "solo se permite cargar Three.js y OrbitControls desde un CDN con versión fija. "
    "No instales paquetes ni cambies configuraciones del PC. Trabaja únicamente en esa "
    "carpeta. Comprueba los archivos con tus herramientas y corrige fallos antes de terminar. "
    "No uses herramientas para abrir ventanas; yo probaré la escena después. "
    "No afirmes que funciona en un navegador si no lo has comprobado. Carpeta: "
)


def run(output: Path, *, followup: str | None = None, conversation_id: str | None = None):
    output = output.resolve()
    if output.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("La carpeta del benchmark debe estar fuera del programa Arfoxia: "
                         "file_operation protege sus archivos. Usa una carpeta nueva en Documentos.")
    if followup:
        if not conversation_id or not output.is_dir():
            raise ValueError("Una iteración requiere el ID del chat y su carpeta existente.")
    else:
        if conversation_id:
            raise ValueError("No reutilices un chat sin indicar una corrección concreta.")
        output.mkdir(parents=True, exist_ok=False)
    prompt = followup or BRIEF + str(output)
    if len(prompt) > 1200:
        raise ValueError("Ruta demasiado larga para el mensaje de Arfoxia.")
    headers = {"Authorization": "Bearer " + ConfigStore().api_token()}
    url = "http://127.0.0.1:8742"
    with httpx.Client(timeout=1800, headers=headers, trust_env=False) as client:
        before = client.get(url + "/api/model/status").raise_for_status().json()
        if not conversation_id:
            conversation = client.post(url + "/api/conversations", json={"title": "Benchmark jardín japonés 3D"}).raise_for_status().json()
            conversation_id = conversation.get("id") or conversation.get("conversation", {}).get("id")
        label = "iteration-" + datetime.now().strftime("%Y%m%d%H%M%S%f") if followup else "report"
        client_message_id = "garden-benchmark-" + uuid4().hex
        # Save the explicit chat ID before a potentially long request, so an
        # interrupted harness can resume without silently creating another chat.
        (output / (label + "-request.json")).write_text(json.dumps(
            {"conversation_id": conversation_id, "client_message_id": client_message_id,
             "prompt": prompt, "guided_iteration": bool(followup)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        started = time.perf_counter()
        request_error = None
        try:
            response = client.post(url + "/api/chat", json={"conversation_id": conversation_id, "message": prompt,
                                  "client_message_id": client_message_id})
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            # A lost client connection does not prove the server executed no
            # actions. Preserve the request identity; never blindly resubmit.
            request_error = type(exc).__name__
            result = {}
        elapsed = time.perf_counter() - started
        actions = result.get("action_results", [])
        report = {"challenge": "Japanese garden 3D / Arfoxia local challenge",
                  "standardized_score": False, "prompt": prompt, "created_at": datetime.now().astimezone().isoformat(),
                  "guided_iteration": bool(followup),
                  "request_error": request_error,
                  "outcome": "request_failed_result_unknown" if request_error else "awaiting_validation",
                  "model": result.get("model", before.get("model")),
                  "model_mode": result.get("model_mode", before.get("requested_mode")),
                  "elapsed_seconds": round(elapsed, 2), "tool_calls": len(actions),
                  "tools": [{"name": action.get("action"), "success": action.get("success")} for action in actions],
                  "html_created": (output / "index.html").is_file(),
                  "conversation_id": conversation_id,
                  "execution_recovery": result.get("execution_recovery", False),
                  "recovery_reason": result.get("recovery_reason"),
                  "loaded_before": before.get("dual_loaded_models"),
                  "assistant_message": result.get("message"),
                  "browser_validation": "pending" if (output / "index.html").is_file() else "not_run_no_html"}
        (output / (label + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / (label + "-raw-reply.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("model", "model_mode", "elapsed_seconds", "tool_calls", "tools", "html_created")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New isolated directory for generated code and local results")
    parser.add_argument("--followup", help="Concrete observed error or missing feature; sends another recorded turn to the model")
    parser.add_argument("--conversation-id", help="Existing benchmark conversation (only with --followup)")
    args = parser.parse_args()
    run(args.output, followup=args.followup, conversation_id=args.conversation_id)
