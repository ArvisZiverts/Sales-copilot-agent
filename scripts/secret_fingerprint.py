"""Print a safe fingerprint of the local webhook secret.

    python -m scripts.secret_fingerprint

Compare the output against https://YOUR-APP/debug/secret-fingerprint. Identical
strings mean both systems hold the same secret; different means a bad paste
somewhere. Neither prints the secret itself.
"""

from app.config import get_settings
from app.security import secret_fingerprint


def main() -> None:
    secret = get_settings().typeform_webhook_secret
    print(f"local .env : {secret_fingerprint(secret)}")
    if secret != secret.strip():
        print("  WARNING: the local value has leading/trailing whitespace")
    if secret.startswith(('"', "'")) or secret.endswith(('"', "'")):
        print("  WARNING: the local value is wrapped in quotes — remove them")


if __name__ == "__main__":
    main()
