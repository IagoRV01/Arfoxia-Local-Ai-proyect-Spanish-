from __future__ import annotations

from pathlib import Path

import pytest

from glaceon_companion.attachments import PreparedAttachment
from glaceon_companion.conversation_storage import (
    ConversationStorage,
    ConversationStorageError,
    ConversationStorageQuotaError,
)
from glaceon_companion.database import Database


def _text_attachment(name: str, value: bytes) -> PreparedAttachment:
    return PreparedAttachment(
        name=name,
        kind="text",
        media_type="text/plain",
        size=len(value),
        text=value.decode("utf-8"),
        archive_bytes=value,
    )


def test_archive_deduplicates_resolves_and_collects_objects(tmp_path: Path) -> None:
    database = Database(tmp_path / "companion.sqlite3")
    storage = ConversationStorage(
        tmp_path / "attachments",
        database,
        limit_bytes=1024**3,
        min_free_bytes=0,
    )
    try:
        conversation = database.create_conversation("Archivos")
        message = database.add_message(
            "user",
            "Dos archivos iguales",
            conversation_id=conversation["id"],
        )
        archived = storage.archive(
            message["id"],
            [
                _text_attachment("primero.txt", b"mismo contenido"),
                _text_attachment("segundo.txt", b"mismo contenido"),
            ],
        )

        assert len(archived) == 2
        assert archived[0]["attachment_id"] == archived[0]["id"]
        assert archived[0]["message_id"] == message["id"]
        status = storage.status()
        assert status["object_count"] == 1
        assert status["attachment_count"] == 2
        assert status["object_bytes"] == len(b"mismo contenido")
        assert status["quota_bytes"] == 1024**3
        assert status["available_bytes"] > 0

        refreshed = database.get_message(message["id"])
        assert refreshed is not None
        assert [item["name"] for item in refreshed["attachments"]] == [
            "primero.txt",
            "segundo.txt",
        ]
        path, metadata = storage.resolve(
            conversation["id"], archived[0]["attachment_id"]
        )
        assert path.read_bytes() == b"mismo contenido"
        assert metadata["name"] == "primero.txt"
        with pytest.raises(FileNotFoundError):
            storage.resolve("otra-conversacion", archived[0]["attachment_id"])

        assert database.delete_message(message["id"]) is True
        collected = storage.delete_unreferenced()
        assert collected["objects_deleted"] == 1
        assert not path.exists()
        assert storage.status()["object_count"] == 0
    finally:
        database.close()


def test_archive_enforces_logical_quota_and_rolls_back_new_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database(tmp_path / "companion.sqlite3")
    roomy = ConversationStorage(
        tmp_path / "attachments",
        database,
        limit_bytes=1024**3,
        min_free_bytes=0,
    )
    try:
        conversation = database.create_conversation("Cuota")
        message = database.add_message(
            "user",
            "Archivo con cuota",
            conversation_id=conversation["id"],
        )
        baseline = roomy.status()["used_bytes"]
        limited = ConversationStorage(
            tmp_path / "attachments",
            database,
            limit_bytes=int(baseline) + 2,
            min_free_bytes=0,
        )
        with pytest.raises(ConversationStorageQuotaError):
            limited.archive(message["id"], [_text_attachment("tres.txt", b"123")])
        assert database.storage_usage()["object_count"] == 0

        original = database.add_message_attachments

        def fail_to_bind(*args, **kwargs):
            raise RuntimeError("fallo simulado")

        monkeypatch.setattr(database, "add_message_attachments", fail_to_bind)
        with pytest.raises(RuntimeError, match="fallo simulado"):
            roomy.archive(message["id"], [_text_attachment("rollback.txt", b"rollback")])
        monkeypatch.setattr(database, "add_message_attachments", original)
        assert database.storage_usage()["object_count"] == 0
        assert list((tmp_path / "attachments" / "objects").rglob("[0-9a-f]" * 64)) == []
    finally:
        database.close()


def test_pdf_without_original_archive_bytes_is_rejected(tmp_path: Path) -> None:
    database = Database(tmp_path / "companion.sqlite3")
    storage = ConversationStorage(
        tmp_path / "attachments",
        database,
        limit_bytes=1024**3,
        min_free_bytes=0,
    )
    try:
        conversation = database.create_conversation("PDF")
        message = database.add_message(
            "user",
            "PDF incompleto",
            conversation_id=conversation["id"],
        )
        incomplete = PreparedAttachment(
            name="documento.pdf",
            kind="pdf",
            media_type="application/pdf",
            size=20,
            text="solo texto extraído",
        )
        with pytest.raises(ConversationStorageError, match="bytes originales"):
            storage.archive(message["id"], [incomplete])
    finally:
        database.close()
