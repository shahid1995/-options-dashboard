"""Provider-neutral transactional email transport (2026-09-16 plan Task 3).

StrikeNova owns all verification/reset semantics and token handling; this
module is ONLY the delivery transport. Authentication flows depend on the
:class:`EmailSender` protocol — never on a vendor SDK.

Senders
-------
- :class:`InMemoryEmailSender` — deterministic test/development capture sink
  (the default). Tests read captured messages via :func:`get_sent_messages`
  / :func:`clear_sent_messages`.
- :class:`HttpEmailSender` — generic HTTP JSON transport for a configured
  production provider (Bearer-style). Provider credentials live ONLY in
  backend environment configuration; they never reach the frontend, logs,
  or security events.
- :class:`BrevoEmailSender` — Brevo REST adapter (``api-key`` header,
  Brevo ``smtp/email`` payload shape). Selected explicitly via
  ``EMAIL_PROVIDER=brevo``.

Provider selection is explicit (``EMAIL_PROVIDER=inmemory|brevo``; default
``inmemory``). A configured-but-missing provider API key fails fast — there
is never a silent fallback from a selected provider to the test sink. No
email credentials, tokens, or message contents are ever logged or persisted
by this module; the deterministic capture mirror exists ONLY for the
in-memory sender (tests), never for a production provider.
"""

from __future__ import annotations

import contextvars
import logging
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
    """Return the sender selected by ``EMAIL_PROVIDER`` — strictly fail-closed.

    ``inmemory`` (default)  → deterministic test sink, never network.
    ``brevo``               → :class:`BrevoEmailSender` (requires
                              ``BREVO_API_KEY``; fails fast when missing —
                              never silently falls back to the test sink).
    ANY OTHER VALUE         → ValueError. Unknown/typo'd provider values can
                              never select a sender — there is no implicit
                              ``EMAIL_API_URL``-keyed fallback (review fix,
                              Issue #65).

    :class:`HttpEmailSender` is retained as a reusable generic transport for
    explicit, intentional callers (and future explicitly-registered
    providers); the factory itself never selects it implicitly.

    Replacing this factory with a Redis/queue-backed or vendor-backed
    transport never changes endpoint contracts.
    """
    global _sender
    if _sender is None:
        provider = (settings.EMAIL_PROVIDER or "inmemory").strip().lower()
        if provider == "inmemory":
            _sender = InMemoryEmailSender()
        elif provider == "brevo":
            if not settings.BREVO_API_KEY:
                # Fail clearly. A selected provider must never silently
                # degrade to the in-memory sink, and the message must not
                # echo any configured secret.
                raise RuntimeError(
                    "EMAIL_PROVIDER=brevo requires BREVO_API_KEY to be "
                    "configured in backend environment settings."
                )
            _sender = BrevoEmailSender(
                api_url=settings.BREVO_API_URL,
                api_key=settings.BREVO_API_KEY,
                from_address=settings.EMAIL_FROM_ADDRESS,
            )
        else:
            # Strictly fail-closed: unknown values raise regardless of any
            # other configuration (e.g. a populated EMAIL_API_URL must NOT
            # select a sender implicitly).
            raise ValueError(
                f"Unsupported EMAIL_PROVIDER {provider!r}. "
                "Use 'inmemory' or 'brevo'."
            )
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
    """Send through the configured transport.

    The deterministic capture mirror runs ONLY when the configured sender is
    the in-memory test sink. A production provider (e.g. Brevo) must not
    persist message contents (which contain verification/reset links) into
    application memory or the database (Issue #65).
    """
    sender = get_email_sender()
    await sender.send(to=to, subject=subject, html=html, text=text)
    if isinstance(sender, InMemoryEmailSender):
        # Mirror into the deterministic capture so tests can assert on
        # delivery. Holds nothing the caller did not already have in scope.
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


logger = logging.getLogger(__name__)


def _split_email_address(address: str) -> tuple[str, str]:
    """Split ``'Name <addr>'`` / ``'addr'`` into ``(name, email)``.

    A missing display name falls back to the bare address.
    """
    if "<" in address and address.endswith(">"):
        name, _, email = address[:-1].partition("<")
        return name.strip() or email.strip(), email.strip()
    return address, address


class BrevoEmailSender:
    """Brevo transactional-email REST adapter (Issue #65).

    Satisfies the provider-neutral :class:`EmailSender` contract so
    authentication/account-security flows remain completely unaware of
    Brevo — no vendor SDK is imported anywhere in the auth flow.

    Brevo API specifics (https://developers.brevo.com/docs/send-a-transactional-email):
    - endpoint ``https://api.brevo.com/v3/smtp/email``;
    - authentication header ``api-key`` (NOT ``Authorization: Bearer``);
    - ``sender`` as ``{"name", "email"}``, recipients as ``[{"email"}]``;
    - content fields ``htmlContent`` / ``textContent``.

    Security: the API key is held only in this instance and used only in
    the ``api-key`` header; it is never logged, never included in raised
    errors, and never persisted. Message contents (which contain
    verification/reset links) are not logged or persisted either.
    """

    def __init__(self, *, api_url: str, api_key: str, from_address: str) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._from_address = from_address

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        import httpx  # deferred: keeps the test path dependency-free

        sender_name, sender_email = _split_email_address(self._from_address)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self._api_url,
                    headers={
                        "api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "sender": {"name": sender_name, "email": sender_email},
                        "to": [{"email": to}],
                        "subject": subject,
                        "htmlContent": html,
                        "textContent": text,
                    },
                )
                resp.raise_for_status()
        except Exception:
            # Never leak the API key, request body, or message contents
            # through logs or exception text.
            logger.error(
                "Brevo email delivery failed (recipient=%s, subject=%s)",
                to,
                subject,
            )
            raise
