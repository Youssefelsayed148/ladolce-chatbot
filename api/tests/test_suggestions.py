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
    blocks = [{"type": "product_card", "data": {}}]
    assert rule_suggestions("pistachio", ["search_products"], blocks)[0] == "Add the first one to my order"


def test_no_tools_means_no_rule():
    assert rule_suggestions("hello", [], []) == []
