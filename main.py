import os
import io
import json
import math
import random
import datetime
import asyncio
import traceback
from typing import List, Optional

import discord
from discord.ext import commands

import aiohttp
from PIL import Image, ImageDraw, ImageFont
import re

# ==== DB & internal ====
from pymongo import MongoClient
from keep_alive import keep_alive

# ---- ENV & Secrets ----
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # bắt buộc
MONGO_URI = os.getenv("MONGO_URI")          # bắt buộc

if not DISCORD_TOKEN:
    raise RuntimeError("Thiếu biến môi trường DISCORD_TOKEN")
if not MONGO_URI:
    raise RuntimeError("Thiếu biến môi trường MONGO_URI")

# ---- Mongo ----
client = MongoClient(MONGO_URI)

# Load dữ liệu & handler
from data_handler import (
    get_user, update_user, create_user,
    get_jackpot, update_jackpot, set_jackpot,
    users_col, backgrounds_col
)

# Load hàm từ fight
from fight import (
    _get_equips, _set_equips, _gear_bonuses,
    _item_display, get_full_stats, update_user_stats,
    auto_check_life_and_death, apply_stat_bonus, remove_stat_bonus
)

# ---- Discord ----
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents, help_command=None)

# ---- Constants ----
ALLOWED_CHANNEL_ID = 1411177026588643369
coin = "<:meme_coin:1362951683814199487>"

dice_emojis = {
    0: "<a:dice_roll:1362951541132099584>",
    1: "<:dice_1:1362951590302056849>",
    2: "<:dice_2:1362951604600307792>",
    3: "<:dice_3:1362951621717266463>",
    4: "<:dice_4:1362951636573487227>",
    5: "<:dice_5:1362951651853336727>",
    6: "<:dice_6:1362951664729854152>",
}

# ---- JSON helpers ----
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

tu_vi = load_json('tu_vi.json')
save_tu_vi = lambda data: save_json('tu_vi.json', data)

gacha_data = load_json('gacha_data.json')
save_gacha_data = lambda data: save_json('gacha_data.json', data)

def get_user_background(user_id: str) -> str:
    doc = backgrounds_col.find_one({"_id": user_id})
    return doc.get("background", None) if doc else None

def set_user_background(user_id: str, background: str):
    backgrounds_col.update_one(
        {"_id": user_id},
        {"$set": {"background": background}},
        upsert=True
    )

def remove_user_background(user_id: str):
    backgrounds_col.delete_one({"_id": user_id})

