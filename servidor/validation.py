"""Validate the free-text "tema" the user submits before it ever reaches a subprocess.

The runner always calls claude via asyncio.create_subprocess_exec with an argument list
(never a shell string), so shell injection is not literally possible either way — but the
platform's own rule is that the topic is never trusted blindly, so we still enforce a
narrow, explicit charset and length here as a second, independent layer.
"""
from __future__ import annotations

MIN_LENGTH = 3
MAX_LENGTH = 80
_ALLOWED_EXTRA = set(" -,.")


class TemaInvalido(ValueError):
    pass


def validar_tema(tema: str) -> str:
    tema = tema.strip()
    if not (MIN_LENGTH <= len(tema) <= MAX_LENGTH):
        raise TemaInvalido(f"o tema tem de ter entre {MIN_LENGTH} e {MAX_LENGTH} caracteres")
    # Letters (any script) and digits via str.isalnum(), plus a short allowlist of
    # separators. No shell metacharacters ($ ` ; | & < > ( ) \ ' " newlines ...) pass this.
    if not all(ch.isalnum() or ch in _ALLOWED_EXTRA for ch in tema):
        raise TemaInvalido(
            "o tema só pode conter letras, dígitos, espaços, vírgulas, pontos e hífens"
        )
    return tema
