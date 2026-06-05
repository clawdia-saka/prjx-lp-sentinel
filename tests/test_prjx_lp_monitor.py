import importlib.util
import pathlib
import sys
import unittest


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "prjx_lp_monitor.py"
spec = importlib.util.spec_from_file_location("prjx_lp_monitor", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not import {MODULE_PATH}")
prjx = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = prjx
spec.loader.exec_module(prjx)


def position(
    *,
    value_usd=100.0,
    price=100.0,
    lower_price=96.5,
    upper_price=130.0,
    fee_amount0=0.0,
    fee_amount1=0.0,
    swap_price=None,
    swap_age_blocks=None,
):
    return prjx.Position(
        position_id="test-1",
        pool="WHYPE/USDC 0.05%",
        token0=prjx.TokenMeta("0x0", "WHYPE", 18),
        token1=prjx.TokenMeta("0x1", "USDC", 6),
        tick=10,
        tick_lower=0,
        tick_upper=20,
        price=price,
        lower_price=lower_price,
        upper_price=upper_price,
        amount0=1.0,
        amount1=100.0,
        fee_amount0=fee_amount0,
        fee_amount1=fee_amount1,
        liquidity=123,
        pool_address="0xpool",
        value_usd=value_usd,
        cost_basis_usd=None,
        fees_usd=0.0,
        rewards_usd=0.0,
        entry_price=None,
        swap_price=swap_price,
        swap_age_blocks=swap_age_blocks,
    )


def cfg(*, min_alert_value_usd=25.0, performance=False):
    data = {
        "wallet": "0xwallet",
        "language": "ja",
        "thresholds": {
            "near_range_edge_pct": 5.0,
            "impermanent_loss_pct": -3.0,
            "roi_pct": -5.0,
            "min_alert_value_usd": min_alert_value_usd,
        },
        "pricing": {"stable_symbols": ["USDC"], "usd_prices": {}},
    }
    if performance:
        data["performance"] = {"enabled": True, "auto_baseline": True, "min_apr_days": 1.0}
    return data


def cooldown_event(*, price=100.0, edge_distance_pct=4.0, severity="warn"):
    return {
        "kind": "NEAR_RANGE_EDGE",
        "severity": severity,
        "position_id": "test-1",
        "pool": "WHYPE/USDC 0.05%",
        "detail": f"edge {edge_distance_pct}",
        "price": price,
        "edge_distance_pct": edge_distance_pct,
        "status": "IN_RANGE",
    }


class TestPrjxLpMonitor(unittest.TestCase):
    def test_swap_topic_hash_is_32_bytes(self):
        self.assertEqual(len(prjx.SWAP_TOPIC0), 66)

    def test_near_edge_alert_names_lower_edge_direction(self):
        lines, events = prjx.evaluate([position()], cfg())

        self.assertIn("下限まで", lines[1])
        self.assertEqual([event["kind"] for event in events], ["NEAR_RANGE_EDGE"])
        self.assertIn("下限まで", events[0]["detail"])
        self.assertIn("下限より上", events[0]["detail"])

    def test_dust_near_edge_is_muted_but_visible_in_snapshot(self):
        lines, events = prjx.evaluate([position(value_usd=1.31)], cfg(min_alert_value_usd=25.0))

        self.assertEqual(events, [])
        self.assertIn("手動リバランス確認", lines[1])
        self.assertIn("通知抑制: 評価額 < $25.00", lines[1])

    def test_upper_edge_direction_is_reported(self):
        lines, events = prjx.evaluate(
            [position(price=100.0, lower_price=70.0, upper_price=103.0)],
            cfg(min_alert_value_usd=0),
        )

        self.assertIn("上限まで", lines[1])
        self.assertEqual(events[0]["kind"], "NEAR_RANGE_EDGE")
        self.assertIn("上限まで", events[0]["detail"])
        self.assertIn("上限より下", events[0]["detail"])

    def test_alert_message_headers_are_japanese(self):
        lines, events = prjx.evaluate([position()], cfg())
        message = prjx.build_alert_message(lines, events, cfg())

        self.assertIn("🚨 アラート:", message)
        self.assertIn("🎯 先に結論:", message)
        self.assertIn("⚠️ 警告 レンジ端接近", message)
        self.assertIn("📸 スナップショット:", message)

    def test_alert_message_uses_blank_lines_between_cards(self):
        lines, events = prjx.evaluate([position()], cfg())
        message = prjx.build_alert_message(lines, events, cfg())

        self.assertIn("📸 スナップショット:\n\n📊 PRJX LP Sentinel", message)
        self.assertIn("\n\n🟡 WHYPE/USDC 0.05% #test-1", message)

    def test_snapshot_uses_readable_telegram_cards(self):
        lines, _events = prjx.evaluate([position(swap_price=99.0, swap_age_blocks=12)], cfg())

        self.assertIn("📊 PRJX LP Sentinel", lines[0])
        self.assertIn("\n", lines[0])
        self.assertIn("💰 評価額", lines[0])
        self.assertIn("🟡 WHYPE/USDC 0.05% #test-1", lines[1])
        self.assertIn("\n📍 状態", lines[1])
        self.assertIn("\n🔁 直近Swap", lines[1])
        self.assertIn("\n🧭 判断: 手動リバランス確認", lines[1])

    def test_collectable_fees_are_valued_in_usd(self):
        lines, _events = prjx.evaluate([position(fee_amount0=0.1, fee_amount1=1.0)], cfg())

        self.assertIn("未回収手数料 $11.00", lines[1])

    def test_observed_baseline_profit_daily_and_apr(self):
        state = {}
        config = cfg(performance=True)

        first_lines, _events = prjx.evaluate([position(value_usd=100.0)], config, state=state, now_ts=1_000_000)
        self.assertIn("観測原価 $100.00", first_lines[0])
        self.assertIn("実利 $0.00(+0.00%)", first_lines[0])
        self.assertEqual(state["performance"]["baselines"]["test-1"]["equity_usd"], 100.0)

        second_lines, _events = prjx.evaluate([position(value_usd=110.0)], config, state=state, now_ts=1_000_000 + 86_400)
        self.assertIn("実利 $10.00(+10.00%)", second_lines[0])
        self.assertIn("日次平均 +10.00%", second_lines[0])
        self.assertIn("APR +3650.00%", second_lines[0])

    def test_recent_swap_rate_is_included_in_snapshot(self):
        lines, _events = prjx.evaluate([position(swap_price=99.0, swap_age_blocks=12)], cfg())

        self.assertIn("直近Swap 99", lines[1])
        self.assertIn("乖離 -1.00%", lines[1])
        self.assertIn("12blk前", lines[1])

    def test_swap_rate_deviation_can_raise_warning(self):
        config = cfg(min_alert_value_usd=0)
        config["pricing"]["swap_rate_overlay"] = {"deviation_warn_pct": 2.0}

        _lines, events = prjx.evaluate([position(swap_price=95.0)], config)

        self.assertIn("SWAP_RATE_DEVIATION", [event["kind"] for event in events])
        self.assertIn("直近Swap", events[-1]["detail"])

    def test_vol_forecast_summary_and_fit_are_rendered(self):
        forecast = {
            "enabled": True,
            "regime": "wide",
            "sample_days": 120,
            "current_price": 100.0,
            "median_pct": 6.0,
            "p75_pct": 8.0,
            "p90_pct": 12.0,
            "last_range_pct": 9.0,
            "p75_lower": 96.0,
            "p75_upper": 104.0,
            "p90_lower": 94.0,
            "p90_upper": 106.0,
            "btc_dvol": 50.0,
            "eth_dvol": 60.0,
            "vix": 18.0,
            "errors": [],
        }

        lines = prjx.format_vol_forecast(forecast, ja=True)
        self.assertIn("🌦 予測レンジ(VIX/BitVol文脈)", "\n".join(lines))
        self.assertIn("p75目安 96 - 104", "\n".join(lines))
        self.assertIn("自動リバランスなし", "\n".join(lines))

        self.assertIn("p75帯OK", prjx.vol_fit_text(position(lower_price=95.0), forecast, ja=True))
        self.assertIn(
            "下限割れ注意",
            prjx.vol_fit_text(position(lower_price=99.0, upper_price=130.0), forecast, ja=True),
        )

    def test_cooldown_suppresses_small_repeat_event(self):
        state = {}
        send_cfg = {
            "cooldown_bypass_price_move_pct": 2.0,
            "cooldown_bypass_edge_move_pct": 1.0,
            "cooldown_bypass_on_severity_escalation": True,
        }

        first = prjx.filter_events_for_cooldown([cooldown_event()], state, 180, send_cfg)
        repeat = prjx.filter_events_for_cooldown(
            [cooldown_event(price=100.5, edge_distance_pct=3.8)],
            state,
            180,
            send_cfg,
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(repeat, [])

    def test_cooldown_allows_material_move_bypass(self):
        state = {}
        send_cfg = {
            "cooldown_bypass_price_move_pct": 2.0,
            "cooldown_bypass_edge_move_pct": 1.0,
            "cooldown_bypass_on_severity_escalation": True,
        }

        prjx.filter_events_for_cooldown([cooldown_event()], state, 180, send_cfg)
        price_move = prjx.filter_events_for_cooldown(
            [cooldown_event(price=102.1, edge_distance_pct=3.8)],
            state,
            180,
            send_cfg,
        )
        edge_move = prjx.filter_events_for_cooldown(
            [cooldown_event(price=102.2, edge_distance_pct=2.7)],
            state,
            180,
            send_cfg,
        )

        self.assertEqual(price_move[0]["cooldown_override_reason"], "price_move")
        self.assertEqual(edge_move[0]["cooldown_override_reason"], "edge_move")

    def test_cooldown_allows_severity_escalation_bypass(self):
        state = {}
        send_cfg = {
            "cooldown_bypass_price_move_pct": 2.0,
            "cooldown_bypass_edge_move_pct": 1.0,
            "cooldown_bypass_on_severity_escalation": True,
        }

        prjx.filter_events_for_cooldown([cooldown_event(severity="warn")], state, 180, send_cfg)
        critical = prjx.filter_events_for_cooldown(
            [cooldown_event(price=100.0, edge_distance_pct=4.0, severity="critical")],
            state,
            180,
            send_cfg,
        )

        self.assertEqual(critical[0]["cooldown_override_reason"], "severity_escalation")


if __name__ == "__main__":
    unittest.main()
