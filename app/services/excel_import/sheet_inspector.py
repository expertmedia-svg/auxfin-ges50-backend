"""Detection des feuilles, previsualisation et suggestion de mapping de
colonnes pour les exports dashboard (xlsx/xls/csv) — section 7."""

from __future__ import annotations

import unicodedata

import pandas as pd
from rapidfuzz import fuzz

# Champs cibles du systeme -> alias frequemment rencontres dans les exports
# (accents/majuscules ignores lors de la comparaison).
FIELD_ALIASES: dict[str, list[str]] = {
    "group_id": [
        "gr plateforme", "id", "id groupe", "groupe", "group id", "group",
        "identifiant", "identifiant groupe", "code groupe",
    ],
    "declared_group_id": ["gr declares", "gr declare", "declared group", "groupe declare"],
    "sync_date": [
        "date synchro", "date synchronisation", "date de synchronisation",
        "date de derniere synchronisation", "derniere synchronisation", "sync date",
    ],
    "application": ["application", "app", "ecoach", "outil"],
    "agent": ["agent", "agent name", "nom agent", "superviseur"],
    "locality": ["localite", "locality", "zone", "commune", "village", "region"],
    "status": ["statut", "status", "etat"],
}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def list_sheets(file_path: str) -> list[str]:
    if file_path.lower().endswith(".csv"):
        return ["CSV"]
    with pd.ExcelFile(file_path) as xls:
        return xls.sheet_names


def read_sheet(file_path: str, sheet_name: str | None) -> pd.DataFrame:
    if file_path.lower().endswith(".csv"):
        return pd.read_csv(file_path, dtype=str, keep_default_na=False)
    return pd.read_excel(file_path, sheet_name=sheet_name, dtype=str, keep_default_na=False)


def preview_sheet(file_path: str, sheet_name: str | None, max_rows: int = 20) -> dict:
    df = read_sheet(file_path, sheet_name)
    columns = [str(c) for c in df.columns]
    rows = df.head(max_rows).to_dict(orient="records")
    return {"columns": columns, "rows": rows, "total_rows": len(df)}


def suggest_column_mapping(columns: list[str]) -> dict[str, str | None]:
    folded_columns = {c: _fold(c) for c in columns}
    mapping: dict[str, str | None] = {}

    for field, aliases in FIELD_ALIASES.items():
        best_column: str | None = None
        best_score = 0.0
        for column, folded in folded_columns.items():
            for alias in aliases:
                score = fuzz.ratio(folded, alias) if folded == alias else fuzz.partial_ratio(folded, alias)
                if folded == alias:
                    score = 100.0
                if score > best_score:
                    best_score = score
                    best_column = column
        mapping[field] = best_column if best_score >= 80 else None

    return mapping
