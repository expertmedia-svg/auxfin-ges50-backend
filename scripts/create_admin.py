"""Cree le compte administrateur initial. Idempotent : si le compte existe
deja, le mot de passe n'est pas ecrase. Si INITIAL_ADMIN_PASSWORD n'est pas
defini dans .env, un mot de passe aleatoire fort est genere et affiche UNE
SEULE FOIS (jamais ecrit en clair en base ni dans les logs applicatifs) ;
le compte doit changer ce mot de passe a sa premiere connexion
(User.must_change_password)."""

from __future__ import annotations

import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.permissions import RoleCode  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.identity import Role, User, UserRole  # noqa: E402


def _generate_strong_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def run() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.initial_admin_email.lower()).one_or_none()
        if existing:
            print(f"L'administrateur {settings.initial_admin_email} existe deja, aucune action.")
            return

        role = db.query(Role).filter(Role.code == RoleCode.SUPER_ADMIN.value).one_or_none()
        if role is None:
            raise RuntimeError("Le role super_admin n'existe pas. Executez d'abord: make seed-config")

        password = settings.initial_admin_password or None
        generated = password is None
        if generated:
            password = _generate_strong_password()

        user = User(
            email=settings.initial_admin_email.lower(),
            full_name=settings.initial_admin_full_name,
            hashed_password=hash_password(password),
            must_change_password=True,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        db.commit()

        print(f"Administrateur cree: {settings.initial_admin_email}")
        if generated:
            print("")
            print("=" * 60)
            print(f"MOT DE PASSE GENERE (a noter maintenant, non recuperable) : {password}")
            print("Changement de mot de passe obligatoire a la premiere connexion.")
            print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    run()
