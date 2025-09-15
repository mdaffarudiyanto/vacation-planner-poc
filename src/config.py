from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class Config:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL")
    data_dir: str = os.getenv("DATA_DIR", "data")
    receipts_dir: str = os.getenv("RECEIPTS_DIR", "data/receipts")

CFG = Config()