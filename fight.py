# fight.py
from typing import Optional, List, Dict
from data_handler import users_col
import json
import os

# --- Shop Data (nếu bạn vẫn dùng JSON cho shop) ---
def load_json(file_name, default_data=None):
    if not os.path.exists(file_name):
        default_data = default_data or {}
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
    with open(file_name, 'r', encoding='utf-8') as f:
        return json.load(f)

shop_data = load_json('shop_data.json')

# --- Thông số mặc định cho Text Fight ---
DEFAULT_TEXTFIGHT = {
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

EQUIP_SLOTS = 3

# === Mongo Functions ===
def get_user_textfight(user_id: str) -> Dict:
    """Lấy hoặc khởi tạo chỉ số fight trong Mongo."""
    doc = users_col.find_one({"_id": user_id}, {"text_fight": 1})
    if not doc or "text_fight" not in doc:
        users_col.update_one(
            {"_id": user_id},
            {"$set": {"text_fight": DEFAULT_TEXTFIGHT}},
            upsert=True
        )
        return DEFAULT_TEXTFIGHT.copy()
    tf = doc["text_fight"]
    # Bổ sung các trường mới nếu thiếu
    for k, v in DEFAULT_TEXTFIGHT.items():
        tf.setdefault(k, v)
    return tf

def update_textfight(user_id: str, data: Dict):
    """Cập nhật 1 hoặc nhiều chỉ số fight."""
    users_col.update_one(
        {"_id": user_id},
        {"$set": {f"text_fight.{k}": v for k, v in data.items()}},
        upsert=True
    )

def modify_hp(user_id: str, delta: int):
    """Tăng/giảm HP, tự giới hạn trong [0, max_hp]."""
    tf = get_user_textfight(user_id)
    new_hp = max(0, min(tf["hp"] + delta, tf["max_hp"]))
    update_textfight(user_id, {"hp": new_hp})
    return new_hp

def modify_mana(user_id: str, delta: int):
    """Tăng/giảm mana, tự giới hạn trong [0, max_mana]."""
    tf = get_user_textfight(user_id)
    new_mana = max(0, min(tf["mana"] + delta, tf["max_mana"]))
    update_textfight(user_id, {"mana": new_mana})
    return new_mana

def reset_textfight(user_id: str):
    """Reset toàn bộ chỉ số fight về mặc định."""
    users_col.update_one({"_id": user_id}, {"$set": {"text_fight": DEFAULT_TEXTFIGHT}}, upsert=True)

# === Equipment (Mongo) ===
def _get_equips(user_id: str) -> List[Optional[str]]:
    """Trả về danh sách 3 ô trang bị (None nếu trống)."""
    doc = users_col.find_one({"_id": user_id}, {"fight_equips": 1}) or {}
    equips = doc.get("fight_equips") or [None] * EQUIP_SLOTS
    equips += [None] * (EQUIP_SLOTS - len(equips))
    return equips[:EQUIP_SLOTS]

def _set_equips(user_id: str, equips: List[Optional[str]]):
    if not isinstance(equips, list) or len(equips) != EQUIP_SLOTS:
        raise ValueError("fight_equips phải là list gồm 3 phần tử")
    users_col.update_one({"_id": user_id}, {"$set": {"fight_equips": equips}}, upsert=True)

# === Item & Bonus ===
def _item_display(item_key: Optional[str]) -> str:
    if not item_key:
        return "— trống —"
    data = shop_data.get(item_key, {})
    icon = data.get("icon", "")
    name = data.get("name", item_key)
    return f"{icon} {name}".strip()

def _gear_bonuses(item_key: str) -> Dict:
    """Lấy stat bonus từ item."""
    item = shop_data.get(item_key) or {}
    stats = item.get("stats", {})
    effects = item.get("effects", {})

    def as_int(x): return int(x) if str(x).isdigit() else 0
    def as_float(x): 
        try: return float(x)
        except: return 0.0

    return {
        "hp_flat": as_int(stats.get("hp", 0)),
        "hp_pct": as_float(effects.get("max_hp_percent", 0)),
        "armor": as_int(stats.get("armor", 0)),
        "dmg_min": as_int(stats.get("dmg_min", 0)),
        "dmg_max": as_int(stats.get("dmg_max", 0))
    }

def _aggregate_bonuses(equips: List[Optional[str]]) -> Dict:
    total = {"hp_flat": 0, "hp_pct": 0.0, "armor": 0, "dmg_min": 0, "dmg_max": 0}
    for key in equips:
        if not key:
            continue
        b = _gear_bonuses(key)
        for k in total:
            total[k] += b[k]
    return total

# === Xuất chỉ số đầy đủ ===
def get_full_stats(user_id: str) -> Dict:
    """Ghép chỉ số fight + bonus từ trang bị."""
    tf = get_user_textfight(user_id)
    equips = _get_equips(user_id)
    bonus = _aggregate_bonuses(equips)

    total = tf.copy()
    total["max_hp"] = int(tf["max_hp"] + bonus["hp_flat"] + tf["max_hp"] * (bonus["hp_pct"] / 100))
    total["armor"] = int(tf["armor"] + bonus["armor"])
    total["ad_min"] = tf["ad"] + bonus["dmg_min"]
    total["ad_max"] = tf["ad"] + bonus["dmg_max"]
    total["equips"] = equips
    return total

def format_stats_display(tf: Dict) -> str:
    """Format chỉ số hiển thị đẹp."""
    return (
        f"❤️ HP: `{tf['hp']}/{tf['max_hp']}`\n"
        f"🔵 Mana: `{tf['mana']}/{tf['max_mana']}`\n"
        f"⚔️ AD: `{tf['ad_min']}–{tf['ad_max']}` | 🔮 AP: `{tf['ap']}`\n"
        f"🛡️ Giáp: `{tf['armor']}` | 🧿 Kháng phép: `{tf['magic_resist']}`\n"
        f"💥 Crit: `{tf['crit_rate']*100:.0f}%` | 💀 Crit DMG: `{tf['crit_damage']*100:.0f}%`\n"
        f"⚡ AS: `{tf['attack_speed']}` | 🩸 Hút máu: `{tf['lifesteal']*100:.0f}%`\n"
        f"🔥 Khuếch đại: `{tf['amplify']*100:.0f}%` | 🪨 Chống chịu: `{tf['resistance']*100:.0f}%`"
    )
