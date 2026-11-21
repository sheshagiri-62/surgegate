from sg_queue import serving
from tests.conftest import body, open_queue


def get(event_id):
    return serving.handler({"pathParameters": {"event": event_id}}, None)  # no JWT: public


def test_serving_is_public_cacheable_and_the_same_for_everyone(aws):
    ev = open_queue(aws["table"], serving_up_to=250, admission_rate=125)
    r = get(ev)
    assert r["statusCode"] == 200
    assert r["headers"]["Cache-Control"] == "public, max-age=5"
    assert body(r)["serving_up_to"] == 250 and body(r)["admission_rate"] == 125
    assert "queue_token" not in body(r) and "position" not in body(r)  # nothing personal


def test_paused_queue_reports_rate_zero(aws):
    ev = open_queue(aws["table"], status="paused", admission_rate=125)
    assert body(get(ev))["admission_rate"] == 0


def test_state_is_cached_in_the_function_for_two_seconds(aws, monkeypatch):
    ev = open_queue(aws["table"], serving_up_to=1)
    get(ev)
    aws["table"].update_item(
        Key={"PK": f"EVENT#{ev}", "SK": "META"},
        UpdateExpression="SET serving_up_to = :n",
        ExpressionAttributeValues={":n": 99},
    )
    assert body(get(ev))["serving_up_to"] == 1  # still cached
    from sg_queue import common

    common._meta_cache.clear()  # (time passing)
    assert body(get(ev))["serving_up_to"] == 99


def test_unknown_or_bad_event_is_404(aws):
    assert get("00000000-0000-4000-8000-000000000000")["statusCode"] == 404
    assert get("nope")["statusCode"] == 404
