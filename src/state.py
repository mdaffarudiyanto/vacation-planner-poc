from __future__ import annotations
from typing import TypedDict, Annotated, Optional, Any, Dict
from langgraph.graph.message import add_messages

class GraphState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    trip_request: Dict[str, Any]
    itinerary_text: Optional[str]
    flight_option: Optional[Dict[str, Any]]
    hotel_option: Optional[Dict[str, Any]]
    total_price: Optional[float]
    awaiting_consent: bool
    consent_granted: Optional[bool]
    error: Optional[str]