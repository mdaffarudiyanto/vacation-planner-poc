# src/llm_tools.py
from __future__ import annotations

import os, json
from typing import Optional, Tuple, Dict, Any, List

from groq import Groq
from src.utils.search_inventory import load_data, find_options
from src.utils.booking import book_and_write_receipt
from src.config import CFG


def _client() -> Optional[Groq]:
    key = os.getenv("GROQ_API_KEY", "")
    return Groq(api_key=key)


TOOLS_SEARCH = [
    {
        "type": "function",
        "function": {
            "name": "search_inventory",
            "description": (
                "Search mock CSV flights & hotels for the best round-trip + hotel combo "
                "that fits the user's budget and dates. Returns one option with total price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string"},
                    "destination": {"type": "string"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "days": {"type": "integer", "minimum": 1},
                    "budget": {"type": "number", "minimum": 0},
                },
                "required": ["origin", "destination", "start_date", "days", "budget"],
                "additionalProperties": False,
            },
        },
    },
]

TOOLS_BOOK = [
    {
        "type": "function",
        "function": {
            "name": "book_trip",
            "description": (
                "Create the booking and write a receipt JSON on disk. "
                "Call only after the user has confirmed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "trip_request": {"type": "object"},
                    "itinerary_text": {"type": "string"},
                    "flight_option": {"type": "object"},
                    "hotel_option": {"type": "object"},
                    "total_price_usd": {"type": "number"},
                },
                "required": [
                    "trip_request",
                    "itinerary_text",
                    "flight_option",
                    "hotel_option",
                    "total_price_usd",
                ],
                "additionalProperties": False,
            },
        },
    },
]


def _exec_tool(name: str, args: Dict[str, Any], *, allow_booking: bool = False) -> Dict[str, Any]:
    if name == "search_inventory":
        flights_df, hotels_df = load_data(CFG.data_dir)
        flight, hotel, total = find_options(
            flights_df,
            hotels_df,
            origin=args["origin"],
            destination=args["destination"],
            start_date=str(args["start_date"]),
            days=int(args["days"]),
            budget=float(args["budget"]),
        )
        if not flight or not hotel or total is None:
            return {"status": "no_match"}
        return {
            "status": "ok",
            "flight_option": flight,
            "hotel_option": hotel,
            "total_price_usd": float(total),
        }

    if name == "book_trip":
        if not allow_booking:
            return {"status": "blocked", "error": "Booking not allowed right now."}
        path = book_and_write_receipt(
            CFG.receipts_dir,
            args["trip_request"],
            args["itinerary_text"],
            args["flight_option"],
            args["hotel_option"],
            float(args["total_price_usd"]),
        )
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
        return {
            "status": "ok",
            "receipt_path": path,
            "booking_id": data.get("booking_id"),
            "flight_id": data.get("flight_id"),
            "hotel_id": data.get("hotel_id"),
            "total_price_usd": data.get("total_price_usd"),
        }

    return {"status": "error", "error": f"Unknown tool: {name}"}


# ---------------------------
# Public helpers for the graph
# ---------------------------

