from __future__ import annotations

import base64
import copy
import getpass
import hashlib
import hmac
import json
import math
import os
import secrets
import stat
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping


SCRYPT_N = 32_768
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 128
DEFAULT_CHALLENGE_TTL_SECONDS = 90.0
MAX_PENDING_CHALLENGES = 32
RATE_LIMIT_FAILURES = 5
RATE_LIMIT_WINDOW_SECONDS = 60.0


class AuthorizationError(RuntimeError):
    """Base error for the local authorization boundary."""


class AuthorizationNotConfiguredError(AuthorizationError):
    pass


class AuthorizationAlreadyConfiguredError(AuthorizationError):
    pass


class AuthorizationStorageError(AuthorizationError):
    pass


class PasswordPolicyError(AuthorizationError):
    pass


class InvalidPasswordError(AuthorizationError):
    pass


class AuthorizationRateLimitedError(AuthorizationError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__(
            f"Demasiados intentos. Inténtalo de nuevo en "
            f"{self.retry_after_seconds} segundos."
        )


class UnknownChallengeError(AuthorizationError):
    pass


class ExpiredChallengeError(AuthorizationError):
    pass


class TooManyChallengesError(AuthorizationError):
    pass


@dataclass(frozen=True, slots=True)
class ChallengeInfo:
    """Safe information that can be shown by a desktop or API client."""

    challenge_id: str
    action: str
    summary: str
    expires_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "challenge_id": self.challenge_id,
            "action": self.action,
            "summary": self.summary,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedAction:
    """The exact server-side action bound to a successfully used challenge."""

    challenge_id: str
    action: str
    arguments: dict[str, Any] = field(repr=False)
    summary: str = ""
    origin: str = "desktop"


@dataclass(slots=True)
class _PendingChallenge:
    challenge_id: str
    action: str
    arguments: dict[str, Any]
    summary: str
    origin: str
    expires_monotonic: float
    expires_at: str

    def public(self) -> ChallengeInfo:
        return ChallengeInfo(
            challenge_id=self.challenge_id,
            action=self.action,
            summary=self.summary,
            expires_at=self.expires_at,
        )


@dataclass(slots=True)
class _VerifierRecord:
    salt: bytes
    verifier: bytes
    failures: int = 0
    failure_window_started_at: float | None = None
    locked_until: float | None = None


def _b64encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64decode(value: Any, expected_length: int) -> bytes:
    if not isinstance(value, str):
        raise ValueError("value must be base64 text")
    decoded = base64.b64decode(value, validate=True)
    if len(decoded) != expected_length:
        raise ValueError("decoded value has an invalid length")
    return decoded


def _derive_verifier(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )


def _validate_new_password(password: str) -> None:
    if not isinstance(password, str):
        raise PasswordPolicyError("La contraseña debe ser texto.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"La contraseña no puede superar {MAX_PASSWORD_LENGTH} caracteres."
        )


def _current_windows_account() -> str:
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    return f"{domain}\\{user}" if domain else user


def harden_authorization_file(path: Path) -> bool:
    """Best-effort restriction of one exact authorization file.

    Failure to adjust permissions never makes authorization succeed or rewrites
    any broader directory. The verifier is salted and deliberately contains no
    plaintext password, but restricting offline access still matters for weak
    passwords.
    """

    target = Path(path).resolve()
    try:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    if os.name != "nt":
        try:
            return stat.S_IMODE(target.stat().st_mode) == 0o600
        except OSError:
            return False

    # icacls receives an argument vector (never a shell command) and is scoped
    # to this exact file. Well-known SIDs keep the rule independent of locale.
    try:
        completed = subprocess.run(
            [
                "icacls.exe",
                str(target),
                "/inheritance:r",
                "/grant:r",
                f"{_current_windows_account()}:(F)",
                "*S-1-5-18:(F)",  # Local System
                "*S-1-5-32-544:(F)",  # Built-in Administrators
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
            shell=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class LocalAuthorizationManager:
    """Password-gated, exact, one-use authorization for local actions.

    Password candidates are used only for a verifier comparison. They are never
    retained in challenge objects, return values, serialized state or messages.
    The caller must keep them out of action arguments and audit records too.
    """

    def __init__(
        self,
        data_dir: Path,
        *,
        challenge_ttl_seconds: float = DEFAULT_CHALLENGE_TTL_SECONDS,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if challenge_ttl_seconds <= 0:
            raise ValueError("challenge_ttl_seconds must be positive")
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir / "authorization.json"
        self.challenge_ttl_seconds = float(challenge_ttl_seconds)
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._lock = threading.RLock()
        self._challenges: dict[str, _PendingChallenge] = {}
        self._storage_error: AuthorizationStorageError | None = None
        try:
            self._record = self._load_record()
        except AuthorizationStorageError as exc:
            # Keep chat and the physical companion available while every
            # sensitive action remains fail-closed.
            self._record = None
            self._storage_error = exc

    @property
    def is_configured(self) -> bool:
        with self._lock:
            return self._record is not None

    @property
    def is_available(self) -> bool:
        with self._lock:
            return self._storage_error is None

    @property
    def storage_error_message(self) -> str | None:
        with self._lock:
            return str(self._storage_error) if self._storage_error is not None else None

    def configure(self, password: str) -> None:
        """Create the first verifier; never silently replaces an existing one."""

        _validate_new_password(password)
        with self._lock:
            self._require_storage_unlocked()
            if self._record is not None:
                raise AuthorizationAlreadyConfiguredError(
                    "La contraseña de autorización ya está configurada."
                )
            salt = secrets.token_bytes(SALT_BYTES)
            self._record = _VerifierRecord(
                salt=salt,
                verifier=_derive_verifier(password, salt),
            )
            try:
                self._save_record_unlocked()
            except Exception:
                self._record = None
                raise

    def change_password(self, current_password: str, new_password: str) -> None:
        """Verify the old password, then replace it with a newly salted verifier."""

        _validate_new_password(new_password)
        with self._lock:
            self._require_storage_unlocked()
            record = self._require_record_unlocked()
            self._verify_password_unlocked(current_password, record)
            salt = secrets.token_bytes(SALT_BYTES)
            previous = self._record
            self._record = _VerifierRecord(
                salt=salt,
                verifier=_derive_verifier(new_password, salt),
            )
            self._challenges.clear()
            try:
                self._save_record_unlocked()
            except Exception:
                self._record = previous
                raise

    def issue_challenge(
        self,
        action: str,
        arguments: Mapping[str, Any] | None,
        summary: str,
        *,
        origin: str = "desktop",
    ) -> ChallengeInfo:
        """Bind a one-use challenge to an immutable snapshot of one action."""

        action_value = str(action).strip()
        if not action_value:
            raise ValueError("action must not be empty")
        try:
            arguments_snapshot = copy.deepcopy(dict(arguments or {}))
        except Exception as exc:
            raise ValueError("action arguments cannot be copied safely") from exc

        with self._lock:
            self._require_storage_unlocked()
            now_monotonic = self._monotonic_clock()
            self._prune_expired_unlocked(now_monotonic)
            if len(self._challenges) >= MAX_PENDING_CHALLENGES:
                raise TooManyChallengesError(
                    "Hay demasiadas autorizaciones pendientes. Cancela alguna o espera."
                )
            challenge_id = secrets.token_urlsafe(32)
            while challenge_id in self._challenges:
                challenge_id = secrets.token_urlsafe(32)
            expires_monotonic = now_monotonic + self.challenge_ttl_seconds
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=self.challenge_ttl_seconds)
            ).isoformat()
            pending = _PendingChallenge(
                challenge_id=challenge_id,
                action=action_value,
                arguments=arguments_snapshot,
                summary=str(summary),
                origin=str(origin),
                expires_monotonic=expires_monotonic,
                expires_at=expires_at,
            )
            self._challenges[challenge_id] = pending
            return pending.public()

    def authorize_and_consume(
        self, challenge_id: str, password: str
    ) -> AuthorizedAction:
        """Authorize the stored action exactly once and return its copied payload."""

        with self._lock:
            self._require_storage_unlocked()
            record = self._require_record_unlocked()
            pending = self._challenges.get(str(challenge_id))
            if pending is None:
                raise UnknownChallengeError(
                    "La autorización no existe, fue cancelada o ya se utilizó."
                )
            if self._monotonic_clock() >= pending.expires_monotonic:
                self._challenges.pop(pending.challenge_id, None)
                raise ExpiredChallengeError("La autorización ha caducado.")

            self._verify_password_unlocked(password, record)
            # Consume while holding the same lock used for verification. A
            # second thread can therefore never execute the same grant.
            consumed = self._challenges.pop(pending.challenge_id)
            return AuthorizedAction(
                challenge_id=consumed.challenge_id,
                action=consumed.action,
                arguments=copy.deepcopy(consumed.arguments),
                summary=consumed.summary,
                origin=consumed.origin,
            )

    def cancel(self, challenge_id: str) -> bool:
        with self._lock:
            return self._challenges.pop(str(challenge_id), None) is not None

    def challenge_info(self, challenge_id: str) -> ChallengeInfo | None:
        """Return public status without exposing the stored action arguments."""

        with self._lock:
            now = self._monotonic_clock()
            self._prune_expired_unlocked(now)
            pending = self._challenges.get(str(challenge_id))
            return pending.public() if pending else None

    def retry_after_seconds(self) -> int:
        """Return the current global lockout duration, or zero."""

        with self._lock:
            self._require_storage_unlocked()
            record = self._require_record_unlocked()
            now = self._wall_clock()
            locked_until = record.locked_until
            if locked_until is None or now >= locked_until:
                return 0
            return max(1, math.ceil(locked_until - now))

    def _require_record_unlocked(self) -> _VerifierRecord:
        if self._record is None:
            raise AuthorizationNotConfiguredError(
                "Configura una contraseña local antes de usar acciones sensibles."
            )
        return self._record

    def _require_storage_unlocked(self) -> None:
        if self._storage_error is not None:
            raise AuthorizationStorageError(str(self._storage_error))

    def _verify_password_unlocked(
        self, password: str, record: _VerifierRecord
    ) -> None:
        now = self._wall_clock()
        self._refresh_rate_window_unlocked(record, now)
        if record.locked_until is not None and now < record.locked_until:
            raise AuthorizationRateLimitedError(
                math.ceil(record.locked_until - now)
            )

        candidate_valid = isinstance(password, str) and len(password) <= MAX_PASSWORD_LENGTH
        candidate = password if candidate_valid else ""
        derived = _derive_verifier(candidate, record.salt)
        valid = candidate_valid and hmac.compare_digest(derived, record.verifier)
        if not valid:
            self._record_failure_unlocked(record, now)
            if record.locked_until is not None and now < record.locked_until:
                raise AuthorizationRateLimitedError(
                    math.ceil(record.locked_until - now)
                )
            raise InvalidPasswordError("La contraseña no es correcta.")

        if (
            record.failures
            or record.failure_window_started_at is not None
            or record.locked_until is not None
        ):
            record.failures = 0
            record.failure_window_started_at = None
            record.locked_until = None
            self._save_record_unlocked()

    def _refresh_rate_window_unlocked(
        self, record: _VerifierRecord, now: float
    ) -> None:
        if record.locked_until is not None:
            if now < record.locked_until:
                return
            record.failures = 0
            record.failure_window_started_at = None
            record.locked_until = None
            return
        started = record.failure_window_started_at
        if started is not None and now - started >= RATE_LIMIT_WINDOW_SECONDS:
            record.failures = 0
            record.failure_window_started_at = None

    def _record_failure_unlocked(
        self, record: _VerifierRecord, now: float
    ) -> None:
        if record.failure_window_started_at is None:
            record.failure_window_started_at = now
            record.failures = 0
        record.failures += 1
        if record.failures >= RATE_LIMIT_FAILURES:
            record.locked_until = now + RATE_LIMIT_WINDOW_SECONDS
        self._save_record_unlocked()

    def _prune_expired_unlocked(self, now_monotonic: float) -> None:
        expired = [
            challenge_id
            for challenge_id, pending in self._challenges.items()
            if now_monotonic >= pending.expires_monotonic
        ]
        for challenge_id in expired:
            self._challenges.pop(challenge_id, None)

    def _load_record(self) -> _VerifierRecord | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            kdf = raw["kdf"]
            expected_kdf = {
                "name": "scrypt",
                "n": SCRYPT_N,
                "r": SCRYPT_R,
                "p": SCRYPT_P,
                "dklen": SCRYPT_DKLEN,
            }
            if raw.get("version") != 1 or kdf != expected_kdf:
                raise ValueError("unsupported authorization verifier format")
            rate = raw.get("rate_limit") or {}
            failures = int(rate.get("failures", 0))
            if failures < 0 or failures > RATE_LIMIT_FAILURES:
                raise ValueError("invalid rate limit failure count")
            window = rate.get("failure_window_started_at")
            locked = rate.get("locked_until")
            return _VerifierRecord(
                salt=_b64decode(raw["salt"], SALT_BYTES),
                verifier=_b64decode(raw["verifier"], SCRYPT_DKLEN),
                failures=failures,
                failure_window_started_at=float(window) if window is not None else None,
                locked_until=float(locked) if locked is not None else None,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthorizationStorageError(
                "El archivo de autorización no es válido; las acciones sensibles están bloqueadas."
            ) from exc

    def _save_record_unlocked(self) -> None:
        self._require_storage_unlocked()
        record = self._require_record_unlocked()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "kdf": {
                "name": "scrypt",
                "n": SCRYPT_N,
                "r": SCRYPT_R,
                "p": SCRYPT_P,
                "dklen": SCRYPT_DKLEN,
            },
            "salt": _b64encode(record.salt),
            "verifier": _b64encode(record.verifier),
            "rate_limit": {
                "failures": record.failures,
                "failure_window_started_at": record.failure_window_started_at,
                "locked_until": record.locked_until,
            },
        }
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".authorization-",
                suffix=".tmp",
                dir=self.data_dir,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            harden_authorization_file(temporary_path)
            os.replace(temporary_path, self.path)
            temporary_path = None
            harden_authorization_file(self.path)
        except OSError as exc:
            raise AuthorizationStorageError(
                "No se pudo guardar el verificador de autorización."
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
