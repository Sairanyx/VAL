"""Quick demo UI: `uv run --group ui streamlit run app/ui.py`"""

import os

import httpx
import streamlit as st

API = os.getenv("API_URL", "http://localhost:8000")
st.title("Since AI Hackathon demo")
if st.button("Ping API"):
    st.json(httpx.get(f"{API}/health").json())
