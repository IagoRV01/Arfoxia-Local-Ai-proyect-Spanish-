from __future__ import annotations

import ctypes
import csv
import hashlib
import hmac
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from queue import Queue
from typing import Any
from urllib.parse import parse_qs, urlsplit

try:
    import winreg
except ImportError:  # pragma: no cover - the desktop application targets Windows.
    winreg = None

import mss
import psutil
from PIL import Image

from .config import PROJECT_ROOT, CompanionConfig
from .database import Database

try:
    from send2trash import send2trash
except ImportError:  # Optional: there is deliberately no permanent-delete fallback.
    send2trash = None


MAX_TEXT_WRITE_BYTES = 1024 * 1024
MAX_PRECONDITION_FILE_BYTES = 64 * 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
AUTHORIZED_URI_SCHEMES = {
    "calculator",
    "mailto",
    "ms-clock",
    "ms-settings",
    "ms-windows-store",
    "shell",
    "spotify",
    "steam",
}
YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}
YOUTUBE_EMBED_HOSTS = {
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
YOUTUBE_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ActionValidationError(ValueError):
    """A bounded action failed validation before touching the operating system."""


@dataclass(slots=True)
class ActionResult:
    success: bool
    action: str
    message: str
    data: dict[str, Any] | None = None
    requires_confirmation: bool = False
    requires_authorization: bool = False
    challenge_id: str | None = None
    authorization_expires_at: str | None = None
    authorization_summary: str | None = None
    password_configured: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionDispatcher:
    """Executes only a closed set of typed operations.

    There is intentionally no generic command, shell, PowerShell, permanent file
    deletion, package installation or arbitrary argument execution endpoint.

    ``execute_validated`` is the boundary used after the service has completed
    any required authorization. ``execute`` remains as a compatibility wrapper
    for callers that still use the old confirmation boolean.
    """

    IMMEDIATE = {"open_app", "open_target", "take_screenshot", "pc_status", "volume"}
    SENSITIVE = {"close_app", "lock_computer", "power", "file_operation"}
    CONFIRM = SENSITIVE  # Compatibility for older callers and documentation.

    def __init__(
        self,
        config: CompanionConfig,
        database: Database,
        data_dir: Path,
        events: Queue[dict[str, Any]],
    ) -> None:
        self.config = config
        self.database = database
        self.data_dir = data_dir
        self.events = events
        self.screenshot_dir = data_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def execute(
        self, action: str, arguments: dict[str, Any] | None = None, confirmed: bool = False
    ) -> ActionResult:
        # A caller-controlled boolean is never a privileged grant. Sensitive
        # execution only happens through CompanionService after a consumed
        # password challenge.
        del confirmed
        if arguments is not None and not isinstance(arguments, dict):
            return self._record(
                action,
                {},
                ActionResult(False, action, "Los argumentos de la acción no son válidos."),
            )
        args = dict(arguments or {})
        if action not in self.IMMEDIATE | self.SENSITIVE:
            result = ActionResult(False, action, "Acción no permitida.")
            return self._record(action, args, result)
        if self.is_sensitive(action, args):
            invalid = self.preflight(action, args)
            if invalid is not None:
                return invalid
            result = ActionResult(
                False,
                action,
                "Esta acción necesita autorización local.",
                data={"arguments": self._redact_arguments(action, args)},
                requires_authorization=True,
            )
            return self._record(action, args, result)
        return self.execute_validated(action, args)

    def execute_validated(
        self, action: str, arguments: dict[str, Any] | None = None
    ) -> ActionResult:
        """Execute a typed action after authorization has been checked centrally."""

        if arguments is not None and not isinstance(arguments, dict):
            return self._record(
                action,
                {},
                ActionResult(False, action, "Los argumentos de la acción no son válidos."),
            )
        args = dict(arguments or {})
        handlers = {
            "open_app": self._open_app,
            "open_target": self._open_target,
            "close_app": self._close_app,
            "take_screenshot": self._take_screenshot,
            "pc_status": self._pc_status,
            "volume": self._volume,
            "lock_computer": self._lock_computer,
            "power": self._power,
            "file_operation": self._file_operation,
        }
        handler = handlers.get(action)
        if handler is None:
            return self._record(
                action, args, ActionResult(False, action, "Acción no permitida.")
            )
        try:
            result = handler(args)
        except ActionValidationError as exc:
            result = ActionResult(False, action, str(exc))
        except Exception:  # User-facing boundary: do not leak paths or OS internals.
            result = ActionResult(
                False, action, "No pude completar la acción de forma segura."
            )
        return self._record(action, args, result)

    def is_sensitive(
        self, action: str, arguments: dict[str, Any] | None = None
    ) -> bool:
        """Classify an action deterministically before an authorization challenge."""

        args = arguments if isinstance(arguments, dict) else {}
        if action in {"close_app", "lock_computer", "file_operation"}:
            return True
        if action == "power":
            return str(args.get("operation", "")).strip().casefold() != "cancel"
        if action == "open_app":
            app_id = str(args.get("app", "")).strip().casefold()
            return app_id not in self.config.apps
        if action != "open_target":
            return action in self.SENSITIVE

        target = str(args.get("target", "")).strip()
        if not target:
            return True
        if target.casefold() in self.config.apps:
            return False
        expanded_target = os.path.expandvars(target)
        looks_like_absolute_path = Path(expanded_target).is_absolute()
        try:
            parsed = urlsplit(target)
        except ValueError:
            return True
        if parsed.scheme and not looks_like_absolute_path:
            return parsed.scheme.casefold() != "https"
        try:
            path = self._validated_path(target)
        except ActionValidationError:
            return True
        # Opening a directory is a navigation action. Opening any file may
        # invoke a registered handler (including macro-capable documents), so
        # it always receives the same local authorization as an executable.
        return not (path.exists() and path.is_dir())

    def preflight(
        self, action: str, arguments: dict[str, Any] | None = None
    ) -> ActionResult | None:
        """Validate a sensitive request without producing any OS side effect."""

        args = dict(arguments or {})
        try:
            self.validate_for_authorization(action, args)
        except ActionValidationError as exc:
            return self._record(action, args, ActionResult(False, action, str(exc)))
        return None

    def validation_failure(
        self, action: str, arguments: dict[str, Any], message: str
    ) -> ActionResult:
        return self._record(action, arguments, ActionResult(False, action, message))

    def validate_for_authorization(
        self, action: str, arguments: dict[str, Any]
    ) -> None:
        if action == "open_target":
            self._validated_open_target(arguments)
            return
        if action == "close_app":
            self._require_keys(arguments, required={"app"}, allowed={"app"})
            app = arguments.get("app")
            if not isinstance(app, str) or app.strip().casefold() not in self.config.apps:
                raise ActionValidationError("La aplicación indicada no está configurada.")
            if not self.config.apps[app.strip().casefold()].processes:
                raise ActionValidationError("La aplicación no admite cierre controlado.")
            return
        if action == "lock_computer":
            self._require_keys(arguments, required=set(), allowed=set())
            return
        if action == "power":
            self._require_keys(
                arguments, required={"operation"}, allowed={"operation"}
            )
            operation = arguments.get("operation")
            if not isinstance(operation, str) or operation.casefold() not in {
                "shutdown",
                "restart",
                "cancel",
            }:
                raise ActionValidationError("Operación de energía no permitida.")
            if not self.config.allow_power_actions:
                raise ActionValidationError(
                    "Las acciones de energía están desactivadas en config.json."
                )
            return
        if action == "file_operation":
            self._validate_file_operation(arguments)
            return
        raise ActionValidationError("Acción sensible no permitida.")

    def canonicalize_authorization_args(
        self, action: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Bind challenges to canonical paths/resolved app targets when possible."""

        prepared = dict(arguments)
        if action == "open_target":
            kind, value = self._validated_open_target(prepared)
            if kind in {"named", "path"}:
                prepared["target"] = value
            return prepared
        if action == "file_operation":
            if "path" in prepared:
                prepared["path"] = str(self._validated_path(prepared["path"]))
            if "destination" in prepared:
                prepared["destination"] = str(
                    self._validated_path(prepared["destination"])
                )
            operation = str(prepared.get("operation") or "").casefold()
            path = Path(str(prepared.get("path") or ""))
            if operation in {"write_text", "append_text"} and path.is_file():
                prepared["_expected_sha256"] = self._file_sha256(path)
        return prepared

    @staticmethod
    def _file_sha256(path: Path) -> str:
        try:
            if path.stat().st_size > MAX_PRECONDITION_FILE_BYTES:
                raise ActionValidationError(
                    "El archivo existente es demasiado grande para una sobrescritura segura."
                )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            return digest.hexdigest()
        except ActionValidationError:
            raise
        except OSError as exc:
            raise ActionValidationError(
                "No pude fijar la versión actual del archivo."
            ) from exc

    def _verify_file_precondition(self, path: Path, args: dict[str, Any]) -> None:
        expected = args.get("_expected_sha256")
        if expected is None:
            return
        if not isinstance(expected, str) or not path.is_file():
            raise ActionValidationError(
                "El archivo cambió desde que se solicitó la autorización."
            )
        if not hmac.compare_digest(self._file_sha256(path), expected):
            raise ActionValidationError(
                "El archivo cambió desde que se solicitó la autorización; vuelve a pedir la acción."
            )

    def _record(
        self, action: str, arguments: dict[str, Any], result: ActionResult
    ) -> ActionResult:
        self.database.audit(
            action,
            self._redact_arguments(action, arguments),
            result.success,
            result.message,
        )
        self.events.put({"type": "action", "action": action, "result": result.to_dict()})
        return result

    @staticmethod
    def _redact_arguments(action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        redacted = dict(arguments)
        if action == "file_operation" and "content" in redacted:
            content = redacted.pop("content")
            replacement: dict[str, Any] = {"redacted": True}
            if isinstance(content, str):
                try:
                    replacement["length_bytes"] = len(content.encode("utf-8"))
                except UnicodeError:
                    replacement["invalid_utf8"] = True
                    replacement["length_characters"] = len(content)
            redacted["content"] = replacement
        return redacted

    def _open_app(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(args, required={"app"}, allowed={"app"})
        if not isinstance(args["app"], str):
            raise ActionValidationError("El identificador de aplicación no es válido.")
        app_id = args["app"].strip().casefold()
        entry = self.config.apps.get(app_id)
        if not entry:
            allowed = ", ".join(sorted(self.config.apps))
            return ActionResult(False, "open_app", f"Aplicación no autorizada. Permitidas: {allowed}")
        self._launch_configured_app(app_id)
        return ActionResult(True, "open_app", f"He abierto {app_id}.")

    def _launch_configured_app(self, app_id: str) -> None:
        entry = self.config.apps[app_id]
        if not entry.command or not all(isinstance(part, str) and part for part in entry.command):
            raise ActionValidationError("La aplicación no tiene un comando configurado válido.")
        command = [os.path.expandvars(part) for part in entry.command]
        executable = Path(command[0])
        if executable.name.lower() != "explorer.exe" and not executable.exists():
            raise ActionValidationError(f"No encuentro {app_id} en la ruta configurada.")
        subprocess.Popen(command, close_fds=True, shell=False)

    def _open_target(self, args: dict[str, Any]) -> ActionResult:
        kind, value = self._validated_open_target(args)
        if kind == "app":
            self._launch_configured_app(value)
            return ActionResult(True, "open_target", f"He abierto {value}.")
        try:
            self._shell_open(value)
        except OSError as exc:
            if kind == "https":
                raise ActionValidationError(
                    "Windows no aceptó la solicitud para abrir el enlace."
                ) from exc
            raise ActionValidationError(
                "Windows no aceptó la solicitud para abrir ese destino."
            ) from exc
        if kind == "https":
            youtube_kind = self._youtube_target_kind(value)
            if youtube_kind == "video":
                message = (
                    "Windows aceptó abrir el vídeo de YouTube en el navegador "
                    "predeterminado."
                )
            elif youtube_kind == "search":
                message = (
                    "Windows aceptó abrir la búsqueda de YouTube en el navegador "
                    "predeterminado."
                )
            elif youtube_kind:
                message = (
                    "Windows aceptó abrir YouTube en el navegador predeterminado."
                )
            else:
                message = (
                    "Windows aceptó abrir el enlace HTTPS en el navegador predeterminado."
                )
            return ActionResult(
                True,
                "open_target",
                message,
                {
                    "target": value,
                    "destination": "default_browser",
                    # ShellExecute/os.startfile acknowledges the launch request,
                    # but it cannot prove that the page finished loading.
                    "launch_status": "accepted_by_windows",
                    "youtube_kind": youtube_kind,
                },
            )
        elif kind in {"uri", "named"}:
            message = "He abierto la ventana o aplicación indicada."
        else:
            path = Path(value)
            path_kind = "carpeta" if path.is_dir() else "archivo"
            message = f"He abierto el {path_kind} indicado."
        return ActionResult(True, "open_target", message)

    def _validated_open_target(self, args: dict[str, Any]) -> tuple[str, str]:
        self._require_keys(args, required={"target"}, allowed={"target"})
        if not isinstance(args["target"], str):
            raise ActionValidationError("El destino no es válido.")
        target = args["target"].strip()
        if not target or len(target) > 2048 or "\x00" in target or "\r" in target or "\n" in target:
            raise ActionValidationError("El destino no es válido.")

        app_id = target.casefold()
        if app_id in self.config.apps:
            return "app", app_id

        expanded_target = os.path.expandvars(target)
        looks_like_absolute_path = Path(expanded_target).is_absolute()
        try:
            parsed = urlsplit(target)
        except ValueError as exc:
            raise ActionValidationError("La dirección indicada no es válida.") from exc
        if parsed.scheme and not looks_like_absolute_path:
            scheme = parsed.scheme.casefold()
            if scheme == "https":
                try:
                    hostname = parsed.hostname
                    username = parsed.username
                    password = parsed.password
                except ValueError as exc:
                    raise ActionValidationError(
                        "La dirección HTTPS no es válida."
                    ) from exc
                if not hostname or username is not None or password is not None:
                    raise ActionValidationError("La dirección HTTPS no es válida.")
                if (
                    "\\" in target
                    or any(char.isspace() for char in target)
                    or re.search(r"%(?![0-9A-Fa-f]{2})", target)
                ):
                    raise ActionValidationError("La dirección HTTPS no es válida.")
                try:
                    # urlsplit defers validation of malformed/out-of-range
                    # ports until this property is accessed.
                    _ = parsed.port
                except ValueError as exc:
                    raise ActionValidationError(
                        "La dirección HTTPS no es válida."
                    ) from exc
                self._youtube_target_kind(target, validate=True)
            elif scheme not in AUTHORIZED_URI_SCHEMES:
                raise ActionValidationError("El protocolo indicado no está permitido.")
            return ("https" if scheme == "https" else "uri"), target

        named_target = self._resolve_named_application(target)
        if named_target is not None:
            return "named", named_target

        path = self._validated_path(target)
        if not path.exists():
            raise ActionValidationError("No encuentro el archivo o carpeta indicado.")
        return "path", str(path)

    @staticmethod
    def _resolve_named_application(target: str) -> str | None:
        """Resolve an installed app name without accepting command arguments."""

        if any(separator in target for separator in ("/", "\\", ":")):
            return None
        if len(target) > 160 or not re.fullmatch(r"[\w .+()\-]+", target, flags=re.UNICODE):
            return None
        candidates = [target]
        if not target.casefold().endswith((".exe", ".com")):
            candidates.append(f"{target}.exe")
        for candidate in candidates:
            located = shutil.which(candidate)
            if located:
                return str(Path(located).resolve())

        if winreg is not None:
            registry_roots = (
                winreg.HKEY_CURRENT_USER,
                winreg.HKEY_LOCAL_MACHINE,
            )
            for candidate in candidates:
                for root in registry_roots:
                    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                        key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{candidate}"
                        try:
                            with winreg.OpenKey(
                                root, key_path, 0, winreg.KEY_READ | view
                            ) as key:
                                value, _ = winreg.QueryValueEx(key, None)
                        except OSError:
                            continue
                        if isinstance(value, str):
                            executable = Path(
                                os.path.expandvars(value.strip().strip('"'))
                            )
                            if executable.is_file():
                                return str(executable.resolve())

        normalized = Path(target).stem.strip().casefold()
        start_roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
            / "Microsoft/Windows/Start Menu/Programs",
        ]
        matches: list[Path] = []
        for root in start_roots:
            if not root.is_dir():
                continue
            try:
                matches.extend(
                    shortcut
                    for shortcut in root.rglob("*.lnk")
                    if shortcut.stem.strip().casefold() == normalized
                )
            except OSError:
                continue
        if matches:
            return str(sorted(matches, key=lambda item: str(item).casefold())[0].resolve())
        return None

    @staticmethod
    def _shell_open(target: str) -> None:
        """Ask Windows to open one exact target without a command interpreter."""

        os.startfile(target)  # type: ignore[attr-defined]

    @staticmethod
    def _youtube_target_kind(
        target: str,
        *,
        validate: bool = False,
    ) -> str | None:
        """Classify YouTube URLs and reject malformed video/search targets.

        This only proves URL syntax. Whether a video actually exists must come
        from a search result; an eleven-character identifier alone is not
        evidence that YouTube has such a video.
        """

        parsed = urlsplit(target)
        hostname = (parsed.hostname or "").casefold().rstrip(".")
        is_short = hostname in YOUTUBE_SHORT_HOSTS
        is_standard = hostname in YOUTUBE_HOSTS
        is_embed = hostname in YOUTUBE_EMBED_HOSTS
        if not (is_short or is_standard or is_embed):
            return None

        segments = [segment for segment in parsed.path.split("/") if segment]
        query = parse_qs(parsed.query, keep_blank_values=True)

        def invalid(message: str) -> None:
            if validate:
                raise ActionValidationError(message)

        if is_short:
            if not segments:
                return "page"
            if len(segments) != 1 or not YOUTUBE_VIDEO_ID.fullmatch(segments[0]):
                invalid("El enlace corto de YouTube no contiene un vídeo válido.")
                return "page"
            return "video"

        route = segments[0].casefold() if segments else ""
        if route == "watch":
            video_ids = query.get("v", [])
            if (
                len(video_ids) != 1
                or not YOUTUBE_VIDEO_ID.fullmatch(video_ids[0])
            ):
                invalid("El enlace de YouTube no contiene un vídeo válido.")
                return "page"
            return "video"

        if route in {"shorts", "live", "v"} or (
            route == "embed"
            and len(segments) > 1
            and segments[1].casefold() != "videoseries"
        ):
            if (
                len(segments) != 2
                or not YOUTUBE_VIDEO_ID.fullmatch(segments[1])
            ):
                invalid("El enlace de YouTube no contiene un vídeo válido.")
                return "page"
            return "video"

        if route == "results":
            searches = query.get("search_query", [])
            if len(searches) != 1 or not searches[0].strip():
                invalid("La búsqueda de YouTube está vacía.")
                return "page"
            return "search"

        return "page"

    @staticmethod
    def _require_keys(
        arguments: dict[str, Any], *, required: set[str], allowed: set[str]
    ) -> None:
        missing = required - arguments.keys()
        unexpected = arguments.keys() - allowed
        if missing:
            raise ActionValidationError(
                f"Faltan argumentos obligatorios: {', '.join(sorted(missing))}."
            )
        if unexpected:
            raise ActionValidationError(
                f"Hay argumentos no permitidos: {', '.join(sorted(unexpected))}."
            )

    @staticmethod
    def _validated_path(value: Any) -> Path:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ActionValidationError("La ruta no es válida.")
        raw = os.path.expandvars(value.strip())
        lowered = raw.replace("/", "\\").casefold()
        if lowered.startswith(("\\\\.\\", "\\\\?\\", "\\??\\", "\\device\\")):
            raise ActionValidationError("No se permiten rutas de dispositivo.")

        candidate = Path(raw)
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise ActionValidationError("La ruta debe ser absoluta y no contener '..'.")
        path = Path(os.path.abspath(candidate))
        if path.parent == path:
            raise ActionValidationError("No se puede operar sobre una raíz del sistema.")

        for part in path.parts[1:]:
            if ":" in part:
                raise ActionValidationError("No se permiten flujos alternativos en rutas.")
            reserved_candidate = part.rstrip(" .").split(".", 1)[0].casefold()
            if reserved_candidate in WINDOWS_RESERVED_NAMES:
                raise ActionValidationError("La ruta contiene un nombre reservado de Windows.")
        return path

    def _file_operation(self, args: dict[str, Any]) -> ActionResult:
        operation = args.get("operation")
        if not isinstance(operation, str):
            raise ActionValidationError("La operación de archivo no es válida.")
        operation = operation.strip().casefold()
        handlers = {
            "create_directory": self._create_directory,
            "write_text": self._write_text,
            "append_text": self._append_text,
            "copy": self._copy_path,
            "move": self._move_path,
            "rename": self._rename_path,
            "trash": self._trash_path,
        }
        handler = handlers.get(operation)
        if handler is None:
            raise ActionValidationError("Operación de archivo no permitida.")
        return handler(args)

    def _validate_file_operation(self, args: dict[str, Any]) -> None:
        operation = args.get("operation")
        if not isinstance(operation, str):
            raise ActionValidationError("La operación de archivo no es válida.")
        operation = operation.strip().casefold()
        if operation == "create_directory":
            self._require_keys(
                args, required={"operation", "path"}, allowed={"operation", "path"}
            )
            path = self._validated_path(args["path"])
            self._ensure_file_path_allowed(path, operation)
            if path.exists():
                raise ActionValidationError("La ruta de destino ya existe.")
            self._require_parent(path)
            return
        if operation in {"write_text", "append_text"}:
            allowed = {"operation", "path", "content"}
            if operation == "write_text":
                allowed.add("overwrite")
            self._require_keys(
                args,
                required={"operation", "path", "content"},
                allowed=allowed,
            )
            path = self._validated_path(args["path"])
            self._ensure_file_path_allowed(path, operation)
            content = self._validated_text(args["content"])
            self._require_parent(path)
            if path.exists() and not path.is_file():
                raise ActionValidationError("La ruta de destino no es un archivo.")
            if operation == "write_text":
                overwrite = self._validated_overwrite(args)
                if path.exists() and not overwrite:
                    raise ActionValidationError(
                        "El archivo ya existe; no se sobrescribe sin permiso explícito."
                    )
                if path.exists() and overwrite:
                    self._file_sha256(path)
            elif path.exists():
                try:
                    existing_size = path.stat().st_size
                except OSError as exc:
                    raise ActionValidationError("No pude comprobar el archivo existente.") from exc
                if existing_size + len(content.encode("utf-8")) > MAX_TEXT_WRITE_BYTES:
                    raise ActionValidationError(
                        "El resultado superaría el límite de texto de 1 MiB."
                    )
                self._file_sha256(path)
            return
        if operation in {"copy", "move", "rename"}:
            source, destination, _ = self._source_and_destination(
                args, operation=operation
            )
            self._ensure_file_path_allowed(source, operation)
            self._ensure_file_path_allowed(destination, operation)
            return
        if operation == "trash":
            self._require_keys(
                args, required={"operation", "path"}, allowed={"operation", "path"}
            )
            path = self._validated_path(args["path"])
            self._ensure_file_path_allowed(path, operation)
            if not path.exists():
                raise ActionValidationError("La ruta indicada no existe.")
            if path.is_symlink():
                raise ActionValidationError("No se enviará un enlace simbólico a la Papelera.")
            if send2trash is None:
                raise ActionValidationError(
                    "No está disponible la integración con la Papelera."
                )
            return
        raise ActionValidationError("Operación de archivo no permitida.")

    def _ensure_file_path_allowed(self, path: Path, operation: str) -> None:
        resolved = path.resolve(strict=False)
        data_root = self.data_dir.resolve()
        project_root = PROJECT_ROOT.resolve()
        if resolved == data_root:
            raise ActionValidationError("La carpeta interna de Arfoxia está protegida.")
        protected_names = {
            "authorization.json",
            "config.json",
            "glaceon.lock",
            "secrets.json",
            "startup-error.log",
        }
        if resolved.parent == data_root and (
            resolved.name.casefold() in protected_names
            or resolved.name.casefold().startswith("companion.sqlite3")
        ):
            raise ActionValidationError("Ese archivo interno de Arfoxia está protegido.")
        try:
            resolved.relative_to(project_root)
        except ValueError:
            pass
        else:
            raise ActionValidationError("Los archivos del propio programa están protegidos.")

        lowered = str(resolved).replace("/", "\\").casefold()
        if "\\start menu\\programs\\startup" in lowered:
            raise ActionValidationError("La carpeta de inicio automático está protegida.")

        if operation in {"trash", "move", "rename"}:
            home = Path.home().resolve()
            broad_roots = {
                home,
                *(home / name for name in ("Desktop", "Documents", "Downloads", "Pictures", "Videos")),
            }
            if resolved in broad_roots:
                raise ActionValidationError(
                    "Esa operación es demasiado amplia; indica un archivo o subcarpeta concreta."
                )

    def _create_directory(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(
            args, required={"operation", "path"}, allowed={"operation", "path"}
        )
        path = self._validated_path(args["path"])
        self._ensure_file_path_allowed(path, "create_directory")
        if path.exists():
            raise ActionValidationError("La ruta de destino ya existe.")
        if not path.parent.exists() or not path.parent.is_dir():
            raise ActionValidationError("La carpeta superior no existe.")
        path.mkdir()
        return ActionResult(
            True, "file_operation", "He creado la carpeta.", {"operation": "create_directory"}
        )

    def _write_text(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(
            args,
            required={"operation", "path", "content"},
            allowed={
                "operation",
                "path",
                "content",
                "overwrite",
                "_expected_sha256",
            },
        )
        path = self._validated_path(args["path"])
        self._ensure_file_path_allowed(path, "write_text")
        content = self._validated_text(args["content"])
        overwrite = self._validated_overwrite(args)
        if path.exists() and not overwrite:
            raise ActionValidationError(
                "El archivo ya existe; no se sobrescribe sin permiso explícito."
            )
        if path.exists() and not path.is_file():
            raise ActionValidationError("La ruta de destino no es un archivo.")
        self._verify_file_precondition(path, args)
        self._atomic_write_text(path, content, overwrite=overwrite)
        return ActionResult(
            True, "file_operation", "He escrito el archivo de texto.", {"operation": "write_text"}
        )

    def _append_text(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(
            args,
            required={"operation", "path", "content"},
            allowed={"operation", "path", "content", "_expected_sha256"},
        )
        path = self._validated_path(args["path"])
        self._ensure_file_path_allowed(path, "append_text")
        addition = self._validated_text(args["content"])
        if path.exists() and not path.is_file():
            raise ActionValidationError("La ruta de destino no es un archivo.")
        self._verify_file_precondition(path, args)
        try:
            if path.exists() and path.stat().st_size > MAX_TEXT_WRITE_BYTES:
                raise ActionValidationError("El archivo existente supera el límite de 1 MiB.")
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except UnicodeError as exc:
            raise ActionValidationError("El archivo existente no contiene texto UTF-8.") from exc
        combined = self._validated_text(existing + addition)
        self._atomic_write_text(path, combined, overwrite=path.exists())
        return ActionResult(
            True, "file_operation", "He añadido texto al archivo.", {"operation": "append_text"}
        )

    @staticmethod
    def _validated_text(value: Any) -> str:
        if not isinstance(value, str):
            raise ActionValidationError("El contenido debe ser texto UTF-8.")
        try:
            encoded = value.encode("utf-8")
        except UnicodeError as exc:
            raise ActionValidationError("El contenido debe ser texto UTF-8 válido.") from exc
        if len(encoded) > MAX_TEXT_WRITE_BYTES:
            raise ActionValidationError("El texto supera el límite de 1 MiB.")
        return value

    @staticmethod
    def _validated_overwrite(args: dict[str, Any]) -> bool:
        overwrite = args.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ActionValidationError("El indicador overwrite debe ser booleano.")
        return overwrite

    @staticmethod
    def _require_parent(path: Path) -> None:
        if not path.parent.exists() or not path.parent.is_dir():
            raise ActionValidationError("La carpeta de destino no existe.")

    def _atomic_write_text(self, path: Path, content: str, *, overwrite: bool) -> None:
        self._require_parent(path)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # On Windows os.rename is atomic and refuses an existing target.
                os.rename(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _source_and_destination(
        self, args: dict[str, Any], *, operation: str
    ) -> tuple[Path, Path, bool]:
        self._require_keys(
            args,
            required={"operation", "path", "destination"},
            allowed={"operation", "path", "destination", "overwrite"},
        )
        source = self._validated_path(args["path"])
        destination = self._validated_path(args["destination"])
        self._ensure_file_path_allowed(source, operation)
        self._ensure_file_path_allowed(destination, operation)
        overwrite = self._validated_overwrite(args)
        if source == destination:
            raise ActionValidationError("El origen y el destino no pueden ser iguales.")
        if not source.exists():
            raise ActionValidationError("La ruta de origen no existe.")
        if source.is_symlink():
            raise ActionValidationError("No se operará sobre un enlace simbólico.")
        self._require_parent(destination)
        if destination.exists() and not overwrite:
            raise ActionValidationError(
                "El destino ya existe; no se sobrescribe sin permiso explícito."
            )
        if destination.exists() and destination.is_dir():
            raise ActionValidationError("No se sobrescribirá una carpeta existente.")
        if source.is_dir():
            try:
                destination.relative_to(source)
            except ValueError:
                pass
            else:
                raise ActionValidationError(
                    "El destino no puede estar dentro de la carpeta de origen."
                )
        if operation == "rename" and source.parent != destination.parent:
            raise ActionValidationError("Renombrar exige mantener la misma carpeta.")
        return source, destination, overwrite

    def _copy_path(self, args: dict[str, Any]) -> ActionResult:
        source, destination, overwrite = self._source_and_destination(
            args, operation="copy"
        )
        if source.is_dir():
            if overwrite:
                raise ActionValidationError("No se sobrescribirá una carpeta con copy.")
            shutil.copytree(source, destination, symlinks=True)
        elif overwrite:
            file_descriptor, temporary_name = tempfile.mkstemp(
                dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
            )
            os.close(file_descriptor)
            temporary = Path(temporary_name)
            try:
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            with source.open("rb") as input_file, destination.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
            shutil.copystat(source, destination)
        return ActionResult(
            True, "file_operation", "He copiado el elemento.", {"operation": "copy"}
        )

    def _move_path(self, args: dict[str, Any]) -> ActionResult:
        source, destination, overwrite = self._source_and_destination(
            args, operation="move"
        )
        if overwrite:
            if source.is_dir():
                raise ActionValidationError("No se sobrescribirá una carpeta con move.")
            os.replace(source, destination)
        else:
            shutil.move(str(source), str(destination))
        return ActionResult(
            True, "file_operation", "He movido el elemento.", {"operation": "move"}
        )

    def _rename_path(self, args: dict[str, Any]) -> ActionResult:
        source, destination, overwrite = self._source_and_destination(
            args, operation="rename"
        )
        if overwrite:
            if source.is_dir():
                raise ActionValidationError("No se sobrescribirá una carpeta al renombrar.")
            os.replace(source, destination)
        else:
            source.rename(destination)
        return ActionResult(
            True, "file_operation", "He renombrado el elemento.", {"operation": "rename"}
        )

    def _trash_path(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(
            args, required={"operation", "path"}, allowed={"operation", "path"}
        )
        path = self._validated_path(args["path"])
        self._ensure_file_path_allowed(path, "trash")
        if not path.exists():
            raise ActionValidationError("La ruta indicada no existe.")
        if path.is_symlink():
            raise ActionValidationError("No se enviará un enlace simbólico a la Papelera.")
        if send2trash is None:
            raise ActionValidationError(
                "No está disponible la integración con la Papelera; no se ha borrado nada."
            )
        send2trash(str(path))
        return ActionResult(
            True,
            "file_operation",
            "He enviado el elemento a la Papelera.",
            {"operation": "trash"},
        )

    def _close_app(self, args: dict[str, Any]) -> ActionResult:
        app_id = str(args.get("app", "")).strip().lower()
        entry = self.config.apps.get(app_id)
        if not entry or not entry.processes:
            return ActionResult(False, "close_app", "Aplicación no autorizada para cierre.")
        allowed = {name.casefold() for name in entry.processes}
        requested: list[tuple[psutil.Process, str]] = []
        for process in psutil.process_iter(["name"]):
            try:
                name = (process.info["name"] or "").casefold()
                if name in allowed:
                    process.terminate()
                    requested.append((process, process.info["name"] or name))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if not requested:
            return ActionResult(False, "close_app", f"{app_id} no estaba en ejecución.")
        gone, alive = psutil.wait_procs(
            [process for process, _ in requested], timeout=3
        )
        gone_ids = {process.pid for process in gone}
        closed = [name for process, name in requested if process.pid in gone_ids]
        if alive:
            return ActionResult(
                False,
                "close_app",
                f"Solicité cerrar {app_id}, pero algún proceso sigue abierto.",
                {"processes_closed": closed, "processes_still_open": len(alive)},
            )
        return ActionResult(
            True, "close_app", f"He cerrado {app_id}.", {"processes": closed}
        )

    def _take_screenshot(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(args, required=set(), allowed={"monitor"})
        self.cleanup_screenshots()
        with mss.mss() as capture:
            requested = args.get("monitor")
            if requested is None:
                monitor_index = next(
                    (
                        index
                        for index, monitor in enumerate(capture.monitors)
                        if index > 0 and monitor.get("is_primary")
                    ),
                    1,
                )
            else:
                monitor_index = int(requested)
            if monitor_index < 1 or monitor_index >= len(capture.monitors):
                monitor_index = 1
            shot = capture.grab(capture.monitors[monitor_index])
            image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.thumbnail((1600, 1000), Image.Resampling.LANCZOS)
        screenshot_id = uuid.uuid4().hex
        output = self.screenshot_dir / f"{screenshot_id}.webp"
        image.save(output, "WEBP", quality=82, method=4)
        return ActionResult(
            True,
            "take_screenshot",
            "He hecho una captura del monitor principal.",
            {"screenshot_id": screenshot_id, "width": image.width, "height": image.height},
        )

    def _pc_status(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(args, required=set(), allowed=set())
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(Path.home().anchor)
        cpu_frequency = psutil.cpu_freq()
        data: dict[str, Any] = {
            "cpu_percent": psutil.cpu_percent(interval=0.15),
            "cpu_name": (
                os.environ.get("PROCESSOR_IDENTIFIER")
                or platform.processor()
                or "Procesador"
            ),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "cpu_frequency_mhz": (
                round(float(cpu_frequency.current), 0) if cpu_frequency else None
            ),
            "memory_percent": memory.percent,
            "memory_used_gb": round(memory.used / 1024**3, 1),
            "memory_total_gb": round(memory.total / 1024**3, 1),
            "memory_available_gb": round(memory.available / 1024**3, 1),
            "disk_percent": disk.percent,
            "disk_used_gb": round(disk.used / 1024**3, 1),
            "disk_total_gb": round(disk.total / 1024**3, 1),
            "disk_free_gb": round(disk.free / 1024**3, 1),
            "system": {
                "os_name": f"{platform.system()} {platform.release()}".strip(),
                "os_version": platform.version(),
                "architecture": platform.machine(),
                "hostname": platform.node(),
                "uptime_seconds": max(0, round(time.time() - psutil.boot_time())),
            },
            "battery": None,
            "gpus": [],
        }
        battery = psutil.sensors_battery()
        if battery:
            data["battery"] = {"percent": battery.percent, "plugged": battery.power_plugged}
        try:
            output = subprocess.run(
                [
                    r"C:\Windows\System32\nvidia-smi.exe",
                    (
                        "--query-gpu=index,uuid,name,driver_version,pci.bus_id,"
                        "utilization.gpu,memory.used,memory.total,memory.free,"
                        "temperature.gpu,power.draw,power.limit"
                    ),
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
                check=True,
                shell=False,
            ).stdout.strip()
            if output:
                ai_uuid = str(getattr(self.config, "ai_gpu_uuid", "")).casefold()
                gaming_uuid = str(
                    getattr(self.config, "gaming_gpu_uuid", "")
                ).casefold()

                def optional_float(value: str) -> float | None:
                    try:
                        return float(value.strip())
                    except (TypeError, ValueError):
                        return None

                gpus: list[dict[str, Any]] = []
                for row in csv.reader(StringIO(output)):
                    if len(row) != 12:
                        continue
                    (
                        index,
                        gpu_uuid,
                        name,
                        driver,
                        bus_id,
                        utilization,
                        used,
                        total,
                        free,
                        temperature,
                        power_draw,
                        power_limit,
                    ) = (part.strip() for part in row)
                    normalized_uuid = gpu_uuid.casefold()
                    if normalized_uuid == ai_uuid:
                        role = "ai"
                    elif normalized_uuid == gaming_uuid or (
                        ai_uuid and normalized_uuid != ai_uuid
                    ):
                        role = "gaming"
                    else:
                        role = "available"
                    entry = {
                        "index": int(index),
                        "uuid": gpu_uuid,
                        "name": name,
                        "role": role,
                        "driver_version": driver,
                        "pci_bus_id": bus_id,
                        "utilization_percent": optional_float(utilization),
                        "memory_used_mb": optional_float(used),
                        "memory_total_mb": optional_float(total),
                        "memory_free_mb": optional_float(free),
                        "temperature_c": optional_float(temperature),
                        "power_draw_w": optional_float(power_draw),
                        "power_limit_w": optional_float(power_limit),
                    }
                    gpus.append(entry)
                data["gpus"] = gpus
                # Preserve the original single-GPU contract for older mobile
                # builds while preferring the dedicated AI card.
                legacy_gpu = next(
                    (gpu for gpu in gpus if gpu["role"] == "ai"),
                    gpus[0] if gpus else None,
                )
                if legacy_gpu is not None:
                    data["gpu"] = {
                        "utilization_percent": legacy_gpu["utilization_percent"],
                        "memory_used_mb": legacy_gpu["memory_used_mb"],
                        "memory_total_mb": legacy_gpu["memory_total_mb"],
                        "temperature_c": legacy_gpu["temperature_c"],
                    }
        except (OSError, ValueError, subprocess.SubprocessError):
            data["gpu"] = None
            data["gpus"] = []
        return ActionResult(True, "pc_status", "Este es el estado actual del PC.", data)

    def _volume(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(
            args, required={"operation"}, allowed={"operation", "steps"}
        )
        operation_value = args.get("operation")
        if not isinstance(operation_value, str):
            raise ActionValidationError("La operación de volumen no es válida.")
        operation = operation_value.lower()
        steps_value = args.get("steps", 2)
        if not isinstance(steps_value, int) or isinstance(steps_value, bool):
            raise ActionValidationError("El número de pasos de volumen no es válido.")
        steps = max(1, min(steps_value, 10))
        keys = {"mute": 0xAD, "down": 0xAE, "up": 0xAF}
        if operation not in keys:
            return ActionResult(False, "volume", "Operación de volumen no permitida.")
        repeats = 1 if operation == "mute" else steps
        for _ in range(repeats):
            ctypes.windll.user32.keybd_event(keys[operation], 0, 0, 0)
            ctypes.windll.user32.keybd_event(keys[operation], 0, 2, 0)
        return ActionResult(True, "volume", f"Volumen: {operation}.")

    def _lock_computer(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(args, required=set(), allowed=set())
        if not ctypes.windll.user32.LockWorkStation():
            return ActionResult(False, "lock_computer", "Windows no permitió bloquear la sesión.")
        return ActionResult(True, "lock_computer", "He bloqueado la sesión.")

    def _power(self, args: dict[str, Any]) -> ActionResult:
        self._require_keys(args, required={"operation"}, allowed={"operation"})
        operation_value = args.get("operation")
        if not isinstance(operation_value, str):
            raise ActionValidationError("Operación de energía no permitida.")
        operation = operation_value.lower()
        if not self.config.allow_power_actions:
            return ActionResult(
                False,
                "power",
                "Las acciones de energía están desactivadas en config.json.",
            )
        commands = {
            "shutdown": ["shutdown.exe", "/s", "/t", "30"],
            "restart": ["shutdown.exe", "/r", "/t", "30"],
            "cancel": ["shutdown.exe", "/a"],
        }
        if operation not in commands:
            return ActionResult(False, "power", "Operación de energía no permitida.")
        completed = subprocess.run(
            commands[operation],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            return ActionResult(
                False,
                "power",
                "Windows rechazó la operación de energía o no había ningún temporizador que cancelar.",
            )
        message = "He cancelado el apagado." if operation == "cancel" else f"He programado {operation} en 30 segundos."
        return ActionResult(True, "power", message)

    def screenshot_path(self, screenshot_id: str) -> Path | None:
        if not screenshot_id.isalnum() or len(screenshot_id) != 32:
            return None
        path = (self.screenshot_dir / f"{screenshot_id}.webp").resolve()
        if path.parent != self.screenshot_dir.resolve() or not path.exists():
            return None
        return path

    def cleanup_screenshots(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(hours=self.config.screenshot_retention_hours)
        for path in self.screenshot_dir.glob("*.webp"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                path.unlink(missing_ok=True)
