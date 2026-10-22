# Pramaan Helpdesk

Pramaan Helpdesk is a support workspace for tickets, customers, contacts, knowledge-base articles and private attachments, with a consistent design system across the app. Email, calling, drafting, enrichment and document processing use one server-side Pramaan client.

When supported by the platform, agents can connect an owned mailbox, send ordinary ticket replies, request telephone callbacks, review reply/article drafts, look up contact/company details and extract attachment text. Calls use the agent's telephone. Requested recordings stay permission protected. Browser calls, automatic acknowledgements and feedback emails, and edited threaded replies use the delivered Pramaan contracts. Automatic email events are off by default and can be enabled in Email Notifications after confirming the default sender is authorised or connecting an outgoing mailbox. Summarise attachment and Review call require an estimate and explicit approval. Without a Pramaan key, outside actions are blocked with a clear configuration message.

Outside operations depend on live platform availability. Calling, mailbox access and recording transcription report a plain unavailable message when refused; queued mail is never marked accepted without a confirmed sending reference or message identifier.

## Quick start

Install Docker with Docker Compose, then run:

```sh
cp .env.example .env  # paste your PRAMAAN_API_KEY into .env
./start
```

Open the address printed by the command (normally http://localhost:18008). Sign in as `Administrator`; the generated password is in `.runtime/local-admin-password`. Startup prints the file location, never the password. No local Python, Node, package-registry account, site name or database password is needed. The standard-library Pramaan client is included. The first build prepares the pinned framework and app dependencies inside Docker. Chromium and fonts for PDF printing are installed in the image; print requests do not download a browser.

The command starts the app, background worker, local update connection, MariaDB and Redis using `docker/docker-compose.yml`. It generates database, Administrator and encryption secrets in ignored `.env`, preserves them on restart and chooses the next port if needed. Site data and private files remain in this compose project's private volumes. Existing sites preserve their own encryption key. Back up `.env` together with those volumes. Stop with `docker compose --env-file .env -f docker/docker-compose.yml down`; this preserves data. This is a local development setup, not a production hosting recipe.

`PRAMAAN_API_KEY` is the only value you enter. `PRAMAAN_BASE_URL` is optional and already has a working client default. Without a key, the app starts and says “Add PRAMAAN_API_KEY to .env”; password sign-in, tickets, internal notes, customers, contacts, articles and private local attachments remain usable. Outside actions are blocked. Connected mail and calling stay off until set up in the app's settings. Automatic email remains off by default. For fixture checks only, `PRAMAAN_FAKE=1` returns a company suggestion and refuses all other outside requests without network access.

For an existing development site prepared by the older helper, use `./scripts/start-local` and its current credentials; it is separate from the Docker site's volumes. If its Administrator password file is missing, generate a replacement with `./review/local-bench execute helpdesk.local_credentials.reset`. That writes `.runtime/bench/.local-admin-password` and prints only its location. It replaces the unknown password. Do not pass a password in a terminal command.

## Feature limits

- Local field dependencies and simple visibility, required-field and read-only rules are supported. Stored custom JavaScript is not executed.
- Attachment summaries require a document with selectable text, up to 10 MiB. Scanned images cannot be read. The summary can be copied into an internal comment; it never changes the ticket by itself.
- Call review requires a completed recorded callback and an owned public HTTPS audio link, up to 10 MB, valid for at least 35 minutes. Findings become an internal note only after a separate confirmation. Unsupported recordings show an unavailable message.
- Browser calling needs HTTPS, or HTTP on localhost/127.0.0.1. For local browser calls, use `http://localhost:18008`. Browser-call recording, transcription and keypad actions are not supported. A relay restart ends active browser calls and sessions; finished relay history is retained for 24 hours.
- Sign-in uses local workspace accounts. Optional single sign-in is unavailable until the platform supplies an authorization-start contract; no external client registration is needed.
- Features depend on capabilities being available to your Pramaan account. Integration checks use fake responses; live email, phone, sign-in and outcome availability have not been verified. For live checks, use one project per organisation until the known platform defect is fixed.

## Checks

```sh
python3 -m unittest discover -s review -p 'test_*.py' -v
python3 -m compileall -q helpdesk
./review/local-bench set-config allow_tests true
./review/local-bench run-tests --app helpdesk
```

Run the backend tests on a disposable local site, with `PRAMAAN_API_KEY` unset and the app server/worker stopped. The tests create local fixtures and use fake Pramaan responses. Same-site customer-app checks are skipped when that optional app is absent. No live email, phone or paid-service test has been authorized.

## Connected accounts

Connecting an outside account, such as a support mailbox or another app, carries a monthly Pramaan charge for each
connected account, billed to the Pramaan account behind `PRAMAAN_API_KEY`. Signing in is free. Disconnecting an account
ends its charge.

## Built on

[Frappe Helpdesk](https://github.com/frappe/helpdesk), source commit `075edde1c072037f50fa73fed4141de0b05097cb`, under AGPL-3.0. Original notices are retained in `LICENSE-ORIGINAL` and `NOTICE`. This template is AGPL-3.0. The retained framework is pinned to `e7ddbac9b5d9601e891dd57f01f4643a14f7f41c`. Internal framework/package identifiers remain where imports, stored records and migrations require them; visible product branding has been replaced.

The Docker start command serves the built interface with a production application server. For development only, set `HELPDESK_DEVELOPMENT=1` in the local environment and recreate the app service; the default keeps development mode off. Traceback details stay hidden in both modes.

Outgoing mail uses the default sender unless an outgoing mailbox is connected. The default is Pramaan Helpdesk on the template sending domain; an administrator can override the single `pramaan_email_sender` site setting with an authorised sender. A reply address is included only when a real outgoing mailbox is configured. Accepted sending references are retained separately from confirmed email thread identifiers.
