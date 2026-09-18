"""Focused provider tests for the Brevo email adapter (Issue #65).

Only the HTTP boundary (httpx.AsyncClient) is mocked — no real Brevo network
call is ever performed. Asserts the exact Brevo wire contract (api-key header,
sender object, recipient list, htmlContent/textContent), provider selection
semantics (explicit, default in-memory, fail-closed on missing key), and the
security properties (no key/token/URL leakage, no content persistence for the
production path).
"""

import json

import httpx
import pytest

from app.config import settings
from app.services import email as email_mod
from app.services.email import (
    BrevoEmailSender,
    InMemoryEmailSender,
    _split_email_address,
    clear_sent_messages,
    get_email_sender,
    get_sent_messages,
    reset_email_sender,
    send_email,
)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


# ---------------------------------------------------------------------------
# HTTP-boundary mock
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code=201):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"error {self.status_code}", request=None, response=None
            )


class CaptureClient:
    """httpx.AsyncClient stand-in: records the request, returns canned replies."""

    last_request = None
    next_response = FakeResponse(201)
    next_exception = None

    def __init__(self, **kwargs):
        CaptureClient.last_request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers=None, json=None):
        CaptureClient.last_request = {"url": url, "headers": headers, "json": json}
        if CaptureClient.next_exception is not None:
            raise CaptureClient.next_exception
        return CaptureClient.next_response


@pytest.fixture
def capture(monkeypatch):
    """Patch the HTTP boundary; returns a handle for assertions."""
    CaptureClient.last_request = None
    CaptureClient.next_response = FakeResponse(201)
    CaptureClient.next_exception = None
    monkeypatch.setattr(httpx, "AsyncClient", CaptureClient)
    return CaptureClient


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "inmemory", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_URL", BREVO_URL, raising=False)
    monkeypatch.setattr(settings, "EMAIL_FROM_ADDRESS", "StrikeNova <no-reply@strikenova.local>", raising=False)
    reset_email_sender()
    yield
    reset_email_sender()


@pytest.fixture(autouse=True)
def _clear_capture():
    clear_sent_messages()
    yield
    clear_sent_messages()


@pytest.fixture
def brevo_sender():
    return BrevoEmailSender(
        api_url=BREVO_URL, api_key="sk_test_key_value", from_address="StrikeNova <no-reply@strikenova.local>"
    )


# ---------------------------------------------------------------------------
# Wire contract
# ---------------------------------------------------------------------------


async def test_endpoint_selection(capture, brevo_sender):
    await brevo_sender.send(to="u@example.com", subject="s", html="<b>h</b>", text="t")
    assert capture.last_request["url"] == BREVO_URL


async def test_api_key_header_not_bearer(capture, brevo_sender):
    await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    headers = capture.last_request["headers"]
    assert headers["api-key"] == "sk_test_key_value"
    assert "Authorization" not in headers
    assert not any("Bearer" in str(v) for v in headers.values())


async def test_sender_structure_name_and_email(capture, brevo_sender):
    await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert capture.last_request["json"]["sender"] == {
        "name": "StrikeNova",
        "email": "no-reply@strikenova.local",
    }


async def test_recipient_structure(capture, brevo_sender):
    await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert capture.last_request["json"]["to"] == [{"email": "u@example.com"}]


async def test_subject_html_content_text_content(capture, brevo_sender):
    await brevo_sender.send(to="u@example.com", subject="Verify", html="<p>hi</p>", text="hi")
    body = capture.last_request["json"]
    assert body["subject"] == "Verify"
    assert body["htmlContent"] == "<p>hi</p>"
    assert body["textContent"] == "hi"


async def test_successful_response_sends_cleanly(capture, brevo_sender):
    capture.next_response = FakeResponse(201)
    await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")  # no exception


async def test_non_2xx_response_raises(capture, brevo_sender):
    capture.next_response = FakeResponse(401)
    with pytest.raises(httpx.HTTPStatusError):
        await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")


async def test_timeout_and_network_failure_propagate(capture, brevo_sender):
    capture.next_exception = httpx.TimeoutException("timed out")
    with pytest.raises(httpx.TimeoutException):
        await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    capture.next_exception = httpx.ConnectError("no route to host")
    with pytest.raises(httpx.ConnectError):
        await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")


