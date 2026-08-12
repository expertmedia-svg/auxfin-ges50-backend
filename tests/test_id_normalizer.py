from app.services.vision.id_normalizer import find_id_candidates, normalize_group_id


def test_normalizes_clean_id():
    result = normalize_group_id("gr1.loumbila-nonguestenga")
    assert result.normalized == "gr1.loumbila-nonguestenga"
    assert result.is_valid_format
    assert not result.requires_manual_review


def test_normalizes_uppercase_and_spaces():
    result = normalize_group_id("GR1.LOUMBILA NONGUESTENGA")
    assert result.normalized == "gr1.loumbila-nonguestenga"


def test_normalizes_dot_with_spaces_around():
    result = normalize_group_id("gr1 . loumbila-nonguestenga")
    assert result.normalized == "gr1.loumbila-nonguestenga"


def test_normalizes_unicode_dash():
    result = normalize_group_id("gr1.loumbila–nonguestenga")
    assert result.normalized == "gr1.loumbila-nonguestenga"


def test_normalizes_underscore_separator():
    result = normalize_group_id("gr1.loumbila_nonguestenga")
    assert result.normalized == "gr1.loumbila-nonguestenga"


def test_fixes_digit_confusion_after_gr():
    # "O" confondu avec "0" par l'OCR dans le segment numerique
    result = normalize_group_id("grO.loumbila-nonguestenga")
    assert result.normalized == "gr0.loumbila-nonguestenga"
    assert result.corrections


def test_empty_input_is_invalid():
    result = normalize_group_id("")
    assert result.normalized is None
    assert not result.is_valid_format


def test_fuzzy_match_against_known_ids():
    known = ["gr1.kar-sam-samatoukoro", "gr2.karangasso-sambla-sembleni"]
    # Faute de frappe OCR plausible sur un caractere
    result = normalize_group_id("gr1.kar-sam-samatoukorp", known_ids=known)
    assert result.fuzzy_match == "gr1.kar-sam-samatoukoro"


def test_ambiguous_fuzzy_matches_require_manual_review():
    known = ["gr1.kar-sam-toukoro", "gr1.kar-sam-toukorx"]
    # "toukors" n'est une correspondance exacte d'aucun des deux IDs connus,
    # et se trouve a egale distance des deux (94.7% chacun).
    result = normalize_group_id("gr1.kar-sam-toukors", known_ids=known)
    # Deux candidats tres proches : jamais de choix automatique.
    assert result.requires_manual_review


def test_find_id_candidates_in_noisy_text():
    text = "07-54  Jeudi 30, Juillet\ngr1.kar-sam-samatoukoro \nFR\nHnanceCoach"
    candidates = find_id_candidates(text)
    assert any("gr1" in c.lower() for c in candidates)
