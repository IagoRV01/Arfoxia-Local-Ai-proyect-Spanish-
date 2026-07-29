from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from glaceon_companion.database import (
    DEFAULT_CONVERSATION_TITLE,
    LEGACY_CONVERSATION_TITLE,
    SCHEMA_VERSION,
    Database,
)


def _legacy_database(path: Path, message_count: int = 104) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE pet_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE action_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                arguments TEXT NOT NULL,
                success INTEGER NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        for index in range(1, message_count + 1):
            role = "user" if index % 2 else "assistant"
            connection.execute(
                "INSERT INTO messages(role, content, created_at) VALUES(?, ?, ?)",
                (
                    role,
                    f"mensaje histórico {index}",
                    f"2026-07-{19 + (index // 50):02d}T12:00:{index % 60:02d}+00:00",
                ),
            )
        connection.commit()
    finally:
        connection.close()


def test_v2_migration_backs_up_and_preserves_all_legacy_messages(tmp_path: Path) -> None:
    path = tmp_path / "companion.sqlite3"
    _legacy_database(path)

    database = Database(path)
    try:
        conversations = database.list_conversations()["items"]
        assert len(conversations) == 1
        legacy = conversations[0]
        assert legacy["title"] == LEGACY_CONVERSATION_TITLE
        assert legacy["message_count"] == 104
        assert legacy["is_default"] is True

        messages = database.recent_messages(200, legacy["id"])
        assert len(messages) == 104
        assert messages[0]["id"] == "1"
        assert messages[-1]["id"] == "104"
        assert messages[0]["content"] == "mensaje histórico 1"
        assert database._connection.execute("PRAGMA user_version").fetchone()[0] == (
            SCHEMA_VERSION
        )
        assert database._connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert database._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert database._connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        database.close()

    backups = list((tmp_path / "backups").glob("companion-pre-v2-*.sqlite3"))
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    try:
        assert backup.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 104
        columns = {
            row[1] for row in backup.execute("PRAGMA table_info(messages)").fetchall()
        }
        assert "conversation_id" not in columns
    finally:
        backup.close()

    reopened = Database(path)
    try:
        assert reopened.ensure_conversation()["title"] == LEGACY_CONVERSATION_TITLE
        assert reopened.recent_messages(200)[-1]["id"] == "104"
    finally:
        reopened.close()


def test_new_and_empty_legacy_databases_remain_without_conversations(
    tmp_path: Path,
) -> None:
    fresh_path = tmp_path / "fresh.sqlite3"
    fresh = Database(fresh_path)
    try:
        assert fresh.list_conversations()["items"] == []
        with pytest.raises(KeyError, match="ninguna conversación"):
            fresh.ensure_conversation()
        only = fresh.create_conversation("Único chat")
        assert fresh.delete_conversation(only["id"]) is True
        assert fresh.list_conversations()["items"] == []
        with pytest.raises(KeyError, match="ninguna conversación"):
            fresh.ensure_conversation()
    finally:
        fresh.close()

    reopened = Database(fresh_path)
    try:
        assert reopened.list_conversations()["items"] == []
    finally:
        reopened.close()

    legacy_path = tmp_path / "empty-legacy.sqlite3"
    _legacy_database(legacy_path, message_count=0)
    migrated = Database(legacy_path)
    try:
        assert migrated.list_conversations()["items"] == []
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM messages"
        ).fetchone()[0] == 0
        with pytest.raises(KeyError, match="ninguna conversación"):
            migrated.ensure_conversation()
    finally:
        migrated.close()


def test_conversation_crud_idempotency_pagination_and_auto_title(tmp_path: Path) -> None:
    database = Database(tmp_path / "companion.sqlite3")
    try:
        initial = database.create_conversation(DEFAULT_CONVERSATION_TITLE)
        assert initial["title"] == DEFAULT_CONVERSATION_TITLE
        first = database.add_message(
            "user",
            "Este es el primer tema de una conversación que debe titularse automáticamente",
            conversation_id=initial["id"],
            origin="mobile",
            client_message_id="mobile-turn-1",
            metadata={"research_mode": False},
        )
        duplicate = database.add_message(
            "user",
            "Este contenido no debe reemplazar el mensaje original.",
            conversation_id=initial["id"],
            origin="mobile",
            client_message_id="mobile-turn-1",
        )
        assert duplicate["id"] == first["id"]
        assert duplicate["content"] == first["content"]
        assert database.get_message_by_client_id(
            initial["id"], "mobile-turn-1"
        ) == first
        assert (
            database.get_message_by_client_id(initial["id"], "turno-inexistente")
            is None
        )
        assert database.get_conversation(initial["id"])["title"].endswith("…")

        second = database.add_message(
            "assistant",
            "Respuesta uno",
            conversation_id=initial["id"],
            metadata={"model": "local"},
        )
        third = database.add_message(
            "user",
            "Segundo tema",
            conversation_id=initial["id"],
        )
        page = database.list_messages(initial["id"], limit=2)
        assert [item["id"] for item in page["items"]] == [second["id"], third["id"]]
        assert page["next_before_id"] == second["id"]
        previous = database.list_messages(
            initial["id"],
            limit=2,
            before=int(page["next_before_id"]),
        )
        assert [item["id"] for item in previous["items"]] == [first["id"]]

        another = database.create_conversation("Otro chat")
        database.add_message(
            "user",
            "Memoria sobre telescopios azules",
            conversation_id=another["id"],
        )
        listing = database.list_conversations(limit=1)
        assert len(listing["items"]) == 1
        assert listing["next_cursor"]
        assert database.list_conversations(
            limit=1, cursor=listing["next_cursor"]
        )["items"]

        renamed = database.rename_conversation(another["id"], "Astronomía")
        assert renamed["title"] == "Astronomía"
        with pytest.raises(KeyError):
            database.ensure_conversation("chat-inexistente")
        with pytest.raises(KeyError):
            database.rename_conversation("chat-inexistente", "Nada")

        assert database.delete_message(third["id"]) is True
        assert database.delete_message(third["id"]) is False
        assert database.delete_conversation(another["id"]) is True
        assert database.delete_conversation(another["id"]) is False
        assert database.ensure_conversation()["id"] == initial["id"]
    finally:
        database.close()


def test_local_memory_search_can_exclude_current_chat_and_returns_title(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "companion.sqlite3")
    try:
        current = database.create_conversation(DEFAULT_CONVERSATION_TITLE)
        old = database.create_conversation("Viaje antiguo")
        database.add_message(
            "user",
            "Mi destino favorito es Kioto en otoño.",
            conversation_id=old["id"],
        )
        database.add_message(
            "user",
            "Kioto también aparece en el chat actual.",
            conversation_id=current["id"],
        )

        matches = database.search_memory(
            "destino Kioto",
            exclude_conversation_id=current["id"],
        )
        assert matches
        assert {item["conversation_id"] for item in matches} == {old["id"]}
        assert matches[0]["conversation_title"] == "Viaje antiguo"
        assert matches[0]["attachments"] == []

        with pytest.raises(ValueError):
            database.search_memory(
                "Kioto",
                conversation_id=current["id"],
                exclude_conversation_id=old["id"],
            )
    finally:
        database.close()
