"""OT-28: the metered lane tells the truth about itself.

A lane that charges money per call must be able to say two things the
harness could not say before: how wide the served model's context is,
and what a run has spent. Both are read from the provider — never
tabled, never assumed — and the second is what NFR-27's cap is built on.
"""

from __future__ import annotations

import pytest

from blended.agent.loop import (
    BMB_ENDPOINT,
    LOCAL_ENDPOINT,
    MAXIMUM_RUN_COST_USD,
    OPENROUTER_ENDPOINT,
    OPENROUTER_MODELS_PATH,
    ContextUndiscovered,
    ModelConfig,
    OllamaClient,
    RunCostExceeded,
    _turn_cost_from_body,
)

# Read from OpenRouter's catalogue 2026-09-10; the harness's metered
# writer and its own eye — tools, structured outputs, text and image.
METERED_MODEL = "deepseek/deepseek-v4.1-flash"
METERED_WINDOW = 1_048_576


def _metered_config(**overrides) -> ModelConfig:
    fields = {
        "model": METERED_MODEL,
        "endpoint": OPENROUTER_ENDPOINT,
        "vision_model": "",
        "api_key": "sk-or-test",
    }
    fields.update(overrides)
    return ModelConfig(**fields)


def _catalogue(monkeypatch, entries, reply=None):
    """A fake OpenRouter answering /v1/models and then chat."""
    calls = []

    def fake_request(self, path, payload, timeout_seconds):
        calls.append((path, payload))
        if path == OPENROUTER_MODELS_PATH:
            return {"data": entries}
        return reply or {
            "choices": [{"message": {"role": "assistant", "content": "pong"}}],
            "usage": {"prompt_tokens": 36, "completion_tokens": 17, "cost": 0.0000312},
        }

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    return calls


def test_the_window_comes_from_the_catalogue_not_a_table(monkeypatch):
    calls = _catalogue(monkeypatch, [{"id": METERED_MODEL, "context_length": METERED_WINDOW}])
    client = OllamaClient(_metered_config())
    assert client.config.context_tokens is None

    status = client.check_connection()

    assert status.ok and "OpenRouter (metered per token)" in status.detail
    assert f"context {METERED_WINDOW:,}" in status.detail
    assert calls[0] == (OPENROUTER_MODELS_PATH, None)  # the catalogue before the ping
    assert client.config.context_tokens == METERED_WINDOW


def test_an_id_the_catalogue_does_not_list_is_refused_by_name(monkeypatch):
    _catalogue(monkeypatch, [{"id": "someone/else", "context_length": 4096}])
    client = OllamaClient(_metered_config(model="deepseek/typo-here"))

    status = client.check_connection()

    assert not status.ok
    assert "deepseek/typo-here is not in OpenRouter's catalogue" in status.detail
    assert "1 ids" in status.detail  # what the endpoint did serve


def test_a_catalogue_entry_without_a_window_is_refused(monkeypatch):
    _catalogue(monkeypatch, [{"id": METERED_MODEL, "context_length": 0}])
    client = OllamaClient(_metered_config())
    with pytest.raises(ContextUndiscovered, match="context_length"):
        client.discover_context()


def test_the_price_is_asked_for_on_this_lane_and_on_no_other():
    metered = OllamaClient(_metered_config())._chat_payload([{"role": "user", "content": "x"}])
    assert metered["usage"] == {"include": True}

    llama_swap = OllamaClient(
        ModelConfig(model="qwen3.8-27b", endpoint=BMB_ENDPOINT, vision_model="", api_key="k")
    )._chat_payload([{"role": "user", "content": "x"}])
    assert "usage" not in llama_swap  # our own hardware charges nothing

    daemon = OllamaClient(
        ModelConfig(model="anything", endpoint=LOCAL_ENDPOINT, vision_model="", context_length=32_768)
    )._chat_payload([{"role": "user", "content": "x"}])
    assert "usage" not in daemon


def test_cost_comes_off_the_usage_object_and_stays_zero_where_none_is_reported():
    # OpenRouter, with the extension: a real measured reply (2026-09-10).
    priced = _turn_cost_from_body(
        {"usage": {"prompt_tokens": 36, "completion_tokens": 17, "cost": 0.0000312}}
    )
    assert priced.cost_usd == pytest.approx(0.0000312)
    assert priced.input_tokens == 36 and priced.output_tokens == 17

    # llama-swap fills in usage but never a price: zero means "charged
    # nothing", not "unknown".
    free = _turn_cost_from_body({"usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    assert free.cost_usd == 0.0 and free.input_tokens == 100

    # The Ollama wire reports neither shape.
    ollama = _turn_cost_from_body({"prompt_eval_count": 7, "eval_count": 3})
    assert ollama.cost_usd == 0.0 and ollama.output_tokens == 3


def test_a_metered_run_stops_at_its_cap_with_both_numbers_named(monkeypatch):
    expensive = {
        "choices": [{"message": {"role": "assistant", "content": "..."}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1000, "cost": 0.2},
    }
    _catalogue(monkeypatch, [{"id": METERED_MODEL, "context_length": METERED_WINDOW}], reply=expensive)
    client = OllamaClient(_metered_config(maximum_run_cost_usd=0.30))
    client.check_connection()

    client.chat([{"role": "user", "content": "one"}])  # $0.20, under the cap
    assert client.spent.cost_usd == pytest.approx(0.2)

    with pytest.raises(RunCostExceeded) as refusal:
        client.chat([{"role": "user", "content": "two"}])  # $0.40, over it
    message = str(refusal.value)
    assert "$0.4000" in message and "$0.3000" in message and "NFR-27" in message
    assert METERED_MODEL in message


def test_only_a_metered_lane_is_capped(monkeypatch):
    """bmb's llama-swap bills nothing per call, so a long run there is
    not a spending accident and must never be stopped as one."""
    def fake_request(self, path, payload, timeout_seconds):
        return {
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            # Big, but inside bmb's 65,536 window: this test is about
            # money, and a prompt over the window is a different error.
            "usage": {"prompt_tokens": 60_000, "completion_tokens": 5000},
        }

    monkeypatch.setattr(OllamaClient, "_request", fake_request)
    client = OllamaClient(
        ModelConfig(model="qwen3.8-27b", endpoint=BMB_ENDPOINT, vision_model="", api_key="k", maximum_run_cost_usd=0.01)
    )
    assert not client.config.is_metered
    client.chat([{"role": "user", "content": "x"}])
    assert client.spent.cost_usd == 0.0


def test_the_cap_is_derived_from_the_heaviest_measured_run():
    """iteration 88 (three_leg_stool, the heaviest run on the disclosed
    surface): 1,353,594 billed input + 24,615 output tokens. At this
    lane's published $0.15/M and $0.60/M that run costs $0.218, and the
    cap must clear it with room."""
    heaviest = 1_353_594 * 0.15 / 1e6 + 24_615 * 0.60 / 1e6
    assert heaviest == pytest.approx(0.2178, abs=1e-4)
    assert MAXIMUM_RUN_COST_USD > heaviest
    assert MAXIMUM_RUN_COST_USD == 0.50
