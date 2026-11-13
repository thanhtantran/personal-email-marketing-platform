"""Metrics registry and exposition contract.

The observability surface is a small local implementation rather than a client
library, so it carries its own tests: label handling, Prometheus text formatting
and the rule that only platform-controlled, low-cardinality labels are exposed
(SPEC.md sections 8 and 10).
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.main import _metrics_authorized
from app.observability.metrics import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    Registry,
)


# ---------------------------------------------------------------- counter
def test_counter_without_labels_exports_a_zero_before_the_first_event() -> None:
    counter = Counter("m_total", "help")
    assert list(counter.samples()) == [("", {}, 0.0)]


def test_counter_accumulates_and_exports_per_label_set() -> None:
    counter = Counter("m_total", "help", ("result",))
    counter.inc(result="ok")
    counter.inc(2, result="ok")
    counter.inc(result="error")

    assert counter.value(result="ok") == 3.0
    assert counter.value(result="error") == 1.0
    assert {(labels["result"], value) for _, labels, value in counter.samples()} == {
        ("error", 1.0),
        ("ok", 3.0),
    }


def test_metric_rejects_a_label_set_that_does_not_match_its_declaration() -> None:
    counter = Counter("m_total", "help", ("result",))
    with pytest.raises(ValueError, match="do not match"):
        counter.inc(outcome="ok")
    with pytest.raises(ValueError, match="do not match"):
        counter.inc()


# ------------------------------------------------------------------ gauge
def test_gauge_moves_up_and_down_and_can_be_cleared() -> None:
    gauge = Gauge("m", "help", ("status",))
    gauge.set(5, status="queued")
    gauge.inc(status="queued")
    gauge.dec(2, status="queued")
    assert gauge.value(status="queued") == 4.0

    gauge.clear()
    # A cleared labelled gauge exports nothing, so a scrape cannot repeat a
    # stale label set after the underlying rows are gone.
    assert list(gauge.samples()) == []


# -------------------------------------------------------------- histogram
def test_histogram_buckets_are_cumulative_and_track_sum_and_count() -> None:
    histogram = Histogram("m_seconds", "help", ("provider",), buckets=(0.5, 1.0))
    histogram.observe(0.25, provider="mock")
    histogram.observe(2.0, provider="mock")

    buckets = {
        labels["le"]: value for _, labels, value in histogram.samples() if "le" in labels
    }
    assert buckets["0.5"] == 1.0
    assert buckets["1"] == 1.0
    assert buckets["+Inf"] == 2.0

    totals = {
        suffix: value for suffix, _, value in histogram.samples() if suffix in {"_sum", "_count"}
    }
    assert totals["_count"] == 2.0
    assert totals["_sum"] == pytest.approx(2.25)


def test_histogram_renders_cumulative_bucket_lines() -> None:
    histogram = Histogram("m_seconds", "help", buckets=(0.5, 1.0))
    histogram.observe(0.25)
    histogram.observe(2.0)
    rendered = "\n".join(
        f"{labels.get('le')}={value}" for _, labels, value in histogram.samples()
    )
    assert "0.5=1.0" in rendered
    assert "+Inf=2.0" in rendered


def test_histogram_sum_and_count_samples_are_present() -> None:
    histogram = Histogram("m_seconds", "help")
    histogram.observe(0.25)
    histogram.observe(0.75)
    suffixes = {suffix for suffix, _, _ in histogram.samples()}
    assert suffixes == {"_bucket", "_sum", "_count"}


# --------------------------------------------------------------- registry
def test_registry_render_emits_help_type_and_samples() -> None:
    registry = Registry()
    counter = registry.register(Counter("demo_total", "demo help", ("result",)))
    counter.inc(result="ok")

    text = registry.render()
    assert "# HELP demo_total demo help" in text
    assert "# TYPE demo_total counter" in text
    assert 'demo_total{result="ok"} 1' in text
    assert text.endswith("\n")


def test_registry_render_escapes_label_values() -> None:
    registry = Registry()
    counter = registry.register(Counter("demo_total", "demo", ("detail",)))
    counter.inc(detail='a"b\nc')
    assert 'demo_total{detail="a\\"b\\nc"} 1' in registry.render()


def test_declared_surface_exposes_the_spec_metrics() -> None:
    names = {metric.name for metric in REGISTRY.metrics}
    assert {
        "email_platform_webhook_intake_total",
        "email_platform_recipient_events_total",
        "email_platform_provider_submissions_total",
        "email_platform_provider_submit_seconds",
        "email_platform_outbox_publish_total",
        "email_platform_outbox_events",
        "email_platform_campaign_recipients",
        "email_platform_webhook_events",
        "email_platform_provider_accounts",
        "email_platform_retention_deleted_total",
        "email_platform_metrics_collection_errors_total",
    } <= names


def test_exposed_labels_never_include_unbounded_identifiers() -> None:
    """Cardinality guard: no label may be a free-text identifier (SPEC.md 8)."""
    forbidden = {"email", "recipient", "recipient_id", "campaign_id", "api_key", "error"}
    for metric in REGISTRY.metrics:
        assert not (set(metric.label_names) & forbidden), metric.name


# --------------------------------------------------- endpoint authorization
def test_metrics_authorization_accepts_only_the_matching_bearer_token() -> None:
    assert _metrics_authorized(_request({"authorization": "Bearer s3cret"}), "s3cret") is True
    # Scheme comparison is case-insensitive, value comparison is not.
    assert _metrics_authorized(_request({"authorization": "bearer s3cret"}), "s3cret") is True
    assert _metrics_authorized(_request({"authorization": "Bearer wrong"}), "s3cret") is False
    assert _metrics_authorized(_request({}), "s3cret") is False
    assert _metrics_authorized(_request({"authorization": "Basic s3cret"}), "s3cret") is False


def _request(headers: dict[str, str]) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/metrics", "headers": raw})
