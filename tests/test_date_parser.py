from datetime import date

from app.services.vision.date_parser import parse_date


def test_parses_iso_date():
    result = parse_date("Synchronise le 2026-07-30 a 10h")
    assert result.normalized_date == "2026-07-30"
    assert not result.missing_year


def test_parses_slash_date():
    result = parse_date("30/07/2026")
    assert result.normalized_date == "2026-07-30"


def test_parses_french_full_date():
    result = parse_date("30 juillet 2026")
    assert result.normalized_date == "2026-07-30"


def test_parses_english_date():
    result = parse_date("Thursday 30 July 2026")
    assert result.normalized_date == "2026-07-30"


def test_missing_year_without_context_stays_unconfirmed():
    result = parse_date("Jeudi 30, Juillet")
    assert result.normalized_date is None
    assert result.missing_year
    assert result.is_ambiguous


def test_missing_year_with_context_is_deduced_but_flagged_ambiguous():
    result = parse_date("Jeudi 30, Juillet", context_date=date(2026, 7, 30))
    assert result.normalized_date == "2026-07-30"
    assert result.is_ambiguous
    assert result.confidence < 0.9


def test_no_date_candidate_returns_none():
    result = parse_date("aucune date visible sur cet ecran")
    assert result.normalized_date is None
    assert result.confidence == 0.0
