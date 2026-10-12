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
            "browser_calling": "Browser calling could not be opened.",
            "automated_threaded_email": "Automated email could not be handed to Pramaan.",
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

    def __init__(self, code="unavailable", *, uncertain=False, job_id=None):
        self.code = code
        self.uncertain = uncertain
        self.job_id = job_id
        super().__init__(
            "The action may already have completed. Check its status before trying again."
            if uncertain else "Pramaan could not complete this request."
        )


MISSING_KEY_MESSAGE = "This needs a Pramaan key. Ask your administrator to set PRAMAAN_API_KEY."


class MissingPramaanKey(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("missing_api_key")
        self.args = (MISSING_KEY_MESSAGE,)


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
        "voice.call.recording.get", "voice.call.end",
        "voice.browser-session.create", "voice.browser-session.refresh",
        "voice.browser-session.close", "voice.browser-session.events",
        "voice.browser-call.start", "voice.browser-call.accept", "voice.browser-call.reject",
        "auth.social.exchange",
    })
    ACTIONS = frozenset({
        "email.send", "email.message.send", "email.message.reply", "email.inbox.create",
        "email.account.connect.start", "email.domain.verify", "voice.call.start-configured",
        "voice.call.end",
        "voice.browser-session.create", "voice.browser-session.refresh",
        "voice.browser-session.close", "voice.browser-call.start",
        "voice.browser-call.accept", "voice.browser-call.reject",
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

    @property
    def configured(self):
        return bool(self._api_key.strip())

    def require_configured(self):
        if not self.configured:
            raise MissingPramaanKey()

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
            # Read only bounded, recognized error codes; never surface the upstream body.
            try:
                payload = json.loads(error.read(16_001))
                code = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(code, dict):
                    code = code.get("code")
                if not code and isinstance(payload, dict):
                    code = payload.get("code")
            except (ValueError, OSError):
                code = None
            return error.code, {"error": code if code in {"upstream_unavailable"} else None}
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, approved_by=None, account=None, plan=None, outcome=False):
        self.require_configured()
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if approved_by:
            headers["Pramaan-Approved-By"] = approved_by
        if account:
            headers["Pramaan-Account"] = account
        if plan:
            headers["Pramaan-Plan"] = plan
        try:
            status, result = self._transport(method, self._base_url + path, headers, body)
        except PramaanError:
            raise
        except Exception:
            raise PramaanError("unavailable", uncertain=method == "POST") from None
        if status >= 400:
            code = "request_rejected"
            uncertain = method == "POST" and status >= 500
            if outcome:
                code = {403: "approval_required", 409: "plan_changed", 429: "try_later"}.get(status, code)
                remote_code = result.get("error") if isinstance(result, dict) else None
                if isinstance(remote_code, dict):
                    remote_code = remote_code.get("code")
                if status == 502 and remote_code == "upstream_unavailable":
                    code, uncertain = "upstream_unavailable", False
            raise PramaanError(code, uncertain=uncertain)
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


    def outcomes_list(self):
        """List the platform's outcome descriptions without running anything."""
        _, result = self._request("GET", "/v1/outcomes", outcome=True)
        return result

    def outcome_get(self, outcome_id):
        _, result = self._request("GET", "/v1/outcomes/" + quote(outcome_id, safe=""), outcome=True)
        return result

    def outcome_estimate(self, outcome_id, body):
        """Return steps, worst-case cost and plan for the exact run body; no charge."""
        _, result = self._request("POST", "/v1/outcomes/" + quote(outcome_id, safe="") + "/estimate",
                                  body, outcome=True)
        return result

    def outcome_run(self, outcome_id, body, *, plan=None, idempotency_key=None,
                    approved_by=None, max_polls=60):
        """Run an explicitly reviewed body once, preserving the complete run report.

        Pass the estimate's plan only after human approval. A stale or changed plan
        requires another estimate and approval; neither requests nor failed runs
        are retried here. No account, end-user or max-price headers are accepted.
        """
        description = self.outcome_get(outcome_id)
        if description.get("available") is False:
            raise PramaanError("upstream_unavailable")
        if description.get("available") is not True:
            raise PramaanError("invalid_response")
        if description.get("requires_approval") and not plan:
            raise PramaanError("approval_required")
        if description.get("effect_class") != "read_only" and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        status, result = self._request("POST", "/v1/outcomes/" + quote(outcome_id, safe=""), body,
                                       plan=plan, idempotency_key=idempotency_key,
                                       approved_by=approved_by, outcome=True)
        if status == 202:
            job_id = result.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise PramaanError("invalid_response", uncertain=True)
            for poll in range(max_polls + 1):
                state = result.get("status")
                if state in {"done", "failed", "cancelled"}:
                    report = result.get("result")
                    if not isinstance(report, dict):
                        raise PramaanError("invalid_response", uncertain=True)
                    return self._outcome_report(report)
                if state not in {"running", "queued"}:
                    raise PramaanError("invalid_response", uncertain=True)
                if poll == max_polls:
                    break
                self._sleep(2)
                try:
                    result = self.job(job_id)
                except PramaanError:
                    # The accepted run may still be acting; never start another.
                    raise PramaanError("job_pending", uncertain=True, job_id=job_id) from None
            raise PramaanError("job_pending", uncertain=True, job_id=job_id)
        return self._outcome_report(result)

    @staticmethod
    def _outcome_report(report):
        if report.get("status") not in {"done", "failed", "declined"}:
            raise PramaanError("invalid_response", uncertain=True)
        # Failed reports may contain completed or unknown effects. Return them
        # intact for review; they must not be mistaken for fallback permission.
        return report


    # Feature contracts delivered on the platform catalogue; each stays false
    # until its own integration and fake checks are in place.
    FEATURES = {
        "browser_calling": True,
        "automated_threaded_email": True,
        "social_sign_in": True,
    }

    def availability(self) -> tuple[FeatureAvailability, ...]:
        return tuple(
            FeatureAvailability(feature, enabled, "" if enabled else str(CapabilityUnavailable(feature)))
            for feature, enabled in self.FEATURES.items()
        )

    def exchange_social_sign_in(
        self,
        *,
        provider_key: str,
        code: str,
        redirect_uri: str,
        pkce_verifier: str | None = None,
        expected_nonce: str | None = None,
        account: str | None = None,
    ) -> dict:
        """Redeem a single-use sign-in code for verified identity claims.

        Upstream credentials never pass through here: the platform returns
        claims only, and the application keeps no authorization secrets.
        """
        inputs = {"providerKey": provider_key, "code": code, "redirectUri": redirect_uri}
        if pkce_verifier:
            inputs["pkceVerifier"] = pkce_verifier
        if expected_nonce:
            inputs["expectedNonce"] = expected_nonce
        _, result = self._request("POST", "/v1/capabilities/auth.social.exchange",
                                  inputs, account=account)
        if not isinstance(result.get("subjectId"), str) or not result.get("subjectId"):
            raise PramaanError("invalid_response")
        claims = {
            "provider_key": result.get("providerKey", provider_key),
            "subject_id": result["subjectId"],
            "email": result.get("email") or "",
            "email_verified": result.get("emailVerified") is True,
            "display_name": result.get("displayName") or "",
        }
        if not claims["email"] or not claims["email_verified"]:
            raise PramaanError("identity_unverified")
        return claims

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
