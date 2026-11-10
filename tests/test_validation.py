import pytest

from server.validation import InvalidTopic, validate_topic


@pytest.mark.parametrize(
    "topic",
    [
        "saude-portugal",
        "Saúde em Portugal",
        "educação, pobreza e desigualdade",
        "a" * 80,
    ],
)
def test_valid_topics_pass(topic: str) -> None:
    assert validate_topic(topic) == topic.strip()


@pytest.mark.parametrize(
    "topic",
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
def test_invalid_topics_rejected(topic: str) -> None:
    with pytest.raises(InvalidTopic):
        validate_topic(topic)
