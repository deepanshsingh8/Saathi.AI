"""Tool schemas for the Sonnet orchestrator (Anthropic native shape).

Each tool dict has ``name``, ``description``, ``input_schema``. The orchestrator
runs the agent loop, dispatches tool_use blocks to Python implementations
(see ``orchestrator.py::TOOL_IMPL``), and threads results back as tool_result
blocks.
"""
from __future__ import annotations

# ─── Shared tools (every subagent gets these) ─────────────────────────────────

SPEAK_TO_MOM = {
    "name": "speak_to_mom",
    "description": (
        "Send a Hindi voice message to Mom on WhatsApp. Use for confirmations, "
        "summaries, and updates. Optionally include 2–3 reply buttons."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": (
                    "Hindi text. Pronunciation overrides are applied "
                    "automatically before TTS. Numbers ≥ ₹100 must be in Hindi words."
                ),
            },
            "buttons": {
                "type": "array",
                "items": {"type": "string", "maxLength": 20},
                "description": "Optional 2–3 reply buttons, e.g. ['हाँ', 'नहीं'].",
                "maxItems": 3,
            },
        },
        "required": ["text"],
    },
}

NOTIFY_DEEP = {
    "name": "notify_deep",
    "description": (
        "Escalate to Deep via Telegram. Use only when blocked or when "
        "confidence is below 0.8 on a high-stakes action."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {"type": "string", "enum": ["info", "warning", "blocked"]},
            "message": {"type": "string"},
        },
        "required": ["severity", "message"],
    },
}

CONFIRM_UNDERSTANDING = {
    "name": "confirm_understanding",
    "description": (
        "Day 6 polish gate: state your understanding of Mom's request and your "
        "confidence (0..1). The orchestrator forces a second voice confirmation "
        "with Mom if confidence < 0.85 before any irreversible action."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
        "required": ["summary", "confidence"],
    },
}

# ─── Medicine ────────────────────────────────────────────────────────────────

SEARCH_MEDICINE = {
    "name": "search_medicine",
    "description": (
        "Search 1mg / PharmEasy for a medicine by name. Returns up to 3 results "
        "with sku, brand, dose, mrp (₹), eta_hours, cod_available."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "e.g. 'Telma 40' or 'टेलमा 40'"},
        },
        "required": ["query"],
    },
}

PLACE_MEDICINE_ORDER = {
    "name": "place_medicine_order",
    "description": (
        "Place a COD order for a SKU returned by a recent search_medicine call. "
        "Uses Mom's saved address and the prescription S3 URI from her profile. "
        "Returns order_id, eta, total."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 3},
            "prescription_s3_uri": {"type": "string"},
        },
        "required": ["sku", "quantity", "prescription_s3_uri"],
    },
}

# ─── Grocery ─────────────────────────────────────────────────────────────────

SEARCH_GROCERY = {
    "name": "search_grocery",
    "description": "Search Blinkit (default) or Swiggy Instamart. Returns up to 3 SKUs.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}

ADD_GROCERY_TO_CART = {
    "name": "add_grocery_to_cart",
    "description": "Add an item to the running grocery cart. Returns updated cart summary.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sku": {"type": "string"},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["sku", "quantity"],
    },
}

GET_GROCERY_CART = {
    "name": "get_grocery_cart",
    "description": "Return the current cart {items, total, eta_minutes} read from the live page.",
    "input_schema": {"type": "object", "properties": {}},
}

PLACE_GROCERY_ORDER = {
    "name": "place_grocery_order",
    "description": "Place the cart as a COD order. Returns order_id, eta, total.",
    "input_schema": {"type": "object", "properties": {}},
}

# ─── Bill ────────────────────────────────────────────────────────────────────

FETCH_BILL = {
    "name": "fetch_bill",
    "description": (
        "Fetch outstanding bill amount. Currently supports utility='electricity' "
        "(JVVNL Jaipur). Returns {amount_paise, due_date, bill_number, "
        "bill_period, payment_url}."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "utility": {"type": "string", "enum": ["electricity", "mobile", "gas", "water"]},
        },
        "required": ["utility"],
    },
}

REQUEST_PAYMENT_VIA_DEEP = {
    "name": "request_payment_via_deep",
    "description": (
        "Hand off the actual payment to Deep via Telegram. Mom does NOT see "
        "this step. Use after Mom confirms the amount in voice."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "utility": {"type": "string"},
            "amount_paise": {"type": "integer"},
            "due_date": {"type": "string"},
            "consumer_number": {"type": "string"},
            "payment_url": {"type": "string"},
        },
        "required": ["utility", "amount_paise", "payment_url"],
    },
}


# ─── Per-intent toolsets (filtered to avoid 35-tool attention degradation) ───

SHARED = [SPEAK_TO_MOM, NOTIFY_DEEP, CONFIRM_UNDERSTANDING]

MEDICINE_TOOLS = SHARED + [SEARCH_MEDICINE, PLACE_MEDICINE_ORDER]
GROCERY_TOOLS = SHARED + [SEARCH_GROCERY, ADD_GROCERY_TO_CART, GET_GROCERY_CART, PLACE_GROCERY_ORDER]
BILL_TOOLS = SHARED + [FETCH_BILL, REQUEST_PAYMENT_VIA_DEEP]


def tools_for(intent: str) -> list[dict]:
    return {
        "medicine": MEDICINE_TOOLS,
        "grocery": GROCERY_TOOLS,
        "bill": BILL_TOOLS,
    }.get(intent, SHARED)
