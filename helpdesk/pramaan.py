"""All outside service calls go through this server-side module."""

from dataclasses import dataclass
from typing import Literal
import json
import math
import copy
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
            "automated_threaded_email": "Automated email is not available yet.",
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


def email_is_trackable(capability, result=None, stored="Unknown"):
    """An explicit sending result overrides the older connected-mail default."""
    if isinstance(result, dict) and "trackable" in result:
        return result["trackable"] is True
    if stored in {"Enabled", "Disabled"}:
        return stored == "Enabled"
    return capability in {"email.message.send", "email.message.reply"}


MISSING_KEY_MESSAGE = "Add PRAMAAN_API_KEY to .env"


class MissingPramaanKey(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("missing_api_key")
        self.args = (MISSING_KEY_MESSAGE,)


class InvalidGenerationRequest(PramaanError):
    http_status_code = 422

    def __init__(self, label, path, reason):
        super().__init__("invalid_request")
        self.args = (f"{label} schema at {path}: {reason}",)


class IncompleteGeneration(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("incomplete_reply")
        self.args = ("The reply is incomplete because it reached the reply limit. Retry this step manually with a larger reply limit.",)


class GenerationConfigurationError(PramaanError):
    http_status_code = 422

    def __init__(self):
        super().__init__("reply_limit_configuration")
        self.args = ("The reply limit is too small to produce an answer. Ask your administrator to increase the reply limit before retrying.",)


def generation_result(capability, inputs, result):
    if capability in {"llm.chat", "llm.complete"} and result.get("finishReason") == "length":
        if inputs.get("jsonSchema") or inputs.get("tools") or result.get("toolCalls"):
            raise IncompleteGeneration()
    return result


class PramaanNotAvailable(PramaanError):
    http_status_code = 503

    def __init__(self, capability):
        super().__init__("not_available_yet")
        surface = "Calling" if capability.startswith("voice.") else (
            "Mailbox email" if capability.startswith("email.") else "Recording transcription")
        self.args = (f"{surface} is not available yet.",)


SCHEMA_KEYS = frozenset({"type", "properties", "required", "additionalProperties", "items",
    "enum", "const", "anyOf", "$defs", "$ref", "title", "description", "default", "examples",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems"})
SCHEMA_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
SCHEMA_BOUNDS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "minItems", "maxItems"})
UNAVAILABLE_CODES = frozenset({"upstream_unavailable", "not_available_yet", "not_available",
    "capability_unavailable", "not_implemented", "unsupported_capability"})


def _schema_path(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _schema_json(value, label, path="#", stack=None, depth=0):
    stack = set() if stack is None else stack
    if depth > 32:
        raise InvalidGenerationRequest(label, path, "JSON value is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if not isinstance(value, (dict, list)) or id(value) in stack:
        raise InvalidGenerationRequest(label, path, "must contain finite JSON values without cycles")
    stack.add(id(value))
    for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
        if not isinstance(key, (str, int)) or isinstance(value, dict) and not isinstance(key, str):
            raise InvalidGenerationRequest(label, path, "property names must be strings")
        _schema_json(item, label, _schema_path(path, key), stack, depth + 1)
    stack.remove(id(value))


def validate_json_schema(value, label="Response"):
    """Validate the platform's bounded subset, including acyclic local references."""
    if not isinstance(value, dict):
        raise InvalidGenerationRequest(label, "#", "root must be a JSON Schema object")
    _schema_json(value, label)
    try:
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    except (ValueError, TypeError, OverflowError):
        raise InvalidGenerationRequest(label, "#", "must be serializable JSON") from None
    if size > 65536:
        raise InvalidGenerationRequest(label, "#", "exceeds 64 KB")
    nodes = set()
    count = 0

    def children(node, path):
        for key in ("properties", "$defs"):
            for name, child in node.get(key, {}).items():
                yield child, _schema_path(_schema_path(path, key), name)
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                yield node[key], _schema_path(path, key)
        for index, child in enumerate(node.get("anyOf", [])):
            yield child, f"{path}/anyOf/{index}"

    def walk(node, path, depth):
        nonlocal count
        def fail(key, reason):
            raise InvalidGenerationRequest(label, _schema_path(path, key) if key else path, reason)
        if not isinstance(node, dict):
            fail("", "must be a schema object")
        if depth > 16:
            fail("", "exceeds depth 16")
        count += 1
        if count > 256:
            fail("", "exceeds 256 schema nodes")
        nodes.add(id(node))
        for key, item in node.items():
            if key not in SCHEMA_KEYS:
                fail(key, "unsupported keyword " + key)
            if key == "type":
                items = item if isinstance(item, list) else [item]
                if not items or any(not isinstance(t, str) or t not in SCHEMA_TYPES for t in items) or len(set(items)) != len(items):
                    fail(key, "invalid type")
            if key in {"properties", "$defs", "items"} and not isinstance(item, dict):
                fail(key, "must be an object")
            if key == "required" and (not isinstance(item, list) or any(not isinstance(t, str) for t in item) or len(set(item)) != len(item)):
                fail(key, "must be distinct property names")
            if key == "additionalProperties" and not isinstance(item, (bool, dict)):
                fail(key, "must be boolean or a schema")
            if key in {"anyOf", "enum"} and (not isinstance(item, list) or not 1 <= len(item) <= (16 if key == "anyOf" else 256)):
                fail(key, "exceeds branch or value limit")
            if key in {"title", "description", "$ref"} and not isinstance(item, str):
                fail(key, "must be a string")
            if key == "examples" and not isinstance(item, list):
                fail(key, "must be an array")
            if key in SCHEMA_BOUNDS and (isinstance(item, bool) or not isinstance(item, (int, float)) or isinstance(item, float) and not math.isfinite(item) or key in {"minLength", "maxLength", "minItems", "maxItems"} and (not isinstance(item, int) or item < 0)):
                fail(key, "invalid bound")
        for child, child_path in children(node, path):
            walk(child, child_path, depth + 1)

    walk(value, "#", 0)
    expanded = 0

    def references(node, path, stack, depth):
        nonlocal expanded
        expanded += 1
        if id(node) in stack or depth > 32 or expanded > 4096:
            raise InvalidGenerationRequest(label, path, "recursive or excessive reference expansion")
        next_stack = stack | {id(node)}
        if "$ref" in node:
            ref, target = node["$ref"], value
            import re
            if not ref.startswith("#/") or re.search(r"~(?![01])", ref):
                raise InvalidGenerationRequest(label, path + "/$ref", "only local #/... references are allowed")
            for key in ref[2:].split("/"):
                key = key.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    raise InvalidGenerationRequest(label, path + "/$ref", "reference does not resolve")
                target = target[key]
            if not isinstance(target, dict) or id(target) not in nodes:
                raise InvalidGenerationRequest(label, path + "/$ref", "reference must resolve to a schema")
            references(target, path + "/$ref", next_stack, depth + 1)
        for child, child_path in children(node, path):
            references(child, child_path, next_stack, depth + 1)

    references(value, "#", set(), 0)
    return value


def normalise_json_schema(value, label="Response"):
    """Strip only refused annotations; unexpressible constraints are rejected."""
    if not isinstance(value, dict):
        raise InvalidGenerationRequest(label, "#", "root must be a JSON Schema object")
    _schema_json(value, label)
    def convert(node, path, depth=0):
        if not isinstance(node, dict) or depth > 16:
            raise InvalidGenerationRequest(label, path, "must be a schema object within depth 16")
        result = {}
        for key, item in node.items():
            if key in {"$schema", "format"}:
                continue
            if key not in SCHEMA_KEYS:
                raise InvalidGenerationRequest(label, _schema_path(path, key), "unsupported keyword " + key)
            if key in {"properties", "$defs"} and isinstance(item, dict):
                result[key] = {name: convert(child, _schema_path(_schema_path(path, key), name), depth + 1) for name, child in item.items()}
            elif key in {"items", "additionalProperties"} and isinstance(item, dict):
                result[key] = convert(item, _schema_path(path, key), depth + 1)
            elif key == "anyOf" and isinstance(item, list):
                result[key] = [convert(child, f"{path}/anyOf/{index}", depth + 1) for index, child in enumerate(item)]
            else:
                result[key] = copy.deepcopy(item)
        return result
    return validate_json_schema(convert(value, "#"), label)


def generation_request(inputs, *, normalise=True):
    """One boundary for chat/completion messages, token limits and schemas."""
    if not isinstance(inputs, dict) or "prompt" in inputs or not isinstance(inputs.get("messages"), list) or not inputs["messages"]:
        raise InvalidGenerationRequest("Generation", "#/messages", "send nonempty messages instead of prompt")
    for index, message in enumerate(inputs["messages"]):
        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or message.get("role") not in {"system", "user", "assistant", "tool"} or not (
                isinstance(message.get("content"), str) or message.get("role") == "assistant" and isinstance(message.get("toolCalls"), list)):
            raise InvalidGenerationRequest("Generation", f"#/messages/{index}", "must be a message with a supported role and text or assistant tool calls")
    request = dict(inputs)
    maximum = inputs.get("maxTokens", 1024) if normalise else inputs.get("maxTokens")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 64:
        raise InvalidGenerationRequest("Generation", "#/maxTokens", "must be an integer of 64 or more")
    request["maxTokens"] = maximum
    validate = normalise_json_schema if normalise else validate_json_schema
    if "jsonSchema" in inputs:
        request["jsonSchema"] = validate(inputs["jsonSchema"], "Response")
    if "tools" in inputs:
        if not isinstance(inputs["tools"], list):
            raise InvalidGenerationRequest("Generation", "#/tools", "must be a list")
        request["tools"] = []
        for tool in inputs["tools"]:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise InvalidGenerationRequest("Generation", "#/tools", "each tool needs a name")
            request["tools"].append({**tool, "parameters": validate(tool.get("parameters"), "Tool " + tool["name"])})
    return request


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
        "email.domain.verify", "companies.enrich", "people.enrich", "llm.complete", "llm.chat",
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
        self._transport = transport or (self._fake if os.environ.get("PRAMAAN_FAKE") == "1" else self._http)
        self._sleep = sleep

    @property
    def configured(self):
        return bool(self._api_key.strip())

    def require_configured(self):
        if not self.configured:
            raise MissingPramaanKey()

    @staticmethod
    def _fake(method, url, headers, body):
        # Explicit local fixture mode has no network transport or outside effects.
        if method == "POST" and urlparse(url).path == "/v1/capabilities/companies.enrich":
            return 200, {"name": "Local fixture company", "industry": "Support"}
        return 503, {"error": {"code": "upstream_unavailable", "retryable": False}}

    def _http(self, method, url, headers, body):
        request = Request(url, data=body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None),
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
                message = code.get("message", "") if isinstance(code, dict) else (payload.get("message", "") if isinstance(payload, dict) else "")
                if isinstance(code, dict):
                    code = code.get("code")
                if not code and isinstance(payload, dict):
                    code = payload.get("code")
                if error.code == 400 and code == "invalid_request" and isinstance(message, str) and "maxtokens" in message.lower():
                    return 400, {"error": {"code": "invalid_request", "message": "maxTokens"}}
            except (ValueError, OSError):
                code = None
            return error.code, {"error": code if isinstance(code, str) and code in UNAVAILABLE_CODES | {"not_found"} else None}
        except (URLError, OSError, ValueError):
            raise PramaanError("unavailable", uncertain=method == "POST") from None

    def _request(self, method, path, body=None, *, idempotency_key=None, approved_by=None, account=None, plan=None, outcome=False, capability=None, content_type="application/json"):
        self.require_configured()
        headers = {"Authorization": "Bearer " + self._api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = content_type
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        # Local actor names belong in application audit records. The API key
        # identifies the platform member; local users are not platform approvers.
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
            remote_code = result.get("error") if isinstance(result, dict) else None
            if isinstance(remote_code, dict):
                remote_code = remote_code.get("code")
            if not remote_code and isinstance(result, dict):
                remote_code = result.get("code")
            remote_error = result.get("error") if isinstance(result, dict) else None
            remote_message = remote_error.get("message", "") if isinstance(remote_error, dict) else (result.get("message", "") if isinstance(result, dict) else "")
            if status == 400 and capability in {"llm.chat", "llm.complete"} and remote_code == "invalid_request" and isinstance(remote_message, str) and "maxtokens" in remote_message.lower():
                raise GenerationConfigurationError()
            if capability and (capability.startswith(("voice.", "email.")) or capability == "audio.transcription.create") and (status == 501 or isinstance(remote_code, str) and remote_code in UNAVAILABLE_CODES):
                raise PramaanNotAvailable(capability)
            if status == 404 and remote_code == "not_found" and capability in {"people.enrich", "companies.enrich"}:
                raise PramaanError("not_found")
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
        self.require_configured()
        if capability not in self.CAPABILITIES:
            raise PramaanError("unsupported_capability")
        if capability in self.ACTIONS and not idempotency_key:
            raise PramaanError("missing_idempotency_key")
        if capability in {"llm.chat", "llm.complete"}:
            inputs = generation_request(inputs)
        status, result = self._request("POST", "/v1/capabilities/" + quote(capability, safe=""), inputs,
                                     idempotency_key=idempotency_key, approved_by=approved_by, capability=capability)
        if status == 202:
            if not isinstance(result.get("job_id"), str) or result.get("status") not in {"running", "done", "failed", "cancelled"}:
                raise PramaanError("invalid_response", uncertain=capability in self.ACTIONS)
        return generation_result(capability, inputs, result)

    def upload_file(self, content, content_type):
        _, result = self._request("POST", "/v1/files?kind=document", content, content_type=content_type)
        if not isinstance(result.get("fileId"), str):
            raise PramaanError("invalid_response")
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
                return generation_result(capability, inputs, completed)
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
        "social_sign_in": False,
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
