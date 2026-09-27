"""Short-lived operator sessions for the Unix-socket relay.

The password hash stays in a root-owned file on the host. This module never
stores or logs a plaintext password and never trusts a caller-supplied actor.
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import stat
import threading
import time
from pathlib import Path
from typing import Callable

COOKIE_NAME = '__Host-awg_cita_auth'
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
_BCRYPT_HASH = re.compile(rb'\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}\Z')


def read_password_hash(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
                info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o640):
            raise ValueError('unsafe operator credential file')
        raw = os.read(fd, 129)
    finally:
        os.close(fd)
    value = raw.strip()
    if len(raw) > 128 or not _BCRYPT_HASH.fullmatch(value):
        raise ValueError('invalid operator credential hash')
    return value


class OperatorAuth:
    def __init__(self, operator_id: str, password_hash: bytes,
                 *, verify: Callable[[bytes, bytes], bool] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if (not isinstance(operator_id, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', operator_id) or
                not isinstance(password_hash, bytes) or not _BCRYPT_HASH.fullmatch(password_hash)):
            raise ValueError('invalid operator credential')
        if verify is None:
            import bcrypt
            verify = bcrypt.checkpw
        self.operator_id = operator_id
        self.password_hash = password_hash
        self.verify = verify
        self.clock = clock
        self.lock = threading.Lock()
        self.sessions: dict[str, float] = {}

    def authenticate(self, username: object, password: object) -> str | None:
        if (not isinstance(username, str) or not isinstance(password, str) or
                len(username) > 64 or not 1 <= len(password) <= 256):
            return None
        try:
            candidate = password.encode('utf-8')
        except UnicodeEncodeError:
            return None
        if len(candidate) > 512:
            return None
        valid_password = self.verify(candidate, self.password_hash)
        if not valid_password or not hmac.compare_digest(username, self.operator_id):
            return None
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = self.clock()
            for key, created in list(self.sessions.items()):
                if now - created >= 3600:
                    del self.sessions[key]
            if len(self.sessions) >= 128:
                self.sessions.pop(next(iter(self.sessions)))
            self.sessions[token] = now
        return token

    def actor(self, cookie_header: str | None) -> str | None:
        if not isinstance(cookie_header, str) or len(cookie_header) > 4096:
            return None
        values = [part.strip().split('=', 1)[1] for part in cookie_header.split(';')
                  if part.strip().startswith(COOKIE_NAME + '=')]
        if len(values) != 1 or not _TOKEN.fullmatch(values[0]):
            return None
        with self.lock:
            created = self.sessions.get(values[0])
            if created is None:
                return None
            if self.clock() - created >= 3600:
                del self.sessions[values[0]]
                return None
        return self.operator_id

    def revoke(self, cookie_header: str | None) -> None:
        if not isinstance(cookie_header, str):
            return
        values = [part.strip().split('=', 1)[1] for part in cookie_header.split(';')
                  if part.strip().startswith(COOKIE_NAME + '=')]
        if len(values) == 1 and _TOKEN.fullmatch(values[0]):
            with self.lock:
                self.sessions.pop(values[0], None)


def session_cookie(token: str) -> str:
    if not _TOKEN.fullmatch(token):
        raise ValueError('invalid operator session')
    return f'{COOKIE_NAME}={token}; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600'


def clear_cookie() -> str:
    return f'{COOKIE_NAME}=; Secure; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'
