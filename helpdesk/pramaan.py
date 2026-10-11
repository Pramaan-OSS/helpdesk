"""All outside service calls go through this server-side module."""

from dataclasses import dataclass
from typing import Literal
import json
import os
import time
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


Feature = Literal["browser_calling", "automated_threaded_email", "social_sign_in"]


class CapabilityUnavailable(RuntimeError):
    """A stable application error safe to show without request data or secrets."""

    code = "capability_unavailable"

    def __init__(self, feature: Feature):
        self.feature = feature
        messages = {
            "browser_calling": "Browser calling is not available yet.",
            "automated_threaded_email": (
                "Automated or edited threaded email is not available yet."
            ),
            "social_sign_in": "Social sign-in is not available yet. Use password sign-in.",
        }
        super().__init__(messages[feature])


@dataclass(frozen=True)
class FeatureAvailability:
    feature: Feature
    enabled: bool
    reason: str


class PramaanError(RuntimeError):
    """Normalized error: never expose an upstream body, provider or secret."""

    def __init__(self, code="unavailable", *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(
            "The action may already have completed. Check its status before trying again."
            if uncertain else "Pramaan could not complete this request."
        )


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PramaanClient:
    """Single server-side HTTP client. Mutating requests are never retried."""

    CAPABILITIES = frozenset({
        "email.send", "email.status", "email.message.send", "email.message.reply",
        "email.messages.list", "email.message.raw.get", "email.message.get",
        "email.inbox.create", "email.inbox.get", "email.inboxes.list",
        "email.account.connect.start", "email.account.connect.status", "email.accounts.list",
        "email.domain.verify", "companies.enrich", "people.enrich", "llm.complete",
        "web.read", "web.crawl", "document.parse", "audio.transcription.create",
        "voice.call.start-configured", "voice.call.get", "voice.calls.list",
        "voice.call.recording.get",
    })
    ACTIONS = frozenset({
        "email.send", "email.message.send", "email.message.reply", "email.inbox.create",
        "email.account.connect.start", "email.domain.verify", "voice.call.start-configured",
    })

    def __init__(self, *, api_key=None, base_url=None, transport=None, sleep=time.sleep):
        self._api_key = api_key if api_key is not None else os.environ.get("PRAMAAN_API_KEY", "")
        self._base_url = (base_url or os.environ.get("PRAMAAN_BASE_URL") or "https://api.pramaan.dev").rstrip("/")
        parsed = urlparse(self._base_url)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "fake-pramaan"}
        ):
            raise PramaanError("invalid_configuration")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise PramaanError("invalid_configuration")
        self._transport = transport or self._http
        self._sleep = sleep

    def _http(self, method, url, headers, body):
        request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        try:
            with build_opener(NoRedirects()).open(request, timeout=30) as response:
                raw = response.read(16_000_001)
                if len(raw) > 16_000_000:
                    raise PramaanError("invalid_response")
                return response.status, json.loads(raw)
        except HTTPError as error:
            # Errors may contain provider names or credentials: never surface their body.
            raise PramaanError("request_rejected", uncertain=method == "POST" and error.code >= 500) from None
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, approved_by=None):
        if not self._api_key:
            raise PramaanError("missing_api_key")
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if approved_by:
            headers["Pramaan-Approved-By"] = approved_by
        try:
            status, result = self._transport(method, self._base_url + path, headers, body)
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=method == "POST") from None
        if status not in {200, 201, 202} or not isinstance(result, dict):
            raise PramaanError("invalid_response", uncertain=method == "POST")
        return status, result

    def run(self, capability, inputs, *, idempotency_key=None, approved_by=None):
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in self.ACTIONS and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        status, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe=""), inputs,
                                     idempotency_key=idempotency_key, approved_by=approved_by)
        if status == 202:
            if not isinstance(result.get("job_id"), str) or result.get("status") not in {"running", "done", "failed", "cancelled"}:
                raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
        return result

    def job(self, job_id):
        _, result = self._request("GET", "/v1/jobs/" + quote(job_id, safe=""))
        return result

    def call(self, capability, inputs, *, idempotency_key=None, approved_by=None, max_polls=60):
        result = self.run(capability, inputs, idempotency_key=idempotency_key, approved_by=approved_by)
        if "job_id" not in result:
            return result
        job_id = result["job_id"]
        for _ in range(max_polls):
            state = result.get("status")
            if state == "done":
                completed = result.get("result")
                if not isinstance(completed, dict):
                    raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
                return completed
            if state in {"failed", "cancelled"}:
                raise PramaanError("job_failed", uncertain=capability in self.ACTIONS)
            if state != "running":
                raise PramaanError("invalid_response")
            self._sleep(2)
            result = self.job(job_id)
        raise PramaanError("job_pending", uncertain=capability in self.ACTIONS)


    def availability(self) -> tuple[FeatureAvailability, ...]:
        return tuple(
            FeatureAvailability(feature, False, str(CapabilityUnavailable(feature)))
            for feature in (
                "browser_calling",
                "automated_threaded_email",
                "social_sign_in",
            )
        )

    def start_browser_voice_session(
        self, *, agent_ref: str, number_ref: str, origin: str
    ) -> None:
        """G1: no browser session contract exists; never mint a vendor token."""
        raise CapabilityUnavailable("browser_calling")

    def send_automated_or_edited_threaded_email(
        self,
        *,
        inbox: str,
        recipients: tuple[str, ...],
        subject: str,
        text: str,
        parent_message_id: str | None = None,
        automated: bool = False,
    ) -> None:
        """G2: do not silently drop threading or loop-prevention requirements.

        Ordinary supported mail uses the supported capability transport. This stub only represents the currently unsupported behavior.
        """
        raise CapabilityUnavailable("automated_threaded_email")

    def exchange_social_sign_in(
        self,
        *,
        connection_ref: str,
        authorization_code: str,
        redirect_uri: str,
        pkce_verifier: str,
        state: str,
    ) -> None:
        """G3: never manufacture an identity or log authorization secrets."""
        raise CapabilityUnavailable("social_sign_in")

    def recording_bytes(self, hosted_file):
        """Read only a platform-returned owned audio file; never forward API keys."""
        import ipaddress
        import socket
        url = hosted_file.get("url", "")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.fragment or hosted_file.get("contentType") not in {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"}
                or not 0 < hosted_file.get("sizeBytes", 0) <= 10_000_000):
            raise PramaanError("invalid_recording")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise PramaanError("invalid_recording")
            with build_opener(NoRedirects()).open(Request(url), timeout=30) as response:
                content = response.read(10_000_001)
            if len(content) > 10_000_000 or len(content) != hosted_file["sizeBytes"]:
                raise PramaanError("invalid_recording")
            return content
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("recording_unavailable") from None
