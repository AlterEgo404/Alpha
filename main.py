import os
import io
import json
import math
import random
import datetime
import asyncio
import traceback

import discord
from discord.ext import commands
from discord.ui import View, Button

import aiohttp
from PIL import Image, ImageDraw, ImageFont

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
    get_user, update_user, create_user, save_user_full,
    get_jackpot, update_jackpot as dh_update_jackpot, set_jackpot,
    users_col
)

# ---- Discord ----
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents, help_command=None)

# ---- Constants ----
ALLOWED_CHANNEL_ID = 1347480186198949920
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

try:
    with open("backgrounds.json", "r", encoding="utf-8") as f:
        user_backgrounds = json.load(f)
except FileNotFoundError:
    user_backgrounds = {}

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

# ---- Permissions & user checks ----
async def check_permission(ctx):
    if ctx.author.id != 1196335145964285984 and ctx.channel.id != ALLOWED_CHANNEL_ID:
        await ctx.reply(f"Lệnh này chỉ có thể được sử dụng trong <# {ALLOWED_CHANNEL_ID} >")
        return False
    return True

async def check_user_data(ctx, user_id):
    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return False
    return True

# ---- HTTP session (reused) ----
http_session: aiohttp.ClientSession | None = None

async def fetch_image(url: str) -> Image.Image | None:
    """Tải ảnh và trả về Image RGBA. Trả None nếu lỗi."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        assert http_session is not None
        async with http_session.get(url) as resp:
            if resp.status != 200:
                print(f"Lỗi tải ảnh: {resp.status} - {url}")
                return None
            data = await resp.read()
        img = Image.open(io.BytesIO(data))
        return img.convert("RGBA")
    except Exception as e:
        print(f"Lỗi khi tải ảnh: {e}")
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
                modifier = random.choice([-0.01, 0.02])
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

# ==== EVENTS ====
@bot.event
async def on_ready():
    global http_session
    print(f'Bot đã đăng nhập với tên {bot.user}')
    http_session = aiohttp.ClientSession()

    bot.loop.create_task(update_company_balances())
    bot.loop.create_task(clean_zero_items())

    # Khởi tạo jackpot nếu chưa có
    if get_jackpot() is None:
        set_jackpot(1_000_000_000)
        print("Đã khởi tạo jackpot mặc định.")

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
    if not await check_permission(ctx): return
    embed = discord.Embed(title="📊 Thông tin Bot", color=discord.Color.red())
    embed.add_field(name="👩‍💻 Nhà phát triển", value="```ansi\n[2;31mAlpha[0m```", inline=True)
    embed.add_field(name="Phiên bản Bot", value="```ansi\n[2;34m2.0.0[0m```")
    embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/1322746396142604378/1322746745440043143/2.png")
    await ctx.reply(embed=embed)

@bot.command(name="jar", help='`$jar`\n> xem hũ jackpot')
async def jp(ctx):
    if not await check_permission(ctx): return
    jackpot_amount = format_currency(get_jackpot() or 0)
    await ctx.reply(f"💰 **Jackpot hiện tại:** {jackpot_amount} {coin}")

@bot.command(name="mk", help='`$mk`\n> xem cửa hàng')
async def shop(ctx):
    if not await check_permission(ctx): return
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
    if not await check_permission(ctx): return
    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id): return
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
    if not await check_permission(ctx): return
    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id): return
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
    if ctx.author.id != 1196335145964285984:
        await ctx.reply("Chỉ người dùng được phép mới có thể sử dụng lệnh này.")
        return
    if not background_url.startswith(("http://", "https://")):
        await ctx.reply("URL không hợp lệ. Vui lòng cung cấp URL hợp lệ.")
        return

    user_id = str(member.id)
    user_backgrounds[user_id] = background_url
    with open("backgrounds.json", "w", encoding="utf-8") as f:
        json.dump(user_backgrounds, f, ensure_ascii=False, indent=4)
    await ctx.reply(f"Đã thay đổi nền của {member.display_name} thành: {background_url}")

@bot.command(name="cccd", help='`$cccd`\n> mở căn cước công dân')
async def cccd(ctx, member: discord.Member = None, size: int = 128):
    if not await check_permission(ctx): return
    member = member or ctx.author
    user_id = str(member.id)

    if not await check_user_data(ctx, user_id): return

    background_url = user_backgrounds.get(
        user_id,
        "https://hinhanhonline.com/Hinhanh/images07/AnhAL/hinh-nen-may-tinh-dep-doc-dao-nhat-19.jpg"
    )

    data = get_user(user_id)
    smart = int(data.get("smart", 0))
    user_name = member.name
    avatar_url = member.display_avatar.with_size(size).url

    level, progress_percentage, next_level_needed_smart = calculate_level_and_progress(smart)

    # Cập nhật vai trò theo tu_vi
    async def update_roles(ctx, member, level):
        for role_info in tu_vi.values():
            role = ctx.guild.get_role(role_info.get("id"))
            if role and role in member.roles:
                await member.remove_roles(role)

        role_name = "None"
        role_id = None
        for name, info in sorted(tu_vi.items(), key=lambda x: x[1]["level_min"], reverse=True):
            if level >= info["level_min"]:
                role_name = name
                role_id = info["id"]
                break

        if role_id:
            role = ctx.guild.get_role(role_id)
            if role and role not in member.roles:
                await member.add_roles(role)
        return role_name

    role_name = await update_roles(ctx, member, level)

    # tải ảnh
    avatar_image = await fetch_image(avatar_url)
    if avatar_image is None:
        await ctx.reply("Lỗi tải ảnh avatar. Vui lòng thử lại sau.")
        return
    avatar_image = avatar_image.resize((120, 120))

    galaxy_background = await fetch_image(background_url)
    if galaxy_background is None:
        await ctx.reply("Lỗi tải ảnh nền. Vui lòng thử lại sau.")
        return
    galaxy_background = galaxy_background.resize((400, 225))

    try:
        server_image = Image.open("1.png").convert("RGBA")
    except Exception:
        await ctx.reply("Lỗi tải ảnh server (1.png).")
        return
    server_image = server_image.resize((80, 80))

    # ghép
    canvas = galaxy_background.copy()
    canvas.paste(server_image, (10, 10), mask=server_image)
    canvas.paste(avatar_image, (20, 85), mask=avatar_image)

    # font
    font_path = "Roboto-Black.ttf"
    try:
        font_small = ImageFont.truetype(font_path, 12)
        font_large = ImageFont.truetype(font_path, 13)
    except IOError:
        font_large = font_small = ImageFont.load_default()

    draw = ImageDraw.Draw(canvas)
    draw_text_with_outline(
        draw,
        f"Tên: {user_name}\nID: {user_id}\nHọc vấn: {format_currency(smart)}\nlv: {format_currency(level)}\nTrình độ: {role_name}",
        (160, 95),
        font_large
    )
    draw_text_with_outline(
        draw,
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA MEME\n          Độc lập - Tự do - Hạnh phúc\n\n                 CĂN CƯỚC CƯ DÂN",
        (100, 20),
        font_large
    )

    # progress bar
    filled_length = int(progress_percentage * 2)  # 0..200
    bar_position = (160, 185, 360, 205)
    draw.rectangle(bar_position, outline="black", width=3)
    draw.rectangle((163, 188, 163 + max(0, filled_length - 6), 202), fill="#1E90FF")
    draw_text_with_outline(draw, f"{smart}/{next_level_needed_smart}", (165, 188), font_small)

    with io.BytesIO() as bio:
        canvas.save(bio, "PNG")
        bio.seek(0)
        await ctx.reply(file=discord.File(fp=bio, filename="cccd.png"))

@bot.command(name="bag", help='`$bag`\n> mở túi')
async def bag(ctx, member: discord.Member = None):
    if not await check_permission(ctx):
        return

    member = member or ctx.author
    user_id = str(member.id)

    if not await check_user_data(ctx, user_id):
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

@bot.command(name="ou", help='`$ou <điểm> <t/x>`\n> chơi tài xỉu')
async def ou(ctx, bet: str, choice: str):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    data = get_user(user_id)
    if not data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return

    if bet.lower() == 'all':
        bet = data.get('points', 0)
    else:
        try:
            bet = int(bet)
        except ValueError:
            await ctx.reply(f"Số {coin} cược không hợp lệ.")
            return

    if bet <= 0 or bet > data.get('points', 0):
        await ctx.reply("Bạn làm đéo gì có tiền mà cược :rofl:")
        return

    choice = choice.lower()
    if choice not in ["t", "x"]:
        await ctx.reply("Bạn phải chọn 't' (Tài) hoặc 'x' (Xỉu).")
        return

    if user_id == "1361702060071850024":
        dice1, dice2, dice3 = random.randint(1, 3), random.randint(1, 3), random.randint(1, 3)
    else:
        dice1, dice2, dice3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    total = dice1 + dice2 + dice3

    # Tính kết quả
    win = (3 <= total <= 10 and choice == "x") or (11 <= total <= 18 and choice == "t")
    if win:
        data['points'] += bet
    else:
        data['points'] -= bet
        dh_update_jackpot(bet)  # Cập nhật jackpot nếu thua

    update_user(user_id, data)

    # Hiển thị xúc xắc
    dice1_emoji = dice_emojis[dice1]
    dice2_emoji = dice_emojis[dice2]
    dice3_emoji = dice_emojis[dice3]
    dice_roll = dice_emojis[0]

    if choice == 'x':
        rolling_message = await ctx.reply(f"`   ` {dice_roll} `   `\n`  `{dice_roll} {dice_roll}`$$`")
    else:
        rolling_message = await ctx.reply(f"`   ` {dice_roll} `   `\n`$$`{dice_roll} {dice_roll}`  `")
    await asyncio.sleep(1)

    if 3 <= total <= 10:
        if choice == "x":
            await rolling_message.edit(content=f"`   ` {dice1_emoji} `Xỉu`\n`  `{dice2_emoji} {dice3_emoji}`$$`")
        else:
            await rolling_message.edit(content=f"`   ` {dice1_emoji} `Xỉu`\n`$$`{dice2_emoji} {dice3_emoji}`  `\nHehe, {ctx.author.mention} ngu thì chết chứ sao :rofl:")
    else:
        if choice == "x":
            await rolling_message.edit(content=f"`Tài` {dice1_emoji} `   `\n`  `{dice2_emoji} {dice3_emoji}`$$`\nHehe, {ctx.author.mention} ngu thì chết chứ sao :rofl:")
        else:
            await rolling_message.edit(content=f"`Tài` {dice1_emoji} `   `\n`$$`{dice2_emoji} {dice3_emoji}`  `")

@bot.command(name="daily", help='`$daily`\n> nhận quà hằng ngày')
async def daily(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    data = get_user(user_id)
    if not data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
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

@bot.command(name="prog", help='`$prog`\n> ăn xin')
async def prog(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    data = get_user(user_id)

    if not data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
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
    if not await check_permission(ctx):
        return

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
                f"Lệnh mua bán:\n> `$mk`, `$ttsp`, `$buy`, `$sell`\n"
                f"Lệnh kiếm tiền:\n> `$daily`, `$prog`, `$hunt`\n"
                f"Lệnh tệ nạn:\n> `$ou`, `$thief`, `$othief`, `$slots`\n"
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

@bot.command(name="thief", help='`$thief <người chơi> [công cụ]`\n> trộm 50% điểm của người khác')
async def rob(ctx, member: discord.Member, tool: str = None):
    if not await check_permission(ctx):
        return

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
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    data = get_user(user_id)
    if not data:
        await ctx.reply("Bạn chưa có tài khoản. Dùng `$start` để tạo.")
        return

    weapons = {
        "g": { "emoji": ":gun: Súng săn", "ammo": 1, "range": (0, 50000) },
        "r": { "emoji": "<:RPG:1325750069189677087> RPG", "ammo": 10, "range": (-2000000, 5000000) },
        "a": { "emoji": "<:Awm:1325747265045794857> Awm", "ammo": 1, "range": (5000, 1000000) },
        "c": { "emoji": "<:cleaner:1347560866291257385> máy hút bụi", "ammo": 0, "range": (3000000, 10000000) }
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
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    user = get_user(user_id)

    if user is None:
        await ctx.reply("Người chơi không tồn tại.")
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
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    user = get_user(user_id)

    if user is None:
        await ctx.reply("Người chơi không tồn tại.")
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

@bot.command(name="othief", help='`$othief <người chơi>`\n> rút tiền từ công ty thằng bạn')
async def orob(ctx, member: discord.Member):
    if not await check_permission(ctx):
        return

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

@bot.command(name="op", help='`$op <người chơi>`\n> săn smart')
async def op(ctx, member: discord.Member):
    if not await check_permission(ctx):
        return

    killer_id = str(ctx.author.id)
    victim_id = str(member.id)
    success = 0.5

    killer = get_user(killer_id)
    victim = get_user(victim_id)

    if killer is None:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng $start để tạo tài khoản.")
        return

    if victim is None:
        await ctx.reply("Nạn nhân ko có trong dữ liệu của trò chơi.")
        return

    now = datetime.datetime.now()
    last_rob = killer.get('last_rob')
    cooldown_time = 60 * 60
    if last_rob:
        time_elapsed = (now - datetime.datetime.strptime(last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_elapsed < cooldown_time:
            if killer['items'].get(':fast_forward: Skip', 0) > 0:
                killer['items'][':fast_forward: Skip'] -= 1
                await ctx.reply("Bạn đã sử dụng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                remaining_time = cooldown_time - time_elapsed
                hours, remainder = divmod(remaining_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                await ctx.reply(f"Bạn phải chờ {int(hours)} giờ {int(minutes)} phút {int(seconds)} giây trước khi săn lại.")
                return

    if killer['items'].get(':bulb: Thông minh', 0) <= 0:
        await ctx.reply("Bạn làm đéo gì có sự thông minh :rofl:")
        return

    if victim_id == killer_id:
        await ctx.reply('mày tính tự solo à con, méo có đâu nhé :>')
        return

    if killer['items'].get('<:big_nao:1308790909353328640> siêu thông minh `Legendary`', 0) > 0:
        success += 0.5

    if random.random() < success:
        killer['items'][':bulb: Thông minh'] -= 1
        await ctx.reply(f"Bạn đã sử dụng sự thông minh để ao trình {member.name} và đã thành công!")

        victim_smart = victim.get('smart', 0)
        if victim_smart <= 0:
            await ctx.reply(f"{member.name} không có học vấn để húp!")
            return

        stolen_points = round(victim_smart * 0.1)
        victim['smart'] -= round(stolen_points * 0.5)
        killer['smart'] += stolen_points
        killer['points'] += stolen_points
        killer['last_rob'] = now.strftime("%Y-%m-%d %H:%M:%S")

        update_user(killer_id, killer)
        update_user(victim_id, victim)

        await ctx.reply(f"Bạn đã húp được {format_currency(stolen_points)} {coin}, học vấn từ {member.name}!")
    else:
        killer['items'][':bulb: Thông minh'] -= 1
        update_user(killer_id, killer)
        await ctx.reply(f"Bạn đã sử dụng sự thông minh để ao trình {member.name} nhưng không thành công.")

@bot.command(name="ping", help='`$ping`\n> xem độ trễ của bot')
async def ping(ctx):
    latency = bot.latency
    await ctx.reply(f'Ping : {latency * 1000:.2f}ms.')

@bot.command(name="lb", help='`$lb`\n> xem bảng xếp hạng')
async def lb(ctx, kind: str = "a"):
    if not await check_permission(ctx):
        return

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
    if not await check_permission(ctx):
        return

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
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    now = datetime.datetime.now()

    user = users_col.find_one({"_id": user_id})
    if not user:
        await ctx.reply("Bạn chưa có tài khoản. Dùng `$start` để bắt đầu.")
        return

    last_study = user.get('last_study')
    cooldown_time = 5 * 60  # 5 phút

    if last_study:
        time_elapsed = (now - datetime.datetime.strptime(last_study, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn cần chờ {minutes} phút {seconds} giây trước khi có thể học tiếp!")
            return

    # Tăng smart và cập nhật last_study
    users_col.update_one(
        {"_id": user_id},
        {
            "$inc": {"smart": 10},
            "$set": {"last_study": now.strftime("%Y-%m-%d %H:%M:%S")}
        }
    )

    await ctx.reply("Bạn vừa học xong ra chơi thôi!")

@bot.command(name="clear")
async def clear_messages(ctx, amount: int):
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.reply("Bạn không có quyền xóa tin nhắn!")
        return

    await ctx.channel.purge(limit=amount)

# ==== RUN ====
keep_alive()
bot.run(DISCORD_TOKEN)
