from __future__ import annotations
from typing import Optional, Dict, Any, List

from langgraph.graph import StateGraph, END
from src.state import GraphState
from src.utils.search_inventory import load_data, available_destinations
from src.agents.base_model import extract_request_with_llm, draft_itinerary_with_llm
from src.agents.model_tools import search_with_tools, book_with_tools
from src.config import CFG

try:
    FLIGHTS_DF, HOTELS_DF = load_data(CFG.data_dir)
except Exception:
    FLIGHTS_DF, HOTELS_DF = None, None

KNOWN_DESTS = available_destinations(HOTELS_DF) if HOTELS_DF is not None else []


def _last_user(state: GraphState) -> Optional[str]:
    for m in reversed(state.get("messages", [])):
        if isinstance(m, dict) and m.get("role") == "user":
            return str(m.get("content", ""))
        if getattr(m, "type", None) in ("human", "user") or getattr(m, "role", None) == "user":
            return str(getattr(m, "content", ""))
    return None

def _contains_yes(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ["yes", "yep", "yeah", "ya", "sure", "confirm", "book", "go ahead"])

def _contains_no(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in ["no", "nope", "nah", "cancel", "stop", "don't", "do not"])


def controller(state: GraphState) -> GraphState:
    s: Dict[str, Any] = dict(state)
    messages: List[Dict[str, Any]] = []
    user_text = _last_user(state) or ""

    # ---------- Consent flow ----------
    if s.get("awaiting_consent"):
        if user_text and _contains_yes(user_text):
            # Allow the model to call the book_trip tool (gated by awaiting_consent)
            text, receipt_path = book_with_tools(
                trip_request=s.get("trip_request", {}) or {},
                itinerary_text=s.get("itinerary_text", "") or "",
                flight_option=s.get("flight_option", {}) or {},
                hotel_option=s.get("hotel_option", {}) or {},
                total_price_usd=float(s.get("total_price", 0.0) or 0.0),
                allow_booking=True,   # <--- gate here
            )
            s["awaiting_consent"] = False
            s["consent_granted"] = True
            if receipt_path:
                s.setdefault("last_receipt_path", receipt_path)
            messages.append({"role": "assistant", "content": text})
            return {**s, "messages": messages}

        if user_text and _contains_no(user_text):
            s["awaiting_consent"] = False
            s["consent_granted"] = False
            messages.append({"role": "assistant", "content": "No problem — booking cancelled. Change dates/budget to try again."})
            return {**s, "messages": messages}

        messages.append({"role": "assistant", "content": "Please reply **yes** to confirm booking, or **no** to cancel."})
        return {**s, "messages": messages}

    # ---------- Parse / merge request ----------
    if user_text:
        extracted = extract_request_with_llm(user_text, KNOWN_DESTS)
        tr = dict(s.get("trip_request", {}))
        tr.update({k: v for k, v in extracted.items() if v is not None})
        s["trip_request"] = tr
    else:
        s.setdefault("trip_request", {})

    tr = s.get("trip_request", {})
    dest = tr.get("destination")

    # Destination guard
    if dest and KNOWN_DESTS and dest not in KNOWN_DESTS:
        messages.append({"role": "assistant", "content": f"Sorry, only destinations in mock data are supported. Try: {', '.join(KNOWN_DESTS)}."})
        return {**s, "messages": messages}

    if not dest:
        messages.append({"role": "assistant", "content": "Where would you like to go? " + (", ".join(KNOWN_DESTS) if KNOWN_DESTS else "")})
        return {**s, "messages": messages}

    days = tr.get("days")
    if not days:
        messages.append({"role": "assistant", "content": "How many days do you want to stay?"})
        return {**s, "messages": messages}

    # If missing inputs, show itinerary once and ask for the rest
    missing = [k for k in ["start_date", "budget", "origin"] if not tr.get(k)]
    if missing:
        if not s.get("itinerary_text"):
            s["itinerary_text"] = draft_itinerary_with_llm(tr)
            messages.append({"role": "assistant", "content": f"Here’s a sample {days}-day plan for {dest}:\n\n{s['itinerary_text']}"})
        asks = []
        if "start_date" in missing: asks.append("trip start date (YYYY-MM-DD)")
        if "budget" in missing:     asks.append("total budget in USD")
        if "origin" in missing:     asks.append("your departure city")
        messages.append({"role": "assistant", "content": "To search flights & hotels, please provide your " + " and ".join(asks) + "."})
        return {**s, "messages": messages}

    # ---------- Search via tools ----------
    if not s.get("itinerary_text"):
        s["itinerary_text"] = draft_itinerary_with_llm(tr)
        messages.append({"role": "assistant", "content": f"Here’s a {tr['days']}-day plan for {tr['destination']}:\n\n{s['itinerary_text']}"})

    summary_text, flight_opt, hotel_opt, total_price = search_with_tools(tr, KNOWN_DESTS)

    if not flight_opt or not hotel_opt or total_price is None:
        messages.append({"role": "assistant", "content": summary_text or "No options were found. Try different dates/budget."})
        return {**s, "messages": messages}

    # Store and ask for consent (booking will only be allowed in the consent branch)
    s["flight_option"] = flight_opt
    s["hotel_option"] = hotel_opt
    s["total_price"] = float(total_price)
    s["awaiting_consent"] = True

    messages.append({"role": "assistant", "content": summary_text})
    return {**s, "messages": messages}


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("controller", controller)
    g.add_edge("controller", END)
    g.set_entry_point("controller")
    return g.compile()