def test_from_address_parsing():
    assert _split_email_address("StrikeNova <no-reply@strikenova.local>") == (
        "StrikeNova",
        "no-reply@strikenova.local",
    )
    assert _split_email_address("no-reply@strikenova.local") == (
        "no-reply@strikenova.local",
        "no-reply@strikenova.local",
    )


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------


def test_default_provider_is_inmemory():
    assert isinstance(get_email_sender(), InMemoryEmailSender)


def test_explicit_brevo_selection_builds_brevo_sender(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "sk_test_key_value", raising=False)
    sender = get_email_sender()
    assert isinstance(sender, BrevoEmailSender)


def test_brevo_without_api_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "", raising=False)
    with pytest.raises(RuntimeError) as exc:
        get_email_sender()
    # The message must not echo any secret and must not promise a fallback.
    assert "sk_" not in str(exc.value)
    assert "BREVO_API_KEY" in str(exc.value)


def test_unknown_provider_rejected(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "sendgrid", raising=False)
    with pytest.raises(ValueError):
        get_email_sender()


def test_unknown_provider_never_falls_through_to_http_sender(monkeypatch):
    """Regression (Issue #65 review fix): an unknown EMAIL_PROVIDER value plus
    a populated EMAIL_API_URL must raise ValueError — it must NEVER silently
    instantiate HttpEmailSender via a legacy implicit fallback."""
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "unknown-provider", raising=False)
    monkeypatch.setattr(settings, "EMAIL_API_URL", "https://legacy.example/send", raising=False)
    monkeypatch.setattr(settings, "EMAIL_API_KEY", "legacy-key", raising=False)
    try:
        get_email_sender()
    except ValueError as exc:
        # Error text must name the offending value, not leak any key.
        assert "unknown-provider" in str(exc)
        assert "legacy-key" not in str(exc)
    else:
        pytest.fail("ValueError not raised for unknown EMAIL_PROVIDER with EMAIL_API_URL set")


def test_existing_api_key_alone_does_not_enable_brevo(monkeypatch):
    """A key sitting in config must not silently switch the provider on."""
    monkeypatch.setattr(settings, "BREVO_API_KEY", "sk_test_key_value", raising=False)
    assert isinstance(get_email_sender(), InMemoryEmailSender)


# ---------------------------------------------------------------------------
# Security properties
# ---------------------------------------------------------------------------


async def test_api_key_not_exposed_in_error_paths(capture, brevo_sender, caplog):
    capture.next_response = FakeResponse(500)
    with pytest.raises(httpx.HTTPStatusError):
        await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert "sk_test_key_value" not in caplog.text


async def test_no_content_persistence_for_production_path(capture, monkeypatch):
    """send_email() must not mirror message contents when a real provider is active."""
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "brevo", raising=False)
    monkeypatch.setattr(settings, "BREVO_API_KEY", "sk_test_key_value", raising=False)
    reset_email_sender()

    await send_email(
        to="u@example.com",
        subject="Verify your email",
        html="<a href='https://app/verify?token=SUPERSECRET'>v</a>",
        text="https://app/verify?token=SUPERSECRET",
    )

    assert get_sent_messages() == []  # nothing persisted for the production path


async def test_inmemory_path_still_captures_for_tests():
    await send_email(to="u@example.com", subject="s", html="h", text="t")
    assert len(get_sent_messages()) == 1


async def test_brevo_does_not_leak_key_in_logs_on_success(capture, brevo_sender, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        await brevo_sender.send(to="u@example.com", subject="s", html="h", text="t")
    assert "sk_test_key_value" not in caplog.text


def test_database_never_receives_brevo_data(brevo_sender):
    """Brevo sends must not write anything to the application database.

    Structural guarantee: the adapter has no database/session parameter, and
    the module holds no DB session — content persistence is impossible by
    construction (see also test_no_content_persistence_for_production_path).
    """
    import inspect

    sig = inspect.signature(BrevoEmailSender.send)
    assert "db" not in sig.parameters
    assert "session" not in sig.parameters
    assert not hasattr(brevo_sender, "_db")
    assert not hasattr(brevo_sender, "_session")
