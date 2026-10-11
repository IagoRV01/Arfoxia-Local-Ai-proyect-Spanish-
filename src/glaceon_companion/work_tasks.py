"""Owner-scoped background work. Never replay an interrupted PC action."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

ACTIVE = {"queued", "running", "cancelling"}
TERMINAL = {"completed", "needs_input", "blocked", "cancelled", "failed", "interrupted"}


class WorkStopped(Exception):
    def __init__(self, status: str, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def is_work_request(text: str) -> bool:
    text = text.strip().casefold().lstrip('¿ ')
    if re.match(r"^(?:how\b|what\b|como\b|cómo\b|qu[eé]\b|explica\b|explain\b|por qu[eé]\b|puedes explicar\b)", text):
        return False
    return bool(re.search(r"\b(?:crea|crear|cr[eé]ame|arregla|arreglar|corrige|corregir|construye|construir|implementa|implementar|programa|programar|modifica|modificar|añade|añadir|anade|haz|hazme|completa|termina|comprueba|comprobar|verifica|verificar|contin[uú]a|sigue|configura|configurar|repara|reparar|desarrolla|desarrollar|genera|generar|continue|resume|build|create|fix|implement|check|make|generate|develop|configure|repair)\b|(?:quiero|necesito) que", text))


class WorkSession:
    MAX_SECONDS = 7200
    MAX_CALLS = 240

    def __init__(self, registry: "WorkTasks", job_id: str, require_work: bool):
        self.registry, self.id, self.require_work = registry, job_id, require_work
        self.cancel = threading.Event()
        self.started = time.monotonic()
        self.calls = 0
        self.rounds = 0
        self.status = "running"

    def check(self):
        if self.cancel.is_set():
            raise WorkStopped("cancelled", "Trabajo detenido por ti. Las acciones ya realizadas no se deshacen.")
        if time.monotonic() - self.started >= self.MAX_SECONDS or self.calls >= self.MAX_CALLS:
            raise WorkStopped("blocked", "El encargo sigue incompleto y ha alcanzado el límite de seguridad (2 horas/240 llamadas). Revisa el progreso antes de continuar.")

    def progress(self, action: str = "model"):
        self.registry.update(self.id, status="running", rounds=self.rounds, calls=self.calls, last_action=str(action)[:80])

    async def generation(self, awaitable):
        pending = asyncio.ensure_future(awaitable)
        try:
            while not pending.done():
                self.check()
                await asyncio.wait({pending}, timeout=.2)
            self.check()
            return pending.result()
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


class WorkTasks:
    """Persist progress/identity only, not prompts, commands or credentials."""
    def __init__(self, path: Path, notify=None):
        self.path = path
        self.notify = notify
        self.lock = threading.RLock()
        self.records: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, WorkSession] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.closed = False
        self.storage_error = False
        if path.exists():
            try:
                if path.stat().st_size > 512000:
                    raise ValueError("Progress store too large")
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not all(isinstance(row, dict) and
                    row.get("id") == key and re.fullmatch(r"[0-9a-f]{32}", key) and
                    isinstance(row.get("conversation_id"), str) and isinstance(row.get("client_message_id"), str) and
                    row.get("status") in ACTIVE | TERMINAL for key, row in loaded.items()):
                    raise ValueError("Invalid progress store")
                self.records = loaded
            except (OSError, ValueError, UnicodeError):
                # Preserve the damaged file; never lose idempotency evidence silently.
                self.storage_error = True
        for record in self.records.values():
            if record.get("status") in ACTIVE:
                record.update(status="interrupted", message="El PC o Arfoxia se reinició. No se han repetido acciones automáticamente; revisa el chat antes de continuar.")
        if self.records:
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    def update(self, job_id: str, **fields):
        with self.lock:
            # Cancellation wins over a simultaneous progress notification.
            if self.records[job_id]["status"] == "cancelling" and fields.get("status") == "running":
                fields["status"] = "cancelling"
            self.records[job_id].update(fields, updated_at=time.time())
            self._save()
            if self.notify:
                self.notify({"type": "work_progress", **self.records[job_id]})

    def get(self, job_id: str):
        with self.lock:
            if job_id not in self.records:
                raise ValueError("La tarea no existe.")
            return dict(self.records[job_id])

    def list(self, conversation_id: str):
        with self.lock:
            return [dict(row) for row in self.records.values() if row["conversation_id"] == conversation_id][-20:]

    def start(self, conversation_id: str, client_id: str, require_work: bool, run):
        with self.lock:
            if self.closed:
                raise ValueError("Arfoxia se está cerrando.")
            if self.storage_error:
                raise ValueError("El registro privado de tareas está dañado. Se ha conservado sin sobrescribir; hay que revisarlo antes de ejecutar encargos para evitar repetir acciones.")
            for record in self.records.values():
                if record["conversation_id"] == conversation_id and record["client_message_id"] == client_id:
                    return dict(record)
                if record["conversation_id"] == conversation_id and record["status"] in ACTIVE:
                    raise ValueError("Ya hay una tarea trabajando en este chat. Espera o detén esa tarea.")
            if sum(row["status"] in ACTIVE for row in self.records.values()) >= 4:
                raise ValueError("Ya hay cuatro tareas pendientes. Espera o detén una.")
            # Bounded private progress storage. Chat/client deduplication remains in SQLite.
            removable = [key for key, row in self.records.items() if row["status"] in TERMINAL]
            for key in removable[:max(0, len(self.records) - 199)]:
                del self.records[key]
            job_id = uuid.uuid4().hex
            self.records[job_id] = dict(id=job_id, conversation_id=conversation_id,
                client_message_id=client_id, status="queued", rounds=0, calls=0,
                require_work=require_work,
                last_action="", created_at=time.time(), updated_at=time.time())
            session = WorkSession(self, job_id, require_work)
            self.sessions[job_id] = session
            self._save()

            def worker():
                try:
                    result = asyncio.run(run(session))
                    self.update(job_id, status=result.get("task_status", "blocked" if result.get("offline") or result.get("generation_empty") else "completed"))
                except WorkStopped as exc:
                    self.update(job_id, status=exc.status, message=exc.message)
                except Exception:
                    self.update(job_id, status="failed", message="Arfoxia encontró un error. No se ha reenviado la petición ni repetido acciones; revisa el chat.")
                finally:
                    with self.lock:
                        self.sessions.pop(job_id, None)
                        self.threads.pop(job_id, None)

            thread = threading.Thread(target=worker, name="arfoxia-work", daemon=True)
            self.threads[job_id] = thread
            thread.start()
            return dict(self.records[job_id])

    def stop(self, job_id: str):
        with self.lock:
            record = self.get(job_id)
            if record["status"] in ACTIVE:
                self.sessions[job_id].cancel.set()
                self.update(job_id, status="cancelling", message="Deteniendo: una herramienta en curso termina antes de parar; no se inicia otra.")
            return self.get(job_id)

    def close(self):
        with self.lock:
            self.closed = True
            for session in self.sessions.values():
                session.cancel.set()
