"""Low-cardinality Prometheus request metrics."""

from prometheus_client import CollectorRegistry, Counter, Histogram


class RequestMetrics:
    """Keep per-application HTTP metrics in an isolated registry."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self._requests = Counter(
            "payagent_http_requests_total",
            "Completed HTTP requests",
            ("method", "route", "status"),
            registry=self.registry,
        )
        self._duration = Histogram(
            "payagent_http_request_duration_seconds",
            "HTTP request duration in seconds",
            ("method", "route"),
            registry=self.registry,
        )

    def observe(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        """Record one completed request using route templates, not raw paths."""
        self._requests.labels(method, route, str(status_code)).inc()
        self._duration.labels(method, route).observe(duration_seconds)
