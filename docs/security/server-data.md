# Data on the server

What the core service keeps, where, and for how long. The demo runs on synthetic data: test personas, no real customer.

What the AI model receives is described in `docs/design/agent-core.md`, section 4 (the privacy boundary) and section 7.6 (the conversation history). In short:
- the model gets the question, the compact results of the calculations, dates and the answer language;
- it never gets a name, an account number, a real merchant name or a transaction row.

File references are to `dev` at 281c6d1.

## What the server stores

| Store | Where | What it holds | How long |
|---|---|---|---|
| Audit file, one record per answer | `var/audit/YYYY-MM-DD.jsonl` (`core/agent/audit.py:3, 22`), written for every `/api/ask` (`core/agent/orchestrator.py:279`) | The customer id and the question word for word (`orchestrator.py:946, 949`), the planner's calls with their arguments, the tools' model views, the numbers with their evidence refs, the model's drafts, the final text and the timings (`orchestrator.py:941-973`). No IP address, no viewer cookie, no transaction rows. | No limit in code |
| Model response cache | `var/gemini-cache/<sha256>.json` (`core/agent/gemini.py:43`), on by default (`gemini.py:261`) | The model's response: the planner's function calls with their arguments, the composer's draft and the token counts (`core/agent/gemini_client.py:346-348, 516-526`). The file name is a SHA-256 of the whole request (`gemini_client.py:496-499`); the request text itself is not stored. | No limit in code |
| Request ledger | `var/gemini-requests.jsonl` (`gemini.py:44`) | One line per request sent to the model: time, kind, model, result, latency and token counts (`gemini_client.py:275-280`). No question and no answer. | No limit in code. The 24 hours in the code are the window of the daily cap, not a retention period. |
| Tool cache | `var/cache/tools.sqlite3` (`core/tools/cache.py:74-75`) | Tool results, keyed by customer, tool and arguments | At most 5,000 entries on disk (`cache.py:72`), no time limit |
| Conversation memory | Process memory only (`core/agent/conversation.py:1-4`) | The last turns of a conversation: questions, calls, model views and the answer with numbers masked | 6 turns, 30 minutes (`conversation.py:16-17`); gone on a restart |
| Service journal | `journalctl -u shadowless1-core` on the instance (`deploy/shadowless1-core.service`, `docs/deploy.md` section "Logs") | Lines of three kinds, none with the question or the model output:<br>• the uvicorn access log: client IP address and request line. It is on, because `deploy/Dockerfile` starts uvicorn without `--no-access-log`;<br>• one line per model request, with counts and timings (`gemini_client.py:537`);<br>• errors, as exception class names.<br>Secret settings are masked in every line (`core/app/secret_mask.py`). | Whatever the instance's journald keeps; the project sets nothing |

The proxy (Caddy) writes no access log: `deploy/Caddyfile` has no `log` directive.

**Access.** On the instance, `var/` is `/var/lib/shadowless1/var`, mode 700: only root and the container user can read it. The journal is readable only by root and the `adm` and `systemd-journal` groups (`docs/deploy.md`, sections "Service data" and "Logs"). Nothing is shipped off the instance. The endpoint that reads audit records exists only when `AUDIT_API=1` is set (`core/agent/api.py:327-330`).

## Known properties of the demo

- **The overview route has the customer id in its path** (`/api/overview/{customer_id}`, `core/app/api/overview.py:154`). The id therefore lands in the access log, next to the client's IP address. With synthetic personas this is acceptable for the demo; a bank service would take the customer from the bank session, not from the path.
- **A bill id that the model sees is derived from the customer id** and the merchant id (`core/tools/bills.py:97-101`). Follow-up in #487.
- **Bill reading** (#250, not in `dev` yet) sends the whole bill image to the model. The response cache then keeps what the model read, the IBAN included. Only the team's synthetic sample bills are sent.
- **The audit file keeps the question word for word.** Anything a user types, such as a name or an IBAN, stays there until the clean-up below.

## Retention, and the clean-up after the event

No store above has a retention period in code, and automatic deletion is not built. Whether to build it is an open team decision; until then, the data is deleted by hand after the event.

On the instance, as root:
- [ ] Stop the service: `systemctl stop shadowless1-core`.
- [ ] Delete the audit files and the response cache: `rm -rf /var/lib/shadowless1/var/audit /var/lib/shadowless1/var/gemini-cache`.
- [ ] Delete the journal: `journalctl --rotate && journalctl --vacuum-time=1s`. This removes the journal of every unit on the instance, not only the core's.
- [ ] If the instance stays, delete the ledger and the tool cache as well: `rm -rf /var/lib/shadowless1/var/gemini-requests.jsonl /var/lib/shadowless1/var/cache`. They hold no question and no answer text.

On every team machine:
- [ ] Delete `var/audit` and `var/gemini-cache` in each checkout and worktree. They are git-ignored, so they never reach the repository, but local runs fill them.
