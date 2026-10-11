# Pramaan Helpdesk

A support workspace with tickets, customers, contacts, articles and private attachments. Outside services use one server-side Pramaan client. The design-system pass is pending; see `BLOCKED.md` and `DONE.md` for the current handoff.

Agents can connect an owned mailbox, send ordinary ticket replies, request telephone callbacks, review reply/article drafts, look up contact/company details and extract attachment text. Calls use the agent's telephone. Requested recordings stay permission protected. Browser calls, automated/edited threaded email and social sign-in remain disabled while the platform issues in `GAPS.md` are open.

## Run locally

Prerequisites: Docker running, Node 24 or newer, npm, Git and [uv](https://docs.astral.sh/uv/). Python 3.14 and a pinned framework checkout are prepared by the first command.

```sh
./review/prepare-local
python3 scripts/setup-local.py
export PRAMAAN_API_KEY='your-key'
./scripts/start-local
```

Open `http://pramaan.localhost:18008/login`. Sign in as `Administrator` using the password saved in `.runtime/bench/.local-admin-password`. Existing sites keep their current password. This is a local development server. The helper creates only the template's own MariaDB and Redis containers; it preserves an existing local site.

The start command runs the web server, the local update connection and a background worker. With a key set, it also starts scheduled mail collection and delivery checks. Without a key, sign-in, tickets and comments work locally, and outside actions fail with a plain message. Stop the command with Ctrl+C. Runtime dependencies are prepared before startup; startup does not download applications.

The only outside-service credential is `PRAMAAN_API_KEY`. `PRAMAAN_BASE_URL` is optional. Set these in the server environment, never in browser code or committed files. `.env.example` is documentation; the start command does not automatically load it. `.runtime`, `.venv`, `.tools`, `vendor` and secret files are ignored by Git.

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
