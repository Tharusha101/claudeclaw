"""OTLP metrics parsing + the usage meter + the receiver endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bridge import create_app
from models import DENY
from telemetry import UsageMeter, parse_metrics
from tests.fake_transport import FakeTransport


def _export(cost, in_tok, out_tok, session="s1"):
    def _dp(value, extra_key, extra_val, is_int):
        num = {"asInt": value} if is_int else {"asDouble": value}
        return {
            **num,
            "attributes": [
                {"key": "session.id", "value": {"stringValue": session}},
                {"key": extra_key, "value": {"stringValue": extra_val}},
            ],
        }

    return {
        "resourceMetrics": [
            {
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "claude_code.cost.usage",
                                "sum": {"dataPoints": [_dp(cost, "model", "opus", False)]},
                            },
                            {
                                "name": "claude_code.token.usage",
                                "sum": {
                                    "dataPoints": [
                                        _dp(in_tok, "type", "input", True),
                                        _dp(out_tok, "type", "output", True),
                                    ]
                                },
                            },
                        ]
                    }
                ]
            }
        ]
    }


def test_parse_sums_tokens_across_types():
    cost, tokens = parse_metrics(_export(0.42, 1000, 500))
    assert cost == {"s1": 0.42}
    assert tokens == {"s1": 1500.0}


def test_meter_totals_and_percent():
    meter = UsageMeter(budget_usd=2.0)
    meter.update(_export(0.50, 1000, 500, session="s1"))
    meter.update(_export(0.30, 200, 100, session="s2"))  # a second session adds on
    assert round(meter.cost, 2) == 0.80
    assert meter.tokens == 1800
    assert meter.percent == 40  # 0.80 / 2.00


def test_otlp_endpoint_updates_meter_and_pushes_to_keytag():
    fake = FakeTransport(DENY)
    client = TestClient(create_app(fake, budget_usd=10.0))

    r = client.post("/v1/metrics", json=_export(1.00, 3000, 1000))
    assert r.status_code == 200

    body = client.get("/usage").json()
    assert body == {"cost_usd": 1.0, "tokens": 4000, "budget_usd": 10.0, "percent": 10}
    assert fake.usages[-1] == (1.0, 4000, 10)  # pushed to the keytag
