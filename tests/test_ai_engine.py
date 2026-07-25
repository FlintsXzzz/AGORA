from agora_main import normalize_numeric_token, fallback_parse_items


def test_normalize_numeric_token_simple():
    assert normalize_numeric_token("Rp 12.345") == 12345.0
    assert normalize_numeric_token("1.234,56") == 1234.56
    assert normalize_numeric_token("no-number") is None


def test_fallback_parse_items_basic():
    payload = {"raw_text": "Nasi Goreng 2 15000\nTeh Botol 1 5000\nTotal 35000"}
    items = fallback_parse_items(payload)
    assert isinstance(items, list)
    assert any('nasi goreng' in it['item'].lower() for it in items)


# Basic smoke test for empty payload
def test_fallback_parse_items_empty():
    assert fallback_parse_items({}) == []
