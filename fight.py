# fight.py
from typing import Optional, List, Dict
import json
import os
from datetime import datetime, timedelta
from discord.ext import tasks
from data_handler import get_user, users_col

# --- Tải dữ liệu shop ---
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
    "basic_damage": 40,
    "ad": 0,
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
        try:
            return float(x)
        except:
            return 0.0

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

def format_stats_display(tf: dict) -> str:
    """Trả về chuỗi hiển thị chỉ số Text Fight theo định dạng đẹp."""
    hp = f"{tf.get('hp', 0)}/{tf.get('max_hp', 0)}"
    mana = f"{tf.get('mana', 0)}/{tf.get('max_mana', 0)}"

    ad = tf.get("ad", 0)
    ap = tf.get("ap", 0)
    armor = tf.get("armor", 0)
    magic_resist = tf.get("magic_resist", 0)
    attack_speed = tf.get("attack_speed", 0)

    crit_rate = round(tf.get("crit_rate", 0) * 100, 1)
    crit_damage = round(tf.get("crit_damage", 0) * 100, 1)
    lifesteal = round(tf.get("lifesteal", 0) * 100, 1)
    amplify = round(tf.get("amplify", 0) * 100, 1)
    resistance = round(tf.get("resistance", 0) * 100, 1)

    return (
        f"**❤️ HP:** {hp}\n"
        f"**🔵 Mana:** {mana}\n"
        f"`  -  |  -  |  -  `\n"
        f"**AD:** {ad} ｜ **AP:** {ap} ｜ **Giáp:** {armor} ｜ **Kháng phép:** {magic_resist} ｜ **AS:** {attack_speed}\n"
        f"**Tỉ lệ Crit:** {crit_rate}% ｜ **ST Crit:** {crit_damage}% ｜ **Hút máu:** {lifesteal}% ｜ **Khuếch đại:** {amplify}% ｜ **Chống chịu:** {resistance}%"
    )

def update_user_stats(user_id: str, data: dict):
    """Cập nhật dữ liệu Text Fight của người chơi trong MongoDB."""
    try:
        users_col.update_one({"_id": user_id}, {"$set": data}, upsert=True)
    except Exception as e:
        print(f"[MongoDB] ❌ Lỗi cập nhật user {user_id}: {e}")


# === Tự động kiểm tra máu và hồi sinh ===
@tasks.loop(seconds=10)
async def auto_check_life_and_death():
    """Tự động kiểm tra trạng thái sinh tử của toàn bộ người chơi mỗi 10 giây."""
    now = datetime.datetime.now()
    for user in users_col.find({}, {"life": 1, "max_life": 1, "death": 1, "death_time": 1}):
        user_id = user["_id"]
        life = user.get("life", 0)
        death = user.get("death", False)
        death_time = user.get("death_time")
        max_life = user.get("max_life", 100)

        # Nếu máu <= 0 và chưa chết -> đánh dấu chết, đặt thời gian tử 1h
        if life <= 0 and not death:
            users_col.update_one(
                {"_id": user_id},
                {"$set": {
                    "death": True,
                    "death_time": now + timedelta(hours=1)
                }}
            )

        # Nếu đã chết và hết 1h -> hồi sinh
        elif death and death_time and now >= death_time:
            users_col.update_one(
                {"_id": user_id},
                {"$set": {
                    "death": False,
                    "life": max_life
                },
                 "$unset": {
                    "death_time": ""
                 }}
            )


def start_auto_check_loop(bot):
    """Khởi động vòng kiểm tra tự động khi bot khởi chạy."""
    if not auto_check_life_and_death.is_running():
        auto_check_life_and_death.start()
