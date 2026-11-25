"""Observability (Day 9 Task 3): structured JSON logs + OpenTelemetry traces to X-Ray.

Logs: one JSON object per line on stdout (Fluent Bit ships them to CloudWatch Logs, where Logs
Insights can filter on any field). When a request is traced, its X-Ray trace id is in the line,
so a slow request in X-Ray leads straight to its log lines and back.

Traces: OpenTelemetry SDK -> OTLP/HTTP -> the CloudWatch agent (EKS add-on) -> X-Ray. X-Ray
style trace ids, and the ALB's X-Amzn-Trace-Id header is honoured. Sampled (default 10%) so a
50k-user test stays inside X-Ray's free 100,000 traces a month. Tracing is OFF unless
OTEL_EXPORTER_OTLP_ENDPOINT is set (tests, laptop).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

_configured = {"logging": False, "tracing": False}


def xray_trace_id() -> str | None:
    """The current span's trace id in X-Ray format (1-<8 hex time>-<24 hex>), if any."""
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover
        return None
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    h = f"{ctx.trace_id:032x}"
    return f"1-{h[:8]}-{h[8:]}"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": os.getenv("OTEL_SERVICE_NAME", "booking-api"),
        }
        if trace_id := xray_trace_id():
            line["trace_id"] = trace_id
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def setup_logging(level: str | None = None) -> None:
    """JSON lines on stdout for our loggers and uvicorn's (access log included)."""
    if _configured["logging"]:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level or os.getenv("LOG_LEVEL", "INFO"))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
    _configured["logging"] = True


def setup_tracing(app=None) -> bool:
    """Start the tracer if an OTLP endpoint is configured. Returns True if tracing is on."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if not endpoint or _configured["tracing"]:
        return _configured["tracing"]

    from opentelemetry import propagate, trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.propagators.aws import AwsXRayPropagator
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    ratio = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "0.1"))
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "booking-api"),
                "service.version": os.getenv("APP_VERSION", "dev"),
                "deployment.environment": os.getenv("ENVIRONMENT", "dev"),
            }
        ),
        id_generator=AwsXRayIdGenerator(),
        sampler=ParentBased(TraceIdRatioBased(ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
    # The ALB starts an X-Amzn-Trace-Id; keep W3C traceparent too.
    propagate.set_global_textmap(
        CompositePropagator([AwsXRayPropagator(), TraceContextTextMapPropagator()])
    )
    BotocoreInstrumentor().instrument()  # DynamoDB, Kinesis, SQS, Step Functions, Secrets
    RedisInstrumentor().instrument()
    # No SQLAlchemy instrumentation: 0.66b2 supports sqlalchemy < 2.1 only, and on our 2.1 it
    # imports the asyncio engine, which needs greenlet (not installed). Request spans still show
    # each endpoint's total time; RDS metrics show the database side.
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    _configured["tracing"] = True
    return True
