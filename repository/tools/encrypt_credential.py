import getpass
from repository.common.credentials import encrypt_credential


def main():
    credential = getpass.getpass(
        "Credential: "
    )

    encrypted = encrypt_credential(
        credential
    )

    print()
    print("Encrypted credential:")
    print(encrypted)


if __name__ == "__main__":
    main()