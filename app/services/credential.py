import json
import os
from cryptography.fernet import Fernet, InvalidToken

def load_fernet_from_env(env_var: str = "APP_CREDENTIAL_KEY") -> Fernet:
    key = os.environ.get(env_var)
    if not key:
        raise ValueError(f"Environment variable '{env_var}' is missing.")
    try:
        return Fernet(key)
    except ValueError as e:
        raise ValueError(f"Invalid Fernet key in '{env_var}': {e}") from e

def encrypt_credential(fernet: Fernet, payload: dict) -> str:
    json_bytes = json.dumps(payload).encode("utf-8")
    return fernet.encrypt(json_bytes).decode("utf-8")

def decrypt_credential(fernet: Fernet, credential_enc: str) -> dict:
    try:
        json_bytes = fernet.decrypt(credential_enc.encode("utf-8"))
        return json.loads(json_bytes.decode("utf-8"))
    except InvalidToken as e:
        raise ValueError("Invalid ciphertext or key") from e
