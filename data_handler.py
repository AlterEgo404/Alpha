import os
from typing import Any, Dict, Optional

from pymongo import MongoClient, ASCENDING

# === KẾT NỐI MONGO ===
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGO_URI")

_client = MongoClient(MONGO_URI)

db = _client["discord_bot"]
users_col = db["users"]
config_col = db["config"]

# _id index đã có sẵn và luôn unique => KHÔNG tạo lại!
# users_col.create_index([("_id", ASCENDING)], unique=True)  # ❌ GÂY LỖI

# Tối ưu một số truy vấn phổ biến (không bắt buộc)
for f in ("points", "company_balance", "smart"):
    try:
        users_col.create_index([(f, ASCENDING)])
    except Exception:
        pass


# === USER HELPERS ===
def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    return users_col.find_one({"_id": user_id})

def create_user(user_id: str, default_data: Optional[Dict[str, Any]] = None) -> None:
    if get_user(user_id) is None:
        doc = default_data or {
            "_id": user_id,
            "points": 0,
            "items": {},
            "smart": 0,
            "streak": 0,
        }
        doc["_id"] = user_id
        users_col.insert_one(doc)

def update_user(user_id: str, update_dict: Dict[str, Any]) -> None:
    if not update_dict:
        return
    has_operator = any(k.startswith("$") for k in update_dict.keys())
    update_payload = update_dict if has_operator else {"$set": update_dict}
    users_col.update_one({"_id": user_id}, update_payload, upsert=True)

def save_user_full(user_id: str, full_data: Dict[str, Any]) -> None:
    full_data = dict(full_data or {})
    full_data["_id"] = user_id
    users_col.replace_one({"_id": user_id}, full_data, upsert=True)


# === JACKPOT HELPERS ===
def get_jackpot() -> Optional[int]:
    doc = config_col.find_one({"_id": "jackpot"})
    return doc["value"] if doc and "value" in doc else None

def update_jackpot(amount: int) -> None:
    config_col.update_one({"_id": "jackpot"}, {"$inc": {"value": int(amount)}}, upsert=True)

def set_jackpot(value: int) -> None:
    config_col.update_one({"_id": "jackpot"}, {"$set": {"value": int(value)}}, upsert=True)
