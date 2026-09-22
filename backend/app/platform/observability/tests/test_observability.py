"""
Observability phase tests.

Covers the metrics endpoint, business-metric recording through the single
choke point, health/readiness observability posture, correlation-ID
propagation, and the log trace-context processor's graceful no-op behaviour.
"""
from prometheus_client import REGISTRY

from app.platform.observability.metrics import record_event
from app.platform.observability.tracing import add_trace_context

# ── /metrics endpoint ────────────────────────────────────────────────────────

async def test_metrics_endpoint_exposes_prometheus_format(client):
    # Warm up a templated route so the labelled HTTP latency family is emitted.
    await client.get("/api/v1/health")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    # Default HTTP metric families from the instrumentator are present.
    assert "aner_http_request_duration_seconds" in body
    assert "aner_http_requests_inprogress" in body


async def test_metrics_endpoint_reports_business_metric_names(client):
    # Touch every business counter so its family is emitted at least once.
    # NOTE: use the real EventType values — payment creation is "transaction.initiated".
    record_event("transaction.initiated")
    record_event("settlement.completed")
    record_event("settlement.failed")
    resp = await client.get("/metrics")
    body = resp.text
    assert "aner_events_published_total" in body
    assert "aner_payments_created_total" in body
    assert "aner_settlements_completed_total" in body


# ── business metric recording ────────────────────────────────────────────────

def _counter(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels or None) or 0.0


def test_record_event_increments_event_counter():
    before = _counter("aner_events_published_total", event_type="transaction.initiated")
    record_event("transaction.initiated")
    after = _counter("aner_events_published_total", event_type="transaction.initiated")
    assert after == before + 1


def test_record_event_maps_payment_created_outcome_counter():
    # Regression: the payment-creation event is "transaction.initiated" (the value
    # of EventType.PAYMENT_CREATED), NOT the literal "payment.created". The outcome
    # handler key must match, or aner_payments_created_total silently stays at 0.
    before = _counter("aner_payments_created_total")
    record_event("transaction.initiated")
    after = _counter("aner_payments_created_total")
    assert after == before + 1


def test_record_event_maps_to_outcome_counter():
    before = _counter("aner_settlements_completed_total")
    record_event("settlement.completed")
    after = _counter("aner_settlements_completed_total")
    assert after == before + 1


def test_record_event_maps_compensation_phase_label():
    before = _counter("aner_compensations_total", phase="started")
    record_event("compensation.started")
    after = _counter("aner_compensations_total", phase="started")
    assert after == before + 1


def test_record_event_unknown_type_is_safe():
    # Unknown types still bump the generic events counter and never raise.
    before = _counter("aner_events_published_total", event_type="some.unknown.event")
    record_event("some.unknown.event")
    after = _counter("aner_events_published_total", event_type="some.unknown.event")
    assert after == before + 1


# ── health / readiness observability posture ─────────────────────────────────

async def test_health_liveness(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


async def test_readiness_reports_observability_block(client):
    resp = await client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    obs = resp.json()["observability"]
    assert obs["metrics_endpoint"] == "/metrics"
    assert "otlp_endpoint" in obs
    assert "tracing_enabled" in obs


# ── correlation ID propagation ───────────────────────────────────────────────

async def test_correlation_id_echoed_from_request(client):
    cid = "11111111-2222-3333-4444-555555555555"
    resp = await client.get("/api/v1/health", headers={"X-Correlation-Id": cid})
    assert resp.headers["X-Correlation-Id"] == cid
    assert "X-Response-Time-Ms" in resp.headers


async def test_correlation_id_generated_when_absent(client):
    resp = await client.get("/api/v1/health")
    assert resp.headers.get("X-Correlation-Id")  # non-empty generated UUID


# ── log trace-context processor ──────────────────────────────────────────────

def test_add_trace_context_noop_without_active_span():
    # No span in scope → processor must leave the event dict untouched.
    event = {"event": "hello"}
    out = add_trace_context(None, "info", dict(event))
    assert out == event
    assert "trace_id" not in out
