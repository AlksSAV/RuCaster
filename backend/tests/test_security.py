"""Тесты security: bcrypt, JWT, rate-limit lockout."""

from __future__ import annotations

import time
from datetime import timedelta
from unittest.mock import patch

from app.core.config import settings
from app.core.security import (
    check_login_lockout,
    create_access_token,
    decode_access_token,
    hash_password,
    record_login_attempt,
    verify_password,
)


class TestHashPassword:
    def test_hash_and_verify(self):
        pw = "secure_password_123"
        h = hash_password(pw)
        assert h.startswith("$2b$")
        assert h != pw
        assert verify_password(pw, h)
        assert not verify_password("wrong_password", h)

    def test_different_hashes_same_password(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # random salt
        assert verify_password("same_password", h1)
        assert verify_password("same_password", h2)


class TestJwtToken:
    def test_encode_decode(self):
        token = create_access_token("testuser")
        assert isinstance(token, str)
        assert decode_access_token(token) == "testuser"

    def test_garbage_token_returns_none(self):
        assert decode_access_token("not.a.jwt.token") is None

    def test_empty_token_returns_none(self):
        assert decode_access_token("") is None

    def test_expired_token_returns_none(self):
        token = create_access_token("testuser", expires_delta=timedelta(minutes=-5))
        assert decode_access_token(token) is None

    def test_wrong_secret_returns_none(self):
        token = create_access_token("testuser")
        with patch.object(settings, "jwt_secret_key", "another_secret_key"):
            assert decode_access_token(token) is None

    def test_different_subjects(self):
        t1 = create_access_token("alice")
        t2 = create_access_token("bob")
        assert decode_access_token(t1) == "alice"
        assert decode_access_token(t2) == "bob"


class TestLoginLockout:
    def setup_method(self):
        from app.core import security

        security._login_attempts.clear()

    def test_unknown_ip_allowed(self):
        assert check_login_lockout("127.0.0.99") is True

    def test_lockout_after_max_failed_attempts(self):
        """По умолчанию 5 неудач подряд -> блокировка (regression: счётчик не должен
        сбрасываться самой проверкой check_login_lockout)."""
        assert settings.max_login_attempts == 5
        ip = "127.0.0.1"
        for _ in range(settings.max_login_attempts - 1):
            assert check_login_lockout(ip) is True
            record_login_attempt(ip, False)
        assert check_login_lockout(ip) is True  # 5-я попытка ещё разрешена
        record_login_attempt(ip, False)
        assert check_login_lockout(ip) is False

    def test_interleaved_checks_do_not_reset_counter(self):
        """Проверки между попытками не должны обнулять счётчик (баг B-002)."""
        ip = "127.0.0.2"
        for _ in range(settings.max_login_attempts):
            assert check_login_lockout(ip) is True
            record_login_attempt(ip, False)
        assert check_login_lockout(ip) is False

    def test_success_resets_counter(self):
        ip = "127.0.0.3"
        for _ in range(settings.max_login_attempts - 1):
            record_login_attempt(ip, False)
        record_login_attempt(ip, True)
        # после успеха можно снова делать max_login_attempts неудач до блокировки
        for _ in range(settings.max_login_attempts - 1):
            assert check_login_lockout(ip) is True
            record_login_attempt(ip, False)
        assert check_login_lockout(ip) is True

    def test_lockout_expires_after_window(self):
        ip = "127.0.0.4"
        for _ in range(settings.max_login_attempts):
            record_login_attempt(ip, False)
        assert check_login_lockout(ip) is False
        # перематываем время вперёд за пределы окна блокировки
        future = time.time() + settings.login_lockout_seconds + 1
        with patch("app.core.security.time.time", return_value=future):
            assert check_login_lockout(ip) is True
            # счётчик обнулён: нужен полный набор неудач для новой блокировки
            for _ in range(settings.max_login_attempts):
                record_login_attempt(ip, False)
            assert check_login_lockout(ip) is False

    def test_different_ips_independent(self):
        ip1, ip2 = "10.0.0.1", "10.0.0.2"
        for _ in range(settings.max_login_attempts):
            record_login_attempt(ip1, False)
        assert check_login_lockout(ip1) is False
        assert check_login_lockout(ip2) is True
