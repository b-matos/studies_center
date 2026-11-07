import pytest

from servidor.validation import TemaInvalido, validar_tema


@pytest.mark.parametrize(
    "tema",
    [
        "saude-portugal",
        "Saúde em Portugal",
        "educação, pobreza e desigualdade",
        "a" * 80,
    ],
)
def test_valid_temas_pass(tema: str) -> None:
    assert validar_tema(tema) == tema.strip()


@pytest.mark.parametrize(
    "tema",
    [
        "ab",  # too short
        "a" * 81,  # too long
        "saude; rm -rf /",
        "saude `whoami`",
        "saude && ls",
        "saude | cat /etc/passwd",
        "saude$(ls)",
        "saude > /tmp/x",
        "saude\nrm -rf /",
        "",
        "   ",
    ],
)
def test_invalid_temas_rejected(tema: str) -> None:
    with pytest.raises(TemaInvalido):
        validar_tema(tema)
