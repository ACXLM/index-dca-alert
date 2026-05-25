import os
import pytest
from cryptography.fernet import Fernet
from app.services.credential import encrypt_credential, decrypt_credential, load_fernet_from_env

def test_encrypt_decrypt_credential():
    fernet = Fernet(Fernet.generate_key())
    payload = {"bot_token": "7xxxxxxx:AAxxxxxx"}
    
    credential_enc = encrypt_credential(fernet, payload)
    
    # Check it's base64url encoded (no specific test needed if it doesn't fail, but we can assert it's a string)
    assert isinstance(credential_enc, str)
    assert "7xxxxxxx:AAxxxxxx" not in credential_enc
    
    # Decrypt
    decrypted = decrypt_credential(fernet, credential_enc)
    assert decrypted == payload

def test_encrypt_different_ciphertexts():
    fernet = Fernet(Fernet.generate_key())
    payload = {"bot_token": "test"}
    
    c1 = encrypt_credential(fernet, payload)
    c2 = encrypt_credential(fernet, payload)
    assert c1 != c2

def test_decrypt_invalid_ciphertext():
    fernet = Fernet(Fernet.generate_key())
    with pytest.raises(Exception):
        decrypt_credential(fernet, "invalid_ciphertext")

def test_load_fernet_missing_env(monkeypatch):
    monkeypatch.delenv("APP_CREDENTIAL_KEY", raising=False)
    with pytest.raises(ValueError, match="APP_CREDENTIAL_KEY"):
        load_fernet_from_env()

def test_load_fernet_invalid_key(monkeypatch):
    monkeypatch.setenv("APP_CREDENTIAL_KEY", "invalid_key")
    with pytest.raises(ValueError):
        load_fernet_from_env()

def test_load_fernet_success(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("APP_CREDENTIAL_KEY", key)
    fernet = load_fernet_from_env()
    assert isinstance(fernet, Fernet)
