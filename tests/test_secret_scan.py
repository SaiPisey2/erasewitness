import json

import pytest

from erasewitness.report.secret_scan import SecretLeakError, scan

KEYS = [
    "sk-" + "A" * 30,
    "sk-proj-" + "B" * 30,
    "apikey_" + "c" * 30,
    "AKIA" + "D" * 16,
    "ghp_" + "e" * 36,
    "AIza" + "f" * 35,
]


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("sep", ["\n", "\t", "\r"])
def test_key_after_json_escape_is_caught(key: str, sep: str) -> None:
    dumped = json.dumps({"text": f"note{sep}{key}"})
    with pytest.raises(SecretLeakError):
        scan({"evidence/derived.json": dumped})


@pytest.mark.parametrize(
    "text",
    [
        "memory/risk-tolerance-and-investment-preferences.md",
        "disk-encryption-settings-for-laptop",
        "task-1234567890abcdefghij",
    ],
)
def test_words_ending_in_sk_are_not_keys(text: str) -> None:
    scan({"f": json.dumps({"text": text})})
