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
backgrounds_col = db["backgrounds"]

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
    user = users_col.find_one({"_id": user_id})
    if not user:
        return None

    # Nếu user chưa có TextFight thì tự thêm vào
    if "TextFight" not in user:
        default_textfight = {
            "hp": 10000,
            "max_hp": 10000,
            "mana": 600,
            "max_mana": 600,
            "ad": 40,
            "ap": 0,
            "armor": 0,
            "magic_resist": 0,
            "crit_rate": 0.3,
            "crit_damage": 2.0,
            "attack_speed": 0.5,
            "lifesteal": 0.0,
            "amplify": 0.0,
            "resistance": 0.0
        }
        users_col.update_one(
            {"_id": user_id},
            {"$set": {"TextFight": default_textfight}}
        )
        user["TextFight"] = default_textfight  # cập nhật cache trong RAM luôn

    return user

def create_user(user_id: str, default_data: Optional[Dict[str, Any]] = None) -> None:
    if get_user(user_id) is None:
        # === Chỉ số TextFight mặc định ===
        default_textfight = {
            "hp": 10000,          # máu hiện tại
            "max_hp": 10000,      # giới hạn máu
            "mana": 600,          # mana hiện tại
            "max_mana": 600,      # giới hạn mana
            "ad": 40,             # sát thương vật lý
            "ap": 0,              # sức mạnh phép
            "armor": 0,           # giáp
            "magic_resist": 0,    # kháng phép
            "crit_rate": 0.3,     # 30%
            "crit_damage": 2.0,   # 200%
            "attack_speed": 0.5,  # tốc đánh
            "lifesteal": 0.0,     # hút máu %
            "amplify": 0.0,       # khuếch đại %
            "resistance": 0.0     # chống chịu %
        }

        # Khi tạo, đặt HP/Mana hiện tại = Max
        default_textfight["hp"] = default_textfight["max_hp"]
        default_textfight["mana"] = default_textfight["max_mana"]

        # === Dữ liệu người chơi cơ bản ===
        doc = default_data or {
            "_id": user_id,
            "points": 0,
            "items": {},
            "smart": 0,
            "streak": 0,
            "TextFight": default_textfight
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
