# Assistant request diagnostics

A failed mapping suggestion in the live smoke test had only a generic UI message. Its original cause is unconfirmed; this change adds correlation for future failures and does not claim to fix that incident.

After authentication and schema validation, the chat route generates a random request ID. Admission, context and quota errors retain their HTTP status and code while adding `detail.request_id` and `X-Assistant-Request-Id`. Streaming errors retain `type/code/message`, add `request_id`, and include a copyable 문의 코드 in the existing message. Successful delta/done payloads are unchanged. Existing clients can ignore the additive field; no request-body changes are required.

The same ID identifies the existing usage observation and a new `assistant_failure` record. Failure records contain only a generated ID, allowlisted stage (admission/context/quota/classification/answer), and allowlisted error code. They exclude user identifiers, request text, editor source, context bodies, raw exceptions, and provider response bodies. The provider still closes on cancellation/timeout. No retry, extra quota reservation, token-limit or classification behavior change is introduced.

## Triage

1. Ask for the 문의 코드 and approximate time, not the conversation, source or API key.
2. Locate `assistant_failure` with that requestId. Check stage and code; correlate `assistant_usage` with the same ID for timing and known token totals.
3. Classification failure: inspect gateway availability/structured-output configuration using synthetic requests. It must not fall through to the answer model.
4. Answer timeout/stream error: inspect service latency and transport; do not automatically replay a potentially charged request.
5. Context/quota error: keep existing ownership/expiry or allowance controls. Do not disable safeguards to make a request succeed.

Requests rejected before the route (authentication/schema), browser/proxy/network failures, and hard process termination may have no ID. This is not complete distributed tracing. Existing frontends may replace HTTP error copy with their own localized notice; the ID remains in the response/header. SSE errors display it through the existing message. Log inspection requires the existing operator permissions; no new endpoint exposes logs.

Validation uses fake providers and checks reference matching, quota single-charge/rejection, safe metadata, unknown exception redaction and existing timeout/cancellation regressions. Production failure diagnosis remains pending a future occurrence or approved deployed smoke test. No deployment is part of this PR.
