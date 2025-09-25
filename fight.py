# fight.py
from typing import Optional, List
from shop_data import shop_data   # hoặc import đúng path bạn đang dùng
from .db import users_col          # hoặc import Mongo connection

# ---- Define for Text Fight ----
# Chỉ số cơ bản
DEFAULT_HP = 100
DEFAULT_ARMOR = 0      # giáp điểm (trừ thẳng damage)
BASE_DMG_MIN = 0
BASE_DMG_MAX = 0
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
