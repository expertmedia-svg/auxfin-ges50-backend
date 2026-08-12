"""Cree ou met a jour des comptes de TEST par role, avec un mot de passe de
developpement connu et fixe, pour permettre une connexion rapide depuis la
page de login pendant les tests manuels.

USAGE DEV/TEST UNIQUEMENT. Ces comptes ne doivent jamais exister sur un
environnement de production reel (mot de passe faible et public dans le
code frontend). Idempotent : si un compte existe deja, son mot de passe et
son role sont resynchronises sur les valeurs ci-dessous."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.core.permissions import RoleCode  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.identity import Role, User, UserRole  # noqa: E402

# Mot de passe de developpement unique, volontairement simple et connu de
# tous : ces comptes n'ont aucune vocation a exister en production.
DEV_PASSWORD = "DevTest2026!"

DEV_ACCOUNTS = [
    {"email": "admin.test@ges-g50.com", "full_name": "Admin (test)", "role": RoleCode.ADMIN},
    {"email": "superviseur.test@ges-g50.com", "full_name": "Superviseur (test)", "role": RoleCode.SUPERVISEUR},
    {"email": "operateur.test@ges-g50.com", "full_name": "Operateur validation (test)", "role": RoleCode.OPERATEUR_VALIDATION},
    {"email": "lecteur.test@ges-g50.com", "full_name": "Lecteur (test)", "role": RoleCode.LECTEUR},
]


def run() -> None:
    db = SessionLocal()
    try:
        for account in DEV_ACCOUNTS:
            role = db.query(Role).filter(Role.code == account["role"].value).one_or_none()
            if role is None:
                raise RuntimeError(
                    f"Le role {account['role'].value} n'existe pas. Executez d'abord: make seed-config"
                )

            user = db.query(User).filter(User.email == account["email"]).one_or_none()
            if user is None:
                user = User(
                    email=account["email"],
                    full_name=account["full_name"],
                    hashed_password=hash_password(DEV_PASSWORD),
                    must_change_password=False,
                )
                db.add(user)
                db.flush()
                print(f"Cree : {account['email']}")
            else:
                user.hashed_password = hash_password(DEV_PASSWORD)
                user.must_change_password = False
                user.is_active = True
                print(f"Mis a jour : {account['email']}")

            existing_link = (
                db.query(UserRole)
                .filter(UserRole.user_id == user.id, UserRole.role_id == role.id)
                .one_or_none()
            )
            if existing_link is None:
                # Retire les eventuels autres roles pour rester coherent avec le nom du compte.
                db.query(UserRole).filter(UserRole.user_id == user.id).delete()
                db.add(UserRole(user_id=user.id, role_id=role.id))

        db.commit()
        print("")
        print("=" * 60)
        print(f"Mot de passe commun a ces comptes de test : {DEV_PASSWORD}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    run()
