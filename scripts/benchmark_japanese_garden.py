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

import httpx

from glaceon_companion.config import ConfigStore

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


def run(output: Path):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    prompt = BRIEF + str(output)
    if len(prompt) > 1200:
        raise ValueError("Ruta demasiado larga para el mensaje de Arfoxia.")
    headers = {"Authorization": "Bearer " + ConfigStore().api_token()}
    url = "http://127.0.0.1:8742"
    with httpx.Client(timeout=1800, headers=headers, trust_env=False) as client:
        before = client.get(url + "/api/model/status").raise_for_status().json()
        conversation = client.post(url + "/api/conversations", json={"title": "Benchmark jardín japonés 3D"}).raise_for_status().json()
        conversation_id = conversation.get("id") or conversation.get("conversation", {}).get("id")
        started = time.perf_counter()
        response = client.post(url + "/api/chat", json={"conversation_id": conversation_id, "message": prompt,
                              "client_message_id": "garden-benchmark-" + datetime.now().strftime("%Y%m%d%H%M%S")})
        response.raise_for_status()
        result = response.json()
        elapsed = time.perf_counter() - started
        actions = result.get("action_results", [])
        report = {"challenge": "Japanese garden 3D / Arfoxia local challenge",
                  "standardized_score": False, "prompt": prompt, "created_at": datetime.now().astimezone().isoformat(),
                  "model": result.get("model"), "model_mode": result.get("model_mode"),
                  "elapsed_seconds": round(elapsed, 2), "tool_calls": len(actions),
                  "tools": [{"name": action.get("action"), "success": action.get("success")} for action in actions],
                  "html_created": (output / "index.html").is_file(),
                  "loaded_before": before.get("dual_loaded_models"),
                  "assistant_message": result.get("message"),
                  "browser_validation": "pending" if (output / "index.html").is_file() else "not_run_no_html"}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "raw-reply.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("model", "model_mode", "elapsed_seconds", "tool_calls", "tools", "html_created")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New isolated directory for generated code and local results")
    args = parser.parse_args()
    run(args.output)
