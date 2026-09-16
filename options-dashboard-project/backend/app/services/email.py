"""Provider-neutral transactional email transport (2026-09-16 plan Task 3).

StrikeNova owns all verification/reset semantics and token handling; this
module is ONLY the delivery transport. Authentication flows depend on the
:class:`EmailSender` protocol — never on a vendor SDK.

Senders
-------
- :class:`InMemoryEmailSender` — deterministic test/development capture sink
  (the default when no provider is configured). Tests read captured messages
  via :func:`get_sent_messages` / :func:`clear_sent_messages`.
- :class:`HttpEmailSender` — generic HTTP JSON transport for a configured
  production provider. Provider credentials live ONLY in backend environment
  configuration (``settings.EMAIL_API_KEY``); they never reach the frontend,
  logs, or security events.

No email credentials are ever logged or persisted here.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import settings


@dataclass
class SentMessage:
    """One captured/sent email. ``raw_token`` is test-sender metadata only so
    tests can exercise token lifecycles; it is NEVER persisted or logged."""

    to: str
    subject: str
    html: str
    text: str
    raw_token: str | None = None


@runtime_checkable
class EmailSender(Protocol):
    """Provider-neutral email transport interface (design spec §8)."""

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None: ...


# ---------------------------------------------------------------------------
# Deterministic in-memory sender (test/development default)
# ---------------------------------------------------------------------------


class InMemoryEmailSender:
    """Deterministic capture sink. Tests do not need a real email provider."""

    def __init__(self) -> None:
        self.messages: list[SentMessage] = []

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.messages.append(
            SentMessage(to=to, subject=subject, html=html, text=text)
        )


_sender: EmailSender | None = None
# Module-level capture for tests using the default sender.
_sent_store: list[SentMessage] = []


def get_email_sender() -> EmailSender:
    """Return the configured sender.

    A provider is used only when ``EMAIL_API_URL`` is configured; otherwise
    the deterministic in-memory sink is returned. Replacing this factory with
    a Redis/queue-backed or vendor-backed transport never changes endpoint
    contracts.
    """
    global _sender
    if _sender is None:
        if settings.EMAIL_API_URL:
            _sender = HttpEmailSender(
                api_url=settings.EMAIL_API_URL,
                api_key=settings.EMAIL_API_KEY,
                from_address=settings.EMAIL_FROM_ADDRESS,
            )
        else:
            _sender = InMemoryEmailSender()
    return _sender


def reset_email_sender() -> None:
    """Forget the cached sender (used by configuration changes and tests)."""
    global _sender
    _sender = None


# Context-local test metadata attached to the next mirrored SentMessage. This
# lets the deterministic test path observe lifecycle details (e.g. the raw
# token inside the emailed link) without adding them to the transport
# interface. Production transports ignore it entirely.
_test_metadata: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "email_test_metadata", default=None
)


def set_test_metadata(metadata: dict | None) -> None:
    """Attach context-local metadata captured by the test sink (tests only)."""
    _test_metadata.set(metadata)


async def send_email(*, to: str, subject: str, html: str, text: str) -> None:
    """Send through the configured transport."""
    sender = get_email_sender()
    await sender.send(to=to, subject=subject, html=html, text=text)
    # Mirror into the deterministic capture so tests can assert on delivery
    # regardless of which transport is configured (tests always run with the
    # in-memory sink). Holds nothing the caller did not already have in scope.
    _sent_store.append(
        SentMessage(
            to=to,
            subject=subject,
            html=html,
            text=text,
            raw_token=(_test_metadata.get() or {}).get("raw_token"),
        )
    )


def get_sent_messages() -> list[SentMessage]:
    """Captured messages for the deterministic test sender."""
    return _sent_store


def clear_sent_messages() -> None:
    _sent_store.clear()


class HttpEmailSender:
    """Generic HTTP JSON transport for a configured transactional provider.

    Deliberately vendor-neutral: the endpoint, key and payload shape are
    configuration, not code. Failures raise so the caller can decide retry
    policy; credentials are used only in the Authorization header here and
    are never logged.
    """

    def __init__(self, *, api_url: str, api_key: str, from_address: str) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._from_address = from_address

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        import httpx  # deferred: keeps the test path dependency-free

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": self._from_address,
                    "to": to,
                    "subject": subject,
                    "html": html,
                    "text": text,
                },
            )
            resp.raise_for_status()
