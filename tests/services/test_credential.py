from __future__ import annotations

import os
import pytest
from cryptography.fernet import Fernet

from app.services.credential import decrypt_credential, encrypt_credential, load_fernet_from_env


def test_encrypt_decrypt_roundtrip() -> None:
    fernet = Fernet(Fernet.generate_key())
    payload = {"bot_token": "7xxxxxxx:AAxxxxxx"}

    credential_enc = encrypt_credential(fernet, payload)
    decrypted = decrypt_credential(fernet, credential_enc)

    assert decrypted == payload


def test_encrypted_output_is_base64url_and_does_not_contain_plaintext() -> None:
    fernet = Fernet(Fernet.generate_key())
    payload = {"bot_token": "secret-token-12345"}

    credential_enc = encrypt_credential(fernet, payload)

    assert isinstance(credential_enc, str)
    assert "secret-token-12345" not in credential_enc
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-_" for c in credential_enc)


def test_encrypting_same_payload_twice_produces_different_ciphertexts() -> None:
    fernet = Fernet(Fernet.generate_key())
    payload = {"bot_token": "test"}

    c1 = encrypt_credential(fernet, payload)
    c2 = encrypt_credential(fernet, payload)

    assert c1 != c2


def test_decrypt_invalid_ciphertext_raises_clear_exception() -> None:
    fernet = Fernet(Fernet.generate_key())

    with pytest.raises(ValueError, match="Invalid ciphertext"):
        decrypt_credential(fernet, "invalid_ciphertext_string")


def test_load_fernet_missing_env_raises_with_variable_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_CREDENTIAL_KEY", raising=False)

    with pytest.raises(ValueError, match="APP_CREDENTIAL_KEY"):
        load_fernet_from_env()


def test_load_fernet_invalid_key_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_CREDENTIAL_KEY", "not_a_valid_fernet_key")

    with pytest.raises(ValueError):
        load_fernet_from_env()


def test_load_fernet_valid_key_returns_fernet_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("APP_CREDENTIAL_KEY", key)

    fernet = load_fernet_from_env()

    assert isinstance(fernet, Fernet)


def test_load_fernet_custom_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("MY_CUSTOM_KEY", key)
    monkeypatch.delenv("APP_CREDENTIAL_KEY", raising=False)

    fernet = load_fernet_from_env("MY_CUSTOM_KEY")

    assert isinstance(fernet, Fernet)


def test_load_fernet_custom_env_var_missing_raises_with_that_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)

    with pytest.raises(ValueError, match="MY_CUSTOM_KEY"):
        load_fernet_from_env("MY_CUSTOM_KEY")
