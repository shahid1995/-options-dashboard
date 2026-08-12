# Very simple in-memory token storage for a single-user MVP.
#
# LIMITATION: if the server restarts, this token is lost and you'll need to
# log in again. Since Upstox tokens expire every day at 3:30 AM anyway,
# this is a fine trade-off for now. A future version can persist this
# to a database if multiple users need to log in.

_state = {"access_token": None}


def set_token(token: str) -> None:
    _state["access_token"] = token


def get_token() -> str | None:
    return _state["access_token"]


def clear_token() -> None:
    _state["access_token"] = None
