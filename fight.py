import os
import json
import random
from typing import List, Optional, Tuple, Dict

import discord
from discord.ext import commands
from data_handler import users_col

# ===== Base stats =====
DEFAULT_HP = 100
DEFAULT_ARMOR = 20  # giáp điểm cố định
BASE_DMG_MIN = 10
BASE_DMG_MAX = 25

EQUIP_SLOTS = 3  # chỉ có 3 ô trang bị

SHOP_PATH = os.path.join(os.path.dirname(__file__), "shop_data.json")

def _load_shop() -> Dict[str, dict]:
    try:
        with open(SHOP_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

SHOP = _load_shop()

def _find_item_key(id_or_name: str) -> Optional[str]:
    """Tìm key trong shop_data theo id (key) hoặc theo tên (case-insensitive)."""
    if id_or_name in SHOP:
        return id_or_name
    # tìm theo tên
    lower = id_or_name.lower()
    for key, item in SHOP.items():
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

def _get_profile(user_id: str) -> Dict[str, int]:
    doc = users_col.find_one({"_id": user_id}, {"fight_hp": 1}) or {}
    hp = int(doc.get("fight_hp", DEFAULT_HP))
    return {"hp": hp}

def _set_hp(user_id: str, hp: int):
    users_col.update_one({"_id": user_id}, {"$set": {"fight_hp": int(hp)}}, upsert=True)

def _user_inventory_count(user_id: str, item_name: str) -> int:
    doc = users_col.find_one({"_id": user_id}, {"items": 1}) or {}
    items = doc.get("items") or {}
    return int(items.get(item_name, 0))

def _equipped_count_of_item(user_id: str, item_key: str) -> int:
    equips = _get_equips(user_id)
    return sum(1 for k in equips if k == item_key)

def _gear_bonuses(item_key: str) -> Dict[str, int]:
    item = SHOP.get(item_key) or {}
    bonuses = item.get("bonuses") or {}
    return {
        "hp": int(bonuses.get("hp", 0)),
        "armor": int(bonuses.get("armor", 0)),
        "dmg_min": int(bonuses.get("dmg_min", 0)),
        "dmg_max": int(bonuses.get("dmg_max", 0)),
    }

def _aggregate_bonuses(equips: List[Optional[str]]) -> Dict[str, int]:
    total = {"hp": 0, "armor": 0, "dmg_min": 0, "dmg_max": 0}
    for key in equips:
        if not key:
            continue
        b = _gear_bonuses(key)
        for k in total:
            total[k] += b[k]
    return total

def _effective_stats(user_id: str) -> Dict[str, int]:
    """Trả về chỉ số hiệu dụng với trang bị: max_hp, armor, dmg_min, dmg_max, curr_hp."""
    equips = _get_equips(user_id)
    agg = _aggregate_bonuses(equips)
    max_hp = DEFAULT_HP + agg["hp"]
    armor = DEFAULT_ARMOR + agg["armor"]
    dmg_min = BASE_DMG_MIN + agg["dmg_min"]
    dmg_max = BASE_DMG_MAX + agg["dmg_max"]
    # đảm bảo hợp lệ
    if dmg_min > dmg_max:
        dmg_min = dmg_max
    curr_hp = _get_profile(user_id)["hp"]
    return {"max_hp": max_hp, "armor": armor, "dmg_min": dmg_min, "dmg_max": dmg_max, "curr_hp": curr_hp}

def _clamp_hp_to_max(user_id: str):
    stats = _effective_stats(user_id)
    if stats["curr_hp"] > stats["max_hp"]:
        _set_hp(user_id, stats["max_hp"])

def _item_display(item_key: Optional[str]) -> str:
    if not item_key:
        return "— trống —"
    data = SHOP.get(item_key, {})
    icon = data.get("icon", "")
    name = data.get("name", item_key)
    return f"{icon} {name}".strip()

class FightEquip(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ===== Combat =====
    @commands.command(name="attack", help="`$attack @user` → tấn công người chơi")
    async def attack(self, ctx: commands.Context, target: discord.Member):
        attacker_id = str(ctx.author.id)
        target_id = str(target.id)

        if target.bot:
            await ctx.reply("❌ Không thể tấn công bot.")
            return
        if target_id == attacker_id:
            await ctx.reply("❌ Không thể tự tấn công chính mình.")
            return

        atk_stats = _effective_stats(attacker_id)
        tgt_stats = _effective_stats(target_id)

        raw = random.randint(atk_stats["dmg_min"], atk_stats["dmg_max"])
        dmg = max(1, raw - tgt_stats["armor"])
        new_hp = max(0, tgt_stats["curr_hp"] - dmg)

        _set_hp(target_id, new_hp)

        msg = (
            f"💥 **{ctx.author.name}** tấn công **{target.name}** gây `{dmg}` sát thương "
            f"(raw {raw} - giáp {tgt_stats['armor']}).\n"
            f"❤️ HP của {target.name}: `{new_hp}/{tgt_stats['max_hp']}`"
        )

        if new_hp <= 0:
            # reset theo max HP mới (có tính trang bị nạn nhân)
            # cần tính lại stats sau khi vẫn còn đeo trang bị
            tgt_stats_after = _effective_stats(target_id)
            _set_hp(target_id, tgt_stats_after["max_hp"])
            msg += f"\n☠️ {target.name} đã gục ngã! HP reset về {tgt_stats_after['max_hp']}."
        await ctx.send(msg)

    # ===== View equips & stats =====
    @commands.command(name="gear", help="`$gear` → xem 3 ô trang bị & chỉ số")
    async def gear(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        member = member or ctx.author
        user_id = str(member.id)
        equips = _get_equips(user_id)
        stats = _effective_stats(user_id)
        lines = [
            f"**Ô 1:** {_item_display(equips[0])}",
            f"**Ô 2:** {_item_display(equips[1])}",
            f"**Ô 3:** {_item_display(equips[2])}",
            "",
            f"❤️ HP: `{stats['curr_hp']}/{stats['max_hp']}`",
            f"🛡️ Giáp (điểm): `{stats['armor']}`",
            f"🗡️ Damage: `{stats['dmg_min']}–{stats['dmg_max']}`",
        ]
        await ctx.reply("\n".join(lines))

    # ===== Equip / Unequip =====
    @commands.command(name="equip", help="`$equip <item_id_or_name> [ô]` → đeo vào ô trống đầu (hoặc ô 1–3 nếu chỉ định)")
    async def equip(self, ctx: commands.Context, item_id_or_name: str, slot: Optional[int] = None):
        user_id = str(ctx.author.id)

        # tìm item
        key = _find_item_key(item_id_or_name)
        if not key:
            await ctx.reply("❌ Không tìm thấy món đó trong cửa hàng.")
            return

        data = SHOP.get(key) or {}
        if not data.get("gear", False):
            await ctx.reply("❌ Món này không phải trang bị.")
            return

        name = data.get("name", key)
        # kiểm tra số lượng sở hữu
        owned = _user_inventory_count(user_id, name)
        if owned <= 0:
            await ctx.reply(f"❌ Bạn không sở hữu **{name}**.")
            return

        equips = _get_equips(user_id)
        # đếm số đang đeo món này
        equipped_cnt = sum(1 for k in equips if k == key)
        if equipped_cnt >= owned:
            await ctx.reply(f"❌ Bạn chỉ sở hữu `{owned}` **{name}** và đã đeo hết.")
            return

        # chọn slot
        if slot is None:
            try:
                idx = equips.index(None)  # ô trống đầu tiên
            except ValueError:
                await ctx.reply("❌ Cả 3 ô đều đã đầy. Hãy chỉ định ô 1–3 để thay thế, hoặc `$unequip <ô>` trước.")
                return
        else:
            if slot not in (1, 2, 3):
                await ctx.reply("❌ Ô hợp lệ: 1, 2, hoặc 3.")
                return
            idx = slot - 1

        # nếu thay thế, không cần kiểm tra trùng vì đã kiểm tra quota ở trên
        equips[idx] = key
        _set_equips(user_id, equips)

        # clamp HP nếu max HP giảm/tăng
        _clamp_hp_to_max(user_id)

        await ctx.reply(f"✅ Đã trang bị **{name}** vào ô `{idx+1}`.")

    @commands.command(name="unequip", help="`$unequip <ô>` → tháo trang bị ở ô 1–3")
    async def unequip(self, ctx: commands.Context, slot: int):
        if slot not in (1, 2, 3):
            await ctx.reply("❌ Ô hợp lệ: 1, 2, hoặc 3.")
            return
        user_id = str(ctx.author.id)
        equips = _get_equips(user_id)
        idx = slot - 1
        if not equips[idx]:
            await ctx.reply("❌ Ô này đang trống.")
            return
        removed_key = equips[idx]
        equips[idx] = None
        _set_equips(user_id, equips)

        # clamp HP nếu max HP giảm
        _clamp_hp_to_max(user_id)

        name = SHOP.get(removed_key, {}).get("name", removed_key)
        await ctx.reply(f"✅ Đã tháo **{name}** khỏi ô `{slot}`.")

    # ===== Quick stats =====
    @commands.command(name="fstats", help="`$fstats [@user]` → xem HP & giáp hiệu dụng")
    async def fstats(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        member = member or ctx.author
        user_id = str(member.id)
        stats = _effective_stats(user_id)
        await ctx.reply(
            f"📊 **{member.name}** — HP: `{stats['curr_hp']}/{stats['max_hp']}`, Giáp: `{stats['armor']}`, "
            f"DMG: `{stats['dmg_min']}–{stats['dmg_max']}`."
        )

async def setup_fight(bot: commands.Bot):
    await bot.add_cog(FightEquip(bot))
