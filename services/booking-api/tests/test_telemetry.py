"""Structured logs (JSON with the X-Ray trace id) and the tracer setup switch."""

import json
import logging
import re

from opentelemetry import trace
from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
from opentelemetry.sdk.trace import TracerProvider

from app import telemetry


def _line(msg="hello", **kw):
    rec = logging.LogRecord("app.test", logging.INFO, __file__, 1, msg, (), None)
    return json.loads(telemetry.JsonFormatter().format(rec))


def test_log_line_is_json_with_the_fields_we_query():
    line = _line()
    assert line["message"] == "hello" and line["level"] == "INFO" and line["logger"] == "app.test"
    assert line["service"] == "booking-api" and line["time"].endswith("+00:00")
    assert "trace_id" not in line  # nothing traced


def test_log_line_carries_the_xray_trace_id_inside_a_span():
    tracer = TracerProvider(id_generator=AwsXRayIdGenerator()).get_tracer("t")
    with tracer.start_as_current_span("request"):
        line = _line()
        ctx = trace.get_current_span().get_span_context()
    assert re.fullmatch(r"1-[0-9a-f]{8}-[0-9a-f]{24}", line["trace_id"])
    assert line["trace_id"].replace("-", "")[1:] == f"{ctx.trace_id:032x}"


def test_exceptions_are_kept_in_one_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    out = telemetry.JsonFormatter().format(rec)
    assert "\n" not in out and "ValueError: boom" in json.loads(out)["exception"]


def test_tracing_is_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setitem(telemetry._configured, "tracing", False)
    assert telemetry.setup_tracing() is False
