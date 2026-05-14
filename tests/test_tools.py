"""Static tests for tool schemas — shape, naming, filtering."""
from __future__ import annotations

from saathi.llm import tools as T


def test_every_tool_has_required_fields():
    for tool in (
        T.SPEAK_TO_MOM, T.NOTIFY_DEEP, T.CONFIRM_UNDERSTANDING,
        T.SEARCH_MEDICINE, T.PLACE_MEDICINE_ORDER,
        T.SEARCH_GROCERY, T.ADD_GROCERY_TO_CART, T.GET_GROCERY_CART, T.PLACE_GROCERY_ORDER,
        T.FETCH_BILL, T.REQUEST_PAYMENT_VIA_DEEP,
    ):
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_tools_for_medicine():
    names = {t["name"] for t in T.tools_for("medicine")}
    assert "search_medicine" in names
    assert "place_medicine_order" in names
    assert "speak_to_mom" in names
    assert "notify_deep" in names
    assert "search_grocery" not in names  # filtered
    assert "fetch_bill" not in names


def test_tools_for_grocery():
    names = {t["name"] for t in T.tools_for("grocery")}
    assert {"search_grocery", "add_grocery_to_cart", "get_grocery_cart",
            "place_grocery_order"} <= names
    assert "search_medicine" not in names


def test_tools_for_bill():
    names = {t["name"] for t in T.tools_for("bill")}
    assert {"fetch_bill", "request_payment_via_deep"} <= names
    assert "search_medicine" not in names


def test_tools_for_unknown_returns_shared_only():
    names = {t["name"] for t in T.tools_for("chitchat")}
    assert names == {"speak_to_mom", "notify_deep", "confirm_understanding"}


def test_tool_count_per_intent_under_attention_threshold():
    """Per PLAN §3.3: keep per-subagent tool count manageable."""
    for intent in ("medicine", "grocery", "bill"):
        assert len(T.tools_for(intent)) <= 8, f"{intent} has too many tools"
