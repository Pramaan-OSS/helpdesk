## Problem

The Pramaan Helpdesk template needs email loop prevention and editable threaded replies. Existing email capabilities cover ordinary sends, attached files, receiving raw messages and normal replies, but their contracts do not preserve all of the source behavior.

Source: local `references/frappe-helpdesk`, commit `075edde1c072037f50fa73fed4141de0b05097cb`:
- `helpdesk/helpdesk/doctype/hd_ticket/hd_ticket.py:161` sends feedback with an `X-Auto-Generated` marker and a thread parent.
- `:773` sends a reply with explicit recipients, subject, sender/reply address, attachments, parent and Message-ID.
- `:917` sends acknowledgements with `X-Auto-Generated: hd-acknowledgement`.
- `helpdesk/overrides/email_account.py:13` detects auto-generated messages to prevent acknowledgement/CC loops.

Local platform contracts inspected: `packages/capabilities/src/capabilities/email.send/index.ts`, `email.message.send/index.ts` and `email.message.reply/index.ts`. `email.send` has no custom message headers or attachments; `email.message.send` supports attachments but no threading/auto-generated headers; `email.message.reply` preserves a parent and supports attachments/CC/BCC but has no primary-recipient or subject override and no auto-generated marker. Its input `messageId` identifies the parent, not a caller-selected outgoing id. Generated outgoing ids can be stored locally, so caller-selected outgoing ids are not essential.

## Requested change

Prefer extending the existing contracts instead of adding a parallel send API:
- A typed `autoSubmitted` field (such as `auto-generated` / `auto-replied`) and/or a tightly constrained app-generated marker. State which outbound APIs support it, and return a normalized unsupported error rather than silently dropping it.
- Explicit threading fields for a new message when a parent is known (`inReplyTo` and bounded `references`), or an equivalent owned-parent reference contract.
- Optional primary-recipient and subject overrides for a reply; retain existing defaults when omitted. Sender/reply-address changes must be constrained to authorized addresses.
- Return the actual RFC Message-ID and opaque ref so Helpdesk stores the id only after confirmed acceptance. Preserve CC/BCC and attachment behavior and document limits.
- Ensure a queued versus accepted versus uncertain outcome remains distinguishable. Idempotency must prevent duplicate sends and there must be no unsafe retry/failover after an ambiguous send.

## Acceptance checks

1. Acknowledgement and feedback messages carry a documented machine-message marker that survives a raw-message round trip and is detectable by inbound loop prevention.
2. Replying with an edited subject or primary recipient preserves the requested parent/thread, CC/BCC and attachments without silently ignoring fields.
3. Reject header injection, unauthorized sender addresses, malformed message ids and oversized references; do not accept unrestricted transport headers.
4. Fake-adapter tests cover repeated idempotency keys, ambiguous failures, unsupported providers and the loopback case: receiving our own acknowledgement never triggers another acknowledgement.
5. Document provider-independent guarantees, update the catalogue and live verification status. Do not send live email without explicit approval.

## Until available

Use existing capabilities only for the subsets they can represent. Disable unsupported edited-thread replies and automated emails whose loop-prevention marker cannot be preserved; do not fall back to SMTP.
