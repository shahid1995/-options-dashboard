from app.services import token_store


def test_get_token_returns_none_initially():
    assert token_store.get_token("any-session") is None


def test_set_token_stores_value_bound_to_session():
    session_id = token_store.set_token("abc123")
    assert token_store.get_token(session_id) == "abc123"


def test_get_token_rejects_wrong_session():
    token_store.set_token("abc123")
    assert token_store.get_token("wrong-session") is None


def test_get_token_rejects_missing_session():
    token_store.set_token("abc123")
    assert token_store.get_token(None) is None


def test_set_token_overwrites_previous_value_and_rotates_session():
    first_session = token_store.set_token("first")
    second_session = token_store.set_token("second")
    assert token_store.get_token(second_session) == "second"
    assert token_store.get_token(first_session) is None


def test_clear_token_removes_value():
    session_id = token_store.set_token("abc123")
    token_store.clear_token()
    assert token_store.get_token(session_id) is None


def test_clear_token_when_already_empty():
    token_store.clear_token()
    assert token_store.get_token(None) is None


def test_oauth_state_consumed_once():
    state = token_store.create_oauth_state()
    assert token_store.consume_oauth_state(state) is True
    assert token_store.consume_oauth_state(state) is False


def test_oauth_state_rejects_unknown_or_missing():
    assert token_store.consume_oauth_state("forged") is False
    assert token_store.consume_oauth_state(None) is False
