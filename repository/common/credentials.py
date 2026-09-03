import os

from cryptography.fernet import Fernet, InvalidToken


def get_master_key():
    master_key = os.getenv("KEYSTONE_MASTER_KEY")

    if not master_key:
        raise RuntimeError(
            "KEYSTONE_MASTER_KEY environment variable is not configured."
        )

    return master_key.encode()


def encrypt_credential(plain_value):
    if not plain_value:
        raise RuntimeError(
            "Credential value cannot be empty."
        )

    fernet = Fernet(get_master_key())

    return fernet.encrypt(
        plain_value.encode()
    ).decode()


def decrypt_credential(encrypted_value):
    if not encrypted_value:
        raise RuntimeError(
            "Credential data is empty."
        )

    try:
        fernet = Fernet(get_master_key())

        return fernet.decrypt(
            encrypted_value.encode()
        ).decode()

    except InvalidToken as exc:
        raise RuntimeError(
            "Credential decryption failed. "
            "The Keystone master key may be incorrect."
        ) from exc