"""Seed des elements techniques necessaires au demarrage : roles, permissions
de base, et les 4 profils d'application eCoach reels (FinanceCoach, PFNLCoach,
YEBCoach, AgriCoach), configures a partir de l'inspection reelle des 4 videos
fournies (aucune donnee metier fictive n'est creee)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal  # noqa: E402
from app.core.permissions import ROLE_LABELS, RoleCode  # noqa: E402
from app.models.applications import Application, ApplicationProfile  # noqa: E402
from app.models.identity import Permission, Role  # noqa: E402

PERMISSIONS = [
    ("evidence.read", "Consulter les preuves"),
    ("evidence.write", "Importer/corriger/valider les preuves"),
    ("dashboard_import.read", "Consulter les imports dashboard"),
    ("dashboard_import.write", "Importer des fichiers dashboard"),
    ("reconciliation.read", "Consulter les rapprochements"),
    ("reconciliation.write", "Lancer un rapprochement"),
    ("reports.read", "Consulter/telecharger les rapports"),
    ("reports.write", "Generer des rapports"),
    ("admin.applications", "Administrer les applications"),
    ("admin.agents", "Administrer les agents"),
    ("admin.users", "Administrer les utilisateurs"),
    ("admin.settings", "Administrer les parametres"),
    ("audit.read", "Consulter le journal d'audit"),
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleCode.SUPER_ADMIN: [p[0] for p in PERMISSIONS],
    RoleCode.ADMIN: [p[0] for p in PERMISSIONS],
    RoleCode.SUPERVISEUR: [
        "evidence.read", "evidence.write", "dashboard_import.read", "dashboard_import.write",
        "reconciliation.read", "reconciliation.write", "reports.read", "reports.write", "audit.read",
    ],
    RoleCode.OPERATEUR_VALIDATION: ["evidence.read", "evidence.write", "reconciliation.read", "reports.read"],
    RoleCode.LECTEUR: ["evidence.read", "dashboard_import.read", "reconciliation.read", "reports.read"],
}

# Profils derives de l'inspection reelle (ffprobe + extraction de frames) des
# 4 videos WhatsApp fournies. Les mots-cles reprennent les libelles reellement
# vus a l'ecran (section 11 du cahier des charges pour la liste generique).
APPLICATION_PROFILES = [
    {
        "code": "financecoach",
        "name": "FinanceCoach",
        "expected_evidence_type": "video",
        "success_keywords": [
            "synchronisation reussie", "donnees synchronisees",
            "synchronisation terminee", "termine", "succes", "success", "completed",
        ],
        "error_keywords": ["echec", "erreur", "connexion impossible", "failed", "error", "timeout"],
        "logo_keywords": ["financecoach", "finance coach"],
        "primary_color_hint": "#2F80ED",
        # sync_status_icon : zone calibree sur une vraie video envoyee via
        # WhatsApp en Phase C — petit badge vert a cote de "Synchroniser",
        # confirme par l'utilisateur comme signe reel de synchronisation
        # (mesure sur une frame reelle 640x400, bbox x=547-561,y=122-136).
        # Le badge coche bleu de "Telecharger" existe aussi mais n'est PAS
        # utilise : sa couleur bleue est quasi identique, chargee ou vide
        # (le contour bleu occupe une surface similaire au disque plein
        # moins le contour blanc de la coche) — non fiable par simple
        # analyse de couleur, contrairement au badge vert qui n'apparait
        # que lorsque la synchronisation est reellement confirmee.
        "screen_zones": {
            "id_date_header": {"x": 0.35, "y": 0.0, "w": 0.65, "h": 0.08},
            "sync_status_icon": {"x": 0.83, "y": 0.27, "w": 0.07, "h": 0.11},
        },
    },
    {
        "code": "pfnlcoach",
        "name": "PFNLCoach",
        "expected_evidence_type": "video",
        # "upload data" coche (texte ET icone verte) suffit a confirmer la
        # synchronisation sur PFNLCoach, meme si Download Data/Download Media
        # restent a faire — confirme par l'utilisateur en Phase C sur une
        # vraie video (Download/Media sont des etapes suivantes du meme
        # ecran, pas une condition de succes de la synchronisation elle-meme).
        "success_keywords": ["upload data", "donnees synchronisees", "success", "completed"],
        # "please provide location permission" retire des mots-cles d'echec :
        # confirme reel (Phase C) que ce message est une demande de permission
        # sans rapport avec l'etat de synchronisation (ex: geolocalisation
        # d'une autre fonctionnalite), pas un signe d'echec — le considerer
        # comme un echec produisait un faux FAILED sur une vraie synchronisation
        # reussie (Upload Data coche).
        "error_keywords": ["erreur", "echec", "failed"],
        "logo_keywords": ["pfnlcoach", "pfnl coach"],
        "primary_color_hint": "#2E7D32",
        # sync_status_icon : zone calibree sur une vraie video envoyee via
        # WhatsApp en Phase C — icone verte a cote de "Upload Data" (mesuree
        # sur une frame reelle 640x400, bbox x=335-351,y=98-117). Signal de
        # secours si le texte OCR est trop bruite pour matcher "upload data".
        "screen_zones": {
            "id_date_header": {"x": 0.3, "y": 0.0, "w": 0.7, "h": 0.08},
            "sync_status_icon": {"x": 0.48, "y": 0.20, "w": 0.11, "h": 0.13},
        },
    },
    {
        "code": "yebcoach",
        "name": "YEBCoach",
        "expected_evidence_type": "video",
        "success_keywords": ["upload complete", "success", "termine", "completed"],
        "error_keywords": ["echec", "erreur", "failed", "error"],
        "logo_keywords": ["yeb", "yebcoach"],
        "primary_color_hint": "#C62828",
        # sync_status_icon : zone calibree sur une vraie video envoyee via
        # WhatsApp en Phase C (voir docs/CALIBRATION_APPLICATIONS.md) — le
        # bouton "Synchroniser" est suivi d'une icone circulaire qui devient
        # verte une fois la synchronisation terminee, sans qu'aucun texte de
        # confirmation n'apparaisse jamais a l'ecran. Coordonnees mesurees
        # directement sur la frame reelle (icone verte a x=513-533,y=132-152
        # sur une image 640x400), avec une marge de securite.
        "screen_zones": {
            "id_date_header": {"x": 0.3, "y": 0.0, "w": 0.7, "h": 0.08},
            "sync_status_icon": {"x": 0.78, "y": 0.30, "w": 0.09, "h": 0.11},
        },
    },
    {
        "code": "agricoach",
        "name": "AgriCoach",
        "expected_evidence_type": "video",
        "success_keywords": ["completed", "success", "donnees synchronisees", "synchronisation terminee"],
        "error_keywords": ["echec", "erreur", "failed", "error"],
        "logo_keywords": ["agricoach", "agri coach"],
        "primary_color_hint": "#388E3C",
        "screen_zones": {"id_date_header": {"x": 0.3, "y": 0.0, "w": 0.7, "h": 0.08}},
    },
]


def run() -> None:
    db = SessionLocal()
    try:
        for code, description in PERMISSIONS:
            if not db.query(Permission).filter(Permission.code == code).first():
                db.add(Permission(code=code, description=description))
        db.commit()

        for role_code in RoleCode:
            role = db.query(Role).filter(Role.code == role_code.value).one_or_none()
            if role is None:
                role = Role(code=role_code.value, name=ROLE_LABELS[role_code])
                db.add(role)
                db.flush()
            wanted_perm_codes = ROLE_PERMISSIONS.get(role_code, [])
            perms = db.query(Permission).filter(Permission.code.in_(wanted_perm_codes)).all()
            role.permissions = perms
        db.commit()

        for profile_data in APPLICATION_PROFILES:
            application = db.query(Application).filter(Application.code == profile_data["code"]).one_or_none()
            if application is None:
                application = Application(code=profile_data["code"], name=profile_data["name"])
                db.add(application)
                db.flush()

            profile = db.query(ApplicationProfile).filter(
                ApplicationProfile.application_id == application.id
            ).one_or_none()
            if profile is None:
                profile = ApplicationProfile(application_id=application.id)
                db.add(profile)

            profile.expected_evidence_type = profile_data["expected_evidence_type"]
            profile.success_keywords = profile_data["success_keywords"]
            profile.error_keywords = profile_data["error_keywords"]
            profile.logo_keywords = profile_data["logo_keywords"]
            profile.primary_color_hint = profile_data["primary_color_hint"]
            profile.screen_zones = profile_data["screen_zones"]

        db.commit()
        print("Seed de configuration termine : roles, permissions et 4 profils d'application reels.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
