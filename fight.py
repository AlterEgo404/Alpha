# fight.py (refactored)
from typing import Optional, List, Dict
import json
import os
from datetime import datetime, timedelta, timezone
from discord.ext import tasks
from data_handler import get_user, users_col
import numbers

# === LOAD SHOP DATA ===
def load_json(file_name: str, default_data=None):
    """Đọc file JSON (tự tạo nếu chưa tồn tại)."""
    if not os.path.exists(file_name):
        default_data = default_data or {}
        with open(file_name, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
    with open(file_name, "r", encoding="utf-8") as f:
        return json.load(f)

shop_data = load_json("shop_data.json")

# === DEFAULT TEXTFIGHT STATS ===
DEFAULT_TEXTFIGHT: Dict[str, float] = {
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

# --- Helpers ---
def _to_number(v):
    """Chuyển sang int nếu có thể, nếu có phần thập phân giữ float."""
    try:
        if isinstance(v, numbers.Number):
            return v
        fv = float(v)
        if fv.is_integer():
            return int(fv)
        return fv
    except Exception:
        return 0

def _ensure_dt_aware(dt):
    """Đảm bảo datetime có timezone (UTC). Trả về None nếu không phải datetime."""
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# === MONGO FUNCTIONS ===
def get_user_textfight(user_id: str) -> Dict:
    """
    Lấy bản sao (in-memory) của text_fight user hoặc khởi tạo mặc định nếu chưa có.
    Trả về dict độc lập (copy) để không sửa trực tiếp object đọc từ PyMongo cursor.
    """
    doc = users_col.find_one({"_id": user_id}, {"text_fight": 1})
    tf = (doc.get("text_fight") if doc else None) or {}
    # Bổ sung trường mới nếu thiếu (không ghi ra DB ở đây, sẽ ghi khi cần)
    for k, v in DEFAULT_TEXTFIGHT.items():
        tf.setdefault(k, v)
    return tf.copy()

def update_textfight(user_id: str, data: Dict):
    """
    Cập nhật 1 hoặc nhiều chỉ số fight.
    - data là dict của các trường bên trong text_fight, ví dụ {"hp": 5000, "mana": 300}
    - Không tạo user mới (upsert=False) để tránh document rác; đảm bảo user được tạo bởi create_user/get_user trước.
    """
    if not isinstance(data, dict) or not data:
        return
    try:
        update_data = {f"text_fight.{k}": v for k, v in data.items()}
        users_col.update_one({"_id": user_id}, {"$set": update_data}, upsert=False)
    except Exception as e:
        print(f"[MongoDB] ❌ Lỗi cập nhật text_fight cho {user_id}: {e}")

def modify_hp(user_id: str, delta: int):
    """Thay đổi HP (cộng/trừ), hạn chế trong [0, max_hp]. Trả về giá trị HP mới."""
    tf = get_user_textfight(user_id)
    try:
        hp = _to_number(tf.get("hp", 0))
        max_hp = _to_number(tf.get("max_hp", DEFAULT_TEXTFIGHT["max_hp"]))
        new_hp = max(0, min(hp + int(delta), int(max_hp)))
        update_textfight(user_id, {"hp": new_hp})
        return new_hp
    except Exception as e:
        print(f"[modify_hp] Lỗi cho {user_id}: {e}")
        return tf.get("hp", 0)

def modify_mana(user_id: str, delta: int):
    """Thay đổi mana (cộng/trừ), hạn chế trong [0, max_mana]. Trả về mana mới."""
    tf = get_user_textfight(user_id)
    try:
        mana = _to_number(tf.get("mana", 0))
        max_mana = _to_number(tf.get("max_mana", DEFAULT_TEXTFIGHT["max_mana"]))
        new_mana = max(0, min(mana + int(delta), int(max_mana)))
        update_textfight(user_id, {"mana": new_mana})
        return new_mana
    except Exception as e:
        print(f"[modify_mana] Lỗi cho {user_id}: {e}")
        return tf.get("mana", 0)

def reset_textfight(user_id: str):
    """Đặt lại toàn bộ chỉ số về mặc định (ghi đè)."""
    try:
        users_col.update_one({"_id": user_id}, {"$set": {"text_fight": DEFAULT_TEXTFIGHT}}, upsert=True)
    except Exception as e:
        print(f"[reset_textfight] Lỗi cho {user_id}: {e}")

# === EQUIPMENT MANAGEMENT ===
def _get_equips(user_id: str) -> List[Optional[str]]:
    """Trả về danh sách 3 ô trang bị (None nếu trống). Luôn trả về list độ dài EQUIP_SLOTS."""
    doc = users_col.find_one({"_id": user_id}, {"fight_equips": 1}) or {}
    equips = doc.get("fight_equips") or []
    # normalize length
    equips = (equips + [None] * EQUIP_SLOTS)[:EQUIP_SLOTS]
    return equips

def _set_equips(user_id: str, equips: List[Optional[str]]):
    """Ghi danh sách trang bị (EQUIP_SLOTS phần tử)."""
    if not isinstance(equips, list) or len(equips) != EQUIP_SLOTS:
        raise ValueError(f"fight_equips phải là list gồm {EQUIP_SLOTS} phần tử")
    try:
        users_col.update_one({"_id": user_id}, {"$set": {"fight_equips": equips}}, upsert=True)
    except Exception as e:
        print(f"[_set_equips] Lỗi khi set equips cho {user_id}: {e}")

# === ITEM AND BONUS HELPERS ===
def _item_display(item_key: Optional[str]) -> str:
    """Hiển thị vật phẩm dạng icon + tên."""
    if not item_key:
        return "— trống —"
    item = shop_data.get(item_key, {})
    return f"{item.get('icon', '')} {item.get('name', item_key)}".strip()

def _gear_bonuses(item_key: str) -> Dict[str, float]:
    """
    Lấy dictionary bonuses từ item:
    - gộp cả "stats" và "effects" nếu có
    - chuyển giá trị không hợp lệ thành 0
    """
    item = shop_data.get(item_key, {})
    bonuses = {}
    for source in (item.get("stats", {}), item.get("effects", {})):
        if not isinstance(source, dict):
            continue
        for k, v in source.items():
            val = _to_number(v)
            bonuses[k] = bonuses.get(k, 0) + val
    return bonuses

def _aggregate_bonuses(equips: List[Optional[str]]) -> Dict[str, float]:
    """Gộp tổng bonus từ danh sách equips (không ghi DB)."""
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
    Áp dụng các bonus 'non-equip' trực tiếp vào text_fight (ghi vĩnh viễn).
    - bonus: dict các chỉ số cần cộng (vd: {"ad": 10, "max_hp": 200})
    - include_equips: nếu True → trả về thêm giá trị đã cộng bonus từ equips (không ghi equips vào DB)
    Trả về dict text_fight (kết quả, nhưng nếu include_equips thì đó là bản tính toán, không ghi equips).
    """
    tf = get_user_textfight(user_id)

    if bonus and isinstance(bonus, dict):
        for stat, value in bonus.items():
            val = _to_number(value)
            tf[stat] = tf.get(stat, 0) + val

        # Lưu lại các thay đổi 'permanent bonus' (chỉ những stat đã chỉnh)
        try:
            # Ghi only changed keys
            update_textfight(user_id, {k: tf[k] for k in bonus.keys()})
        except Exception as e:
            print(f"[apply_stat_bonus] Lỗi ghi DB cho {user_id}: {e}")

    if include_equips:
        equips = _get_equips(user_id)
        equip_bonus = _aggregate_bonuses(equips)
        # trả về bản tính toán tạm (không ghi equip bonuses vào DB)
        combined = tf.copy()
        for stat, v in equip_bonus.items():
            combined[stat] = combined.get(stat, 0) + v
        return combined

    return tf

def remove_stat_bonus(user_id: str, bonus: Dict[str, float] = None, include_equips: bool = False):
    """
    Trừ các chỉ số permanent (vd: lúc tháo buff) khỏi text_fight.
    - bonus: dict các chỉ số cần trừ
    - include_equips: nếu True → trả về bản tính toán sau khi trừ equip bonuses (không ghi)
    """
    tf = get_user_textfight(user_id)

    if bonus and isinstance(bonus, dict):
        for stat, value in bonus.items():
            val = _to_number(value)
            tf[stat] = tf.get(stat, 0) - val

        try:
            update_textfight(user_id, {k: tf[k] for k in bonus.keys()})
        except Exception as e:
            print(f"[remove_stat_bonus] Lỗi ghi DB cho {user_id}: {e}")

    if include_equips:
        equips = _get_equips(user_id)
        equip_bonus = _aggregate_bonuses(equips)
        combined = tf.copy()
        for stat, v in equip_bonus.items():
            combined[stat] = combined.get(stat, 0) - v
        return combined

    return tf

# === FULL STATS (computed on-the-fly) ===
def get_full_stats(user_id: str) -> Dict:
    """
    Trả về chỉ số đầy đủ của người chơi:
    - base = text_fight (những gì lưu trong DB)
    - equips bonuses được tính ở runtime, không ghi vào DB
    Trả về dict kết hợp và kèm key "equips" (list các key).
    """
    tf = get_user_textfight(user_id)
    equips = _get_equips(user_id)
    equip_bonus = _aggregate_bonuses(equips)

    total = tf.copy()
    for stat, val in equip_bonus.items():
        total[stat] = total.get(stat, 0) + val

    total["equips"] = equips
    return total

# === BACKWARDS-COMPATIBLE ALIAS ===
def update_user_stats(user_id: str, data: dict):
    """Alias cho update_textfight (giữ tên cũ nếu code khác gọi)."""
    return update_textfight(user_id, data)

# === AUTO CHECK hp/DEATH ===
@tasks.loop(minutes=1)
async def auto_check_life_and_death():
    """Kiểm tra trạng thái sinh tử của người chơi (theo text_fight)."""
    now = datetime.now(timezone.utc)
    try:
        cursor = users_col.find(
            {"$or": [
                {"text_fight.hp": {"$lte": 0}},
                {"death": True}
            ]},
            {
                "_id": 1,
                "text_fight.hp": 1,
                "text_fight.max_hp": 1,
                "death": 1,
                "death_time": 1
            }
        )

        for user in cursor:
            user_id = user["_id"]
            text_fight = user.get("text_fight", {}) or {}
            hp = _to_number(text_fight.get("hp", 0))
            max_hp = _to_number(text_fight.get("max_hp", DEFAULT_TEXTFIGHT["max_hp"]))
            death = bool(user.get("death", False))
            death_time = _ensure_dt_aware(user.get("death_time"))

            # Khi người chơi chết (chỉ đặt cờ + time)
            if hp <= 0 and not death:
                try:
                    users_col.update_one(
                        {"_id": user_id},
                        {"$set": {"death": True, "death_time": now + timedelta(hours=1)}}
                    )
                except Exception as e:
                    print(f"[auto_check] Lỗi set death cho {user_id}: {e}")

            # Khi người chơi hồi sinh
            elif death and death_time is not None and now >= death_time:
                try:
                    users_col.update_one(
                        {"_id": user_id},
                        {
                            "$set": {"death": False, "text_fight.hp": int(max_hp)},
                            "$unset": {"death_time": ""}
                        }
                    )
                except Exception as e:
                    print(f"[auto_check] Lỗi revive {user_id}: {e}")

    except Exception as e:
        print(f"[auto_check_life_and_death] Lỗi tổng: {e}")

# === STARTUP UTILS ===
def reapply_equipment_stats_on_startup():
    """
    (Legacy helper) Nếu trước đây bạn từng *ghi trực tiếp* bonuses của equipment xuống DB,
    hàm này cố gắng không làm gì gây nhân đôi. Trong thiết kế hiện tại bonuses của equipment
    được tính tại runtime trong get_full_stats(), nên không cần reapply.
    Đây là một hàm no-op giữ tương thích (gọi nó an toàn).
    """
    print("reapply_equipment_stats_on_startup: thiết kế mới tính equip bonuses on-the-fly; không có action.")

# End of file