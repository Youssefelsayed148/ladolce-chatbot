import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "model_check", Path(__file__).resolve().parents[1] / "scripts" / "model_check.py")
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)


def _turn(tools=(), blocks=(), used=None, plates=(), reply="ok", chips=("a",)):
    return dict(tools=list(tools), blocks=list(blocks), max_used=used, plate_ids=list(plates),
                reply=reply, suggestions=list(chips), conversation_id="c")


GOOD = [
    _turn(["list_plate_sizes"], ["plate_size_options"]),
    _turn(["start_plate"], ["plate_builder"], 0, [1]),
    _turn(["add_item_to_plate"], ["plate_builder"], 6, [1]),
    _turn(["add_item_to_plate"], ["plate_builder"], 6, [1]),
    _turn(["set_finish"], ["plate_builder"], 6, [1]),
    _turn(["request_review"], ["review_order_button"], None, [], chips=()),
]


def test_good_flow_passes_everything():
    assert all(ok for _, ok in mc.evaluate(GOOD))


def test_model_that_skips_tools_fails():
    bad = list(GOOD)
    bad[1] = _turn([], [], None, [])  # "we've started a box" in prose only
    failed = [n for n, ok in mc.evaluate(bad) if not ok]
    assert "box started with start_plate" in failed


def test_restarting_the_box_and_tables_are_caught():
    bad = list(GOOD)
    bad[3] = _turn(["start_plate"], ["plate_builder"], 0, [2], reply="| a |\n|---|")
    failed = [n for n, ok in mc.evaluate(bad) if not ok]
    assert {"overfill refused, box not restarted", "only one box created in the whole flow",
            "no markdown tables in any reply"} <= set(failed)


def test_sse_parsing_and_summary():
    lines = ['data: {"type": "conversation", "conversation_id": "x"}',
             'data: {"type": "tool_call", "name": "start_plate", "arguments": {}}',
             'data: {"type": "token", "text": "Hi"}', "", "data: not json"]
    t = mc.summarize_turn(mc.parse_sse_lines(lines))
    assert t["tools"] == ["start_plate"] and t["reply"] == "Hi" and t["conversation_id"] == "x"
