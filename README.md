# ✈️ Travel Planner (PoC)

Minimal end-to-end agent that:

- understands a natural-language trip request,
- drafts a short itinerary,
- searches mock flight & hotel CSVs,
- proposes the best combo within the user's budget,
- asks for consent, then "books" and writes a JSON receipt,
- charges a mock credit card,
- shows all receipts in a My Trips tab.

Built with Streamlit, LangGraph, and an open-source LLM via Groq (default: Qwen). The data is local-only (no real APIs).

## Demo flow

In Chat, ask:

```
Plan me a trip from Jakarta to Singapore for 3 days with a budget of $1500 from 2025-12-10
```

The app shows a 3-day itinerary and a proposal (flight + hotel) under budget.

Reply yes to book. A JSON receipt is written and visible under My Trips.
The receipt includes masked card details and a running balance (from data/mock_payment.json).

## Project structure

```
.
├── app.py                      # Streamlit UI (Chat + My Trips)
├── data/
│   ├── mock_flights_by_date.csv
│   ├── mock_hotels.csv
│   ├── mock_payment.json       # mock card + running balance
│   └── receipts/               # JSON receipts (written at booking time)
├── src/
│   ├── config.py               # paths, defaults (CFG.data_dir, CFG.receipts_dir)
│   ├── graph/
│   │   └── build_graph.py      # LangGraph controller (consent, flow)
│   ├── agents/
│   │   ├── base_model.py       # LLM-only tasks: request extraction + itinerary drafting
│   │   └── model_tools.py       # Tool/function-calling to search & book
│   ├── state.py                # Graph state dataclass
│   ├── utils/
│   │   ├── booking.py          # writes receipt + mock charge + increments balance
│   │   ├── search_inventory.py # deterministic "maximize ≤ budget" search on CSVs
│   │   ├── text.py             # sanitizer (strips <think> etc.)
│   │   └── receipt_view.py     # Convert bookings in json format to markdown
├── pyproject.toml              # uv/PEP 621 project config (deps)
└── README.md
```

## Requirements

- Python 3.11+
- uv (fast Python package manager): https://github.com/astral-sh/uv
- A Groq API key in your environment (free account works for testing)

## Setup

### Install deps

```bash
uv sync
```

### Environment

Create `.env` in the project root:

```bash
GROQ_API_KEY=YOUR_GROQ_KEY
GROQ_MODEL=qwen/qwen3-32b
```

### Run

```bash
streamlit run app.py
```

## Mock data & schemas

### Flights (data/mock_flights_by_date.csv)

Flexible header mapping is used; include at least:

- **Origin**: departure_city | origin | from | depart_city
- **Destination**: arrival_city | destination | to | arrive_city
- **Date**: departure_date | date | flight_date | depart_date
- **Price**: price_per_adult_usd | price_usd | price | price_per_ticket_usd | fare_usd
- **(Optional)** direction = OUTBOUND / RETURN

### Hotels (data/mock_hotels.csv)

- **City**: city | destination | location
- **Nightly price**: price_per_night_usd | price_usd | nightly_usd | price_per_night
- **Availability window**: availability_start_date, availability_end_date
- **(Optional)** rating: rating_out_of_10 | star_rating | stars

The agent only supports destinations present in the mock hotels. If you ask for a new city, it will ask you to try another destination.

### Mock payments (with running balance)

`data/mock_payment.json`:

```json
{
  "cardholder_name": "Name",
  "card_number": "4242424242424242",
  "exp_month": 12,
  "exp_year": 2030,
  "network": "Visa",
  "billing_address": {
    "line1": "123 Demo Street",
    "city": "Jakarta",
    "country": "ID",
    "postal_code": "10210"
  },
}
```

On each booking:

- the app masks the card (brand + last4) in the receipt,
- increments "balance" by the booking total and writes back to this file,

## How the agent works (in short)

1. **Understanding**: `src/agent/base_model.py` parses the user's message (origin, destination, dates, days, budget, currency) and drafts a small itinerary (no chain-of-thought; sanitized).

2. **Search (tool)**: `src/utils/search_inventory.py` deterministically finds the maximum-cost combo ≤ budget for the given dates:
   - matches outbound on the start date and return on start + days − 1,
   - filters available hotels for the full range,
   - maximizes (flight + hotel_nights) under the budget with sensible tie-breakers (rating, flight spend).

3. **Consent**: The agent summarizes the option and asks for yes/no.

4. **Booking (tool)**: On "yes", `src/utils/booking.py` writes a JSON receipt under `data/receipts/`, and charges the mock card

## Example prompts

- "Plan me a trip from Jakarta to Singapore for 3 days with a budget of $1500 from 2025-12-10"
- "Plan a 3-day trip to Tokyo" → the agent asks for missing budget/dates/origin.
- "Yes" → books using the shown option and writes the receipt.

## Tuning & switches

- **Model**: set `GROQ_MODEL`.
- **Data/receipts paths**: edit `src/config.py` (`CFG.data_dir`, `CFG.receipts_dir`).
- **Token usage**: the current design is "lean" (deterministic search tool).
  If you want an "all-LLM selection" demo later, switch to the `get_inventory` / `choose_combo` flow in `llm_tools.py` (expect higher token usage).

## Notes & limitations

- All flights/hotels are mock CSVs. No real availability or external pricing.
- Payment is fake; receipts and balances are for demo purposes only.
- Time zones and multi-traveler pricing are out of scope for this PoC.

