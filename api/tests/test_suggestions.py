from app.services.suggestions import rule_suggestions


def test_box_in_progress_points_at_dates_and_finish():
    blocks = [{"type": "plate_builder", "data": {"capacity_used": 3, "capacity_total": 18}}]
    chips = rule_suggestions("add ajwa", ["add_item_to_plate"], blocks)
    assert "Choose a ribbon finish" in chips and len(chips) == 3


def test_full_box_points_at_finish_gift_review():
    blocks = [{"type": "plate_builder", "data": {"capacity_used": 18, "capacity_total": 18}}]
    assert rule_suggestions("add", ["add_item_to_plate"], blocks) == [
        "Choose a ribbon finish", "Add a gift message", "Review my order"]


def test_box_flow_progression():
    assert rule_suggestions("", ["set_finish"], [])[0] == "Add a gift message"
    assert rule_suggestions("", ["set_gift_message"], [])[0] == "Review my order"
    assert rule_suggestions("", ["request_review"], [{"type": "review_order_button"}]) == []
    # refused review (no button) still gets helpful chips
    assert rule_suggestions("", ["request_review"], [])[0] == "Choose a ribbon finish"


def test_sizes_listing_gets_size_questions():
    assert "Which size is best for a gift?" in rule_suggestions("sizes?", ["list_plate_sizes"], [])


def test_policy_topics_are_scoped_to_the_question():
    ship = rule_suggestions("Do you ship internationally?", ["search_knowledge_base"], [])
    assert "How long does delivery take?" in ship
    ret = rule_suggestions("what is the return policy", ["search_knowledge_base"], [])
    assert "What is your return policy?" in ret
    assert ship != ret


def test_product_search_with_cards_offers_add():
    blocks = [{"type": "product_card", "data": {"name": "Pistachio Date Paste"}}]
    assert rule_suggestions("pistachio", ["search_products"], blocks)[0] == "Add Pistachio Date Paste to my order"


def test_no_tools_means_no_rule():
    assert rule_suggestions("hello", [], []) == []


from app.services.suggestions import drop_impossible  # noqa: E402


def _card(name, labels=()):
    return {"type": "product_card", "data": {
        "name": name, "variants": [{"variant_id": i, "label": l, "price": 1} for i, l in enumerate(labels)]}}


def test_bestsellers_offer_boxes_custom_and_sizes():
    chips = rule_suggestions("What are your best sellers?", ["search_products"], [_card("Khudri", ["500g / S"])])
    assert chips == ["Show me gift boxes", "Build me a custom box", "What sizes do you have?"]


def test_variant_card_offers_the_other_weight_not_a_blind_add():
    chips = rule_suggestions(
        "khudri almond", ["search_products"], [_card("Khudri Dates with Almond", ["500g / S", "500g / M", "1kg / L"])]
    )
    assert chips[0] == "Which is better value, 500g or 1kg?"
    assert "Add the first one to my order" not in chips


def test_single_option_card_offers_a_named_add():
    chips = rule_suggestions("royal", ["search_products"], [_card("The Royal Assortment")])
    assert chips[0] == "Add The Royal Assortment to my order"
    chips = rule_suggestions("x", ["search_products"], [_card("Khudri", ["500g"])])
    assert chips[0] == "Add Khudri to my order"


def test_failed_add_does_not_offer_review():
    chips = rule_suggestions("add it", ["add_single_product"], [], failed_tools=["add_single_product"])
    assert not any("review" in c.lower() for c in chips)
    assert chips  # still useful


def test_empty_cart_summary_does_not_offer_review():
    chips = rule_suggestions("my cart", ["get_cart_summary"], [], cart_empty=True)
    assert not any("review" in c.lower() for c in chips)


def test_drop_impossible_actions():
    chips = ["Review my order", "Choose a ribbon finish", "Add a gift message", "Which dates can I add?",
             "Show me gift boxes", "Build me a custom box"]
    assert drop_impossible(chips, cart_empty=True, has_box=False) == ["Show me gift boxes", "Build me a custom box"]
    kept = drop_impossible(["Review my order", "Choose a ribbon finish"], cart_empty=False, has_box=True)
    assert kept == ["Review my order", "Choose a ribbon finish"]
    # a cart with only a pack: review works, box steps do not
    assert drop_impossible(["Review my order", "Add a gift message"], cart_empty=False, has_box=False) == ["Review my order"]
