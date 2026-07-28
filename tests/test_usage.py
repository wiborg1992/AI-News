"""Tokenforbrug og omkostningsestimat."""

from types import SimpleNamespace

from ai_news.config import load_config
from ai_news.llm import UsageTracker

PRICES = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
}


def _usage(inp=0, out=0, cache_read=0, cache_write=0):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def test_cost_is_computed_per_model():
    t = UsageTracker()
    t.record("claude-haiku-4-5", _usage(1_000_000, 1_000_000))
    # 1 USD input + 5 USD output
    assert t.cost_usd(PRICES) == 6.0


def test_cost_sums_across_models():
    t = UsageTracker()
    t.record("claude-haiku-4-5", _usage(1_000_000, 0))      # 1.00
    t.record("claude-sonnet-5", _usage(0, 1_000_000))       # 10.00
    assert t.cost_usd(PRICES) == 11.0


def test_calls_and_totals_accumulate():
    t = UsageTracker()
    t.record("claude-haiku-4-5", _usage(100, 20))
    t.record("claude-haiku-4-5", _usage(300, 40))
    assert t.calls == 2
    assert t.input_tokens == 400
    assert t.output_tokens == 60


def test_cache_tokens_are_priced_differently():
    """Cache-læsning er ~0,1x input; cache-skrivning ~1,25x."""
    t = UsageTracker()
    t.record("claude-haiku-4-5", _usage(cache_read=1_000_000))
    assert round(t.cost_usd(PRICES), 4) == 0.10

    t2 = UsageTracker()
    t2.record("claude-haiku-4-5", _usage(cache_write=1_000_000))
    assert round(t2.cost_usd(PRICES), 4) == 1.25


def test_unknown_model_costs_zero_but_is_flagged():
    t = UsageTracker()
    t.record("en-ukendt-model", _usage(1_000_000, 1_000_000))
    assert t.cost_usd(PRICES) == 0.0
    assert any("ukendt pris" in line for line in t.report(PRICES))


def test_report_without_calls():
    assert UsageTracker().report(PRICES) == ["LLM-forbrug: ingen API-kald i denne kørsel."]


def test_report_includes_dkk_when_rate_given():
    t = UsageTracker()
    t.record("claude-haiku-4-5", _usage(1_000_000, 0))
    assert "DKK" in t.report(PRICES, dkk_per_usd=7.0)[-1]
    assert "DKK" not in t.report(PRICES, dkk_per_usd=0)[-1]


def test_config_loads_prices():
    cfg = load_config("config.yaml")
    assert cfg.prices[cfg.scoring_model]["input"] > 0
    assert cfg.prices[cfg.summary_model]["output"] > 0
    assert cfg.dkk_per_usd > 0
