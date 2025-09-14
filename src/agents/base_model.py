from __future__ import annotations

import os
import json
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field
from dateutil.parser import parse as parse_dt
from groq import Groq



class TripRequest(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    days: Optional[int] = None
    budget: Optional[float] = None
    currency: Optional[str] = "USD"

    def normalized(self, known_destinations: List[str]) -> Dict[str, Any]:
        """Trim fields, coerce date to YYYY-MM-DD, enforce known destinations, and basic type guards."""
        out = self.model_dump()

        for k in ("origin", "destination", "currency", "start_date"):
            if out.get(k) and isinstance(out[k], str):
                out[k] = out[k].strip() or None

        if out.get("start_date"):
            try:
                d = parse_dt(out["start_date"]).date()
                out["start_date"] = d.strftime("%Y-%m-%d")
            except Exception:
                pass

        if known_destinations:
            dest = out.get("destination")
            if dest and dest not in known_destinations:
                out["destination"] = None

        if out.get("days") is not None:
            try:
                di = int(out["days"])
                out["days"] = di if di > 0 else None
            except Exception:
                out["days"] = None

        if out.get("budget") is not None and not out.get("currency"):
            out["currency"] = "USD"

        return out


def _client() -> Optional[Groq]:
    key = os.getenv("GROQ_API_KEY")
    return Groq(api_key=key)

def extract_request_with_llm(user_text: str, known_destinations: List[str]) -> Dict[str, Any]:
    cli = _client()
    if cli is None:
        return {}

    system = (
        "You extract trip fields from the user and return ONLY a valid JSON object with keys: "
        "{origin, destination, start_date, days, budget, currency}. "
        "If a field is unknown, set it to null. "
        "Use ISO date format YYYY-MM-DD for start_date if present. "
        "Do NOT include chain-of-thought or <think>…</think> content in any form."
        f"If destination is present, it MUST be one of: {', '.join(known_destinations)}."
    )

    try:
        resp = cli.chat.completions.create(
            model=os.getenv("GROQ_MODEL"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)

        obj = TripRequest.model_validate(data).normalized(known_destinations)
        return obj
    
    except Exception:
        return {}

def draft_itinerary_with_llm(request: Dict[str, Any]) -> str:
    cli = _client()
    days = request.get("days") or 3
    dest = request.get("destination") or "the destination"

    user_prompt = (
        f"Create a concise {days}-day itinerary for {dest}. "
        "Use bullets per day (3–5 items), include one local food tip and a transport hint each day. "
        "Keep total under 180 words."
    )

    if cli is None:
        return "Itinerary unavailable: LLM client not configured (missing GROQ_API_KEY or library)."

    try:
        resp = cli.chat.completions.create(
            model=os.getenv("GROQ_MODEL"),
            messages=[
                {"role": "system", "content": "You are a concise, practical travel writer."},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
        )
        return (resp.choices[0].message.content or "").strip() or "Itinerary unavailable: empty LLM response."
    except Exception as e:
        return f"Itinerary unavailable due to LLM error: {e}"


__all__ = [
    "extract_request_with_llm",
    "draft_itinerary_with_llm",
    "TripRequest",
]