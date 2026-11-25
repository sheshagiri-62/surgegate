"""Requests straight to execute-api (no CloudFront origin header) are refused when required."""

import pytest

from sg_queue import common


def _event(header=None):
    return {"headers": {"x-origin-verify": header} if header is not None else {}}


@pytest.fixture
def required(monkeypatch):
    monkeypatch.setenv("ORIGIN_VERIFY_REQUIRED", "true")
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET", "s" * 48)
    monkeypatch.setenv("ORIGIN_VERIFY_HEADER", "x-origin-verify")


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("ORIGIN_VERIFY_REQUIRED", raising=False)
    assert common.from_edge(_event())


def test_required_needs_the_exact_secret(required):
    assert common.from_edge(_event("s" * 48))
    assert not common.from_edge(_event())
    assert not common.from_edge(_event("s" * 47))
    assert not common.from_edge(_event("x" * 48))


def test_required_without_a_secret_refuses(monkeypatch, required):
    monkeypatch.setenv("ORIGIN_VERIFY_SECRET", "")
    assert not common.from_edge(_event(""))


def test_handlers_are_wrapped(required):
    from sg_queue import admit, join, position, serving

    for mod in (join, position, admit, serving):
        r = mod.handler({"headers": {}, "pathParameters": {"event": "x"}}, None)
        assert r["statusCode"] == 403 and "site's address" in r["body"], mod.__name__
