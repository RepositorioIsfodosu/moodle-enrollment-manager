from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class VaultError(Exception):
    pass


def vault() -> MultiFernet:
    setting = get_settings().moodle_token_keys
    try:
        keys = setting.get_secret_value().split(",") if setting else []
        if not keys or len(keys) > 5:
            raise ValueError
        return MultiFernet([Fernet(key.strip().encode("ascii")) for key in keys])
    except (ValueError, TypeError, UnicodeError):
        raise VaultError("Cifrado no configurado correctamente") from None


def encrypt_token(token: str) -> str:
    return vault().encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return vault().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise VaultError("Token no descifrable; verificar claves") from None


def rotate_token(ciphertext: str) -> str:
    try:
        return vault().rotate(ciphertext.encode()).decode()
    except (InvalidToken, UnicodeError):
        raise VaultError("Token no descifrable; verificar claves") from None