# ---- Image/Text helpers ----
def draw_text_with_outline(draw, text, position, font, outline_color="black", fill_color="white"):
    x, y = position
    offsets = [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2)]
    for ox, oy in offsets:
        draw.text((x + ox, y + oy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)

def format_currency(amount):
    try:
        return f"{int(amount):,}".replace(",", " ")
    except Exception:
        return str(amount)

def count_items(items):
    counts = {}
    for name in items or {}:
        counts[name] = counts.get(name, 0) + 1
    return counts

# --- Server image & font cache ---
_SERVER_IMG_CACHE = None
_FONT_CACHE = {}

def _get_font(sz: int):
    key = ("Roboto-Black.ttf", sz)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    try:
        font = ImageFont.truetype("Roboto-Black.ttf", sz)
    except IOError:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font

async def _ensure_server_img():
    global _SERVER_IMG_CACHE
    if _SERVER_IMG_CACHE is None:
        try:
            _SERVER_IMG_CACHE = Image.open("1.png").convert("RGBA").resize((80, 80))
        except Exception:
            _SERVER_IMG_CACHE = None

def _render_cccd_canvas(canvas, user_name, user_id, smart, level, role_name,
                        progress_pct, next_smart):
    draw = ImageDraw.Draw(canvas)
    font_small = _get_font(12)
    font_large = _get_font(13)

    # Header
    draw_text_with_outline(
        draw,
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA MEME\n          Độc lập - Tự do - Hạnh phúc\n\n                 CĂN CƯỚC CƯ DÂN",
        (100, 20), font_large
    )

    # Thông tin cơ bản
    draw_text_with_outline(
        draw,
        f"Tên: {user_name}\nID: {user_id}\nHọc vấn: {format_currency(smart)}\n"
        f"lv: {format_currency(level)}\nTrình độ: {role_name}",
        (160, 85), font_large
    )

    # Thanh tiến độ học vấn
    pct = max(0.0, min(1.0, (progress_pct or 0) / 100.0))
    bar_left, bar_top, bar_right, bar_bottom = 160, 185, 360, 205
    draw.rectangle((bar_left, bar_top, bar_right, bar_bottom), outline="black", width=3)
    inner_left, inner_top = bar_left + 3, bar_top + 3
    inner_right = inner_left + int((bar_right - bar_left - 6) * pct)
    inner_bottom = bar_bottom - 3
    if inner_right > inner_left:
        draw.rectangle((inner_left, inner_top, inner_right, inner_bottom), fill="#1E90FF")
    draw_text_with_outline(draw, f"{smart}/{next_smart}", (inner_left + 2, inner_top), font_small)

    bio = io.BytesIO()
    canvas.save(bio, "PNG")
    bio.seek(0)
    return bio

# ---- Gacha ----
def roll_gacha_from_pool():
    rarity_list = list(gacha_data["rarity_chance"].keys())
    rarity_weights = list(gacha_data["rarity_chance"].values())
    selected_rarity = random.choices(rarity_list, weights=rarity_weights, k=1)[0]
    item_name = random.choice(gacha_data["gacha_pool"][selected_rarity])
    return {"name": item_name, "rarity": selected_rarity}

def calculate_level_and_progress(smart):
    level = int(math.log2(smart / 5 + 1)) + 1
    needed_smart = 5 * ((2 ** (level - 1)) - 1)
    current_smart = max(0, smart - 5 * ((2 ** (level - 2)) - 1)) if level > 1 else smart
    next_level_needed_smart = 5 * ((2 ** level) - 1)
    progress_percentage = min((smart / next_level_needed_smart) * 100, 100) if next_level_needed_smart > 0 else 0
    return level, round(progress_percentage, 2), next_level_needed_smart

def _best_tuvi_role(level: int):
    """Trả về (role_name, role_id) tốt nhất theo level, hoặc ('None', None) nếu không có."""
    best_name, best_id, best_min = "None", None, -1
    for name, info in tu_vi.items():
        lvmin = int(info.get("level_min", 0))
        if level >= lvmin and lvmin > best_min:
            best_name, best_id, best_min = name, int(info.get("id", 0)), lvmin
    return best_name, (best_id if best_id != 0 else None)

async def _ensure_server_img():
    """Đảm bảo _SERVER_IMG_CACHE đã được load & resize sẵn."""
    global _SERVER_IMG_CACHE
    if _SERVER_IMG_CACHE is None:
        try:
            _SERVER_IMG_CACHE = Image.open("1.png").convert("RGBA").resize((80, 80))
        except Exception:
            _SERVER_IMG_CACHE = None

# ---- Permissions & user checks ----
async def check_permission(ctx, user_id):

    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return False

    return True

# ---- HTTP session (reused) ----
http_session: aiohttp.ClientSession | None = None

# --- Image cache & timeout for fetch_image ---
_IMG_BYTES_CACHE = {}  # url -> bytes (avatar/bg)

async def fetch_image(url: str, timeout_sec: int = 5, cache: bool = True):
    """Tải ảnh RGBA, có cache và timeout. Trả None nếu lỗi/chậm."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        if cache and url in _IMG_BYTES_CACHE:
            return Image.open(io.BytesIO(_IMG_BYTES_CACHE[url])).convert("RGBA")
        assert http_session is not None
        async with http_session.get(
            url, timeout=aiohttp.ClientTimeout(total=timeout_sec)
        ) as resp:
            if resp.status != 200:
                print("fetch_image status", resp.status, url)
                return None
            data = await resp.read()
        if cache:
            _IMG_BYTES_CACHE[url] = data
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as e:
        print("fetch_image error:", e, url)
        return None

# ---- Background tasks ----
async def update_company_balances():
    """Cứ 60s: biến động dương/lỗ nhẹ với balance công ty."""
    while True:
        try:
            cursor = users_col.find({"company_balance": {"$gt": 0}}, {"company_balance": 1})
            for doc in cursor:
                uid = doc["_id"]
                balance = doc.get("company_balance", 0)
                modifier = random.choice([-0.01, 0.01])
                new_balance = max(0, int(balance + balance * modifier))
                if new_balance != balance:
                    update_user(uid, {"company_balance": new_balance})
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(60)

async def clean_zero_items():
    """Cứ 10s: xoá item có số lượng <= 0 để gọn DB."""
    while True:
        try:
            cursor = users_col.find({"items": {"$exists": True}})
            for doc in cursor:
                uid = doc["_id"]
                items = doc.get("items", {}) or {}
                new_items = {k: v for k, v in items.items() if isinstance(v, int) and v > 0}
                if new_items != items:
                    update_user(uid, {"items": new_items})
        except Exception:
            traceback.print_exc()
        await asyncio.sleep(10)

_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]+:(\d+)>")
_EMOJI_IMG_CACHE = {}  # (emoji_id, size) -> PIL.Image

async def icon_to_image(icon_str: str, size: int = 24):
    """
    Trả về PIL.Image (RGBA) từ icon custom emoji <:...:id> / <a:...:id>.
    Dùng Discord CDN. Có cache theo (id, size).
    """
    if not icon_str:
        return None
    m = _CUSTOM_EMOJI_RE.fullmatch(icon_str.strip())
    if not m:
        return None  # không phải custom emoji

    emoji_id = m.group(1)
    cache_key = (emoji_id, size)
    if cache_key in _EMOJI_IMG_CACHE:
        return _EMOJI_IMG_CACHE[cache_key]

    # Ưu tiên PNG (fallback WEBP)
    for ext in ("png", "webp"):
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size={size}&quality=lossless"
        img = await fetch_image(url)  # hàm async của bạn, trả PIL.Image RGBA
        if img:
            img = img.resize((size, size))
            _EMOJI_IMG_CACHE[cache_key] = img
            return img
    return None

# ==== EVENTS ====
@bot.event
async def on_ready():
    global http_session
    print(f'Bot đã đăng nhập với tên {bot.user}')
    http_session = aiohttp.ClientSession()

    bot.loop.create_task(update_company_balances())
    bot.loop.create_task(clean_zero_items())
    if not auto_check_life_and_death.is_running():
        auto_check_life_and_death.start()
    print(f"✅ Bot đã khởi động: {bot.user}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.reply("❌ Lệnh bạn nhập không tồn tại. Vui lòng kiểm tra lại :>")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("⚠️ Bạn thiếu một tham số cần thiết. Vui lòng kiểm tra lại cú pháp lệnh.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("❌ Đối số bạn nhập không hợp lệ. Vui lòng kiểm tra lại.")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.reply("🚫 Bạn không có quyền sử dụng lệnh này.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(f"⏳ Lệnh đang trong thời gian hồi. Thử lại sau `{round(error.retry_after, 1)} giây`.")
    elif isinstance(error, commands.CheckFailure):
        await ctx.reply("❗Bạn không được phép sử dụng lệnh này ở đây.")
    else:
        # In đầy đủ stacktrace cho dễ debug
        traceback.print_exc()
        await ctx.reply("⚠️ Đã xảy ra lỗi không mong muốn. Vui lòng thử lại sau!")

@bot.event
async def on_close():
    # đóng session HTTP nếu có
    global http_session
    try:
        if http_session and not http_session.closed:
            await http_session.close()
    finally:
        http_session = None

# ==== COMMANDS ==== 
# (Phần dưới GIỮ NGUYÊN đa số logic của bạn; chỉ sửa các điểm lỗi/bảo mật)

@bot.command(name="start", help='`$start`\n> Khởi tạo tài khoản')
async def start(ctx):

    user_id = str(ctx.author.id)
    member = ctx.author

    if get_user(user_id):
        await ctx.reply(f"Bạn đã có tài khoản rồi, {ctx.author.mention} ơi! Không cần tạo lại nữa.")
        return

    user_data = {"points": 10000, "items": {}, "smart": 100}
    create_user(user_id, user_data)

    role_id = 1316985467853606983
    role = ctx.guild.get_role(role_id)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
    else:
        await ctx.reply("Không thể tìm thấy vai trò cần thiết trong server.")

    await ctx.reply(f"Tài khoản của bạn đã được tạo thành công, {ctx.author.mention}!")

@bot.command(name="info", help='`$info`\n> xem thông tin của Bot')
async def info(ctx):
    embed = discord.Embed(title="📊 Thông tin Bot", color=discord.Color.red())
    embed.add_field(name="👩‍💻 Nhà phát triển", value="```ansi\n[2;31mAlpha[0m```", inline=True)
    embed.add_field(name="Phiên bản Bot", value="```ansi\n[2;34m2.0.0[0m```")
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1322746396142604378/1322746745440043143/2.png")
    await ctx.reply(embed=embed)

@bot.command(name="jar", help='`$jar`\n> xem hũ jackpot')
async def jp(ctx):
    jackpot_amount = format_currency(get_jackpot() or 0)
    await ctx.reply(f"💰 **Jackpot hiện tại:** {jackpot_amount} {coin}")

@bot.command(name="shop", help='`$shop`\n> xem cửa hàng')
async def shop(ctx):
    embed = discord.Embed(
        title="🏬 **Cửa hàng**",
        description="Mua: `$buy <id> <số lượng>` • Bán: `$sell <id> <số lượng>`",
        color=discord.Color.red()
    )
    for item_id, item in shop_data.items():
        name = item.get("name", "Không tên")
        price = item.get("price", 0)
        icon = item.get("icon", "")
        embed.add_field(
            name=f"`{item_id}` {icon} {name}",
            value=f"`{format_currency(price)}` {coin}",
            inline=True
        )
    await ctx.reply(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_id: str, quantity: int):

    user_id = str(ctx.author.id)

    if not await check_permission(ctx, user_id):
        return

    if item_id not in shop_data:
        await ctx.reply("Không tìm thấy mặt hàng trong cửa hàng.")
        return
    if quantity <= 0:
        await ctx.reply("Số lượng phải lớn hơn không.")
        return

    item_data = shop_data[item_id]
    item_name = item_data['name']
    user = get_user(user_id)
    if not user:
        await ctx.reply("Không tìm thấy dữ liệu người dùng.")
        return

    user_items = user.get('items', {}) or {}
    total_price = int(item_data['price']) * int(quantity)

    if total_price > user.get('points', 0):
        await ctx.reply("Bạn không đủ tiền để mua món này.")
        return

    if item_id == "01" and "company_balance" not in user:
        user["company_balance"] = 0

    user['points'] = user.get('points', 0) - total_price
    user_items[item_name] = int(user_items.get(item_name, 0)) + int(quantity)
    user['items'] = user_items
    update_user(user_id, user)

    await ctx.reply(f"Bạn đã mua {quantity} {item_name}.")

@bot.command(name="sell")
async def sell(ctx, item_id: str, quantity: int):

    user_id = str(ctx.author.id)

    if not await check_permission(ctx, user_id):
        return

    if item_id not in shop_data:
        await ctx.reply("Không thấy mặt hàng này trong cửa hàng.")
        return
    if quantity <= 0:
        await ctx.reply("Số lượng phải lớn hơn không.")
        return

    item_data = shop_data[item_id]
    item_name = item_data['name']
    selling_price = round(int(item_data['price']) * int(quantity) * 0.9)

    user = get_user(user_id)
    if not user:
        await ctx.reply("Không tìm thấy dữ liệu người dùng.")
        return

    user_items = user.get('items', {}) or {}
    current_quantity = int(user_items.get(item_name, 0))

    if current_quantity < quantity:
        await ctx.reply("Bạn không có đủ mặt hàng này để bán.")
        return

    user_items[item_name] = current_quantity - quantity

    if item_id == "01" and user_items.get(":office: Công ty", 0) == 0:
        user.pop("company_balance", None)

    user['points'] = int(user.get('points', 0)) + selling_price
    user['items'] = user_items
    update_user(user_id, user)

    await ctx.reply(f"Bạn đã bán {quantity} {item_name} và nhận {format_currency(selling_price)} {coin}.")

@bot.command(name="ttsp", help="`$ttsp <id sản phẩm>`\n> Hiển thị thông tin sản phẩm")
async def ttsp(ctx, item_id):
    item_data = shop_data.get(item_id)
    if not item_data:
        await ctx.reply("Không tìm thấy sản phẩm với ID này.")
        return
    embed = discord.Embed(
        title=f"Thông tin sản phẩm:\n{item_data.get('name','(Không tên)')}",
        color=discord.Color.red()
    )
    embed.add_field(name="Mô tả", value=item_data.get('description','(không có)'), inline=False)
    embed.add_field(name="Giá mua", value=f'`{format_currency(item_data.get("price",0))}` {coin}', inline=True)
    embed.add_field(name="Giá bán", value=f'`{format_currency(round(item_data.get("price",0) * 0.9))}` {coin}', inline=True)
    await ctx.reply(embed=embed)

@bot.command(name="setb")
async def set_background(ctx, member: discord.Member, background_url: str):

    if ctx.author.id != 1361702060071850024:
        await ctx.reply("Chỉ người dùng được phép mới có thể sử dụng lệnh này.")
        return

    # Check link hợp lệ
    if not background_url.startswith(("http://", "https://")):
        await ctx.reply("URL không hợp lệ. Vui lòng cung cấp URL hợp lệ.")
        return

    user_id = str(member.id)

    # Lưu vào DB Mongo
    set_user_background(user_id, background_url)

    await ctx.reply(f"✅ Đã thay đổi nền của **{member.display_name}** thành: {background_url}")

@bot.command(name="cccd", help='`$cccd`\n> mở căn cước công dân')
async def cccd(ctx, member: discord.Member = None, size: int = 128):

    member = member or ctx.author
    user_id = str(member.id)

    if not await check_permission(ctx, user_id):
        return

    # ===== DB & chỉ số học vấn =====
    data = get_user(user_id) or {}
    smart = int(data.get("smart", 0))
    user_name = member.name

    avatar_asset = member.display_avatar.with_size(size)
    if hasattr(avatar_asset, "with_static_format"):
        avatar_asset = avatar_asset.with_static_format("webp")
    avatar_url = avatar_asset.url

    level, progress_pct, next_smart = calculate_level_and_progress(smart)

    # ===== Role tu_vi =====
    def _best_tuvi_role(level: int):
        best_name, best_id, best_min = "None", None, -1
        for name, info in tu_vi.items():
            lvmin = int(info.get("level_min", 0))
            if level >= lvmin and lvmin > best_min:
                best_name, best_id, best_min = name, int(info.get("id", 0)), lvmin
        return best_name, (best_id if best_id else None)

    role_name, role_id = _best_tuvi_role(level)
    wanted = ctx.guild.get_role(role_id) if role_id else None
    tuvi_role_ids = {int(info.get("id", 0)) for info in tu_vi.values() if "id" in info}
    current_tuvi_roles = [r for r in member.roles if r.id in tuvi_role_ids]
    try:
        to_remove = [r for r in current_tuvi_roles if (not wanted or r.id != wanted.id)]
        if to_remove:
            await member.remove_roles(*to_remove, reason="Update cấp bậc tu_vi")
        if wanted and wanted not in member.roles:
            await member.add_roles(wanted, reason="Assign cấp bậc tu_vi")
    except discord.Forbidden:
        pass

    # ===== Tải ảnh (song song) =====
    bg_url = get_user_background(user_id)
    if not bg_url:
        bg_url = "https://wallpaperaccess.com/full/1556608.jpg"  # default
    await _ensure_server_img()
    avatar_img, bg_img = await asyncio.gather(
        fetch_image(avatar_url, timeout_sec=6),
        fetch_image(bg_url, timeout_sec=6),
    )
    if not avatar_img:
        await ctx.reply("Lỗi tải ảnh avatar.")
        return
    if not bg_img:
        await ctx.reply("Lỗi tải ảnh nền.")
        return

    # ===== Ghép ảnh =====
    avatar_img = avatar_img.resize((120, 120))
    canvas = bg_img.resize((400, 225)).copy()
    if _SERVER_IMG_CACHE:
        canvas.paste(_SERVER_IMG_CACHE, (10, 10), mask=_SERVER_IMG_CACHE)
    canvas.paste(avatar_img, (20, 85), mask=avatar_img)

    # ===== Render CCCD (chỉ thông tin cơ bản + học vấn) =====
    bio = await asyncio.to_thread(
        _render_cccd_canvas,
        canvas, user_name, user_id, smart, level, role_name,
        progress_pct, next_smart
    )

    await ctx.reply(file=discord.File(fp=bio, filename="cccd.png"))

@bot.command(name="bag", help='`$bag`\n> mở túi')
async def bag(ctx, member: discord.Member = None):
    
    member = member or ctx.author
    user_id = str(member.id)
    
    if not await check_permission(ctx, user_id):
        return

    # Lấy dữ liệu người dùng từ MongoDB
    data = get_user(user_id)
    points = format_currency(data.get('points', 0))
    items = data.get('items', {})
    company_balance = data.get("company_balance")

    # Định dạng danh sách item
    if not items:
        item_list = "Trống."
    else:
        item_list = ""
        for item_name, quantity in items.items():
            item_list += f"{item_name}: {quantity}\n"

    company_text = f"**Công ty**: {format_currency(company_balance)} {coin}." if company_balance is not None else ""

    # Tạo embed trả về
    embed = discord.Embed(
        title=f"**:luggage: Túi**\n{member}",
        description=(f"**Tài khoản**: {points} {coin}.\n"
                     f"**Kho đồ**:\n{item_list}"
                     f"{company_text}"),
        color=discord.Color.red()
    )

    await ctx.reply(embed=embed)

@bot.command(name="tx", help='`$tx <điểm> <t/x>`\n> chơi tài xỉu')
async def tx(ctx, bet: str, choice: str):
    try:
        user_id = str(ctx.author.id)
        data = get_user(user_id)

        if not await check_permission(ctx, user_id):
            return

        # Lấy jackpot hiện tại
        jackpot_amount = int(get_jackpot() or 0)
        jackpot_display = format_currency(jackpot_amount)

        # Xử lý tiền cược
        if bet.lower() == "all":
            bet_val = int(data.get("points", 0))
        else:
            try:
                bet_val = int(bet)
            except:
                await ctx.reply("Số tiền cược không hợp lệ.")
                return

        if bet_val <= 0 or bet_val > int(data.get("points", 0)):
            await ctx.reply("Bạn không đủ tiền để cược.")
            return

        # Kiểm tra lựa chọn
        choice = choice.lower()
        if choice not in ["t", "x"]:
            await ctx.reply("Bạn phải chọn 't' (Tài) hoặc 'x' (Xỉu).")
            return

        # ===== Gieo xúc xắc =====
        dice1, dice2, dice3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
        total = dice1 + dice2 + dice3

        # ===== KẾT QUẢ =====
        jackpot_won = False
        lose_protected = False
        win = (3 <= total <= 10 and choice == "x") or (11 <= total <= 18 and choice == "t")

        if bet_val * 500 >= jackpot_amount and total in (3, 18) and jackpot_amount > 0:
            # Ăn jackpot
            data["points"] += jackpot_amount
            set_jackpot(0)
            jackpot_won = True

        elif win:
            # Thắng
            data["points"] += bet_val

        else:
            # Thua — kiểm tra vật phẩm miễn thua
            items = data.get("items", {})
            mooncake_count = items.get(":moon_cake: Đậu xanh", 0)

            if mooncake_count > 0:
                lose_protected = True
                items[":moon_cake: Đậu xanh"] = mooncake_count - 1
                data["items"] = items
            else:
                # Không có vật phẩm => mất tiền + góp jackpot
                data["points"] -= bet_val
                update_jackpot(bet_val)

        # ===== Cập nhật DB =====
        update_user(user_id, data)

        # ===== Animation xúc xắc =====
        def _emoji(i):
            return dice_emojis.get(i, str(i))

        dice1_emoji, dice2_emoji, dice3_emoji = _emoji(dice1), _emoji(dice2), _emoji(dice3)
        dice_roll = _emoji(0)

        if choice == 'x':
            rolling_message = await ctx.reply(f"`   ` {dice_roll} `   `\n`  `{dice_roll} {dice_roll}`$$`")
        else:
            rolling_message = await ctx.reply(f"`   ` {dice_roll} `   `\n`$$`{dice_roll} {dice_roll}`  `")

        await asyncio.sleep(1)

        # ===== Hiển thị kết quả =====
        jackpot_text = f"\n🎉 Bạn ăn JACKPOT **{jackpot_display}**!" if jackpot_won else ""
        protection_text = "\nBạn đã đổi :moon_cake: đậu xanh để hoàn lại tiền thua" if lose_protected else ""

        if 3 <= total <= 10:  # Xỉu
            if choice == "x":
                await rolling_message.edit(
                    content=f"`   ` {dice1_emoji} `Xỉu`\n`  `{dice2_emoji} {dice3_emoji}`$$`{jackpot_text}{protection_text}"
                )
            else:
                await rolling_message.edit(
                    content=f"`   ` {dice1_emoji} `Xỉu`\n`$$`{dice2_emoji} {dice3_emoji}`  `\nHehe, {ctx.author.mention} ngu thì chết chứ sao :rofl:{jackpot_text}{protection_text}"
                )
        else:  # Tài
            if choice == "x":
                await rolling_message.edit(
                    content=f"`Tài` {dice1_emoji} `   `\n`  `{dice2_emoji} {dice3_emoji}`$$`\nHehe, {ctx.author.mention} ngu thì chết chứ sao :rofl:{jackpot_text}{protection_text}"
                )
            else:
                await rolling_message.edit(
                    content=f"`Tài` {dice1_emoji} `   `\n`$$`{dice2_emoji} {dice3_emoji}`  `{jackpot_text}{protection_text}"
                )

    except Exception as e:
        await ctx.reply(f"Đã xảy ra lỗi: {e}")

@bot.command(name="daily", help='`$daily`\n> nhận quà hằng ngày')
async def daily(ctx):

    user_id = str(ctx.author.id)
    data = get_user(user_id)

    if not await check_permission(ctx, user_id):
        return

    last_daily = data.get('last_daily')
    now = datetime.datetime.now()

    if last_daily is not None:
        last_daily_date = datetime.datetime.strptime(last_daily, "%Y-%m-%d")

        if last_daily_date.date() == now.date():
            next_daily = last_daily_date + datetime.timedelta(days=1)
            time_remaining = next_daily - now
            hours, remainder = divmod(time_remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            await ctx.reply(f"Bạn đã nhận quà hằng ngày rồi. Vui lòng thử lại sau: {hours} giờ {minutes} phút {seconds} giây.")
            return

        elif (now - last_daily_date).days == 1:
            data['streak'] = data.get('streak', 0) + 1
        else:
            data['streak'] = 1
    else:
        data['streak'] = 1

    base_reward = 5000
    streak_bonus = data['streak'] * 100
    total_reward = base_reward + streak_bonus

    data['points'] = data.get('points', 0) + total_reward
    data['last_daily'] = now.strftime("%Y-%m-%d")

    update_user(user_id, data)

    await ctx.reply(
        f"Bạn đã nhận được {format_currency(total_reward)} {coin}!"
        f" (Thưởng streak: {streak_bonus} {coin}, chuỗi ngày: {data['streak']} ngày)"
    )

@bot.command(name="beg", help='`$beg`\n> ăn xin')
async def beg(ctx):

    user_id = str(ctx.author.id)
    data = get_user(user_id)

    if not await check_permission(ctx, user_id):
        return

    last_beg = data.get('last_beg')
    now = datetime.datetime.now()

    if last_beg is not None:
        cooldown_time = 3 * 60  # 3 phút
        time_elapsed = (now - datetime.datetime.strptime(last_beg, "%Y-%m-%d %H:%M:%S")).total_seconds()

        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn đã ăn xin rồi, vui lòng thử lại sau {minutes} phút {seconds} giây.")
            return

    if data.get('points', 0) < 100_000:
        beg_amount = random.randint(0, 5000)
        data['points'] = data.get('points', 0) + beg_amount
    else:
        await ctx.reply('giàu mà còn đi ăn xin đéo thấy nhục à')
        return

    data['last_beg'] = now.strftime("%Y-%m-%d %H:%M:%S")

    update_user(user_id, data)

    await ctx.reply(f"Bạn đã nhận được {format_currency(beg_amount)} {coin} từ việc ăn xin!")

@bot.command(name="dn", help='`$dn <điểm> <người chơi>`\n> donate điểm cho người khác')
async def give(ctx, amount: int, member: discord.Member):

    giver_id = str(ctx.author.id)
    receiver_id = str(member.id)

    giver_data = get_user(giver_id)
    receiver_data = get_user(receiver_id)

    if not giver_data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return

    if not receiver_data:
        await ctx.reply("Có vẻ đối tượng chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return

    if amount <= 0:
        await ctx.reply(f"Số {coin} phải lớn hơn 0!")
        return

    if amount > giver_data.get('points', 0):
        await ctx.reply(f"Bạn không đủ {coin} để tặng!")
        return

    # Trừ điểm người gửi, cộng điểm người nhận
    giver_data['points'] -= amount
    receiver_data['points'] += amount

    # Lưu dữ liệu
    update_user(giver_id, giver_data)
    update_user(receiver_id, receiver_data)

    await ctx.reply(f"Bạn đã tặng {format_currency(amount)} {coin} cho {member.mention}!")

@bot.command(name="?", aliases=["help"], help="Hiển thị danh sách lệnh hoặc thông tin chi tiết về một lệnh.")
async def help(ctx, command=None):
    """Provides detailed help for commands or a general list of commands."""

    if command is None:
        embed = discord.Embed(
            title="Danh sách lệnh",
            description=(
                f"Lệnh tài khoản:\n> `$start`, `$lb`, `$dn`, `$cccd`, `$bag`\n"
                f"Lệnh mua bán:\n> `$shop`, `$ttsp`, `$buy`, `$sell`\n"
                f"Lệnh kiếm tiền:\n> `$daily`, `$beg`, `$hunt`\n"
                f"Lệnh tệ nạn:\n> `$tx`, `$rob`, `$orob`\n"
                f"Lệnh học vấn:\n> `$op`, `$study`"
            ),
            color=discord.Color.red()
        )
        
        await ctx.reply(embed=embed)
    else:
        cmd = bot.get_command(command)
        if cmd:
            embed = discord.Embed(title=f"Lệnh: `{cmd.name}`", description=cmd.help, color=discord.Color.red())
            await ctx.send(embed=embed)
        else:
            await ctx.send("Lệnh không tồn tại.")

@bot.command(name="rob", help='`$rob <người chơi> [công cụ]`\n> trộm 50% điểm của người khác')
async def rob(ctx, member: discord.Member, tool: str = None):

    robber_id = str(ctx.author.id)
    victim_id = str(member.id)
    status = member.status

    robber_data = get_user(robber_id)
    victim_data = get_user(victim_id)

    if not robber_data:
        await ctx.reply("Bạn chưa có tài khoản. Dùng `$start` để tạo.")
        return
    if not victim_data:
        await ctx.reply("Nạn nhân chưa có tài khoản.")
        return
    if victim_id == '1243079760062709854':
        await ctx.reply("Định làm gì với Admin Bot đấy?")
        return
    if status == discord.Status.online:
        await ctx.reply("Nó đang online đấy, cẩn thận không nó đấm!")
        return

    now = datetime.datetime.now()
    last_rob = robber_data.get("last_rob")
    if last_rob:
        elapsed = (now - datetime.datetime.strptime(last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if elapsed < 3600:
            skip = robber_data.get("items", {}).get(":fast_forward: Skip", 0)
            if skip > 0:
                update_user(robber_id, {"$inc": {"items.:fast_forward: Skip": -1}})
                await ctx.reply("Bạn đã dùng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                remaining = 3600 - int(elapsed)
                h, m = divmod(remaining, 60*60)
                m, s = divmod(m, 60)
                await ctx.reply(f"Bạn phải chờ {h} giờ {m} phút {s} giây nữa.")
                return

    items_r = robber_data.get("items", {})
    items_v = victim_data.get("items", {})
    has_lock = items_v.get(":lock: Ổ khóa", 0) > 0
    pet_guard = items_v.get(":dog: Pet bảo vệ", 0) > 0
    pet_thief = items_r.get(":cat: Pet trộm", 0) > 0

    if has_lock:
        tools = {
            "b": { "emoji": ":bomb: Bom", "chance": 0.75 },
            "w": { "emoji": ":wrench: Kìm", "chance": 0.5 },
            "c": { "emoji": "<:cleaner:1347560866291257385> máy hút bụi", "chance": 0.85 }
        }

        chosen_tool = tool.lower() if tool else None
        if chosen_tool in tools:
            tool_data = tools[chosen_tool]
            emoji = tool_data["emoji"]
            if items_r.get(emoji, 0) <= 0:
                await ctx.reply("Bạn không có công cụ đó.")
                return
            chance = tool_data["chance"]
            if pet_guard:
                chance -= 0.1
            if pet_thief:
                chance += 0.1
            success = random.random() < chance
            if success:
                update_user(victim_id, {"$inc": {f"items.:lock: Ổ khóa": -1}})
                update_user(robber_id, {"$inc": {f"items.{emoji}": -1}})
                if chosen_tool == "c":
                    if items_v:
                        random_item = random.choice(list(items_v.keys()))
                        update_user(victim_id, {"$inc": {f"items.{random_item}": -2000}})
                        await ctx.reply(f"Dùng {emoji} phá khóa và hút 2000 {random_item} của {member.mention}!")
                    else:
                        await ctx.reply("Dùng máy hút bụi phá khoá, nhưng họ không có gì để hút.")
                else:
                    await ctx.reply(f"Bạn đã dùng {emoji} và phá vỡ Ổ khóa của {member.mention}!")
            else:
                await ctx.reply("Phá khoá thất bại!")
                return
        else:
            await ctx.reply("Chọn `b`, `w`, hoặc `c` làm công cụ.")
            return

    victim_points = victim_data.get("points", 0)
    if victim_points <= 0:
        await ctx.reply(f"{member.name} không có {coin} để cướp.")
        return

    stolen = round(victim_points * 0.5)
    update_user(victim_id, {"$inc": {"points": -stolen}})
    update_user(robber_id, {
        "$inc": {"points": stolen},
        "$set": {"last_rob": now.strftime("%Y-%m-%d %H:%M:%S")}
    })
    await ctx.reply(f"Bạn đã cướp {format_currency(stolen)} {coin} từ {member.name}!")

@bot.command(name="hunt", help='`$hunt <weapon>`\n> đi săn kiếm tiền')
async def hunt(ctx, weapon: str):

    user_id = str(ctx.author.id)
    data = get_user(user_id)

    if not await check_permission(ctx, user_id):
        return

    weapons = {
        "g": { "emoji": ":gun: Súng săn", "ammo": 1, "range": (0, 50000) },
        "r": { "emoji": "<:RPG:1413753013473906748> RPG", "ammo": 10, "range": (-2000000, 5000000) },
        "a": { "emoji": "<:AWM:1413753446846431282> Awm", "ammo": 1, "range": (5000, 1000000) }
    }

    if weapon not in weapons:
        await ctx.reply("Vũ khí không hợp lệ!")
        return

    now = datetime.datetime.now()
    last_hunt = data.get("last_hunt")
    if last_hunt:
        elapsed = (now - datetime.datetime.strptime(last_hunt, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if elapsed < 300:
            remaining = int(300 - elapsed)
            m, s = divmod(remaining, 60)
            await ctx.reply(f"Chờ {m} phút {s} giây trước khi săn tiếp!")
            return

    weapon_info = weapons[weapon]
    items = data.get("items", {})
    weapon_count = items.get(weapon_info["emoji"], 0)
    bullet_count = items.get(":bullettrain_side: Viên đạn", 0)

    if weapon_count < 1:
        await ctx.reply(f"Bạn cần {weapon_info['emoji']} để đi săn!")
        return
    if bullet_count < weapon_info["ammo"]:
        await ctx.reply(f"Bạn cần {weapon_info['ammo']} viên đạn để đi săn!")
        return

    update = {
        "$inc": {
            "points": random.randint(*weapon_info["range"]),
            "items.:bullettrain_side: Viên đạn": -weapon_info["ammo"]
        },
        "$set": { "last_hunt": now.strftime("%Y-%m-%d %H:%M:%S") }
    }

    if weapon == "c":
        update["$inc"].pop("items.:bullettrain_side: Viên đạn", None)
        update["$unset"] = {f"items.{weapon_info['emoji']}": ""}

    update_user(user_id, update)
    reward = update["$inc"].get("points", 0)
    await ctx.reply(f"Bạn đã săn được {format_currency(reward)} {coin}!")

@bot.command(name="in", help='`$in <số điểm>`\n> bơm tiền vào công ty')
async def invest(ctx, amount: int):

    user_id = str(ctx.author.id)
    user = get_user(user_id)

    if not await check_permission(ctx, user_id):
        return

    if ':office: Công ty' not in user.get('items', {}):
        await ctx.reply(f"{ctx.author.mention} Bạn làm đéo gì có :office: Công ty mà đầu tư :rofl:")
        return

    if amount <= 0:
        await ctx.reply("Số điểm phải lớn hơn 0.")
        return

    if user['points'] < amount:
        await ctx.reply(f"Bạn không có đủ {coin} để đầu tư.")
        return

    # Cập nhật
    user['points'] -= amount
    user['company_balance'] = user.get('company_balance', 0) + amount
    update_user(user_id, user)

    await ctx.reply(f"Bạn đã đầu tư {format_currency(amount)} {coin} vào công ty.")

@bot.command(name="wi", help='`$wi <số điểm>`\n> rút tiền ra')
async def withdraw(ctx, amount: int):

    user_id = str(ctx.author.id)
    user = get_user(user_id)

    if not await check_permission(ctx, user_id):
        return

    if amount <= 0:
        await ctx.reply("Số điểm phải lớn hơn 0.")
        return

    if user.get('company_balance', 0) < amount:
        await ctx.reply(f"Công ty của bạn không có đủ {coin} để rút.")
        return

    # Cập nhật
    user['company_balance'] -= amount
    user['points'] += amount
    update_user(user_id, user)

    await ctx.reply(f"Bạn đã rút {format_currency(amount)} {coin} từ công ty.")

@bot.command(name="orob", help='`$orob <người chơi>`\n> rút tiền từ công ty thằng bạn')
async def orob(ctx, member: discord.Member):

    orobber_id = str(ctx.author.id)
    victim_id = str(member.id)
    status = member.status

    orobber = get_user(orobber_id)
    victim = get_user(victim_id)

    if orobber is None:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return

    if victim is None:
        await ctx.reply("Nạn nhân ko có trong dữ liệu của trò chơi.")
        return

    now = datetime.datetime.now()
    last_rob = orobber.get('last_rob')
    if last_rob:
        time_elapsed = (now - datetime.datetime.strptime(last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60
        if time_elapsed < cooldown_time:
            if orobber['items'].get(':fast_forward: Skip', 0) > 0:
                orobber['items'][':fast_forward: Skip'] -= 1
                await ctx.reply(f"Bạn đã sử dụng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
                hours, minutes = divmod(minutes, 60)
                await ctx.reply(f"Bạn phải chờ {hours} giờ {minutes} phút {seconds} giây trước khi cướp lại.")
                return

    if status == discord.Status.online:
        await ctx.reply('Nó đang on đếy, cẩn thận ko nó đấm')
        return
        
    if victim_id == "1243079760062709854":
        await ctx.reply('Định làm gì với công ty của Admin Bot đếy, mày cẩn thận')
        return

    if orobber['items'].get(':credit_card: thẻ công ty giả', 0) > 0:
        orobber['items'][':credit_card: thẻ công ty giả'] -= 1
        if random.random() < 0.25:
            await ctx.reply(f"Bạn đã sử dụng Thẻ giả để rút {coin} của {member.name} và đã thành công!")

            victim_balance = victim.get('company_balance', 0)
            if victim_balance <= 0:
                await ctx.reply(f"{member.name} không có {coin} để cướp!")
                return

            stolen_points = round(victim_balance * 0.5)

            victim['company_balance'] -= stolen_points
            orobber['points'] += stolen_points
            orobber['last_rob'] = now.strftime("%Y-%m-%d %H:%M:%S")

            update_user(orobber_id, orobber)
            update_user(victim_id, victim)

            await ctx.reply(f"Bạn đã rút được {format_currency(stolen_points)} {coin} từ {member.name}!")
        else:
            update_user(orobber_id, orobber)
            await ctx.reply(f"Bạn đã sử dụng Thẻ giả để rút {coin} của {member.name} nhưng không thành công.")
            return
    else:
        await ctx.reply("Bạn làm đéo gì có thẻ mà rút")

@bot.command(name="op", help='`$op <người chơi> [st<số>]`\n> săn smart, có thể dùng sáng tạo để tăng tỉ lệ')
async def op(ctx, member: discord.Member, creativity: str = None):

    oper_id = str(ctx.author.id)
    victim_id = str(member.id)

    oper = get_user(oper_id)
    victim = get_user(victim_id)

    if oper is None:
        return await ctx.reply("Bạn chưa có tài khoản, vui lòng dùng $start trước.")
    if victim is None:
        return await ctx.reply("Nạn nhân không có trong dữ liệu.")
    if oper_id == victim_id:
        return await ctx.reply("Bạn không thể tự OP chính mình 🤣")

    # Cooldown 5 phút
    now = datetime.datetime.now()
    last_op = oper.get("last_op")
    cooldown_time = 300  # 5 phút
    if last_op:
        elapsed = (now - datetime.datetime.strptime(last_op, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if elapsed < cooldown_time:
            remain = cooldown_time - elapsed
            m, s = divmod(remain, 60)
            return await ctx.reply(f"⏳ Đang bổ sung kiến thức trong {int(m)} phút {int(s)} giây")

    # --- Tính tỉ lệ thành công ---
    oper_smart = oper.get("smart", 0)
    victim_smart = victim.get("smart", 0)

    base_success = 0.5  # mặc định 50%
    stolen_ratio = 0.1  # mặc định ăn 10%

    if oper_smart >= victim_smart:
        success_rate = 0.7  # dễ thành công hơn (70%)
    else:
        success_rate = 0.3  # khó hơn (30%)
        stolen_ratio = 0.2  # ăn nhiều hơn

    # --- Nếu có dùng sáng tạo ---
    creativity_used = 0
    if creativity and creativity.startswith("st"):
        try:
            creativity_used = int(creativity[2:]) if len(creativity) > 2 else 1
        except ValueError:
            creativity_used = 1

        available = oper["items"].get(":bulb: sự sáng tạo", 0)
        if available < creativity_used:
            return await ctx.reply(f"Bạn không đủ sự sáng tạo (còn {available}).")

        # Trừ sáng tạo
        oper["items"][":bulb: sự sáng tạo"] -= creativity_used
        success_rate += 0.1 * creativity_used
        success_rate = min(success_rate, 0.95)  # cap 95%

    # --- Thử vận may ---
    if random.random() < success_rate:
        if victim_smart <= 0:
            msg = f"{member.name} không có học vấn để húp."
        else:
            stolen = round(victim_smart * stolen_ratio)
            victim["smart"] -= round(stolen * 0.5)
            oper["smart"] += stolen
            oper["points"] += stolen
            msg = (
                f"🎯 Thành công! Bạn đã húp {format_currency(stolen)} {coin} "
                f"và học vấn từ {member.name}! "
                f"{'(Dùng ' + str(creativity_used) + ' sáng tạo)' if creativity_used else ''}"
            )
    else:
        msg = (
            f"💨 Bạn đã cố ao trình {member.name} nhưng thất bại. "
            f"{'(Dù đã dùng ' + str(creativity_used) + ' sáng tạo)' if creativity_used else ''}"
        )

    # Lưu cooldown
    oper["last_op"] = now.strftime("%Y-%m-%d %H:%M:%S")

    update_user(oper_id, oper)
    update_user(victim_id, victim)

    await ctx.reply(msg)

@bot.command(name="lb", help='`$lb`\n> xem bảng xếp hạng')
async def lb(ctx, kind: str = "a"):

    kind_map = {
        "a": ("points", "🏦 Tài khoản"),
        "o": ("company_balance", "🏢 Công ty"),
        "s": ("smart", "📚 Học vấn"),
    }

    field, label = kind_map.get(kind, (None, None))
    if not field:
        await ctx.reply(
            "Loại bảng xếp hạng không hợp lệ. Vui lòng sử dụng:\n"
            "`$lb a` - Tài khoản\n"
            "`$lb o` - Công ty\n"
            "`$lb s` - Học vấn."
        )
        return

    top_users = users_col.find().sort(field, -1).limit(10)
    leaderboard = ""
    for idx, user in enumerate(top_users, start=1):
        try:
            member = await bot.fetch_user(int(user['_id']))
            name = member.name
        except:
            name = f"Người chơi {user['_id']}"

        score = user.get(field, 0)
        leaderboard += f"**{idx}.** {name}: `{format_currency(score)}`\n"

    embed = discord.Embed(
        title=f"Bảng xếp hạng {label}",
        description=leaderboard or "Không có dữ liệu.",
        color=discord.Color.gold()
    )
    await ctx.reply(embed=embed)

@bot.command(name='gacha', help='`$gacha`\n> gacha ra những thứ hay ho')
async def gacha(ctx):

    user_id = str(ctx.author.id)
    user_roles = [role.name for role in ctx.author.roles]
    user = users_col.find_one({"_id": user_id})

    if not user:
        await ctx.reply("Bạn chưa có tài khoản. Dùng `$start` để bắt đầu.")
        return

    # Kiểm tra cooldown
    now = datetime.datetime.now()
    last_gacha = user.get('last_gacha')
    if last_gacha:
        time_elapsed = (now - datetime.datetime.strptime(last_gacha, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_elapsed < 3600:
            minutes, seconds = divmod(int(3600 - time_elapsed), 60)
            await ctx.reply(f"Bạn phải chờ {minutes} phút {seconds} giây trước khi quay gacha lại.")
            return

    if "Trung học Phổ thông" in user_roles:
        if user.get('points', 0) < 10_000_000_000:
            await ctx.reply(f'Bạn không đủ {coin} để gacha!')
            return

        # Trừ tiền và thông minh
        users_col.update_one(
            {"_id": user_id},
            {
                "$inc": {
                    "points": -10_000_000_000,
                    "smart": -1_000_000
                },
                "$set": {
                    "last_gacha": now.strftime("%Y-%m-%d %H:%M:%S")
                }
            }
        )

        result = roll_gacha_from_pool()
        item_name = result.get("name", "Không rõ")
        rarity = result.get("rarity", "không xác định")

        # Cập nhật vật phẩm
        users_col.update_one(
            {"_id": user_id},
            {"$inc": {f"items.{item_name}": 1}}
        )

        rarity_colors = {
            "tốt": discord.Color.green(),
            "hiếm": discord.Color.blue(),
            "sử thi": discord.Color.purple(),
            "huyền thoại": discord.Color.orange()
        }

        embed = discord.Embed(
            title="🎲 Gacha Roll 🎲",
            description=f"Bạn đã quay được: **{item_name}**\n🔹 Độ hiếm: `{rarity.upper()}`",
            color=rarity_colors.get(rarity, discord.Color.gold())
        )
        await ctx.reply(embed=embed)

@bot.command(name='study', help='`$study`\n> Học tăng trình độ')
async def study(ctx):
    
    user_id = str(ctx.author.id)
    data = get_user(user_id)

    if not data:
        await ctx.reply("Bạn chưa có tài khoản, dùng `$start` để bắt đầu.")
        return

    # Check sách vở
    books = data.get("items", {}).get(":books: Sách vở", 0)
    if books <= 0:
        await ctx.send("📚 Bạn cần có ít nhất 1 quyển **sách vở** để học!")
        return

    # Cooldown 5 phút
    now = datetime.datetime.now()
    last_study_str = data.get("last_study")
    cooldown_time = 300  # 5 phút
    if last_study_str:
        try:
            last_study = datetime.datetime.strptime(last_study_str, "%Y-%m-%d %H:%M:%S")
            elapsed = (now - last_study).total_seconds()
            if elapsed < cooldown_time:
                remain = cooldown_time - elapsed
                m, s = divmod(remain, 60)
                await ctx.reply(f"⏳ Thời gian nghỉ giải lao còn {int(m)} phút {int(s)} giây")
                return
        except Exception:
            pass  # Nếu parse lỗi thì coi như chưa học lần nào

    # Tăng học vấn
    gain = 10 * books
    data["smart"] = data.get("smart", 0) + gain

    # 10% cơ hội nhận "sự sáng tạo"
    bonus_msg = ""
    if random.random() < 0.1:
        creativity = data["items"].get(":bulb: sự sáng tạo", 0)
        data["items"][":bulb: sự sáng tạo"] = creativity + 1
        bonus_msg = "✨ Bạn đã nảy ra **một ý tưởng sáng tạo**!"

    # Lưu lại thời gian học
    data["last_study"] = now.strftime("%Y-%m-%d %H:%M:%S")

    update_user(user_id, data)

    await ctx.send(f"📖 Bạn học hành chăm chỉ và nhận được **+{gain} học vấn**! {bonus_msg}")

# === Text fight ===
@bot.command(name="stats", help="Hiển thị chỉ số chiến đấu của bạn hoặc người khác.")
async def stats(ctx, member: discord.Member = None):
    """Hiển thị chỉ số Text Fight của bản thân hoặc người khác."""
    member = member or ctx.author
    user_id = str(member.id)

    # --- Lấy dữ liệu từ MongoDB ---
    tf = get_full_stats(user_id)

    # --- Lấy chỉ số cơ bản ---
    hp = f"{int(tf.get('hp', 0))}/{int(tf.get('max_hp', 0))}"
    mana = f"{int(tf.get('mana', 0))}/{int(tf.get('max_mana', 0))}"
    basic_damage = tf.get('basic_damage', 0)
    ad = tf.get('ad', 0)
    ap = tf.get('ap', 0)
    armor = tf.get('armor', 0)
    magic_resist = tf.get('magic_resist', 0)
    attack_speed = round(tf.get('attack_speed', 0), 2)
    crit_rate = round(tf.get('crit_rate', 0) * 100, 1)
    crit_damage = round(tf.get('crit_damage', 0) * 100, 1)
    lifesteal = round(tf.get('lifesteal', 0) * 100, 1)
    amplify = round(tf.get('amplify', 0) * 100, 1)
    resistance = round(tf.get('resistance', 0) * 100, 1)
    equips = tf.get("equips", [None, None, None])

    # --- Kiểm tra trạng thái sống/chết ---
    status_icon = "💀" if tf.get("hp", 0) <= 0 else "❤️"

    # --- Embed hiển thị ---
    embed = discord.Embed(
        title=f"{status_icon} Chỉ số chiến đấu của {member.display_name}",
        color=discord.Color.red()
    )

    # --- Hàng 1: HP & Mana ---
    embed.add_field(name="HP", value=f"{hp} <:Health:1426153576249430079>", inline=True)
    embed.add_field(name="Mana", value=f"{mana} <:Mana:1426153608361279558>", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # --- Hàng 2: Sức tấn công cơ bản + AD + AP ---
    embed.add_field(name="<:BasicDamage:1428307672574459914> ST Cơ bản", value=f"{basic_damage}", inline=True)
    embed.add_field(name="<:AD:1426154602335698974> Vật lý", value=f"{ad}", inline=True)
    embed.add_field(name="<:AP:1426153499766427679> Phép", value=f"{ap}", inline=True)

    # --- Hàng 3: Phòng thủ ---
    embed.add_field(name="<:Armor:1426153517609127966> Giáp", value=f"{armor}", inline=True)
    embed.add_field(name="<:MagicResist:1426153593148411934> Kháng phép", value=f"{magic_resist}", inline=True)
    embed.add_field(name="<:AS:1426153532620279951> Tốc đánh", value=f"{attack_speed}", inline=True)

    # --- Hàng 4: Crit, Lifesteal ---
    embed.add_field(name="<:CritChance:1426153545131884617> Tỷ lệ chí mạng", value=f"{crit_rate}%", inline=True)
    embed.add_field(name="<:CritDamage:1426153557798944849> Sát thương chí mạng", value=f"{crit_damage}%", inline=True)
    embed.add_field(name="<:scaleSV:1426154642676646039> Hút máu", value=f"{lifesteal}%", inline=True)

    # --- Hàng 5: Khuếch đại, Chống chịu ---
    embed.add_field(name="<:scaleDA:1426153627281526886> Khuếch đại", value=f"{amplify}%", inline=True)
    embed.add_field(name="<:scaleDR:1426153642527817799> Chống chịu", value=f"{resistance}%", inline=True)
    embed.add_field(name="<:scalemanaregen:1426483869120594070> Hồi mana", value="0%", inline=True)

    # --- Hiển thị 3 ô trang bị ---
    equip_display = ""
    for i in range(3):
        item = equips[i]
        equip_display += f"**Slot {i+1}:** {_item_display(item) if item else ':black_large_square:'}\n"
    embed.add_field(name="🎒 Trang bị", value=equip_display.strip(), inline=False)

    await ctx.send(embed=embed)

@bot.command(name="attack", help="Tấn công người chơi khác (Text Fight).")
async def attack(ctx, target: discord.Member):
    """Thực hiện một đòn đánh thường giữa hai người chơi."""
    attacker = ctx.author
    if target.id == attacker.id:
        await ctx.send("❌ Bạn không thể tự tấn công chính mình!")
        return

    attacker_id = str(attacker.id)
    target_id = str(target.id)

    # --- Lấy dữ liệu người chơi ---
    try:
        attacker_data = get_full_stats(attacker_id)
        target_data = get_full_stats(target_id)
    except Exception as e:
        await ctx.send(f"❌ Không thể lấy dữ liệu người chơi: {e}")
        return

    # --- Lấy các chỉ số cần thiết ---
    basic_damage = attacker_data.get("basic_damage", 0)
    attack_speed = attacker_data.get("attack_speed", 1)
    crit_rate = attacker_data.get("crit_rate", 0)
    crit_damage = attacker_data.get("crit_damage", 2)
    lifesteal = attacker_data.get("lifesteal", 0)

    armor = target_data.get("armor", 0)
    resistance = target_data.get("resistance", 0)

    attacker_hp = attacker_data.get("hp", 0)
    attacker_max_hp = attacker_data.get("max_hp", 0)
    target_hp = target_data.get("hp", 0)
    target_max_hp = target_data.get("max_hp", 0)

    # --- Tính sát thương ---
    damage = basic_damage * attack_speed
    is_crit = False
    if random.random() < crit_rate:
        damage *= crit_damage
        is_crit = True

    # --- Giảm sát thương bởi giáp (armor) ---
    damage *= (100 / (100 + armor))
    damage = round(damage)

    # --- Áp dụng sát thương ---
    new_target_hp = max(target_hp - damage, 0)

    # --- Hút máu (lifesteal) ---
    heal = round(damage * lifesteal)
    new_attacker_hp = min(attacker_hp + heal, attacker_max_hp)

    # --- Cập nhật MongoDB ---
    update_user_stats(attacker_id, {"hp": new_attacker_hp})
    update_user_stats(target_id, {"hp": new_target_hp})

    # --- Tạo tin nhắn kết quả ---
    msg = (
        f"⚔️ **{attacker.display_name}** tấn công **{target.display_name}**!\n"
        f"🗡️ Gây **{damage}** sát thương"
    )
    if is_crit:
        msg += " 💥 (Chí mạng!)"

    # --- Kiểm tra tử vong ---
    if new_target_hp <= 0:
        msg += f"\n💀 **{target.display_name}** đã bị hạ gục!"

    await ctx.reply(msg)

@bot.command(name="equip", help="Trang bị vật phẩm bằng key trong shop_data.json (VD: $equip 11)")
async def equip(ctx, item_key: str = None):
    """Trang bị vật phẩm (text fight gear)."""
    user_id = str(ctx.author.id)

    # --- Kiểm tra input ---
    if not item_key:
        await ctx.send("⚠️ Vui lòng nhập **key** của vật phẩm (VD: `$equip 11`).")
        return

    item = shop_data.get(item_key)
    if not item:
        await ctx.send(f"❌ Không tìm thấy vật phẩm có key `{item_key}` trong shop_data.json.")
        return

    if not item.get("gear", False):
        await ctx.send(f"❌ `{_item_display(item_key)}` không phải là vật phẩm có thể trang bị.")
        return

    # --- Lấy dữ liệu người chơi ---
    user = users_col.find_one({"_id": user_id}, {"items": 1, "fight_equips": 1}) or {}
    items = user.get("items", {})
    equips = _get_equips(user_id)

    item_name = item["name"]

    # --- Kiểm tra người chơi có item ---
    if items.get(item_name, 0) <= 0:
        await ctx.send(f"Bạn không có `{item_name}` trong túi để trang bị!")
        return

    # --- Kiểm tra slot trống ---
    try:
        empty_slot = equips.index(None)
    except ValueError:
        empty_slot = -1

    if empty_slot == -1:
        await ctx.send("❌ Bạn đã đầy 3 ô trang bị! Hãy tháo một món trước khi trang bị mới.")
        return

    # --- Trang bị vật phẩm ---
    equips[empty_slot] = item_key
    _set_equips(user_id, equips)

    # --- Giảm số lượng trong túi ---
    items[item_name] -= 1
    if items[item_name] <= 0:
        del items[item_name]

    users_col.update_one(
        {"_id": user_id},
        {"$set": {"items": items}},
        upsert=False
    )

    await ctx.send(
        f"✅ Bạn đã trang bị **{_item_display(item_key)}** vào ô **#{empty_slot + 1}**!\n"
        f"Chỉ số của bạn sẽ được cập nhật tự động."
    )

@bot.command(name="unequip", help="Tháo vật phẩm khỏi ô trang bị (1-3).")
async def unequip(ctx, slot: int = None):
    """Tháo trang bị từ ô chỉ định."""
    user_id = str(ctx.author.id)

    if slot is None or not (1 <= slot <= 3):
        await ctx.send("⚠️ Vui lòng nhập số ô hợp lệ (1-3).")
        return

    equips = _get_equips(user_id)
    item_key = equips[slot - 1]

    if not item_key:
        await ctx.send(f"⚠️ Ô {slot} hiện đang trống, không có gì để tháo.")
        return

    item = shop_data.get(item_key)
    if not item:
        await ctx.send("⚠️ Vật phẩm này không còn tồn tại trong shop_data.json!")
        return

    # --- Xóa trang bị khỏi slot ---
    equips[slot - 1] = None
    _set_equips(user_id, equips)

    # --- Trả lại vật phẩm vào túi ---
    user = users_col.find_one({"_id": user_id}, {"items": 1}) or {}
    items = user.get("items", {})
    item_name = item["name"]
    items[item_name] = items.get(item_name, 0) + 1

    users_col.update_one(
        {"_id": user_id},
        {"$set": {"items": items}},
        upsert=False
    )

    await ctx.send(
        f"🧰 Bạn đã tháo **{_item_display(item_key)}** khỏi ô **#{slot}** và trả lại vào túi.\n"
        f"Chỉ số của bạn sẽ được tự động cập nhật."
    )

@bot.command(name="clear")
async def clear_messages(ctx, amount: int):
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.reply("Bạn không có quyền xóa tin nhắn!")
        return

    await ctx.channel.purge(limit=amount)

# ==== RUN ====
keep_alive()
bot.run(DISCORD_TOKEN)
