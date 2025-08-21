import os
from typing import Any, Dict, Optional

from pymongo import MongoClient, ASCENDING

# === KẾT NỐI MONGO (an toàn) ===
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGO_URI")

_client = MongoClient(MONGO_URI)

db = _client["discord_bot"]
users_col = db["users"]
config_col = db["config"]

# Tạo index cơ bản (id người dùng & vài trường phổ biến)
users_col.create_index([("_id", ASCENDING)], unique=True)
# Tối ưu truy vấn leaderboard (không bắt buộc, nhưng hữu ích):
for f in ("points", "company_balance", "smart"):
    try:
        users_col.create_index([(f, ASCENDING)])
    except Exception:
        pass


# === USER HELPERS ===
def get_user(user_id: str) -> Optional[Dict[str, Any]]:
    """Lấy user theo _id; trả None nếu không có."""
    return users_col.find_one({"_id": user_id})


def create_user(user_id: str, default_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Tạo user mới nếu chưa tồn tại. Không ghi đè user cũ.
    """
    if get_user(user_id) is None:
        doc = default_data or {
            "_id": user_id,
            "points": 0,
            "items": {},
            "smart": 0,
            "streak": 0,
        }
        # đảm bảo _id đúng
        doc["_id"] = user_id
        users_col.insert_one(doc)


def update_user(user_id: str, update_dict: Dict[str, Any]) -> None:
    """
    Cập nhật user. Nếu update_dict đã chứa Mongo operators ($inc/$set/...) thì dùng nguyên vẹn.
    Nếu KHÔNG chứa operator, tự bọc vào $set.
    """
    if not update_dict:
        return

    has_operator = any(k.startswith("$") for k in update_dict.keys())
    update_payload = update_dict if has_operator else {"$set": update_dict}

    users_col.update_one({"_id": user_id}, update_payload, upsert=True)


def save_user_full(user_id: str, full_data: Dict[str, Any]) -> None:
    """
    Ghi đè toàn bộ document user (replace).
    """
    full_data = dict(full_data or {})
    full_data["_id"] = user_id
    users_col.replace_one({"_id": user_id}, full_data, upsert=True)


# === JACKPOT HELPERS ===
def get_jackpot() -> Optional[int]:
    """
    Trả về giá trị jackpot hoặc None nếu chưa có document.
    (Để main có thể khởi tạo mặc định khi None.)
    """
    jackpot_doc = config_col.find_one({"_id": "jackpot"})
    return jackpot_doc["value"] if jackpot_doc and "value" in jackpot_doc else None


def update_jackpot(amount: int) -> None:
    """
    Tăng/giảm jackpot theo amount (có thể âm/dương).
    """
    config_col.update_one(
        {"_id": "jackpot"},
        {"$inc": {"value": int(amount)}},
        upsert=True,
    )


def set_jackpot(value: int) -> None:
    """
    Đặt jackpot = value.
    """
    config_col.update_one(
        {"_id": "jackpot"},
        {"$set": {"value": int(value)}},
        upsert=True,
    )
