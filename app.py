from __future__ import annotations
import os, json, glob
import streamlit as st
from dotenv import load_dotenv

from src.graph.build_graph import build_graph
from src.config import CFG
from src.utils.text import sanitize_model_text
from src.utils.receipt_view import render_booking_markdown, _fmt_money


load_dotenv()

st.set_page_config(page_title="AI Travel Planner (PoC)", page_icon="✈️", layout="wide")
st.title("AI Travel Planner (PoC)")

def _role_and_content(m):
    """Normalize dict messages or LangChain messages (HumanMessage/AIMessage/ChatMessage)."""
    if isinstance(m, dict):
        role = m.get("role") or "assistant"
        content = m.get("content") or ""
    else:
        role = getattr(m, "role", None) or getattr(m, "type", None) or "assistant"
        role = {"human": "user", "ai": "assistant"}.get(role, role)
        content = getattr(m, "content", "")
    return role, content

if "graph_app" not in st.session_state:
    st.session_state.graph_app = build_graph()

# agent_state = state your graph needs (trip_request, flags, etc.)
if "agent_state" not in st.session_state:
    st.session_state.agent_state = {"messages": []}

# chat_log = full UI transcript (user + assistant)
if "chat_log" not in st.session_state:
    st.session_state.chat_log = []

tab_chat, tab_trips = st.tabs(["💬 Chat", "🧳 My Trips"])

with tab_chat:
    # 1) Render past conversation first
    for m in st.session_state.chat_log:
        with st.chat_message(m["role"]):
            st.markdown(sanitize_model_text(m["content"]))

    # 2) Read input
    user_input = st.chat_input("Ask me to plan a trip…")

    if user_input:
        # 2a) Show the user's message immediately
        st.session_state.chat_log.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # 2b) Prepare a minimal agent call state (graph only needs the last user turn)
        call_state = dict(st.session_state.agent_state)
        call_state["messages"] = [{"role": "user", "content": user_input}]

        # 2c) Reserve an assistant bubble and run the agent
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                new_state = st.session_state.graph_app.invoke(call_state)

                # Keep only real assistant messages; drop echoes/placeholders
                assistant_msgs = []
                for m in new_state.get("messages", []):
                    role, text = _role_and_content(m)
                    if (role or "").lower() != "assistant":
                        continue
                    if not text:
                        continue
                    # remove internal tags and whitespace before comparisons
                    clean_text = sanitize_model_text(str(text)).strip()
                    if not clean_text:
                        continue
                    # skip if the model echoed the user's last input
                    if clean_text == user_input.strip():
                        continue
                    # de-dupe against the last assistant message already shown
                    if (st.session_state.chat_log 
                        and st.session_state.chat_log[-1]["role"] == "assistant"
                        and st.session_state.chat_log[-1]["content"].strip() == clean_text):
                        continue
                    assistant_msgs.append(clean_text)

                # Render the filtered assistant messages
                for clean_text in assistant_msgs:
                    st.session_state.chat_log.append({"role": "assistant", "content": clean_text})
                    st.markdown(clean_text)

        # 2d) Persist non-message state back to the agent_state for next turn
        for k, v in new_state.items():
            if k != "messages":
                st.session_state.agent_state[k] = v
            

with tab_trips:
    st.subheader("Booking IDs")
    files = sorted(glob.glob(os.path.join(CFG.receipts_dir, "*.json")))
    if not files:
        st.info("No bookings yet. Confirm a booking in chat to see receipts here.")
    for fp in files:
        try:
            with open(fp, "r") as f:
                data = json.load(f)
        except Exception:
            continue

        total = data.get("total_price_usd")
        rid = data.get("booking_id", "Receipt")
        title = f"{rid}"
        if total is not None:
            title += f" — {_fmt_money(total)}"

        with st.expander(title, expanded=False):
            # pretty markdown summary
            st.markdown(render_booking_markdown(data, fp))
            # download button (more reliable than links on some hosts)
            try:
                with open(fp, "rb") as fh:
                    st.download_button(
                        "⬇️ Download JSON",
                        data=fh.read(),
                        file_name=os.path.basename(fp),
                        mime="application/json",
                        use_container_width=True,
                    )
            except Exception:
                pass
