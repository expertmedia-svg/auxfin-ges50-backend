from enum import StrEnum


class RoleCode(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    SUPERVISEUR = "superviseur"
    OPERATEUR_VALIDATION = "operateur_validation"
    LECTEUR = "lecteur"


ROLE_LABELS: dict[str, str] = {
    RoleCode.SUPER_ADMIN: "Super administrateur",
    RoleCode.ADMIN: "Administrateur",
    RoleCode.SUPERVISEUR: "Superviseur",
    RoleCode.OPERATEUR_VALIDATION: "Operateur de validation",
    RoleCode.LECTEUR: "Lecteur",
}

# Roles allowed to write/modify data (upload, import, validate, correct, configure).
WRITE_ROLES = {RoleCode.SUPER_ADMIN, RoleCode.ADMIN, RoleCode.SUPERVISEUR, RoleCode.OPERATEUR_VALIDATION}
# Roles allowed to administer applications/agents/users/settings.
ADMIN_ROLES = {RoleCode.SUPER_ADMIN, RoleCode.ADMIN}
# Every authenticated, active user can read.
READ_ROLES = {
    RoleCode.SUPER_ADMIN,
    RoleCode.ADMIN,
    RoleCode.SUPERVISEUR,
    RoleCode.OPERATEUR_VALIDATION,
    RoleCode.LECTEUR,
}
