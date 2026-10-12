# Pramaan Helpdesk

Pramaan Helpdesk is a support workspace for tickets, customers, contacts, knowledge-base articles and private attachments, with a consistent design system across the app. Email, calling, drafting, enrichment and document processing use one server-side Pramaan client.

Agents can connect an owned mailbox, send ordinary ticket replies, request telephone callbacks, review reply/article drafts, look up contact/company details and extract attachment text. Calls use the agent's telephone. Requested recordings stay permission protected. Browser calls, automatic acknowledgements and feedback, edited threaded replies and invited-account social sign-in use the delivered Pramaan contracts. Automatic email events are off by default and can be enabled in Email Notifications after connecting an outgoing mailbox. Summarise attachment and Review call require an estimate and explicit approval. Without a Pramaan key, outside-action controls show the configuration message and are disabled.

## Run locally

Prerequisites: Docker running, Node 24 or newer, npm, Git and [uv](https://docs.astral.sh/uv/). Python 3.14 and a pinned framework checkout are prepared by the first command.

```sh
./review/prepare-local
python3 scripts/setup-local.py
export PRAMAAN_API_KEY='your-key'
./scripts/start-local
```

Open `http://pramaan.localhost:18008/login`. For a fresh site created by this helper, sign in as `Administrator` using `.runtime/bench/.local-admin-password`. Existing sites keep their current password; that file may not exist. If the password is unknown, reset it with `./review/local-bench set-admin-password <new-password>` (this replaces it, rather than recovering it). This is a local development server. The helper creates only the template's own MariaDB and Redis containers; it preserves an existing local site.

The start command runs the web server, the local update connection and a background worker. With a key set, it also starts scheduled mail collection and delivery checks. Without a key, password sign-in, tickets, internal comments, customers, contacts, articles and local attachments work. Outside-action controls are disabled and explain that an administrator must set a Pramaan key. Stop the command with Ctrl+C. Runtime dependencies are prepared before startup; startup does not download applications.

The only outside-service credential is `PRAMAAN_API_KEY`. `PRAMAAN_BASE_URL` is optional. Set these in the server environment, never in browser code or committed files. `.env.example` is documentation; the start command does not automatically load it. `.runtime`, `.venv`, `.tools`, `vendor` and secret files are ignored by Git.

## Feature limits

- Attachment summaries require a document with selectable text, up to 10 MiB. Scanned images cannot be read. The summary can be copied into an internal comment; it never changes the ticket by itself.
- Call review requires a completed recorded callback and an owned public HTTPS audio link, up to 10 MB, valid for at least 35 minutes. Findings become an internal note only after a separate confirmation. Unsupported recordings show an unavailable message.
- Browser calling needs HTTPS, or HTTP on localhost/127.0.0.1. For local browser calls, use `http://localhost:18008`. Browser-call recording, transcription and keypad actions are not supported. A relay restart ends active browser calls and sessions; finished relay history is retained for 24 hours.
- Single sign-in admits only invited accounts with a verified email. Its redirect needs HTTPS or HTTP on localhost. Password sign-in remains available.
- Features depend on capabilities being available to your Pramaan account. Integration checks use fake responses; live email, phone, sign-in and outcome availability have not been verified. For live checks, use one project per organisation until the known platform defect is fixed.

## Checks

```sh
python3 -m unittest discover -s review -p 'test_*.py' -v
python3 -m compileall -q helpdesk
./review/local-bench set-config allow_tests true
./review/local-bench run-tests --app helpdesk
```

Run the backend tests on a disposable local site, with `PRAMAAN_API_KEY` unset and the app server/worker stopped. The tests create local fixtures and use fake Pramaan responses. Same-site customer-app checks are skipped when that optional app is absent. No live email, phone or paid-service test has been authorized.

## Built on

[Frappe Helpdesk](https://github.com/frappe/helpdesk), source commit `075edde1c072037f50fa73fed4141de0b05097cb`, under AGPL-3.0. Original notices are retained in `LICENSE-ORIGINAL` and `NOTICE`. This template is AGPL-3.0. The retained framework is pinned to `e7ddbac9b5d9601e891dd57f01f4643a14f7f41c`. Internal framework/package identifiers remain where imports, stored records and migrations require them; visible product branding has been replaced.
