from typing import Optional, List, Dict
import json
import os
from datetime import datetime, timedelta
from discord.ext import tasks
from data_handler import get_user, users_col

# === LOAD SHOP DATA ===
def load_json(file_name: str, default_data=None):
    """Đọc file JSON (tự tạo nếu chưa tồn tại)."""
    if not os.path.exists(file_name):
        default_data = default_data or {}
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
    with open(file_name, 'r', encoding='utf-8') as f:
        return json.load(f)

shop_data = load_json("shop_data.json")

# === DEFAULT TEXTFIGHT STATS ===
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

# === MONGO FUNCTIONS ===
def get_user_textfight(user_id: str) -> Dict:
    """Lấy hoặc khởi tạo chỉ số fight của người chơi."""
    doc = users_col.find_one({"_id": user_id}, {"text_fight": 1})
    tf = doc.get("text_fight") if doc else None
    if not tf:
        users_col.update_one(
            {"_id": user_id},
            {"$set": {"text_fight": DEFAULT_TEXTFIGHT}},
            upsert=True
        )
        return DEFAULT_TEXTFIGHT.copy()
    # Bổ sung trường mới nếu thiếu
    for k, v in DEFAULT_TEXTFIGHT.items():
        tf.setdefault(k, v)
    return tf

def update_textfight(user_id: str, data: Dict):
    """Cập nhật 1 hoặc nhiều chỉ số fight."""
    if not data:
        return
    users_col.update_one(
        {"_id": user_id},
        {"$set": {f"text_fight.{k}": v for k, v in data.items()}},
        upsert=True
    )

def modify_hp(user_id: str, delta: int):
    """Thay đổi HP và giới hạn trong [0, max_hp]."""
    tf = get_user_textfight(user_id)
    new_hp = max(0, min(tf["hp"] + delta, tf["max_hp"]))
    update_textfight(user_id, {"hp": new_hp})
    return new_hp

def modify_mana(user_id: str, delta: int):
    """Thay đổi mana và giới hạn trong [0, max_mana]."""
    tf = get_user_textfight(user_id)
    new_mana = max(0, min(tf["mana"] + delta, tf["max_mana"]))
    update_textfight(user_id, {"mana": new_mana})
    return new_mana

def reset_textfight(user_id: str):
    """Đặt lại toàn bộ chỉ số về mặc định."""
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"text_fight": DEFAULT_TEXTFIGHT}},
        upsert=True
    )

# === EQUIPMENT MANAGEMENT ===
def _get_equips(user_id: str) -> List[Optional[str]]:
    """Trả về danh sách 3 ô trang bị (None nếu trống)."""
    doc = users_col.find_one({"_id": user_id}, {"fight_equips": 1}) or {}
    equips = doc.get("fight_equips") or [None] * EQUIP_SLOTS
    equips = (equips + [None] * EQUIP_SLOTS)[:EQUIP_SLOTS]
    return equips

def _set_equips(user_id: str, equips: List[Optional[str]]):
    """Ghi danh sách trang bị (3 ô cố định)."""
    if not isinstance(equips, list) or len(equips) != EQUIP_SLOTS:
        raise ValueError("fight_equips phải là list gồm 3 phần tử")
    users_col.update_one(
        {"_id": user_id},
        {"$set": {"fight_equips": equips}},
        upsert=True
    )

# === ITEM AND BONUS ===
def _item_display(item_key: Optional[str]) -> str:
    """Hiển thị vật phẩm dạng icon + tên."""
    if not item_key:
        return "— trống —"
    item = shop_data.get(item_key, {})
    return f"{item.get('icon', '')} {item.get('name', item_key)}".strip()

def _gear_bonuses(item_key: str) -> Dict[str, float]:
    """Lấy toàn bộ bonus (stats + effects) từ item."""
    item = shop_data.get(item_key, {})
    bonuses = {}

    for source in (item.get("stats", {}), item.get("effects", {})):
        for k, v in source.items():
            try:
                val = float(v)
                if val.is_integer():
                    val = int(val)
            except (ValueError, TypeError):
                val = 0
            bonuses[k] = bonuses.get(k, 0) + val
    return bonuses

def _aggregate_bonuses(equips: List[Optional[str]]) -> Dict[str, float]:
    """Gộp bonus từ tất cả trang bị lại."""
    total = {}
    for key in equips:
        if not key:
            continue
        bonuses = _gear_bonuses(key)
        for stat, value in bonuses.items():
            total[stat] = total.get(stat, 0) + value
    return total

