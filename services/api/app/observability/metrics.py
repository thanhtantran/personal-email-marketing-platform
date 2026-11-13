"""Dependency-free metrics registry with Prometheus text exposition.

The platform needs a small, auditable surface -- counters, gauges and a few
latency histograms -- so this is a short local implementation rather than a
client library dependency. Two rules are non-negotiable (SPEC.md section 8):

* labels are low-cardinality and only ever carry platform-controlled values
  (provider name, event type, status, outcome). A recipient address, an API key,
  a raw error message or a campaign id must never become a label, because labels
  are exported, logged and retained outside the platform's own controls;
* every metric is declared in this module, so the exposed surface is reviewable
  in one diff instead of appearing implicitly at call sites.

Counters live in process memory and reset on restart, which is why every rate is
computed downstream over a range (``rate()``) rather than from a raw value.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from collections.abc import Iterable, Iterator

#: Seconds. Chosen around the provider request budget (SEND_REQUEST_TIMEOUT_SECONDS)
#: so a scrape shows how much of that budget is normally consumed.
HISTOGRAM_BUCKETS: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

#: A sample is ``(name suffix, labels, value)``; the registry prefixes the
#: metric name. Counters and gauges use the empty suffix.
Sample = tuple[str, dict[str, str], float]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if value == math.inf:
        return "+Inf"
    if value == -math.inf:
        return "-Inf"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def _labels_text(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = ",".join(f'{name}="{_escape(value)}"' for name, value in sorted(labels.items()))
    return "{" + pairs + "}"


class _Metric:
    """Shared label handling for every metric type."""

    kind = "untyped"

    def __init__(self, name: str, help_text: str, labels: Iterable[str] = ()) -> None:
        self.name = name
        self.help = help_text
        self.label_names = tuple(labels)
        self._lock = threading.Lock()

    def _key(self, labels: dict[str, str]) -> tuple[str, ...]:
        if set(labels) != set(self.label_names):
            raise ValueError(
                f"{self.name}: labels {tuple(sorted(labels))} do not match {self.label_names}"
            )
        return tuple(str(labels[name]) for name in self.label_names)

    def _labels(self, key: tuple[str, ...]) -> dict[str, str]:
        return dict(zip(self.label_names, key, strict=True))

    def samples(self) -> Iterator[Sample]:
        raise NotImplementedError


class Counter(_Metric):
    """Monotonically increasing total."""

    kind = "counter"

    def __init__(self, name: str, help_text: str, labels: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labels)
        self._values: dict[tuple[str, ...], float] = defaultdict(float)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] += amount

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def samples(self) -> Iterator[Sample]:
        with self._lock:
            items = sorted(self._values.items())
        if not items and not self.label_names:
            # Export a zero so the metric is discoverable before its first event.
            yield "", {}, 0.0
            return
        for key, value in items:
            yield "", self._labels(key), value


class Gauge(_Metric):
    """A value that can go up and down, including one read at scrape time."""

    kind = "gauge"

    def __init__(self, name: str, help_text: str, labels: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labels)
        self._values: dict[tuple[str, ...], float] = {}

    def set(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        self.inc(-amount, **labels)

    def value(self, **labels: str) -> float:
        return self._values.get(self._key(labels), 0.0)

    def clear(self) -> None:
        """Drop every sample, so a scrape cannot export a stale label set."""
        with self._lock:
            self._values.clear()

    def samples(self) -> Iterator[Sample]:
        with self._lock:
            items = sorted(self._values.items())
        if not items and not self.label_names:
            yield "", {}, 0.0
            return
        for key, value in items:
            yield "", self._labels(key), value


class Histogram(_Metric):
    """Cumulative bucket counts plus sum and count (Prometheus semantics)."""

    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        labels: Iterable[str] = (),
        buckets: Iterable[float] = HISTOGRAM_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, labels)
        self.buckets = tuple(buckets)
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sums: dict[tuple[str, ...], float] = defaultdict(float)
        self._totals: dict[tuple[str, ...], int] = defaultdict(int)

    def observe(self, value: float, **labels: str) -> None:
        key = self._key(labels)
        with self._lock:
            counts = self._counts.setdefault(key, [0] * len(self.buckets))
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[index] += 1
            self._sums[key] += value
            self._totals[key] += 1

    def samples(self) -> Iterator[Sample]:
        with self._lock:
            keys = sorted(self._counts)
            counts = {key: list(self._counts[key]) for key in keys}
            sums = {key: self._sums[key] for key in keys}
            totals = {key: self._totals[key] for key in keys}
        for key in keys:
            labels = self._labels(key)
            for bound, count in zip(self.buckets, counts[key], strict=True):
                yield "_bucket", {"le": _number(bound), **labels}, float(count)
            yield "_bucket", {"le": "+Inf", **labels}, float(totals[key])
            yield "_sum", labels, sums[key]
            yield "_count", labels, float(totals[key])


class Registry:
    """Ordered collection of metrics rendered in Prometheus text format."""

    def __init__(self) -> None:
        self._metrics: list[_Metric] = []

    def register[MetricT: _Metric](self, metric: MetricT) -> MetricT:
        self._metrics.append(metric)
        return metric

    @property
    def metrics(self) -> tuple[_Metric, ...]:
        return tuple(self._metrics)

    def render(self) -> str:
        lines: list[str] = []
        for metric in self._metrics:
            lines.append(f"# HELP {metric.name} {_escape(metric.help)}")
            lines.append(f"# TYPE {metric.name} {metric.kind}")
            for suffix, labels, value in metric.samples():
                lines.append(f"{metric.name}{suffix}{_labels_text(labels)} {_number(value)}")
        return "\n".join(lines) + "\n"


REGISTRY = Registry()


def _counter(name: str, help_text: str, labels: Iterable[str] = ()) -> Counter:
    return REGISTRY.register(Counter(name, help_text, labels))


def _gauge(name: str, help_text: str, labels: Iterable[str] = ()) -> Gauge:
    return REGISTRY.register(Gauge(name, help_text, labels))


def _histogram(name: str, help_text: str, labels: Iterable[str] = ()) -> Histogram:
    return REGISTRY.register(Histogram(name, help_text, labels))


# ------------------------------------------------------------------ intake
WEBHOOK_INTAKE = _counter(
    "email_platform_webhook_intake_total",
    "Provider webhook deliveries by intake result (accepted, duplicate, rejected).",
    ("result",),
)

RECIPIENT_EVENTS = _counter(
    "email_platform_recipient_events_total",
    "Normalized recipient events by type and whether they were new or a replay.",
    ("event_type", "result"),
)

# ---------------------------------------------------------------- provider
PROVIDER_SUBMISSIONS = _counter(
    "email_platform_provider_submissions_total",
    "Provider submissions classified by outcome (never retried blindly when ambiguous).",
    ("provider", "outcome"),
)

PROVIDER_SUBMIT_SECONDS = _histogram(
    "email_platform_provider_submit_seconds",
    "Provider submit request duration in seconds.",
    ("provider",),
)

# ------------------------------------------------------------------- queue
OUTBOX_PUBLISH = _counter(
    "email_platform_outbox_publish_total",
    "Transactional outbox publishes by result (published, retry, failed, unmapped).",
    ("result",),
)

# ------------------------------------------------------------ scrape-time
OUTBOX_EVENTS = _gauge(
    "email_platform_outbox_events",
    "Outbox events currently in the store, by status (queue depth).",
    ("status",),
)

OUTBOX_OLDEST_PENDING_AGE = _gauge(
    "email_platform_outbox_oldest_pending_age_seconds",
    "Age of the oldest publishable outbox event; a rising value means the queue is stalled.",
)

CAMPAIGN_RECIPIENTS = _gauge(
    "email_platform_campaign_recipients",
    "Campaign ledger rows by recipient status.",
    ("status",),
)

WEBHOOK_EVENTS = _gauge(
    "email_platform_webhook_events",
    "Accepted webhook deliveries by processing status.",
    ("status",),
)

WEBHOOK_OLDEST_UNPROCESSED_AGE = _gauge(
    "email_platform_webhook_oldest_unprocessed_age_seconds",
    "Age of the oldest webhook delivery that is accepted but not yet normalized.",
)

PROVIDER_ACCOUNTS = _gauge(
    "email_platform_provider_accounts",
    "Provider accounts by status and health state.",
    ("status", "health_state"),
)

RETENTION_DELETED = _counter(
    "email_platform_retention_deleted_total",
    "Retention job deletions by dataset (raw_webhook, staged_upload, import_row).",
    ("dataset",),
)

METRICS_ERRORS = _counter(
    "email_platform_metrics_collection_errors_total",
    "Scrape-time collector failures; a non-zero value means some gauges are stale.",
)
