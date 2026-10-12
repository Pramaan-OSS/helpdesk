## Problem

The Pramaan Helpdesk template cannot preserve its browser phone without connecting directly to a voice vendor. The current voice catalogue covers telephone calls and server-side call control, but does not expose a browser audio session, registration, incoming-call acceptance, or a provider-neutral browser transport.

Source: local `references/frappe-helpdesk`, commit `075edde1c072037f50fa73fed4141de0b05097cb`. Relevant files: `desk/src/components/telephony/TwilioCallUI.vue:176,243,252,276,300,355` and `desk/src/components/Settings/Telephony/TwilioSettings.vue:160`. The UI currently uses `@twilio/voice-sdk`, gets and refreshes access tokens, registers a device, receives calls, accepts/rejects them, connects outgoing calls, mutes and disconnects. Backend telephony is a separate dependency and was not available for a full audit.

## Requested contract (proposed, not existing capability ids)

- `voice.browser-session.create`: input an owned agent identity, owned calling-number ref, allowed origin and a bounded lifetime. Output an opaque session ref, expiry and a short-lived Pramaan browser connection credential. Never expose `PRAMAAN_API_KEY` or vendor credentials to the browser.
- `voice.browser-session.refresh` / `voice.browser-session.close`: renew or revoke an owned session with explicit expiry and disconnect behavior.
- A Pramaan-hosted browser audio and event transport, including incoming ringing, connected, rejected, failed and ended states. Events need stable ids, a resumable cursor and tenant/agent scoping. Merely issuing a Twilio token does not satisfy the template's requirement that outside traffic go through Pramaan.
- `voice.browser-call.start`, `voice.browser-call.accept`, `voice.browser-call.reject`, `voice.browser-call.end`: input owned session/call refs, an E.164 destination for start, and a caller correlation id for the local ticket. Output owned call ref and normalized state. Define how mute/unmute relates to local microphone state versus remote call control.
- Document origin enforcement, microphone permission handling, reconnect behavior, concurrency and duration/cost limits. Use idempotency for actions; a transport timeout must not silently redial.

## Acceptance checks

1. Two permitted test agents can make and receive a test call without vendor SDK imports, credentials, domains or ids in the product UI, logs or browser traffic.
2. Incoming accept/reject, outgoing dialing, mute, hangup, expiry, refresh, revoked sessions and network reconnect have documented outcomes.
3. Replayed events and repeated actions do not duplicate calls or ticket activity; another tenant cannot operate a session or read its events.
4. Call refs work with documented call history/recording capabilities, or the API explicitly reports unsupported combinations.
5. Contract and adapter tests use fakes; any live phone test requires owner approval. Update CAPABILITIES.md and mark live status honestly.

## Until available

Disable the browser phone and remove the direct SDK. Existing telephone-to-telephone capabilities can cover a separately labeled callback feature, but are not a browser phone replacement. Local manual call notes can remain.
