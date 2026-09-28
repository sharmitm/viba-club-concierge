# Observability spec (`OB`)

Implementation: `viba_concierge/core/logging.py` (`JsonFormatter`, `span`,
`log_event`, `current_trace_id`, `current_agent`).

### OB-01 One request, one trace
**Rule.** Every log line MUST be a single JSON object carrying `trace_id` and
`agent`. All lines emitted while handling one `propose()` MUST share the
`trace_id` returned on the result.
**Acceptance.**
- Capturing logs during `propose()`, every line parses as JSON and every
  `trace_id` equals `result.trace_id`; more than one `agent` value appears
  (orchestrator plus sub-agents).
**Status.** enforced

### OB-02 Spans time work and never swallow errors
**Rule.** `span` MUST log `span.start` and `span.end` with `duration_ms`. On an
exception it MUST log `span.error` with `duration_ms` and the formatted
traceback in `error`, then re-raise.
**Acceptance.**
- A successful span emits start and end with a numeric `duration_ms`.
- A failing span emits `span.error` whose `error` contains the exception message,
  and the exception propagates to the caller.
**Status.** enforced
