from app.services import token_store


def test_get_token_returns_none_initially():
    assert token_store.get_token() is None


def test_set_token_stores_value():
    token_store.set_token("abc123")
    assert token_store.get_token() == "abc123"


def test_set_token_overwrites_previous_value():
    token_store.set_token("first")
    token_store.set_token("second")
    assert token_store.get_token() == "second"


def test_clear_token_removes_value():
    token_store.set_token("abc123")
    token_store.clear_token()
    assert token_store.get_token() is None


def test_clear_token_when_already_empty():
    token_store.clear_token()
    assert token_store.get_token() is None
