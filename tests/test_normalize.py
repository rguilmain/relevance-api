from app.normalize import normalize_query


def test_trims_leading_and_trailing_whitespace():
    assert normalize_query("  red shoes  ") == "red shoes"


def test_collapses_internal_whitespace():
    assert normalize_query("red    shoes") == "red shoes"


def test_lowercases_mixed_case():
    assert normalize_query("Red SHOE") == "red shoe"


def test_handles_tabs_and_newlines():
    assert normalize_query("\tRed\n  Shoes\r\n") == "red shoes"


def test_whitespace_only_is_empty():
    assert normalize_query("   ") == ""
    assert normalize_query("\t\n ") == ""
    assert normalize_query("") == ""


def test_is_idempotent():
    once = normalize_query("  Red   SHOE ")
    assert normalize_query(once) == once == "red shoe"


def test_different_spellings_match():
    assert normalize_query("  Red   SHOE ") == normalize_query("red shoe")
