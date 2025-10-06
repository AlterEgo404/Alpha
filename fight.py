# fight.py
from typing import Optional, List
from data_handler import users_col, get_user, update_user       # hoặc import Mongo connection
import json
import os
import datetime

def load_json(file_name, default_data=None):
    if not os.path.exists(file_name):
        default_data = default_data or {}
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
    with open(file_name, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(file_name, data):
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

shop_data = load_json('shop_data.json')
save_shop_data = lambda data: save_json('shop_data.json', data)

# ---- Define for Text Fight ----
# Chỉ số cơ bản
DEFAULT_HP = 400
DEFAULT_ARMOR = 0      # giáp điểm (trừ thẳng damage)
BASE_DMG_MIN = 10
BASE_DMG_MAX = 60
EQUIP_SLOTS = 3         # 3 ô trang bị

def _find_item_key(id_or_name: str) -> Optional[str]:
    """Tìm key trong shop_data theo id (key) hoặc theo tên (không phân biệt hoa/thường)."""
    if id_or_name in shop_data:
        return id_or_name
    lower = str(id_or_name).lower()
    for key, item in shop_data.items():
        if str(item.get("name", "")).lower() == lower:
            return key
    return None

def _get_equips(user_id: str) -> List[Optional[str]]:
    doc = users_col.find_one({"_id": user_id}, {"fight_equips": 1}) or {}
    equips = doc.get("fight_equips")
    if not isinstance(equips, list):
        equips = [None] * EQUIP_SLOTS
    if len(equips) < EQUIP_SLOTS:
        equips = equips + [None] * (EQUIP_SLOTS - len(equips))
    return equips[:EQUIP_SLOTS]

def _set_equips(user_id: str, equips: List[Optional[str]]):
    if not isinstance(equips, list) or len(equips) != EQUIP_SLOTS:
        raise ValueError("equips phải là list có đúng 3 phần tử")
    users_col.update_one({"_id": user_id}, {"$set": {"fight_equips": equips}}, upsert=True)

def _get_curr_hp(user_id: str) -> int:
    doc = users_col.find_one({"_id": user_id}, {"fight_hp": 1}) or {}
    return int(doc.get("fight_hp", DEFAULT_HP))

def _set_curr_hp(user_id: str, hp: int):
    users_col.update_one({"_id": user_id}, {"$set": {"fight_hp": int(hp)}}, upsert=True)

def _user_inventory_count(user_id: str, item_name: str) -> int:
    """Kho đồ lưu theo TÊN item."""
    doc = users_col.find_one({"_id": user_id}, {"items": 1}) or {}
    items = doc.get("items") or {}
    return int(items.get(item_name, 0))

def _gear_bonuses(item_key):
    """
    Đọc stats + effects từ 1 item.
    - stats: cộng thẳng
    - effects: buff đặc biệt (ví dụ % máu)
    """
    item = shop_data.get(item_key) or {}
    stats = item.get("stats", {})
    effects = item.get("effects", {})

    def as_int(x):
        try:
            return int(x)
        except Exception:
            return 0

    return {
        "hp_flat": as_int(stats.get("hp", 0)),
        "armor": as_int(stats.get("armor", 0)),
        "dmg_min": as_int(stats.get("dmg_min", 0)),
        "dmg_max": as_int(stats.get("dmg_max", 0)),
        "hp_pct": float(effects.get("max_hp_percent", 0))
    }

def _aggregate_bonuses(equips):
    total = {"hp_flat": 0, "hp_pct": 0.0, "armor": 0, "dmg_min": 0, "dmg_max": 0}
    for key in equips:
        if not key:
            continue
        b = _gear_bonuses(key)
        total["hp_flat"] += b["hp_flat"]
        total["hp_pct"]  += b["hp_pct"]
        total["armor"]   += b["armor"]
        total["dmg_min"] += b["dmg_min"]
        total["dmg_max"] += b["dmg_max"]
    return total

def _effective_stats(user_id):
    """
    Max HP = (DEFAULT_HP + hp_flat) * (1 + hp_pct/100)
    Armor  = DEFAULT_ARMOR + armor (điểm)
    Damage = BASE + bonus (dmg_min <= dmg_max)
    """
    equips = _get_equips(user_id)
    agg = _aggregate_bonuses(equips)

    base_hp = DEFAULT_HP + agg["hp_flat"]
    max_hp = max(1, int(base_hp * (1.0 + agg["hp_pct"] / 100.0)))

    armor = DEFAULT_ARMOR + agg["armor"]

    dmg_min = BASE_DMG_MIN + agg["dmg_min"]
    dmg_max = BASE_DMG_MAX + agg["dmg_max"]
    if dmg_min > dmg_max:
        dmg_min = dmg_max

    curr_hp = _get_curr_hp(user_id)
    return {"max_hp": max_hp, "armor": armor, "dmg_min": dmg_min, "dmg_max": dmg_max, "curr_hp": curr_hp}

def _clamp_hp_to_max(user_id: str):
    stats = _effective_stats(user_id)
    if stats["curr_hp"] > stats["max_hp"]:
        _set_curr_hp(user_id, stats["max_hp"])

def _item_display(item_key: Optional[str]) -> str:
    if not item_key:
        return "— trống —"
    data = shop_data.get(item_key, {})
    icon = data.get("icon", "")
    name = data.get("name", item_key)
    return f"{icon} {name}".strip()

def check_player_dead(user_id: str):
    """
    Kiểm tra trạng thái sống/chết của người chơi.
    - Nếu fight_hp > 0: sống, return (True, None)
    - Nếu fight_hp <= 0 và chưa có dead_until: đánh dấu chết trong 1h
    - Nếu dead_until còn hạn: khóa toàn bộ lệnh
    - Nếu hết hạn: hồi sinh (đầy máu)
    Trả về: (alive: bool, message: Optional[str])
    """
    data = get_user(user_id)
    if not data:
        return True, None  # chưa có dữ liệu → cho qua

    hp = int(data.get("fight_hp", 0))
    now = datetime.now()

    # Nếu còn máu thì được dùng lệnh
    if hp > 0:
        return True, None

    # Nếu máu <= 0
    dead_until = data.get("dead_until")

    # Nếu đã có thời gian chết trong DB
    if dead_until:
        try:
            dead_until_dt = datetime.strptime(str(dead_until), "%Y-%m-%d %H:%M:%S")
        except Exception:
            # Nếu format lạ -> reset lại
            dead_until_dt = now + timedelta(hours=1)
            data["dead_until"] = dead_until_dt.strftime("%Y-%m-%d %H:%M:%S")
            update_user(user_id, data)
            return False, f"💀 Bạn vừa gục và phải chờ 1 giờ để hồi sinh (đến {data['dead_until']})."

        # Nếu vẫn đang trong thời gian án tử
        if now < dead_until_dt:
            remain = dead_until_dt - now
            m, s = divmod(int(remain.total_seconds()), 60)
            h, m = divmod(m, 60)
            msg = f"💀 Bạn đã chết! Hãy chờ {h} giờ {m} phút để hồi sinh."
            return False, msg
        else:
            # Đã hết án tử → hồi sinh
            max_hp = data.get("max_life", 100)
            data["fight_hp"] = int(max_hp)
            data["dead_until"] = None
            update_user(user_id, data)
            return True, "✨ Bạn đã hồi sinh và có thể chiến đấu tiếp!"
    else:
        # Chưa có dead_until → người chơi vừa chết
        new_dead = now + timedelta(hours=1)
        data["dead_until"] = new_dead.strftime("%Y-%m-%d %H:%M:%S")
        data["fight_hp"] = 0
        update_user(user_id, data)
        msg = f"💀 Bạn vừa gục và sẽ phải chờ 1 giờ để hồi sinh (đến {data['dead_until']})."
        return False, msg
