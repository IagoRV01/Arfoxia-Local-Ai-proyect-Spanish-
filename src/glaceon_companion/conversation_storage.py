from __future__ import annotations

import hashlib
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .database import Database, StorageLimitExceeded

if TYPE_CHECKING:
    from .attachments import PreparedAttachment


DEFAULT_STORAGE_LIMIT_BYTES = 150 * 1024**3
DEFAULT_MIN_FREE_BYTES = 20 * 1024**3


class ConversationStorageError(ValueError):
    """Safe, user-facing failure while archiving a conversation file."""


class ConversationStorageQuotaError(ConversationStorageError):
    """The logical quota or minimum free-disk reserve would be exceeded."""


class ConversationStorageCorruptionError(ConversationStorageError):
    """Stored metadata and bytes do not agree."""


class ConversationStorage:
    """Content-addressed, quota-aware archive for conversation attachments."""

    def __init__(
        self,
        root: Path,
        database: Database,
        limit_bytes: int = DEFAULT_STORAGE_LIMIT_BYTES,
        min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    ) -> None:
        self.root = Path(root).resolve()
        self.objects_dir = self.root / "objects"
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.database = database
        self.limit_bytes = max(1, int(limit_bytes))
        self.min_free_bytes = max(0, int(min_free_bytes))
        self._lock = threading.RLock()

    def archive(
        self,
        message_id: int | str,
        prepared_list: Iterable[PreparedAttachment],
    ) -> list[dict[str, Any]]:
        """Archive attachments and bind them atomically to an existing message.

        ``PreparedAttachment.archive_bytes`` is the original validated upload.
        The fallback exists for older image/text objects while callers migrate;
        PDF files deliberately require ``archive_bytes`` because extracted text
        is not a faithful archive of the source document.
        """

        message = self.database.get_message(int(message_id))
        if message is None:
            raise KeyError("Mensaje no encontrado.")
        prepared = list(prepared_list)
        if not prepared:
            return []

        payloads: list[tuple[Any, bytes, str]] = []
        for attachment in prepared:
            data = self._archive_payload(attachment)
            digest = hashlib.sha256(data).hexdigest()
            payloads.append((attachment, data, digest))

        with self._lock:
            overhead = self._database_overhead_bytes()
            if overhead >= self.limit_bytes:
                raise ConversationStorageQuotaError(
                    "La base de conversaciones ha alcanzado el límite de almacenamiento."
                )
            max_object_bytes = self.limit_bytes - overhead
            disk_free = shutil.disk_usage(self.root).free
            paths: dict[str, Path] = {}
            object_records: dict[str, dict[str, Any]] = {}
            new_digests: set[str] = set()
            physical_bytes_to_write = 0

            for _, data, digest in payloads:
                relative = Path("objects") / digest[:2] / digest
                target = self._resolve_relative(relative.as_posix())
                paths[digest] = target
                row = self.database.get_storage_object(digest)
                if row is None:
                    new_digests.add(digest)
                elif (
                    int(row["byte_size"]) != len(data)
                    or str(row["relative_path"]) != relative.as_posix()
                ):
                    raise ConversationStorageCorruptionError(
                        "La metadata del archivo guardado no coincide con su contenido."
                    )
                if target.exists():
                    self._verify_file(target, digest, len(data))
                else:
                    physical_bytes_to_write += len(data)
                object_records[digest] = {
                    "sha256": digest,
                    "relative_path": relative.as_posix(),
                    "byte_size": len(data),
                }

            if physical_bytes_to_write > max(0, disk_free - self.min_free_bytes):
                raise ConversationStorageQuotaError(
                    "No hay espacio libre suficiente sin comprometer la reserva de Windows."
                )

            written: set[str] = set()
            try:
                for _, data, digest in payloads:
                    target = paths[digest]
                    if target.exists():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._write_atomic(target, data)
                    written.add(digest)

                try:
                    self.database.register_storage_objects(
                        object_records.values(),
                        max_object_bytes=max_object_bytes,
                    )
                except StorageLimitExceeded as exc:
                    raise ConversationStorageQuotaError(str(exc)) from exc

                attachment_records = []
                for attachment, data, digest in payloads:
                    attachment_records.append(
                        {
                            "id": uuid.uuid4().hex,
                            "name": self._safe_name(str(attachment.name)),
                            "kind": str(attachment.kind),
                            "media_type": str(attachment.media_type),
                            "original_size": max(
                                0, int(getattr(attachment, "size", len(data)))
                            ),
                            "object_sha256": digest,
                        }
                    )
                stored = self.database.add_message_attachments(
                    int(message_id),
                    attachment_records,
                )
            except Exception:
                for digest in new_digests:
                    removed = self.database.delete_storage_object_if_unreferenced(digest)
                    if removed or self.database.get_storage_object(digest) is None:
                        paths[digest].unlink(missing_ok=True)
                raise

        return [self._public_attachment(item) for item in stored]

    def resolve(
        self,
        conversation_id: str,
        attachment_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        """Resolve an attachment only when it belongs to the requested chat."""

        with self._lock:
            metadata = self.database.get_attachment(attachment_id)
            if (
                metadata is None
                or str(metadata["conversation_id"]) != str(conversation_id)
            ):
                raise FileNotFoundError("Adjunto no encontrado.")
            path = self._resolve_relative(str(metadata["relative_path"]))
            if not path.is_file():
                raise FileNotFoundError("El archivo adjunto ya no está disponible.")
            if path.stat().st_size != int(metadata["stored_size"]):
                raise ConversationStorageCorruptionError(
                    "El tamaño del adjunto guardado no coincide con la base de datos."
                )
            return path, self._public_attachment(metadata)

    def delete_unreferenced(self) -> dict[str, int]:
        """Delete unreferenced database objects and safe orphan hash files."""

        deleted_objects = 0
        deleted_bytes = 0
        with self._lock:
            for item in self.database.list_unreferenced_storage_objects():
                path = self._resolve_relative(str(item["relative_path"]))
                quarantine = path.with_name(f".{path.name}.{uuid.uuid4().hex}.deleting")
                if path.exists():
                    path.replace(quarantine)
                try:
                    removed = self.database.delete_storage_object_if_unreferenced(
                        str(item["sha256"])
                    )
                    if not removed:
                        if quarantine.exists():
                            quarantine.replace(path)
                        continue
                    deleted_objects += 1
                    deleted_bytes += int(item["byte_size"])
                    quarantine.unlink(missing_ok=True)
                except Exception:
                    if quarantine.exists():
                        quarantine.replace(path)
                    raise

            registered = {
                str(item["sha256"])
                for item in self._all_registered_objects()
            }
            for prefix in self.objects_dir.iterdir():
                if not prefix.is_dir():
                    continue
                for path in prefix.iterdir():
                    name = path.name.casefold()
                    if (
                        path.is_file()
                        and len(name) == 64
                        and all(character in "0123456789abcdef" for character in name)
                        and name not in registered
                    ):
                        deleted_bytes += path.stat().st_size
                        path.unlink(missing_ok=True)
                try:
                    prefix.rmdir()
                except OSError:
                    pass
        return {"objects_deleted": deleted_objects, "bytes_deleted": deleted_bytes}

    def status(self) -> dict[str, int | bool]:
        usage = self.database.storage_usage()
        object_bytes = int(usage["object_bytes"])
        overhead = self._database_overhead_bytes()
        used = object_bytes + overhead
        disk_free = int(shutil.disk_usage(self.root).free)
        quota_available = max(0, self.limit_bytes - used)
        disk_available = max(0, disk_free - self.min_free_bytes)
        available = min(quota_available, disk_available)
        return {
            "quota_bytes": self.limit_bytes,
            "used_bytes": used,
            "object_bytes": object_bytes,
            "database_bytes": overhead,
            "free_bytes": disk_free,
            "available_bytes": available,
            "min_free_bytes": self.min_free_bytes,
            "object_count": int(usage["object_count"]),
            "attachment_count": int(usage["attachment_count"]),
            "writable": available > 0,
        }

    def _all_registered_objects(self) -> list[dict[str, Any]]:
        return self.database.list_storage_objects()

    def _database_overhead_bytes(self) -> int:
        total = 0
        candidates = [
            self.database.path,
            Path(f"{self.database.path}-wal"),
            Path(f"{self.database.path}-shm"),
        ]
        for path in candidates:
            try:
                total += path.stat().st_size
            except OSError:
                pass
        backup_dir = self.database.path.parent / "backups"
        if backup_dir.is_dir():
            for path in backup_dir.glob("*.sqlite3"):
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _archive_payload(attachment: PreparedAttachment) -> bytes:
        value = getattr(attachment, "archive_bytes", None)
        if callable(value):
            value = value()
        if isinstance(value, (bytes, bytearray, memoryview)) and value:
            return bytes(value)
        image = getattr(attachment, "image_bytes", None)
        if isinstance(image, (bytes, bytearray, memoryview)) and image:
            return bytes(image)
        text = getattr(attachment, "text", None)
        if str(getattr(attachment, "kind", "")).casefold() == "text" and text:
            return str(text).encode("utf-8")
        raise ConversationStorageError(
            "El adjunto no incluye los bytes originales necesarios para archivarlo."
        )

    @staticmethod
    def _safe_name(value: str) -> str:
        name = Path(str(value).replace("\\", "/")).name.strip(" .")
        return (name or "adjunto")[:180].rstrip(" .")

    def _resolve_relative(self, relative_path: str) -> Path:
        relative = Path(str(relative_path).replace("\\", "/"))
        if relative.is_absolute():
            raise ConversationStorageCorruptionError(
                "La ruta interna del adjunto no es válida."
            )
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ConversationStorageCorruptionError(
                "La ruta interna del adjunto sale del archivo permitido."
            ) from exc
        return candidate

    @staticmethod
    def _write_atomic(target: Path, data: bytes) -> None:
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                temporary.unlink(missing_ok=True)
            else:
                temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _verify_file(path: Path, digest: str, expected_size: int) -> None:
        if path.stat().st_size != expected_size:
            raise ConversationStorageCorruptionError(
                "Un objeto existente tiene un tamaño inesperado."
            )
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != digest:
            raise ConversationStorageCorruptionError(
                "Un objeto existente no coincide con su hash."
            )

    @staticmethod
    def _public_attachment(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(value["id"]),
            "attachment_id": str(value["id"]),
            "message_id": str(value["message_id"]),
            "conversation_id": str(value["conversation_id"]),
            "name": str(value["name"]),
            "kind": str(value["kind"]),
            "media_type": str(value["media_type"]),
            "size": int(value["size"]),
            "stored_size": int(value["stored_size"]),
            "created_at": str(value["created_at"]),
        }
