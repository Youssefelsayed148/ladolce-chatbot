"""Scripted order flow against a running chat API, to compare LLM models.

Usage (against the live stack, or local):
    python scripts/model_check.py --base-url https://chat.example.com --label gpt-4.1-mini

Set LLM_MODEL in the server's .env, redeploy, run this, repeat per model. Each step
checks what the guest would see (cards) and which tools the model really called.
Uses one fresh conversation; creates a cart draft (no order is placed). Mind the
chat rate limit (default 20/minute): the flow sends 7 messages.
"""

import argparse
import json
import sys

import httpx

# (message, check name, predicate over that turn's summary)
STEPS = [
    ("what sizes do the boxes come in", "size cards shown",
     lambda t, s: "plate_size_options" in t["blocks"]),
    ("I'd like to build a custom box in The Classic Petite.", "box started with start_plate",
     lambda t, s: "start_plate" in t["tools"] and "plate_builder" in t["blocks"]),
    ("add 6 Ajwa Date to my box", "dates added with add_item_to_plate",
     lambda t, s: "add_item_to_plate" in t["tools"] and t["max_used"] == 6),
    ("add 40 Jordanian Majdool Date to my box", "overfill refused, box not restarted",
     lambda t, s: "start_plate" not in t["tools"] and (t["max_used"] or 0) <= 18),
    ("use the Royal Gold ribbon", "ribbon set with set_finish",
     lambda t, s: "set_finish" in t["tools"]),
    ("review my order", "review requested",
     lambda t, s: "request_review" in t["tools"] and "review_order_button" in t["blocks"]),
]


def parse_sse_lines(lines) -> list[dict]:
    events = []
    for line in lines:
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def summarize_turn(events: list[dict]) -> dict:
    blocks = [e["block"] for e in events if e["type"] == "ui_block"]
    plates = [b["data"] for b in blocks if b["type"] == "plate_builder"]
    reply = "".join(e["text"] for e in events if e["type"] == "token")
    suggestions = next((e["suggestions"] for e in reversed(events) if e["type"] == "suggestions_block"), [])
    return {
        "tools": [e["name"] for e in events if e["type"] == "tool_call"],
        "blocks": [b["type"] for b in blocks],
        "plate_ids": sorted({p["cart_item_id"] for p in plates}),
        "max_used": max((p["capacity_used"] for p in plates), default=None),
        "reply": reply,
        "suggestions": suggestions,
        "conversation_id": next((e["conversation_id"] for e in events if e["type"] == "conversation"), None),
    }


def evaluate(turns: list[dict]) -> list[tuple[str, bool]]:
    """Per-step results plus flow-wide checks, from the summarized turns."""
    results = [(name, bool(pred(t, None))) for (_, name, pred), t in zip(STEPS, turns)]
    all_plate_ids = {i for t in turns for i in t["plate_ids"]}
    results.append(("only one box created in the whole flow", len(all_plate_ids) <= 1))
    results.append(("no markdown tables in any reply", not any("|---" in t["reply"] for t in turns)))
    results.append(("follow-up chips on every turn", all(len(t["suggestions"]) > 0 for t in turns[:-1])))
    return results


def run(base_url: str) -> list[dict]:
    turns, conversation_id = [], None
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=120) as client:
        for message, _, _ in STEPS:
            with client.stream("POST", "/api/chat",
                               json={"message": message, "conversation_id": conversation_id}) as resp:
                resp.raise_for_status()
                events = parse_sse_lines(resp.iter_lines())
            turn = summarize_turn(events)
            conversation_id = turn["conversation_id"] or conversation_id
            turns.append(turn)
            print(f"  > {message}\n    tools={turn['tools']} blocks={turn['blocks']}")
    return turns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--label", default="", help="model name, for the report header only")
    args = ap.parse_args()

    print(f"Model check {args.label} against {args.base_url}")
    results = evaluate(run(args.base_url))
    failed = [name for name, ok in results if not ok]
    print()
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (" - OK to use" if not failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