def apply_stat_bonus(user_id: str, bonus: Dict[str, float] = None, include_equips: bool = False):
    """
    Cộng chỉ số cơ bản cho người chơi.
    - bonus: dict các chỉ số cần cộng (vd: {"ad": 10, "max_hp": 200})
    - include_equips: nếu True → cộng luôn bonus từ tất cả trang bị hiện có
    """
    tf = get_user_textfight(user_id)

    # Bonus riêng (vật phẩm, buff,...)
    if bonus:
        for stat, value in bonus.items():
            try:
                val = float(value)
                if val.is_integer():
                    val = int(val)
            except (ValueError, TypeError):
                val = 0
            tf[stat] = tf.get(stat, 0) + val

    # Bonus từ trang bị
    if include_equips:
        equips = _get_equips(user_id)
        equip_bonus = _aggregate_bonuses(equips)
        for stat, value in equip_bonus.items():
            tf[stat] = tf.get(stat, 0) + value

    update_textfight(user_id, tf)
    return tf

def remove_stat_bonus(user_id: str, bonus: Dict[str, float] = None, include_equips: bool = False):
    """
    Trừ các chỉ số cơ bản của người chơi.
    - bonus: dict chứa các chỉ số cần trừ (vd: {"ad": 10, "max_hp": 200})
    - include_equips: nếu True thì tự động trừ toàn bộ bonus từ trang bị hiện tại
    """
    tf = get_user_textfight(user_id)

    # --- Trừ chỉ số từ bonus riêng (tháo đồ, mất buff, v.v.) ---
    if bonus:
        for stat, value in bonus.items():
            try:
                val = float(value)
                if val.is_integer():
                    val = int(val)
            except (ValueError, TypeError):
                val = 0
            tf[stat] = tf.get(stat, 0) - val

    # --- Trừ toàn bộ bonus từ trang bị hiện có ---
    if include_equips:
        equips = _get_equips(user_id)
        equip_bonus = _aggregate_bonuses(equips)
        for stat, value in equip_bonus.items():
            tf[stat] = tf.get(stat, 0) - value

    update_textfight(user_id, tf)
    return tf

# === FULL STATS ===
def get_full_stats(user_id: str) -> Dict:
    """Tính toán chỉ số đầy đủ của người chơi (fight + equips)."""
    tf = get_user_textfight(user_id)
    equips = _get_equips(user_id)
    bonus = _aggregate_bonuses(equips)

    total = tf.copy()
    for stat, val in bonus.items():
        total[stat] = total.get(stat, 0) + val

    total["equips"] = equips
    return total

# === UPDATE USER ===
def update_user_stats(user_id: str, data: dict):
    """Cập nhật dữ liệu Text Fight của người chơi."""
    if not data:
        return
    try:
        users_col.update_one({"_id": user_id}, {"$set": data}, upsert=True)
    except Exception as e:
        print(f"[MongoDB] ❌ Lỗi cập nhật user {user_id}: {e}")

# === AUTO CHECK LIFE/DEATH ===
@tasks.loop(seconds=10)
async def auto_check_life_and_death():
    """Kiểm tra trạng thái sinh tử mỗi 10 giây."""
    now = datetime.now()
    for user in users_col.find({}, {"life": 1, "max_life": 1, "death": 1, "death_time": 1}):
        user_id = user["_id"]
        life = user.get("life", 0)
        death = user.get("death", False)
        death_time = user.get("death_time")
        max_life = user.get("max_life", 100)

        if life <= 0 and not death:
            users_col.update_one(
                {"_id": user_id},
                {"$set": {"death": True, "death_time": now + timedelta(hours=1)}}
            )
        elif death and death_time and now >= death_time:
            users_col.update_one(
                {"_id": user_id},
                {
                    "$set": {"death": False, "life": max_life},
                    "$unset": {"death_time": ""}
                }
            )

async def reapply_equipment_stats():
    """Tự động cộng lại chỉ số từ trang bị khi bot khởi động."""
    for user in users_col.find({}, {"_id": 1, "fight_equips": 1}):
        user_id = user["_id"]
        equips = user.get("fight_equips", [])
        for item_key in equips:
            if not item_key:
                continue
            item = shop_data.get(item_key)
            if not item:
                continue
            bonus = item.get("stats", {})
            apply_stat_bonus(user_id, bonus)
    print("✅ Đã tự động cộng lại chỉ số từ toàn bộ trang bị khi khởi động bot.")

def start_auto_check_loop(bot):
    """Khởi động vòng kiểm tra tự động khi bot sẵn sàng."""
    if not auto_check_life_and_death.is_running():
        auto_check_life_and_death.start()