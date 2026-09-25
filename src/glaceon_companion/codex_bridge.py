"""Puente local y limitado entre Arfoxia y Codex app-server.

El puente no expone una orden genérica ni acepta comandos de shell. Solo permite
listar tareas, resolver un título de forma inequívoca y solicitar la interrupción
de un turno que app-server confirme como activo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import unicodedata
from collections import deque
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Protocol, Self


JsonObject = dict[str, Any]


class CodexBridgeError(RuntimeError):
    """Base para errores seguros que puede mostrar la interfaz de Arfoxia."""


class CodexUnavailableError(CodexBridgeError):
    """Codex app-server no está instalado o no responde."""


class CodexProtocolError(CodexBridgeError):
    """app-server devolvió una respuesta que no cumple el protocolo esperado."""


class CodexRpcError(CodexBridgeError):
    """Error JSON-RPC devuelto por app-server, sin incluir datos sensibles."""

    def __init__(self, method: str, code: int | None, message: str) -> None:
        self.method = method
        self.code = code
        self.rpc_message = message
        super().__init__(f"Codex rechazó {method}: {message}")


class InvalidTaskNameError(CodexBridgeError):
    """El título solicitado es vacío, excesivo o contiene caracteres de control."""


class TaskNotFoundError(CodexBridgeError):
    """No se encontró ninguna tarea con el título solicitado."""


class AmbiguousTaskError(CodexBridgeError):
    """Más de una tarea coincide y, por seguridad, no se elige una al azar."""

    def __init__(self, query: str, candidates: list["CodexTask"]) -> None:
        self.query = query
        self.candidates = tuple(candidates)
        names = ", ".join(task.name for task in candidates[:5])
        suffix = "…" if len(candidates) > 5 else ""
        super().__init__(
            f"Hay varias tareas que coinciden con «{query}»: {names}{suffix}. "
            "Indica un título más concreto."
        )


class NoActiveTurnError(CodexBridgeError):
    """La tarea existe, pero app-server no informa de un turno en ejecución."""


class MultipleActiveTurnsError(CodexBridgeError):
    """Estado inesperado: más de un turno figura como activo."""


@dataclass(frozen=True, slots=True)
class CodexTask:
    thread_id: str
    name: str
    preview: str
    status: str
    cwd: str | None = None
    updated_at: int | None = None

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PauseResult:
    task_name: str
    thread_id: str
    turn_id: str
    success: bool = True

    def to_dict(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpenTaskResult:
    task_name: str
    thread_id: str
    uri: str

    def to_dict(self) -> JsonObject:
        return asdict(self)


class AppServerTransport(Protocol):
    """Superficie mínima para poder probar el puente sin tocar tareas reales."""

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None: ...

    def request(self, method: str, params: JsonObject | None = None) -> Any: ...


_END_OF_STREAM = object()


class CodexAppServerClient(AbstractContextManager["CodexAppServerClient"]):
    """Cliente JSONL síncrono para ``codex app-server`` mediante stdio.

    Se crea un proceso hijo local y nunca se abre un puerto de red. Las peticiones
    iniciadas por el servidor se rechazan: este cliente no concede permisos ni
    confirma acciones en nombre del usuario.
    """

    def __init__(
        self,
        command: tuple[str, ...] | None = None,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.command = command or self.default_command()
        self.timeout_seconds = max(1.0, min(float(timeout_seconds), 60.0))
        self._process: subprocess.Popen[str] | None = None
        self._messages: Queue[JsonObject | BaseException | object] = Queue()
        self._request_lock = threading.Lock()
        self._request_id = 0
        self._stderr: deque[str] = deque(maxlen=20)
        self._closed = False

    @staticmethod
    def default_command() -> tuple[str, ...]:
        # Codex Desktop mantiene una copia del CLI compatible con el formato de
        # sus rollouts. Se prefiere a un wrapper npm antiguo que pueda aparecer
        # antes en PATH y no sea capaz de leer las tareas recientes de la app.
        if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
            desktop_bin = Path(os.environ["LOCALAPPDATA"]) / "OpenAI" / "Codex" / "bin"
            desktop_candidates = sorted(
                desktop_bin.glob("*/codex.exe"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if desktop_candidates:
                return (str(desktop_candidates[0]), "app-server")

        candidates = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return (resolved, "app-server")

        if os.name == "nt" and os.environ.get("APPDATA"):
            fallback = Path(os.environ["APPDATA"]) / "npm" / "codex.cmd"
            if fallback.is_file():
                return (str(fallback), "app-server")
        raise CodexUnavailableError("No encuentro la instalación local de Codex.")

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        if self._closed:
            raise CodexUnavailableError("El cliente de Codex ya está cerrado.")

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise CodexUnavailableError("No pude iniciar Codex app-server.") from exc

        threading.Thread(target=self._read_stdout, daemon=True, name="arfoxia-codex-jsonl").start()
        threading.Thread(target=self._drain_stderr, daemon=True, name="arfoxia-codex-stderr").start()
        try:
            self._request_started(
                "initialize",
                {
                    "clientInfo": {
                        "name": "arfoxia",
                        "title": "Arfoxia local companion",
                        "version": "0.15.0",
                    }
                },
            )
            self._notify("initialized", {})
        except BaseException:
            self.close()
            raise

    def request(self, method: str, params: JsonObject | None = None) -> Any:
        if not method or any(ord(character) < 0x20 for character in method):
            raise ValueError("Método JSON-RPC no válido.")
        if self._process is None:
            self.start()
        with self._request_lock:
            return self._request_started(method, params or {})

    def _request_started(self, method: str, params: JsonObject) -> Any:
        self._request_id += 1
        request_id = self._request_id
        self._write({"method": method, "id": request_id, "params": params})
        deadline = time.monotonic() + self.timeout_seconds

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexUnavailableError(f"Codex no respondió a {method} a tiempo.")
            try:
                message = self._messages.get(timeout=remaining)
            except Empty as exc:
                raise CodexUnavailableError(f"Codex no respondió a {method} a tiempo.") from exc

            if message is _END_OF_STREAM:
                raise CodexUnavailableError("Codex app-server cerró la conexión.")
            if isinstance(message, BaseException):
                raise CodexProtocolError("Codex devolvió una línea JSONL no válida.") from message
            if not isinstance(message, dict):
                raise CodexProtocolError("Codex devolvió un mensaje no válido.")

            # Nunca aprobar solicitudes iniciadas por el servidor. No deberían
            # aparecer en list/read/interrupt, pero el cierre seguro evita que una
            # ampliación futura convierta este cliente en un canal de autorización.
            if "method" in message and "id" in message:
                self._write(
                    {
                        "id": message["id"],
                        "error": {
                            "code": -32601,
                            "message": "Arfoxia no admite solicitudes iniciadas por el servidor.",
                        },
                    }
                )
                continue
            if message.get("id") != request_id:
                # Las notificaciones carecen de id. No contienen la respuesta a
                # esta petición y pueden descartarse en este cliente síncrono.
                continue
            if "error" in message:
                error = message.get("error") or {}
                if not isinstance(error, dict):
                    raise CodexProtocolError("Codex devolvió un error JSON-RPC no válido.")
                code = error.get("code") if isinstance(error.get("code"), int) else None
                rpc_message = str(error.get("message") or "error desconocido")[:500]
                raise CodexRpcError(method, code, rpc_message)
            if "result" not in message:
                raise CodexProtocolError("La respuesta de Codex no contiene result.")
            return message["result"]

    def _notify(self, method: str, params: JsonObject) -> None:
        self._write({"method": method, "params": params})

    def _write(self, payload: JsonObject) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise CodexUnavailableError("Codex app-server no está disponible.")
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise CodexUnavailableError("Se perdió la conexión local con Codex.") from exc

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            self._messages.put(_END_OF_STREAM)
            return
        try:
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("JSON-RPC message is not an object")
                    self._messages.put(message)
                except (json.JSONDecodeError, ValueError) as exc:
                    self._messages.put(exc)
        finally:
            self._messages.put(_END_OF_STREAM)

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr.append(line.rstrip()[:500])

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        self._process = None
        if process is None:
            return

        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)


TransportFactory = Callable[[], AppServerTransport]


class CodexBridge:
    """Operaciones de alto nivel permitidas para la integración con Eevee/Codex."""

    MAX_TASKS = 200
    PAGE_SIZE = 100
    MAX_QUERY_LENGTH = 160
    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,199}$")

    SOURCE_KINDS = [
        "cli",
        "vscode",
        "exec",
        "appServer",
        "subAgent",
        "subAgentReview",
        "subAgentCompact",
        "subAgentThreadSpawn",
        "subAgentOther",
        "unknown",
    ]

    def __init__(
        self,
        client_factory: TransportFactory | None = None,
        uri_opener: Callable[[str], None] | None = None,
    ) -> None:
        self._client_factory: TransportFactory = client_factory or CodexAppServerClient
        self._uri_opener = uri_opener or self._open_uri

    def list_tasks(self, search_term: str | None = None, *, limit: int = 50) -> list[CodexTask]:
        query = self._validate_query(search_term) if search_term is not None else None
        safe_limit = max(1, min(int(limit), self.MAX_TASKS))
        with self._client_factory() as client:
            return self._list_tasks(client, query, safe_limit)

    def resolve_task(self, task_name: str) -> CodexTask:
        query = self._validate_query(task_name)
        with self._client_factory() as client:
            tasks = self._list_tasks(client, query, self.PAGE_SIZE)
            return self._resolve(query, tasks)

    def pause_task(self, task_name: str) -> PauseResult:
        """Interrumpe una única tarea activa identificada por su título.

        La confirmación de usuario se exige en la capa de servicio/UI. Este método
        supone que ya fue obtenida, pero vuelve a comprobar título, hilo y turno
        para evitar que una selección ambigua actúe sobre la tarea equivocada.
        """

        query = self._validate_query(task_name)
        with self._client_factory() as client:
            task = self._resolve(query, self._list_tasks(client, query, self.PAGE_SIZE))
            detail = client.request(
                "thread/read", {"threadId": task.thread_id, "includeTurns": True}
            )
            if not isinstance(detail, dict) or not isinstance(detail.get("thread"), dict):
                raise CodexProtocolError("Codex no devolvió el detalle de la tarea.")
            thread = detail["thread"]
            returned_thread_id = self._identifier(thread.get("id"), "threadId")
            if returned_thread_id != task.thread_id:
                raise CodexProtocolError("Codex devolvió una tarea distinta de la solicitada.")

            turns = thread.get("turns")
            if not isinstance(turns, list):
                raise CodexProtocolError("Codex no devolvió la lista de turnos.")
            active_turn_ids = [
                self._identifier(turn.get("id"), "turnId")
                for turn in turns
                if isinstance(turn, dict) and turn.get("status") == "inProgress"
            ]
            if not active_turn_ids:
                raise NoActiveTurnError(
                    f"La tarea «{task.name}» no tiene ningún turno activo que pausar."
                )
            if len(active_turn_ids) > 1:
                raise MultipleActiveTurnsError(
                    f"La tarea «{task.name}» informa de varios turnos activos; no he pausado ninguno."
                )

            turn_id = active_turn_ids[0]
            # Esta es la única llamada que cambia estado. No se reenvía el nombre,
            # texto libre ni ninguna instrucción del modelo.
            client.request(
                "turn/interrupt",
                {"threadId": task.thread_id, "turnId": turn_id},
            )
            return PauseResult(task.name, task.thread_id, turn_id)

    def open_task(self, task_name: str) -> OpenTaskResult:
        """Abre una tarea exacta mediante el protocolo registrado por Codex."""

        task = self.resolve_task(task_name)
        uri = f"codex://threads/{task.thread_id}"
        try:
            self._uri_opener(uri)
        except OSError as exc:
            raise CodexUnavailableError("Windows no pudo abrir la tarea en Codex.") from exc
        return OpenTaskResult(task.name, task.thread_id, uri)

    @staticmethod
    def _open_uri(uri: str) -> None:
        if os.name != "nt" or not hasattr(os, "startfile"):
            raise CodexUnavailableError(
                "Abrir tareas de Codex mediante enlace directo solo está disponible en Windows."
            )
        os.startfile(uri)  # type: ignore[attr-defined]

    def _list_tasks(
        self,
        client: AppServerTransport,
        search_term: str | None,
        limit: int,
    ) -> list[CodexTask]:
        tasks: list[CodexTask] = []
        cursor: str | None = None
        while len(tasks) < limit:
            params: JsonObject = {
                "limit": min(self.PAGE_SIZE, limit - len(tasks)),
                "sortKey": "updated_at",
                "sortDirection": "desc",
                "sourceKinds": self.SOURCE_KINDS,
            }
            if search_term:
                params["searchTerm"] = search_term
            if cursor:
                params["cursor"] = cursor
            response = client.request("thread/list", params)
            if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                raise CodexProtocolError("Codex no devolvió una lista de tareas válida.")
            for raw_task in response["data"]:
                if isinstance(raw_task, dict):
                    # Las operaciones de subagentes aparecen como hilos sin título;
                    # no son tareas visibles que el usuario pueda nombrar de forma
                    # inequívoca en la barra lateral de Codex.
                    if not str(raw_task.get("name") or "").strip():
                        continue
                    tasks.append(self._parse_task(raw_task))
                    if len(tasks) >= limit:
                        break
            next_cursor = response.get("nextCursor")
            if not next_cursor or len(tasks) >= limit:
                break
            if not isinstance(next_cursor, str) or len(next_cursor) > 1000:
                raise CodexProtocolError("Codex devolvió un cursor no válido.")
            cursor = next_cursor
        return tasks

    @classmethod
    def _parse_task(cls, payload: JsonObject) -> CodexTask:
        thread_id = cls._identifier(payload.get("id"), "threadId")
        raw_name = payload.get("name")
        preview = str(payload.get("preview") or "").strip()[:500]
        name = str(raw_name or "").strip()
        if not name:
            name = preview.splitlines()[0][:120] if preview else "(sin título)"
        status_payload = payload.get("status")
        status = (
            str(status_payload.get("type") or "unknown")
            if isinstance(status_payload, dict)
            else str(status_payload or "unknown")
        )
        cwd_value = payload.get("cwd")
        cwd = str(cwd_value)[:1000] if cwd_value else None
        updated_value = payload.get("updatedAt")
        updated_at = updated_value if isinstance(updated_value, int) else None
        return CodexTask(thread_id, name[:200], preview, status[:40], cwd, updated_at)

    @classmethod
    def _resolve(cls, query: str, tasks: list[CodexTask]) -> CodexTask:
        normalized_query = cls._normalize(query)
        exact = [task for task in tasks if cls._normalize(task.name) == normalized_query]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise AmbiguousTaskError(query, exact)

        partial = [task for task in tasks if normalized_query in cls._normalize(task.name)]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise AmbiguousTaskError(query, partial)
        raise TaskNotFoundError(f"No encuentro ninguna tarea de Codex llamada «{query}».")

    @classmethod
    def _validate_query(cls, value: str | None) -> str:
        query = str(value or "").strip()
        if not query:
            raise InvalidTaskNameError("Indica el título de la tarea de Codex.")
        if len(query) > cls.MAX_QUERY_LENGTH:
            raise InvalidTaskNameError("El título de la tarea es demasiado largo.")
        if any(unicodedata.category(character) == "Cc" for character in query):
            raise InvalidTaskNameError("El título contiene caracteres de control.")
        return query

    @staticmethod
    def _normalize(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        without_marks = "".join(
            character for character in decomposed if not unicodedata.combining(character)
        )
        return " ".join(without_marks.split())

    @classmethod
    def _identifier(cls, value: Any, label: str) -> str:
        identifier = str(value or "")
        if not cls._SAFE_IDENTIFIER.fullmatch(identifier):
            raise CodexProtocolError(f"Codex devolvió un {label} no válido.")
        return identifier
