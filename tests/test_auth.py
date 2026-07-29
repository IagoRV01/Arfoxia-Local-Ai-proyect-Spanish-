from __future__ import annotations

import base64
import json
import threading

import pytest

from glaceon_companion.auth import (
    MAX_PASSWORD_LENGTH,
    AuthorizationAlreadyConfiguredError,
    AuthorizationNotConfiguredError,
    AuthorizationRateLimitedError,
    AuthorizationStorageError,
    ExpiredChallengeError,
    InvalidPasswordError,
    LocalAuthorizationManager,
    PasswordPolicyError,
    UnknownChallengeError,
)


class MutableClock:
    def __init__(self, value: float = 1_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def configured_manager(tmp_path, *, ttl: float = 90.0):
    monotonic = MutableClock()
    wall = MutableClock(10_000.0)
    manager = LocalAuthorizationManager(
        tmp_path,
        challenge_ttl_seconds=ttl,
        monotonic_clock=monotonic,
        wall_clock=wall,
    )
    manager.configure("test-passphrase")
    return manager, monotonic, wall


def test_configure_stores_only_a_salted_scrypt_verifier(tmp_path):
    password = "sample-only-password"
    manager = LocalAuthorizationManager(tmp_path)

    assert manager.is_configured is False
    manager.configure(password)

    raw_text = (tmp_path / "authorization.json").read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    assert manager.is_configured is True
    assert password not in raw_text
    assert raw["kdf"] == {
        "name": "scrypt",
        "n": 32_768,
        "r": 8,
        "p": 1,
        "dklen": 32,
    }
    assert len(base64.b64decode(raw["salt"], validate=True)) == 16
    assert len(base64.b64decode(raw["verifier"], validate=True)) == 32

    reloaded = LocalAuthorizationManager(tmp_path)
    challenge = reloaded.issue_challenge("power", {"operation": "restart"}, "Reiniciar")
    authorized = reloaded.authorize_and_consume(challenge.challenge_id, password)
    assert authorized.action == "power"


def test_configuration_is_fail_closed_and_cannot_be_replaced(tmp_path):
    manager = LocalAuthorizationManager(tmp_path)
    challenge = manager.issue_challenge("power", {}, "Apagar")
    with pytest.raises(AuthorizationNotConfiguredError):
        manager.authorize_and_consume(challenge.challenge_id, "1234")
    with pytest.raises(PasswordPolicyError):
        manager.configure("123")

    manager.configure("1234")
    with pytest.raises(AuthorizationAlreadyConfiguredError):
        manager.configure("different-password")
    with pytest.raises(PasswordPolicyError):
        manager.change_password("1234", "x" * (MAX_PASSWORD_LENGTH + 1))


def test_challenge_binds_a_deep_copy_and_is_one_use(tmp_path):
    manager, _, _ = configured_manager(tmp_path)
    arguments = {"paths": ["one.txt"], "options": {"overwrite": False}}
    challenge = manager.issue_challenge(
        "write_files", arguments, "Modificar one.txt", origin="desktop"
    )
    arguments["paths"].append("injected.txt")
    arguments["options"]["overwrite"] = True

    with pytest.raises(InvalidPasswordError):
        manager.authorize_and_consume(challenge.challenge_id, "wrong-password")
    assert manager.challenge_info(challenge.challenge_id) == challenge

    authorized = manager.authorize_and_consume(
        challenge.challenge_id, "test-passphrase"
    )
    assert authorized.action == "write_files"
    assert authorized.arguments == {
        "paths": ["one.txt"],
        "options": {"overwrite": False},
    }
    assert authorized.origin == "desktop"
    assert "test-passphrase" not in repr(challenge)
    assert "test-passphrase" not in repr(authorized)
    with pytest.raises(UnknownChallengeError):
        manager.authorize_and_consume(challenge.challenge_id, "test-passphrase")


def test_challenge_expires_and_can_be_cancelled(tmp_path):
    manager, monotonic, _ = configured_manager(tmp_path, ttl=10)
    expired = manager.issue_challenge("power", {}, "Apagar")
    monotonic.advance(10)
    with pytest.raises(ExpiredChallengeError):
        manager.authorize_and_consume(expired.challenge_id, "test-passphrase")

    cancelled = manager.issue_challenge("power", {}, "Reiniciar")
    assert manager.cancel(cancelled.challenge_id) is True
    assert manager.cancel(cancelled.challenge_id) is False
    with pytest.raises(UnknownChallengeError):
        manager.authorize_and_consume(cancelled.challenge_id, "test-passphrase")


def test_five_failures_lock_authorization_for_sixty_seconds(tmp_path):
    manager, _, wall = configured_manager(tmp_path)
    challenge = manager.issue_challenge("power", {}, "Apagar")

    for _ in range(4):
        with pytest.raises(InvalidPasswordError):
            manager.authorize_and_consume(challenge.challenge_id, "not-correct")
    with pytest.raises(AuthorizationRateLimitedError) as locked:
        manager.authorize_and_consume(challenge.challenge_id, "not-correct")
    assert locked.value.retry_after_seconds == 60
    assert manager.retry_after_seconds() == 60

    with pytest.raises(AuthorizationRateLimitedError):
        manager.authorize_and_consume(challenge.challenge_id, "test-passphrase")
    wall.advance(60)
    authorized = manager.authorize_and_consume(
        challenge.challenge_id, "test-passphrase"
    )
    assert authorized.action == "power"
    assert manager.retry_after_seconds() == 0


def test_rate_limit_survives_a_manager_reload(tmp_path):
    manager, _, wall = configured_manager(tmp_path)
    challenge = manager.issue_challenge("power", {}, "Apagar")
    for _ in range(5):
        expected = (
            AuthorizationRateLimitedError if _ == 4 else InvalidPasswordError
        )
        with pytest.raises(expected):
            manager.authorize_and_consume(challenge.challenge_id, "wrong-value")

    reloaded = LocalAuthorizationManager(tmp_path, wall_clock=wall)
    new_challenge = reloaded.issue_challenge("power", {}, "Apagar")
    with pytest.raises(AuthorizationRateLimitedError):
        reloaded.authorize_and_consume(new_challenge.challenge_id, "test-passphrase")


def test_change_password_requires_current_and_invalidates_challenges(tmp_path):
    manager, _, _ = configured_manager(tmp_path)
    pending = manager.issue_challenge("power", {}, "Reiniciar")
    with pytest.raises(InvalidPasswordError):
        manager.change_password("incorrect-old", "new-test-passphrase")

    manager.change_password("test-passphrase", "new-test-passphrase")
    assert manager.challenge_info(pending.challenge_id) is None
    challenge = manager.issue_challenge("power", {}, "Reiniciar")
    with pytest.raises(InvalidPasswordError):
        manager.authorize_and_consume(challenge.challenge_id, "test-passphrase")
    authorized = manager.authorize_and_consume(
        challenge.challenge_id, "new-test-passphrase"
    )
    assert authorized.action == "power"


def test_authorizing_one_challenge_is_atomic_across_threads(tmp_path):
    manager, _, _ = configured_manager(tmp_path)
    challenge = manager.issue_challenge("power", {}, "Reiniciar")
    barrier = threading.Barrier(8)
    successes = []
    failures = []

    def authorize() -> None:
        barrier.wait()
        try:
            successes.append(
                manager.authorize_and_consume(
                    challenge.challenge_id, "test-passphrase"
                )
            )
        except UnknownChallengeError as exc:
            failures.append(exc)

    threads = [threading.Thread(target=authorize) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(successes) == 1
    assert len(failures) == 7


def test_corrupt_or_unexpected_verifier_file_fails_closed(tmp_path):
    path = tmp_path / "authorization.json"
    path.write_text('{"version": 999}', encoding="utf-8")

    manager = LocalAuthorizationManager(tmp_path)
    assert manager.is_available is False
    assert manager.is_configured is False
    with pytest.raises(AuthorizationStorageError):
        manager.issue_challenge("power", {}, "Apagar")
    with pytest.raises(AuthorizationStorageError):
        manager.configure("test-passphrase")
