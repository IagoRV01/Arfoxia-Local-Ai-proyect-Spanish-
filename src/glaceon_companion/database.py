from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .state import PetState


SCHEMA_VERSION = 2
DEFAULT_CONVERSATION_TITLE = "Nueva conversación"
LEGACY_CONVERSATION_TITLE = "Historial anterior"

_AUDIT_SECRET_KEYS = {
    "authorization",
    "authorization_secret",
    "password",
    "passphrase",
    "pin",
    "secret",
    "token",
}
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEARCH_WORD = re.compile(r"\w{2,}", re.UNICODE)
_MESSAGE_ROLES = {"assistant", "system", "tool", "user"}


class StorageLimitExceeded(ValueError):
    """The durable object store would exceed its configured logical limit."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def redact_audit_value(value: Any, key: str = "") -> Any:
    """Return an audit-safe copy without credentials or file contents."""

    normalized_key = key.casefold().replace("-", "_")
    if normalized_key == "content" and isinstance(value, str):
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            return {
                "redacted": True,
                "invalid_utf8": True,
                "length_characters": len(value),
            }
        return {
            "redacted": True,
            "length": len(value),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if any(part in normalized_key for part in _AUDIT_SECRET_KEYS):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): redact_audit_value(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_audit_value(item) for item in value]
    return value


class Database:
    """Thread-safe SQLite persistence for pet state, chats and archived files.

    One connection is shared by the desktop and API threads. Every public
    operation is serialized by ``_lock`` and multi-statement writes use
    ``BEGIN IMMEDIATE`` so a retry can never observe a half-created turn.
    """

    def __init__(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            path,
            check_same_thread=False,
            timeout=5.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._fts_available = False
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._configure_connection()
        self._init_search_index()

    # ------------------------------------------------------------------
    # Schema and migration

    def _init_schema(self) -> None:
        with self._lock:
            tables = {
                str(row["name"])
                for row in self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not tables:
                self._create_fresh_schema()
                return

            message_columns = {
                str(row["name"])
                for row in self._connection.execute("PRAGMA table_info(messages)")
            }
            version = int(
                self._connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if "messages" in tables and "conversation_id" not in message_columns:
                self._backup_before_v2()
                self._migrate_v1_to_v2()
            elif version < SCHEMA_VERSION:
                self._upgrade_partial_v2()
            else:
                self._ensure_v2_tables()

    def _create_fresh_schema(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._create_base_tables()
            self._create_conversation_tables()
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _backup_before_v2(self) -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = backup_dir / f"{self.path.stem}-pre-v2-{timestamp}.sqlite3"
        destination = sqlite3.connect(backup_path)
        try:
            self._connection.backup(destination)
        except Exception:
            destination.close()
            backup_path.unlink(missing_ok=True)
            raise
        else:
            destination.close()
        return backup_path

    def _migrate_v1_to_v2(self) -> None:
        legacy_id = uuid.uuid4().hex
        message_stats = self._connection.execute(
            "SELECT COUNT(*) AS count, MIN(created_at) AS first_at, "
            "MAX(created_at) AS last_at, MAX(id) AS last_id FROM messages"
        ).fetchone()
        count = int(message_stats["count"])
        now = _utc_now()
        created_at = str(message_stats["first_at"] or now)
        updated_at = str(message_stats["last_at"] or created_at)

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._create_base_tables()
            self._create_conversations_table()
            if count:
                self._connection.execute(
                    """
                    INSERT INTO conversations(
                        id, title, created_at, updated_at, last_message_id,
                        archived_at, pinned, summary, summary_through_message_id,
                        revision, is_default
                    ) VALUES(?, ?, ?, ?, ?, NULL, 0, '', NULL, ?, 1)
                    """,
                    (
                        legacy_id,
                        LEGACY_CONVERSATION_TITLE,
                        created_at,
                        updated_at,
                        message_stats["last_id"],
                        count,
                    ),
                )
            self._connection.execute("ALTER TABLE messages RENAME TO messages_v1")
            self._create_messages_table()
            self._connection.execute(
                """
                INSERT INTO messages(
                    id, conversation_id, role, content, origin,
                    client_message_id, metadata_json, created_at
                )
                SELECT id, ?, role, content, 'legacy', NULL, '{}', created_at
                FROM messages_v1
                ORDER BY id
                """,
                (legacy_id,),
            )
            self._connection.execute("DROP TABLE messages_v1")
            self._create_storage_tables()
            self._create_indexes()
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _upgrade_partial_v2(self) -> None:
        """Finish an interrupted/development v2 schema without touching messages."""

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._create_base_tables()
            self._create_conversation_tables()
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _ensure_v2_tables(self) -> None:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._create_base_tables()
            self._create_conversation_tables()
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def _create_base_tables(self) -> None:
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS pet_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS action_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                arguments TEXT NOT NULL,
                success INTEGER NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
        ):
            self._connection.execute(statement)

    def _create_conversation_tables(self) -> None:
        self._create_conversations_table()
        self._create_messages_table()
        self._create_storage_tables()
        self._create_indexes()

    def _create_conversations_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_id INTEGER,
                archived_at TEXT,
                pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                summary TEXT NOT NULL DEFAULT '',
                summary_through_message_id INTEGER,
                revision INTEGER NOT NULL DEFAULT 0,
                is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
            )
            """
        )

    def _create_messages_table(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
                content TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT 'desktop',
                client_message_id TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )

    def _create_storage_tables(self) -> None:
        for statement in (
            """
            CREATE TABLE IF NOT EXISTS storage_objects (
                sha256 TEXT PRIMARY KEY,
                relative_path TEXT NOT NULL UNIQUE,
                byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id TEXT PRIMARY KEY,
                message_id INTEGER NOT NULL
                    REFERENCES messages(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                media_type TEXT NOT NULL,
                original_size INTEGER NOT NULL CHECK (original_size >= 0),
                object_sha256 TEXT NOT NULL
                    REFERENCES storage_objects(sha256) ON DELETE RESTRICT,
                created_at TEXT NOT NULL,
                UNIQUE(message_id, ordinal)
            )
            """,
        ):
            self._connection.execute(statement)

    def _create_indexes(self) -> None:
        for statement in (
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_conversations_default
                ON conversations(is_default) WHERE is_default = 1
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_conversations_updated
                ON conversations(pinned DESC, updated_at DESC, id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_messages_conversation_id
                ON messages(conversation_id, id DESC)
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ux_messages_client_id
                ON messages(conversation_id, client_message_id)
                WHERE client_message_id IS NOT NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_attachments_message
                ON attachments(message_id, ordinal)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_attachments_object
                ON attachments(object_sha256)
            """,
        ):
            self._connection.execute(statement)

    def _configure_connection(self) -> None:
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA synchronous = NORMAL")
            self._connection.execute("PRAGMA journal_mode = WAL")
            violations = self._connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise sqlite3.IntegrityError(
                    f"La base de datos contiene {len(violations)} referencias inválidas."
                )

    def _init_search_index(self) -> None:
        with self._lock:
            exists = self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'message_fts'"
            ).fetchone()
            try:
                with self._connection:
                    self._connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts "
                        "USING fts5(content, tokenize='unicode61')"
                    )
                    self._connection.executescript(
                        """
                        CREATE TRIGGER IF NOT EXISTS messages_fts_insert
                        AFTER INSERT ON messages BEGIN
                            INSERT INTO message_fts(rowid, content)
                            VALUES (new.id, new.content);
                        END;
                        CREATE TRIGGER IF NOT EXISTS messages_fts_delete
                        AFTER DELETE ON messages BEGIN
                            DELETE FROM message_fts WHERE rowid = old.id;
                        END;
                        CREATE TRIGGER IF NOT EXISTS messages_fts_update
                        AFTER UPDATE OF content ON messages BEGIN
                            DELETE FROM message_fts WHERE rowid = old.id;
                            INSERT INTO message_fts(rowid, content)
                            VALUES (new.id, new.content);
                        END;
                        """
                    )
                    if not exists:
                        self._connection.execute(
                            "INSERT INTO message_fts(rowid, content) "
                            "SELECT id, content FROM messages"
                        )
            except sqlite3.OperationalError:
                self._fts_available = False
            else:
                self._fts_available = True

    # ------------------------------------------------------------------
    # Pet state and audit

    def load_state(self) -> PetState:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM pet_state WHERE id = 1"
            ).fetchone()
        if not row:
            state = PetState()
            self.save_state(state)
            return state
        state = PetState(**json.loads(row["payload"]))
        state.advance()
        self.save_state(state)
        return state

    def save_state(self, state: PetState) -> None:
        payload = json.dumps(
            {key: value for key, value in state.as_public_dict().items() if key != "mood"},
            ensure_ascii=False,
        )
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO pet_state(id, payload) VALUES(1, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                (payload,),
            )

    def audit(self, action: str, arguments: dict[str, Any], success: bool, detail: str) -> None:
        safe_arguments = redact_audit_value(arguments)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO action_audit(action, arguments, success, detail, created_at) "
                "VALUES(?, ?, ?, ?, ?)",
                (
                    action,
                    json.dumps(safe_arguments, ensure_ascii=False),
                    int(success),
                    detail,
                    _utc_now(),
                ),
            )

    # ------------------------------------------------------------------
    # Conversations

    def create_conversation(
        self,
        title: str = DEFAULT_CONVERSATION_TITLE,
        *,
        conversation_id: str | None = None,
        created_at: str | None = None,
        make_default: bool = False,
    ) -> dict[str, Any]:
        identifier = self._validate_conversation_id(conversation_id or uuid.uuid4().hex)
        clean_title = self._clean_title(title)
        timestamp = str(created_at or _utc_now())
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                has_default = self._connection.execute(
                    "SELECT 1 FROM conversations WHERE is_default = 1"
                ).fetchone()
                default_value = int(make_default or has_default is None)
                if default_value:
                    self._connection.execute(
                        "UPDATE conversations SET is_default = 0 WHERE is_default = 1"
                    )
                self._connection.execute(
                    """
                    INSERT INTO conversations(
                        id, title, created_at, updated_at, last_message_id,
                        archived_at, pinned, summary, summary_through_message_id,
                        revision, is_default
                    ) VALUES(?, ?, ?, ?, NULL, NULL, 0, '', NULL, 0, ?)
                    """,
                    (identifier, clean_title, timestamp, timestamp, default_value),
                )
                row = self._conversation_row(identifier)
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return self._conversation_dict(row)

    def ensure_conversation(
        self,
        conversation_id: str | None = None,
        title: str = DEFAULT_CONVERSATION_TITLE,
    ) -> dict[str, Any]:
        """Resolve an existing conversation without ever creating one.

        ``title`` is retained for source compatibility with older integrations;
        conversation creation is now exclusively handled by
        :meth:`create_conversation`.
        """

        del title
        with self._lock:
            if conversation_id is not None:
                identifier = self._validate_conversation_id(conversation_id)
                row = self._conversation_row(identifier)
                if row is not None:
                    return self._conversation_dict(row)
                raise KeyError("Conversación no encontrada.")

            selected = self._connection.execute(
                "SELECT id FROM conversations WHERE is_default = 1 LIMIT 1"
            ).fetchone()
            row = (
                self._conversation_row(str(selected["id"]))
                if selected is not None
                else None
            )
            if row is None:
                selected = self._connection.execute(
                    "SELECT id FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1"
                ).fetchone()
                if selected is not None:
                    with self._connection:
                        self._connection.execute(
                            "UPDATE conversations SET is_default = 1 WHERE id = ?",
                            (selected["id"],),
                        )
                    row = self._conversation_row(str(selected["id"]))
            if row is not None:
                return self._conversation_dict(row)
            raise KeyError("No hay ninguna conversación.")

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        identifier = self._validate_conversation_id(conversation_id)
        with self._lock:
            row = self._conversation_row(identifier)
        return self._conversation_dict(row) if row is not None else None

    def list_conversations(
        self,
        limit: int = 50,
        cursor: str | None = None,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        page_size = max(1, min(int(limit), 100))
        parameters: list[Any] = []
        clauses: list[str] = []
        if not include_archived:
            clauses.append("c.archived_at IS NULL")
        if cursor:
            pinned, updated_at, identifier = self._decode_conversation_cursor(cursor)
            clauses.append(
                "("
                "c.pinned < ? OR "
                "(c.pinned = ? AND c.updated_at < ?) OR "
                "(c.pinned = ? AND c.updated_at = ? AND c.id < ?)"
                ")"
            )
            parameters.extend(
                [pinned, pinned, updated_at, pinned, updated_at, identifier]
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(page_size + 1)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT c.*,
                       COUNT(m.id) AS message_count,
                       (
                           SELECT content FROM messages lm
                           WHERE lm.id = c.last_message_id
                       ) AS last_message_preview
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                {where}
                GROUP BY c.id
                ORDER BY c.pinned DESC, c.updated_at DESC, c.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        has_more = len(rows) > page_size
        selected = rows[:page_size]
        items = [self._conversation_dict(row) for row in selected]
        next_cursor = None
        if has_more and selected:
            last = selected[-1]
            next_cursor = self._encode_conversation_cursor(
                int(last["pinned"]),
                str(last["updated_at"]),
                str(last["id"]),
            )
        return {"items": items, "next_cursor": next_cursor}

    def rename_conversation(self, conversation_id: str, title: str) -> dict[str, Any]:
        identifier = self._validate_conversation_id(conversation_id)
        clean_title = self._clean_title(title)
        now = _utc_now()
        with self._lock, self._connection:
            result = self._connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ?, "
                "revision = revision + 1 WHERE id = ?",
                (clean_title, now, identifier),
            )
            if result.rowcount != 1:
                raise KeyError("Conversación no encontrada.")
            row = self._conversation_row(identifier)
        return self._conversation_dict(row)

    def delete_conversation(self, conversation_id: str) -> bool:
        identifier = self._validate_conversation_id(conversation_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT is_default FROM conversations WHERE id = ?",
                    (identifier,),
                ).fetchone()
                if row is None:
                    self._connection.rollback()
                    return False
                was_default = bool(row["is_default"])
                self._connection.execute(
                    "DELETE FROM conversations WHERE id = ?", (identifier,)
                )
                if was_default:
                    replacement = self._connection.execute(
                        "SELECT id FROM conversations "
                        "ORDER BY updated_at DESC, id DESC LIMIT 1"
                    ).fetchone()
                    if replacement is not None:
                        self._connection.execute(
                            "UPDATE conversations SET is_default = 1 WHERE id = ?",
                            (replacement["id"],),
                        )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return True

    # ------------------------------------------------------------------
    # Messages and local memory

    def add_message(
        self,
        role: str,
        content: str,
        *,
        conversation_id: str | None = None,
        origin: str = "desktop",
        client_message_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_role = str(role or "").strip().casefold()
        if normalized_role not in _MESSAGE_ROLES:
            raise ValueError("Rol de mensaje no válido.")
        value = str(content)
        normalized_origin = str(origin or "desktop").strip()[:40] or "desktop"
        normalized_client_id = (
            str(client_message_id).strip()[:128] if client_message_id else None
        )
        metadata_json = json.dumps(dict(metadata or {}), ensure_ascii=False)
        timestamp = str(created_at or _utc_now())

        conversation = self.ensure_conversation(conversation_id)
        identifier = str(conversation["id"])
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                if normalized_client_id is not None:
                    existing = self._connection.execute(
                        "SELECT id FROM messages "
                        "WHERE conversation_id = ? AND client_message_id = ?",
                        (identifier, normalized_client_id),
                    ).fetchone()
                    if existing is not None:
                        self._connection.rollback()
                        message = self.get_message(int(existing["id"]))
                        if message is None:
                            raise sqlite3.IntegrityError("Mensaje idempotente no encontrado.")
                        return message
                cursor = self._connection.execute(
                    """
                    INSERT INTO messages(
                        conversation_id, role, content, origin,
                        client_message_id, metadata_json, created_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        normalized_role,
                        value,
                        normalized_origin,
                        normalized_client_id,
                        metadata_json,
                        timestamp,
                    ),
                )
                message_id = int(cursor.lastrowid)
                conversation_row = self._connection.execute(
                    "SELECT title, last_message_id FROM conversations WHERE id = ?",
                    (identifier,),
                ).fetchone()
                title = str(conversation_row["title"]) if conversation_row else ""
                auto_title = None
                if (
                    normalized_role == "user"
                    and title == DEFAULT_CONVERSATION_TITLE
                    and conversation_row is not None
                    and conversation_row["last_message_id"] is None
                ):
                    auto_title = self._title_from_first_message(value)
                self._connection.execute(
                    "UPDATE conversations SET updated_at = ?, last_message_id = ?, "
                    "title = COALESCE(?, title), "
                    "revision = revision + 1 WHERE id = ?",
                    (timestamp, message_id, auto_title, identifier),
                )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        message = self.get_message(message_id)
        if message is None:
            raise sqlite3.IntegrityError("No se pudo recuperar el mensaje guardado.")
        return message

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM messages WHERE id = ?", (int(message_id),)
            ).fetchone()
            if row is None:
                return None
            attachments = self._attachments_for_messages([int(row["id"])])
        return self._message_dict(row, attachments.get(int(row["id"]), []))

    def get_message_by_client_id(
        self,
        conversation_id: str,
        client_message_id: str,
    ) -> dict[str, Any] | None:
        identifier = self._validate_conversation_id(conversation_id)
        client_identifier = str(client_message_id or "").strip()
        if not client_identifier:
            return None
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM messages "
                "WHERE conversation_id = ? AND client_message_id = ?",
                (identifier, client_identifier),
            ).fetchone()
            if row is None:
                return None
            attachments = self._attachments_for_messages([int(row["id"])])
        return self._message_dict(row, attachments.get(int(row["id"]), []))

    def delete_message(self, message_id: int) -> bool:
        identifier = int(message_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    "SELECT conversation_id FROM messages WHERE id = ?", (identifier,)
                ).fetchone()
                if row is None:
                    self._connection.rollback()
                    return False
                conversation_id = str(row["conversation_id"])
                self._connection.execute("DELETE FROM messages WHERE id = ?", (identifier,))
                last = self._connection.execute(
                    "SELECT id, created_at FROM messages "
                    "WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                now = str(last["created_at"]) if last is not None else _utc_now()
                self._connection.execute(
                    "UPDATE conversations SET last_message_id = ?, updated_at = ?, "
                    "revision = revision + 1 WHERE id = ?",
                    (
                        int(last["id"]) if last is not None else None,
                        now,
                        conversation_id,
                    ),
                )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return True

    def recent_messages(
        self,
        limit: int = 16,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        conversation = self.ensure_conversation(conversation_id)
        page_size = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation["id"], page_size),
            ).fetchall()
            selected = list(reversed(rows))
            attachment_map = self._attachments_for_messages(
                [int(row["id"]) for row in selected]
            )
        return [
            self._message_dict(row, attachment_map.get(int(row["id"]), []))
            for row in selected
        ]

    def list_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        *,
        before: int | None = None,
        after: int | None = None,
    ) -> dict[str, Any]:
        if before is not None and after is not None:
            raise ValueError("before y after no pueden usarse a la vez.")
        identifier = self._validate_conversation_id(conversation_id)
        if self.get_conversation(identifier) is None:
            raise KeyError("Conversación no encontrada.")
        page_size = max(1, min(int(limit), 100))
        parameters: list[Any] = [identifier]
        clause = ""
        ascending = after is not None
        if before is not None:
            clause = "AND id < ?"
            parameters.append(int(before))
        elif after is not None:
            clause = "AND id > ?"
            parameters.append(int(after))
        order = "ASC" if ascending else "DESC"
        parameters.append(page_size + 1)
        with self._lock:
            rows = self._connection.execute(
                f"SELECT * FROM messages WHERE conversation_id = ? {clause} "
                f"ORDER BY id {order} LIMIT ?",
                parameters,
            ).fetchall()
            has_more = len(rows) > page_size
            selected = list(rows[:page_size])
            if not ascending:
                selected.reverse()
            attachment_map = self._attachments_for_messages(
                [int(row["id"]) for row in selected]
            )
        items = [
            self._message_dict(row, attachment_map.get(int(row["id"]), []))
            for row in selected
        ]
        next_cursor: str | None = None
        if has_more and items:
            next_cursor = str(items[-1]["id"] if ascending else items[0]["id"])
        return {
            "items": items,
            "next_cursor": next_cursor,
            "next_before_id": next_cursor if not ascending else None,
            "next_after_id": next_cursor if ascending else None,
        }

    def search_memory(
        self,
        query: str,
        limit: int = 20,
        *,
        conversation_id: str | None = None,
        exclude_conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        words = _SEARCH_WORD.findall(str(query or "").casefold())[:12]
        if not words:
            return []
        page_size = max(1, min(int(limit), 50))
        identifier = (
            self._validate_conversation_id(conversation_id)
            if conversation_id is not None
            else None
        )
        excluded_identifier = (
            self._validate_conversation_id(exclude_conversation_id)
            if exclude_conversation_id is not None
            else None
        )
        if identifier is not None and excluded_identifier is not None:
            raise ValueError(
                "conversation_id y exclude_conversation_id no pueden combinarse."
            )
        with self._lock:
            rows: list[sqlite3.Row]
            if self._fts_available:
                expression = " OR ".join(f'"{word.replace(chr(34), "")}"' for word in words)
                parameters: list[Any] = [expression]
                conversation_clause = ""
                if identifier is not None:
                    conversation_clause = "AND m.conversation_id = ?"
                    parameters.append(identifier)
                elif excluded_identifier is not None:
                    conversation_clause = "AND m.conversation_id != ?"
                    parameters.append(excluded_identifier)
                parameters.append(page_size)
                try:
                    rows = self._connection.execute(
                        f"""
                        SELECT m.*, c.title AS conversation_title
                        FROM message_fts
                        JOIN messages m ON m.id = message_fts.rowid
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE message_fts MATCH ? {conversation_clause}
                        ORDER BY bm25(message_fts), m.id DESC
                        LIMIT ?
                        """,
                        parameters,
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = self._fallback_memory_rows(
                        words,
                        page_size,
                        identifier,
                        excluded_identifier,
                    )
            else:
                rows = self._fallback_memory_rows(
                    words,
                    page_size,
                    identifier,
                    excluded_identifier,
                )
            attachment_map = self._attachments_for_messages(
                [int(row["id"]) for row in rows]
            )
        return [
            self._message_dict(row, attachment_map.get(int(row["id"]), []))
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Durable attachments and storage objects

    def register_storage_objects(
        self,
        objects: Iterable[Mapping[str, Any]],
        *,
        max_object_bytes: int,
    ) -> list[dict[str, Any]]:
        records: dict[str, tuple[str, int, str]] = {}
        for item in objects:
            digest = self._validate_sha256(str(item["sha256"]))
            relative_path = str(item["relative_path"]).replace("\\", "/")
            byte_size = int(item["byte_size"])
            if byte_size < 0:
                raise ValueError("El tamaño del objeto no puede ser negativo.")
            created_at = str(item.get("created_at") or _utc_now())
            existing = records.get(digest)
            candidate = (relative_path, byte_size, created_at)
            if existing is not None and existing[:2] != candidate[:2]:
                raise ValueError("Dos objetos comparten hash pero no metadata.")
            records[digest] = candidate

        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                used = int(
                    self._connection.execute(
                        "SELECT COALESCE(SUM(byte_size), 0) FROM storage_objects"
                    ).fetchone()[0]
                )
                output: list[dict[str, Any]] = []
                additional = 0
                for digest, (relative_path, byte_size, created_at) in records.items():
                    row = self._connection.execute(
                        "SELECT * FROM storage_objects WHERE sha256 = ?", (digest,)
                    ).fetchone()
                    if row is not None:
                        if (
                            str(row["relative_path"]) != relative_path
                            or int(row["byte_size"]) != byte_size
                        ):
                            raise sqlite3.IntegrityError(
                                "Colisión o metadata inconsistente en el archivo."
                            )
                        output.append(self._storage_object_dict(row))
                        continue
                    additional += byte_size
                    output.append(
                        {
                            "sha256": digest,
                            "relative_path": relative_path,
                            "byte_size": byte_size,
                            "created_at": created_at,
                        }
                    )
                if used + additional > max(0, int(max_object_bytes)):
                    raise StorageLimitExceeded(
                        "El archivo de conversaciones ha alcanzado su límite."
                    )
                for item in output:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO storage_objects("
                        "sha256, relative_path, byte_size, created_at"
                        ") VALUES(?, ?, ?, ?)",
                        (
                            item["sha256"],
                            item["relative_path"],
                            item["byte_size"],
                            item["created_at"],
                        ),
                    )
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return output

    def get_storage_object(self, sha256: str) -> dict[str, Any] | None:
        digest = self._validate_sha256(sha256)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM storage_objects WHERE sha256 = ?", (digest,)
            ).fetchone()
        return self._storage_object_dict(row) if row is not None else None

    def list_unreferenced_storage_objects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT so.*
                FROM storage_objects so
                LEFT JOIN attachments a ON a.object_sha256 = so.sha256
                WHERE a.id IS NULL
                ORDER BY so.created_at, so.sha256
                """
            ).fetchall()
        return [self._storage_object_dict(row) for row in rows]

    def delete_storage_object_if_unreferenced(self, sha256: str) -> bool:
        digest = self._validate_sha256(sha256)
        with self._lock, self._connection:
            result = self._connection.execute(
                "DELETE FROM storage_objects "
                "WHERE sha256 = ? AND NOT EXISTS("
                "SELECT 1 FROM attachments WHERE object_sha256 = ?"
                ")",
                (digest, digest),
            )
        return result.rowcount == 1

    def storage_usage(self) -> dict[str, int]:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS object_count, "
                "COALESCE(SUM(byte_size), 0) AS object_bytes FROM storage_objects"
            ).fetchone()
            attachment_count = int(
                self._connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0]
            )
        return {
            "object_count": int(row["object_count"]),
            "object_bytes": int(row["object_bytes"]),
            "attachment_count": attachment_count,
        }

    def list_storage_objects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM storage_objects ORDER BY created_at, sha256"
            ).fetchall()
        return [self._storage_object_dict(row) for row in rows]

    def add_message_attachments(
        self,
        message_id: int,
        attachments: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        records = list(attachments)
        if not records:
            return []
        identifier = int(message_id)
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                message = self._connection.execute(
                    "SELECT conversation_id FROM messages WHERE id = ?", (identifier,)
                ).fetchone()
                if message is None:
                    raise KeyError("Mensaje no encontrado.")
                start = int(
                    self._connection.execute(
                        "SELECT COALESCE(MAX(ordinal), -1) + 1 "
                        "FROM attachments WHERE message_id = ?",
                        (identifier,),
                    ).fetchone()[0]
                )
                ids: list[str] = []
                for offset, item in enumerate(records):
                    attachment_id = str(item.get("id") or uuid.uuid4().hex)
                    if not _CONVERSATION_ID.fullmatch(attachment_id):
                        raise ValueError("Identificador de adjunto no válido.")
                    digest = self._validate_sha256(str(item["object_sha256"]))
                    if self._connection.execute(
                        "SELECT 1 FROM storage_objects WHERE sha256 = ?", (digest,)
                    ).fetchone() is None:
                        raise KeyError("Objeto de almacenamiento no encontrado.")
                    created_at = str(item.get("created_at") or _utc_now())
                    self._connection.execute(
                        """
                        INSERT INTO attachments(
                            id, message_id, ordinal, name, kind, media_type,
                            original_size, object_sha256, created_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            attachment_id,
                            identifier,
                            start + offset,
                            str(item["name"])[:180],
                            str(item["kind"])[:30],
                            str(item["media_type"])[:120],
                            max(0, int(item["original_size"])),
                            digest,
                            created_at,
                        ),
                    )
                    ids.append(attachment_id)
                rows = self._connection.execute(
                    "SELECT a.*, m.conversation_id, so.relative_path, so.byte_size "
                    "FROM attachments a "
                    "JOIN messages m ON m.id = a.message_id "
                    "JOIN storage_objects so ON so.sha256 = a.object_sha256 "
                    f"WHERE a.id IN ({','.join('?' for _ in ids)}) "
                    "ORDER BY a.ordinal",
                    ids,
                ).fetchall()
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()
        return [self._attachment_dict(row, internal=True) for row in rows]

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        identifier = str(attachment_id)
        if not _CONVERSATION_ID.fullmatch(identifier):
            return None
        with self._lock:
            row = self._connection.execute(
                """
                SELECT a.*, m.conversation_id, so.relative_path, so.byte_size
                FROM attachments a
                JOIN messages m ON m.id = a.message_id
                JOIN storage_objects so ON so.sha256 = a.object_sha256
                WHERE a.id = ?
                """,
                (identifier,),
            ).fetchone()
        return self._attachment_dict(row, internal=True) if row is not None else None

    # ------------------------------------------------------------------
    # Row conversion and validation

    def _conversation_row(self, conversation_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id)
                       AS message_count,
                   (SELECT content FROM messages lm WHERE lm.id = c.last_message_id)
                       AS last_message_preview
            FROM conversations c
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()

    @staticmethod
    def _conversation_dict(row: sqlite3.Row) -> dict[str, Any]:
        preview = str(row["last_message_preview"] or "")
        if len(preview) > 180:
            preview = f"{preview[:177]}…"
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "last_message_id": (
                str(row["last_message_id"]) if row["last_message_id"] is not None else None
            ),
            "preview": preview,
            "last_message_preview": preview,
            "message_count": int(row["message_count"] or 0),
            "archived": row["archived_at"] is not None,
            "archived_at": (
                str(row["archived_at"]) if row["archived_at"] is not None else None
            ),
            "pinned": bool(row["pinned"]),
            "summary": str(row["summary"] or ""),
            "summary_through_message_id": (
                int(row["summary_through_message_id"])
                if row["summary_through_message_id"] is not None
                else None
            ),
            "revision": int(row["revision"]),
            "is_default": bool(row["is_default"]),
        }

    @staticmethod
    def _message_dict(
        row: sqlite3.Row,
        attachments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "origin": str(row["origin"]),
            "client_message_id": (
                str(row["client_message_id"])
                if row["client_message_id"] is not None
                else None
            ),
            "metadata": metadata,
            "created_at": str(row["created_at"]),
            "attachments": attachments,
            **(
                {"conversation_title": str(row["conversation_title"])}
                if "conversation_title" in row.keys()
                else {}
            ),
        }

    def _attachments_for_messages(
        self, message_ids: list[int]
    ) -> dict[int, list[dict[str, Any]]]:
        if not message_ids:
            return {}
        rows = self._connection.execute(
            "SELECT a.*, so.byte_size "
            "FROM attachments a "
            "JOIN storage_objects so ON so.sha256 = a.object_sha256 "
            f"WHERE a.message_id IN ({','.join('?' for _ in message_ids)}) "
            "ORDER BY a.message_id, a.ordinal",
            message_ids,
        ).fetchall()
        output: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            output.setdefault(int(row["message_id"]), []).append(
                self._attachment_dict(row, internal=False)
            )
        return output

    @staticmethod
    def _attachment_dict(
        row: sqlite3.Row,
        *,
        internal: bool,
    ) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": str(row["id"]),
            "attachment_id": str(row["id"]),
            "message_id": str(row["message_id"]),
            "name": str(row["name"]),
            "kind": str(row["kind"]),
            "media_type": str(row["media_type"]),
            "size": int(row["original_size"]),
            "stored_size": int(row["byte_size"]),
            "created_at": str(row["created_at"]),
        }
        if "conversation_id" in row.keys():
            value["conversation_id"] = str(row["conversation_id"])
        if internal:
            value["object_sha256"] = str(row["object_sha256"])
            value["relative_path"] = str(row["relative_path"])
        return value

    @staticmethod
    def _storage_object_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "sha256": str(row["sha256"]),
            "relative_path": str(row["relative_path"]),
            "byte_size": int(row["byte_size"]),
            "created_at": str(row["created_at"]),
        }

    def _fallback_memory_rows(
        self,
        words: list[str],
        limit: int,
        conversation_id: str | None,
        exclude_conversation_id: str | None,
    ) -> list[sqlite3.Row]:
        clauses = ["LOWER(m.content) LIKE ?" for _ in words]
        parameters: list[Any] = [f"%{word}%" for word in words]
        conversation_clause = ""
        if conversation_id is not None:
            conversation_clause = "AND m.conversation_id = ?"
            parameters.append(conversation_id)
        elif exclude_conversation_id is not None:
            conversation_clause = "AND m.conversation_id != ?"
            parameters.append(exclude_conversation_id)
        parameters.append(limit)
        return self._connection.execute(
            f"SELECT m.*, c.title AS conversation_title "
            f"FROM messages m JOIN conversations c ON c.id = m.conversation_id "
            f"WHERE ({' OR '.join(clauses)}) "
            f"{conversation_clause} ORDER BY m.id DESC LIMIT ?",
            parameters,
        ).fetchall()

    @staticmethod
    def _validate_conversation_id(value: str) -> str:
        identifier = str(value or "").strip()
        if not _CONVERSATION_ID.fullmatch(identifier):
            raise ValueError("Identificador de conversación no válido.")
        return identifier

    @staticmethod
    def _validate_sha256(value: str) -> str:
        digest = str(value or "").strip().casefold()
        if not _SHA256.fullmatch(digest):
            raise ValueError("Hash de almacenamiento no válido.")
        return digest

    @staticmethod
    def _clean_title(value: str) -> str:
        title = " ".join(str(value or "").split()).strip()
        if not title:
            raise ValueError("El título de la conversación está vacío.")
        return title[:120]

    @staticmethod
    def _title_from_first_message(value: str) -> str | None:
        title = " ".join(str(value or "").split()).strip()
        if not title:
            return None
        if len(title) <= 60:
            return title
        return f"{title[:57].rstrip()}…"

    @staticmethod
    def _encode_conversation_cursor(pinned: int, updated_at: str, identifier: str) -> str:
        payload = json.dumps(
            [int(pinned), str(updated_at), str(identifier)],
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_conversation_cursor(value: str) -> tuple[int, str, str]:
        try:
            encoded = str(value).encode("ascii")
            encoded += b"=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
            if not isinstance(payload, list) or len(payload) != 3:
                raise ValueError
            pinned = int(payload[0])
            if pinned not in {0, 1}:
                raise ValueError
            updated_at = str(payload[1])
            identifier = Database._validate_conversation_id(str(payload[2]))
            return pinned, updated_at, identifier
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Cursor de conversaciones no válido.") from exc

    def close(self) -> None:
        with self._lock:
            self._connection.close()