def search_with_tools(
    trip_req: Dict[str, Any], known_destinations: List[str]
) -> Tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[float]]:
    cli = _client()
    if cli is None:
        return ("LLM tools unavailable (missing GROQ_API_KEY).", None, None, None)

    system = (
        "You are an expert travel assistant.\n"
        "Do NOT include chain-of-thought or <think>…</think> content in any form.\n"
        "When a structured trip request is provided, you MUST call the function `search_inventory` exactly once.\n"
        "After the tool result, reply with a clean Markdown summary (no raw dicts/JSON):\n"
        "- Show flight legs (outbound/return) with cities, dates, and times if available.\n"
        "- Show hotel name, nightly price, nights, and total.\n"
        "- Show totals and ask the user to reply 'yes' to confirm or 'no' to cancel.\n"
        "HARD RULES:\n"
        "- NEVER exceed the provided budget. If no combination fits, say so explicitly and suggest changing dates/budget.\n"
        "- Do not fabricate or alter prices.\n"
        "- End with a one-line budget check like: `Budget check: $<total> <= $<budget> ✅` or `Budget check: $<total> > $<budget> ❌`.\n"
    )
    user = "Trip request to search:\n" + json.dumps(
        {
            "origin": trip_req.get("origin"),
            "destination": trip_req.get("destination"),
            "start_date": trip_req.get("start_date"),
            "days": trip_req.get("days"),
            "budget": trip_req.get("budget"),
            "currency": trip_req.get("currency", "USD"),
            "note": f"Destination must be one of: {', '.join(known_destinations)}",
        },
        ensure_ascii=False,
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # 1st call (expect tool call)
    resp = cli.chat.completions.create(
        model=os.getenv("GROQ_MODEL"),
        messages=messages,
        tools=TOOLS_SEARCH,
        tool_choice="auto",
        temperature=0.0,
    )
    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)

    if tool_calls:
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = _exec_tool(name, args, allow_booking=False)
            messages.append({"role": "assistant", "tool_calls": [tc], "content": None})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        # 2nd call (final natural-language summary)
        resp2 = cli.chat.completions.create(
            model=os.getenv("GROQ_MODEL"),
            messages=messages,
            temperature=0.2,
        )
        final_text = (resp2.choices[0].message.content or "").strip()

        # pull structured result from last tool message
        last_tool = next((m for m in reversed(messages) if m.get("role") == "tool"), None)
        flight_opt = hotel_opt = None
        total_price = None
        if last_tool:
            try:
                payload = json.loads(last_tool["content"])
                if payload.get("status") == "ok":
                    flight_opt = payload.get("flight_option")
                    hotel_opt = payload.get("hotel_option")
                    total_price = payload.get("total_price_usd")
            except Exception:
                pass

        return final_text, flight_opt, hotel_opt, total_price

    return (msg.content or "I didn’t receive enough info to search inventory."), None, None, None


def book_with_tools(
    trip_request: Dict[str, Any],
    itinerary_text: str,
    flight_option: Dict[str, Any],
    hotel_option: Dict[str, Any],
    total_price_usd: float,
    *,
    allow_booking: bool,
) -> Tuple[str, Optional[str]]:
    """
    Ask the model to call `book_trip`. Returns (assistant_text, receipt_path|None).
    Execution is permitted only if allow_booking=True (controller sets this).
    """
    cli = _client()
    if cli is None:
        return ("Booking unavailable (missing GROQ_API_KEY).", None)

    system = (
        "You are a careful travel assistant.\n"
        "Do NOT include chain-of-thought or <think>…</think> content in any form.\n"
        "Call `book_trip` exactly once ONLY if booking is allowed AND the total price does not exceed the user's budget.\n"
        "After the tool result, write a short Markdown confirmation including receipt path and booking IDs.\n"
        "HARD RULES:\n"
        "- Do not call `book_trip` if total_price_usd > trip_request.budget; instead, explain the issue.\n"
        "- Do not print raw dicts/JSON.\n"
    )

    user_payload = {
        "trip_request": trip_request,
        "itinerary_text": itinerary_text,
        "flight_option": flight_option,
        "hotel_option": hotel_option,
        "total_price_usd": float(total_price_usd),
    }
    user = "Booking payload:\n" + json.dumps(user_payload, ensure_ascii=False)

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    # 1st call (expect tool call)
    resp = cli.chat.completions.create(
        model=os.getenv("GROQ_MODEL"),
        messages=messages,
        tools=TOOLS_BOOK,
        tool_choice="auto",
        temperature=0.0,
    )
    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)

    if tool_calls:
        last_result = None
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = _exec_tool(name, args, allow_booking=allow_booking)
            last_result = result
            messages.append({"role": "assistant", "tool_calls": [tc], "content": None})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        # 2nd call (final natural-language confirmation)
        resp2 = cli.chat.completions.create(
            model=os.getenv("GROQ_MODEL"),
            messages=messages,
            temperature=0.2,
        )
        final_text = (resp2.choices[0].message.content or "").strip()

        receipt_path = None
        if last_result and last_result.get("status") == "ok":
            receipt_path = last_result.get("receipt_path")

        return final_text, receipt_path

    # No tool call
    return (msg.content or "I didn’t receive a booking call."), None
