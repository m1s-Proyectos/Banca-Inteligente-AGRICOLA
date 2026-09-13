import hashlib
import hmac

from app.core.config import settings


def normalize_dob(value: str) -> str:
    """Normaliza la fecha antes de compararla o hashearla.

    ponytail: solo unifica separadores, no reordena componentes (DD-MM-YYYY
    contra YYYY-MM-DD). Techo conocido: al hashear, esta normalizacion queda
    congelada — cambiarla invalida todos los dob_hash almacenados y obliga a
    re-sembrar. Upgrade: parsear a date y hashear el isoformat.
    """
    return value.strip().replace("/", "-")


def hash_dob(value: str) -> str:
    """HMAC-SHA256 de la fecha de nacimiento con APP_SECRET.

    La fecha solo se usa para comparar en verify_identity, nunca se muestra,
    asi que no necesita ser reversible: un HMAC es mas seguro que cifrarla
    porque no hay clave cuya fuga revele el dato.
    """
    return hmac.new(
        settings.app_secret.encode("utf-8"),
        normalize_dob(value).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def dob_matches(stored_hash: str, supplied_dob: str) -> bool:
    return hmac.compare_digest(stored_hash, hash_dob(supplied_dob))
