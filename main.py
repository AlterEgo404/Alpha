import discord
from discord.ext import commands
from discord.ui import View, Button
import json
import os
import random
import datetime
import asyncio
from PIL import Image, ImageDraw, ImageFont
import io
import math
import aiohttp

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='$', intents=intents, help_command=None)

def draw_text_with_outline(draw, text, position, font, outline_color="black", fill_color="white"):
    x, y = position
    offsets = [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2)]
    for ox, oy in offsets:
        draw.text((x + ox, y + oy), text, font=font, fill=outline_color)
    draw.text((x, y), text, font=font, fill=fill_color)

dice_emojis = {
    0: "<a:dice_roll:1362951541132099584>",
    1: "<:dice_1:1362951590302056849>",
    2: "<:dice_2:1362951604600307792>",
    3: "<:dice_3:1362951621717266463>",
    4: "<:dice_4:1362951636573487227>",
    5: "<:dice_5:1362951651853336727>",
    6: "<:dice_6:1362951664729854152>"
}

coin = "<:meme_coin:1362951683814199487>"

def load_json(file_name, default_data=None):
    """Load dữ liệu từ file JSON. Nếu file không tồn tại, tạo mới với dữ liệu mặc định."""
    if not os.path.exists(file_name):
        default_data = default_data or {}
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)

    with open(file_name, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(file_name, data):
    """Lưu dữ liệu vào file JSON."""
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Load dữ liệu
from data_handler import (
    get_user, update_user, create_user, save_user_full,get_jackpot, update_jackpot, set_jackpot,create_leaderboard
    )
shop_data = load_json('shop_data.json')
save_shop_data = lambda data: save_json('shop_data.json', data)
tu_vi = load_json('tu_vi.json')
save_tu_vi = lambda data: save_json('tu_vi.json', data)
gacha_data = load_json('gacha_data.json')
save_gacha_data = lambda data: save_json('gacha_data.json', data)

try:
    with open("backgrounds.json", "r") as f:
        user_backgrounds = json.load(f)
except FileNotFoundError:
    user_backgrounds = {}

async def update_company_balances():
    while True:
        all_users = get_user("*")
        for user_id, data in all_users.items():
            if isinstance(data, dict) and data.get("company_balance", 0) > 0:
                balance = data["company_balance"]
                modifier = random.choice([-0.01, 0.02])
                new_balance = balance + balance * modifier
                data["company_balance"] = max(0, int(new_balance))
                update_user(user_id, {"company_balance": data["company_balance"]})

        await asyncio.sleep(60)

async def clean_zero_items():
    while True:
        all_users = get_user("*")
        for user_id, data in all_users.items():
            if isinstance(data, dict) and "items" in data:
                new_items = {item: count for item, count in data["items"].items() if count > 0}
                if new_items != data["items"]:
                    update_user(user_id, {"items": new_items})
        await asyncio.sleep(10)

async def check_permission(ctx):
    if ctx.author.id != 1196335145964285984 and ctx.channel.id != ALLOWED_CHANNEL_ID:
        await ctx.reply(f"Lệnh này chỉ có thể được sử dụng trong <#1347480186198949920>")
        return False
    return True

async def check_user_data(ctx, user_id):
    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return False
    return True

async def fetch_image(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    print(f"Lỗi tải ảnh: {resp.status} - {url}")
                    return None
                image_bytes = await resp.read()

        # Kiểm tra dữ liệu có phải ảnh hợp lệ không
        image = Image.open(io.BytesIO(image_bytes))
        return image.convert("RGBA")  # Chuyển thành RGBA để tránh lỗi khi dán ảnh

    except Exception as e:
        print(f"Lỗi khi tải ảnh: {e}")
        return None
    
async def update_roles(ctx, member, level):
    """Cập nhật vai trò cho người dùng dựa trên cấp độ."""
    for role_info in tu_vi.values():
        role = ctx.guild.get_role(role_info["id"])
        if role and role in member.roles:
            await member.remove_roles(role)

    role_name = None
    for name, info in sorted(tu_vi.items(), key=lambda x: x[1]["level_min"], reverse=True):
        if level >= info["level_min"]:
            role_name = name
            role_id = info["id"]
            break

    if role_name:
        role = ctx.guild.get_role(role_id)
        if role and role not in member.roles:
            await member.add_roles(role)
    else:
        role_name = "None"

    return role_name

def count_items(items):
    """Đếm số lượng từng loại item."""
    item_counts = {}
    for item_name in items:
        item_counts[item_name] = item_counts.get(item_name, 0) + 1
    return item_counts

def format_item_display(item_counts):
    """Định dạng hiển thị danh sách đồ."""
    item_display = []
    for item_name, count in item_counts.items():
        icon = shop_data.get(item_name, {}).get('icon', '')
        item_display.append(f"`{count}` {icon} {item_name}" if icon else f"`{count}` {item_name}")
    return "\n".join(item_display) if item_display else "Trống"

def update_jackpot(loss_amount):
    current = get_jackpot()
    update_jackpot(loss_amount)

def create_leaderboard(key="points"):
    """Tạo bảng xếp hạng từ MongoDB dựa trên key (mặc định là 'points')."""
    all_users = get_user("*")
    sorted_users = sorted(
        ((user_id, data) for user_id, data in all_users.items()
         if isinstance(data, dict) and key in data),
        key=lambda x: x[1][key],
        reverse=True
    )

    leaderboard = "\n".join(
        f"> <@{user_id}>: {format_currency(data[key])} {coin}"
        for user_id, data in sorted_users
    )

    return leaderboard if leaderboard else "Không có dữ liệu."

def calculate_level_and_progress(smart):
    level = int(math.log2(smart / 5 + 1)) + 1
    needed_smart = 5 * ((2 ** (level - 1)) - 1)
    current_smart = max(0, smart - 5 * ((2 ** (level - 2)) - 1)) if level > 1 else smart
    
    next_level_needed_smart = 5 * ((2 ** level) - 1)
    progress_percentage = min((smart / next_level_needed_smart) * 100, 100) if next_level_needed_smart > 0 else 0

    return level, round(progress_percentage, 2), next_level_needed_smart

def roll_gacha_from_pool():
    # Bước 1: Random chọn nhóm trước
    rarity_list = list(gacha_data["rarity_chance"].keys())
    rarity_weights = list(gacha_data["rarity_chance"].values())

    selected_rarity = random.choices(rarity_list, weights=rarity_weights, k=1)[0]

    # Bước 2: Random vật phẩm trong nhóm đã chọn
    item_name = random.choice(gacha_data["gacha_pool"][selected_rarity])

    return {"name": item_name, "rarity": selected_rarity}

def format_currency(amount):
    return f"{amount:,.0f}".replace(",", " ")

ALLOWED_CHANNEL_ID = 1347480186198949920

@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập với tên {bot.user}')
    bot.loop.create_task(update_company_balances())
    bot.loop.create_task(clean_zero_items())

    # Kiểm tra nếu chưa có jackpot trong DB thì tạo mới
    if get_jackpot() is None:
        set_jackpot(1000000000)
        print("Đã khởi tạo jackpot mặc định.")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.reply("Lệnh bạn nhập không tồn tại. Vui lòng kiểm tra lại :>")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.reply("Bạn thiếu một tham số cần thiết. Vui lòng kiểm tra lại cú pháp lệnh.")
    elif isinstance(error, commands.BadArgument):
        await ctx.reply("Đối số bạn nhập không hợp lệ. Vui lòng kiểm tra lại.")
    else:
        # In lỗi ra console để debug
        print(f"Lỗi không xác định: {type(error).__name__} - {error}")
        await ctx.reply("Đã xảy ra lỗi không mong muốn. Vui lòng thử lại sau!")

@bot.command(name="start", help='`$start`\n> Khởi tạo tài khoản')
async def start(ctx):
    user_id = str(ctx.author.id)
    member = ctx.author

    if user_id in user_data:
        await ctx.reply(f"Bạn đã có tài khoản rồi, {ctx.author.mention} ơi! Không cần tạo lại nữa.")
        return

    # Khởi tạo tài khoản mới
    user_data[user_id] = {
        "points": 10000,
        "items": {},
        "smart": 100
    }

    # Kiểm tra vai trò và thêm vai trò cho người dùng
    role_id = 1316985467853606983
    role = ctx.guild.get_role(role_id)
    if role:
        if role not in member.roles:
            await member.add_roles(role)
        else:
            print(f"{member.name} đã có vai trò {role.name}")
    else:
        await ctx.reply("Không thể tìm thấy vai trò cần thiết trong server.")

    # Lưu lại dữ liệu người dùng
    save_user_data(user_data)

    # Thông báo cho người dùng
    await ctx.reply(f"Tài khoản của bạn đã được tạo thành công, {ctx.author.mention}!")

@bot.command(name="info", help='`$info`\n> xem thông tin của Bot')
async def info(ctx):
    if not await check_permission(ctx):
        return

    embed = discord.Embed(title="📊 Thông tin Bot", color=discord.Color.red())
    embed.add_field(name="👩‍💻 Nhà phát triển", value=f"```ansi\n[2;31mAlpha[0m```", inline=True)
    embed.add_field(name="Phiên bản Bot", value=f'```ansi\n[2;34m2.0.0[0m\n```')
    embed.set_thumbnail(url='https://cdn.discordapp.com/attachments/1322746396142604378/1322746745440043143/2.png?ex=6771ff67&is=6770ade7&hm=a9ec85dbd4076a807af3bccecb32e2eb8bd4b577d2a34f6e8d95dfbc4a9f327a&')

    await ctx.reply(embed=embed)

@bot.command(name="jar", help='`$jar`\n> xem hũ jackpot')
async def jp(ctx):
    if not await check_permission(ctx):
        return

    jackpot_amount = format_currency(user_data.get('jackpot', 0))
    await ctx.reply(f"💰 **Jackpot hiện tại:** {jackpot_amount} {coin}")
@bot.command(name="mk", help='`$mk`\n> xem cửa hàng')
async def shop(ctx):
    if not await check_permission(ctx):
        return

    embed = discord.Embed(
        title='🏬**Cửa hàng**\nMua bằng lệnh `$buy <id> <số lượng>`.\nBán bằng lệnh `$sell <id> <số lượng>`.',
        color=discord.Color.red())

    for item_id, item in shop_data.items():
        embed.add_field(
            name=f"`{item_id}` {item['name']}\n`{format_currency(item['price'])}` {coin}",
            value=f"\t",
            inline=True
        )

    await ctx.reply(embed=embed)

@bot.command(name="buy")
async def buy(ctx, item_id: str, quantity: int):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    if item_id not in shop_data:
        await ctx.reply("Không tìm thấy mặt hàng trong cửa hàng.")
        return

    if quantity <= 0:
        await ctx.reply("Số lượng phải lớn hơn không.")
        return

    item_data = shop_data[item_id]
    item_name = item_data['name']

    # Lấy danh sách vật phẩm của người dùng
    user_items = user_data[user_id].get('items', {})

    total_price = item_data['price'] * quantity

    if total_price > user_data[user_id]['points']:
        await ctx.reply("Bạn làm đéo gì có đủ tiền mà đòi mua")
        return
    
    if item_id == "01":
        if "company_balance" not in user_data[user_id]:
            user_data[user_id]["company_balance"] = 0

    if item_id == "03":
        if "company_balance" not in user_data[user_id]:
            user_data[user_id]["garden"] = {}

    # Trừ điểm của người dùng
    user_data[user_id]['points'] -= total_price

    # Thêm vật phẩm vào kho đồ của người dùng
    user_items[item_name] = user_items.get(item_name, 0) + quantity
    user_data[user_id]['items'] = user_items

    save_user_data(user_data)

    await ctx.reply(f"Bạn đã mua {quantity} {item_name}.")

@bot.command(name="sell")
async def sell(ctx, item_id: str, quantity: int):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    if item_id not in shop_data:
        await ctx.reply("Méo thấy mặt hàng này trong cửa hàng.")
        return

    if quantity <= 0:
        await ctx.reply("Số lượng phải lớn hơn không.")
        return

    item_data = shop_data[item_id]
    item_name = item_data['name']
    selling_price = round(item_data['price'] * quantity * 0.9)

    # Lấy danh sách vật phẩm của người dùng
    user_items = user_data[user_id].get('items', {})

    # Kiểm tra xem người dùng có đủ vật phẩm để bán không
    current_quantity = user_items.get(item_name, 0)
    
    if current_quantity < quantity:
        await ctx.reply("Bạn không có đủ mặt hàng này để bán.")
        return

    # Trừ số lượng vật phẩm từ kho đồ người dùng
    user_items[item_name] -= quantity

    # Kiểm tra và xóa `company_balance` nếu bán ID "01" và không còn trong kho
    if item_id == "01" and "company_balance" in user_data[user_id]:
        if user_data[user_id]['items'].get(":office: Công ty", 0) == 0:
            del user_data[user_id]["company_balance"]

    # Cập nhật điểm của người dùng
    user_data[user_id]['points'] += selling_price
    user_data[user_id]['items'] = user_items

    save_user_data(user_data)

    await ctx.reply(f"Bạn đã bán {quantity} {item_name} và nhận được {format_currency(selling_price)} {coin}.")

@bot.command(name="ttsp", help="`$ttsp <id sản phẩm>`\n> Hiển thị thông tin sản phẩm")
async def ttsp(ctx, item_id):
    if item_id in shop_data:
        item_data = shop_data[item_id]
        embed = discord.Embed(
            title=f"Thông tin sản phẩm:\n{item_data['name']}",
            color=discord.Color.red()
        )
        embed.add_field(name="Mô tả", value=item_data['description'], inline=False)
        embed.add_field(name="Giá mua", value=f'`{format_currency(item_data["price"])}` {coin}', inline=True)
        embed.add_field(name="Giá bán", value=f'`{format_currency(round(item_data["price"] * 0.9))}` {coin}', inline=True)
        await ctx.reply(embed=embed)
    else:
        await ctx.reply("Không tìm thấy sản phẩm với ID này.")

@bot.command(name="setb")
async def set_background(ctx, member: discord.Member, background_url: str):
    if ctx.author.id != 1196335145964285984:
        await ctx.reply("Chỉ người dùng được phép mới có thể sử dụng lệnh này.")
        return

    if not background_url.startswith("http"):
        await ctx.reply("URL không hợp lệ. Vui lòng cung cấp một URL hợp lệ.")
        return

    user_id = str(member.id)
    user_backgrounds[user_id] = background_url

    # Lưu lại dữ liệu vào file
    with open("backgrounds.json", "w") as f:
        json.dump(user_backgrounds, f, indent=4)

    await ctx.reply(f"Đã thay đổi nền của {member.display_name} thành: {background_url}")

@bot.command(name="cccd", help='`$cccd`\n> mở căn cước công dân')
async def cccd(ctx, member: discord.Member = None, size: int = 128):
    if not await check_permission(ctx):
        return

    if member is None:
        member = ctx.author

    user_id = str(member.id)
    background_url = user_backgrounds.get(user_id, "https://hinhanhonline.com/Hinhanh/images07/AnhAL/hinh-nen-may-tinh-dep-doc-dao-nhat-19.jpg") if isinstance(user_backgrounds, dict) else "https://hinhanhonline.com/Hinhanh/images07/AnhAL/hinh-nen-may-tinh-dep-doc-dao-nhat-19.jpg"

    if not await check_user_data(ctx, user_id):
        return

    smart = user_data[user_id]["smart"]
    user_name = member.name
    avatar_url = member.display_avatar.with_size(size).url

    level, progress_percentage, next_level_needed_smart = calculate_level_and_progress(smart)

    # Cập nhật vai trò
    role_name = await update_roles(ctx, member, level)

    # Tải hình ảnh avatar và background bất đồng bộ
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

    server_image = Image.open("E:\\usb\\Alpha\\1.png")  # Mở ảnh từ byte stream
    if server_image is None:
        await ctx.reply("Lỗi tải ảnh server.")
        return
    server_image = server_image.resize((80, 80))

    # Ghép ảnh
    galaxy_background.paste(server_image, (10, 10), mask=server_image)
    galaxy_background.paste(avatar_image, (20, 85), mask=avatar_image)

    # Cài đặt phông chữ
    font_path = "Roboto-Black.ttf"
    try:
        font_small = ImageFont.truetype(font_path, 12)
        font_large = ImageFont.truetype(font_path, 13)
    except IOError:
        font_large = font_small = ImageFont.load_default()

    draw = ImageDraw.Draw(galaxy_background)
    draw_text_with_outline(draw, f"Tên: {user_name}\nID: {user_id}\nHọc vấn: {format_currency(smart)}\nlv: {format_currency(level)}\nTrình độ: {role_name}", (160, 95), font_large)
    draw_text_with_outline(draw, f"CỘNG HÒA XÃ HỘI CHỦ NGHĨA MEME\n          Độc lập - Tự do - Hạnh phúc\n\n                 CĂN CƯỚC CƯ DÂN", (100, 20), font_large)
    
    # Vẽ thanh tiến độ
    filled_length = progress_percentage * 2
    bar_position = (160, 185, 160 + 200, 205)
    draw.rectangle(bar_position, outline="black", width=3)
    draw.rectangle((163, 188, 157 + filled_length, 202), fill="#1E90FF")

    draw_text_with_outline(draw, f"{smart}/{next_level_needed_smart}", (165, 188), font_small)

    # Lưu và gửi ảnh
    with io.BytesIO() as image_binary:
        galaxy_background.save(image_binary, "PNG")
        image_binary.seek(0)
        await ctx.reply(file=discord.File(fp=image_binary, filename="cccd.png"))

@bot.command(name="bag", help='`$bag`\n> mở túi')
async def bag(ctx, member: discord.Member = None):
    if not await check_permission(ctx):
        return

    member = member or ctx.author
    user_id = str(member.id)

    if not await check_user_data(ctx, user_id):
        return

    points = format_currency(user_data[user_id].get('points', 0))
    items = user_data[user_id].get('items', {})

    if not items:
        item_list = "Trống."
    else:
        # Đếm và định dạng danh sách đồ
        item_list = ""
        for item_name, quantity in items.items():
            item_list += f"{item_name}: {quantity}\n"

    # Lấy company_balance nếu có
    company_balance = user_data[user_id].get("company_balance")
    company_text = f"**Công ty**: {format_currency(company_balance)} {coin}." if company_balance is not None else ""

    # Tạo embed
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

    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    if bet.lower() == 'all':
        bet = user_data[user_id]['points']
    else:
        try:
            bet = int(bet)
        except ValueError:
            await ctx.reply(f"Số {coin} cược không hợp lệ.")
            return

    if bet <= 0 or bet > user_data[user_id]['points']:
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

    if (3 <= total <= 10 and choice == "x") or (11 <= total <= 18 and choice == "t"):
        user_data[user_id]['points'] += bet
    else:
        user_data[user_id]['points'] -= bet

    save_user_data(user_data)

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
            await rolling_message.edit(content=f"`   ` {dice1_emoji} `Xỉu`\n`$$`{dice2_emoji} {dice3_emoji}`  `\nHehe,{ctx.author.mention} ngu thì chết chứ sao :rofl:")
    if 11 <= total <= 18:
        if choice == "x":
            await rolling_message.edit(content=f"`Tài` {dice1_emoji} `   `\n`  `{dice2_emoji} {dice3_emoji}`$$`\nHehe,{ctx.author.mention} ngu thì chết chứ sao :rofl:")
        else:
            await rolling_message.edit(content=f"`Tài` {dice1_emoji} `   `\n`$$`{dice2_emoji} {dice3_emoji}`  `")

@bot.command(name="daily", help='`$daily`\n> nhận quà hằng ngày')
async def daily(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    last_daily = user_data[user_id].get('last_daily')
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
            user_data[user_id]['streak'] += 1
        else:
            user_data[user_id]['streak'] = 1
    else:
        user_data[user_id]['streak'] = 1

    base_reward = 5000
    streak_bonus = user_data[user_id]['streak'] * 100
    total_reward = base_reward + streak_bonus

    user_data[user_id]['points'] += total_reward
    user_data[user_id]['last_daily'] = now.strftime("%Y-%m-%d")

    save_user_data(user_data)

    await ctx.reply(f"Bạn đã nhận được {format_currency(total_reward)} {coin}! (Thưởng streak: {streak_bonus} {coin}, chuỗi ngày: {user_data[user_id]['streak']} ngày)")

@bot.command(name="prog", help='`$prog`\n> ăn xin')
async def prog(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not get_user(user_id):
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    last_beg = user_data[user_id].get('last_beg')
    now = datetime.datetime.now()

    if last_beg is not None:
        cooldown_time = 3 * 60
        time_elapsed = (now - datetime.datetime.strptime(last_beg, "%Y-%m-%d %H:%M:%S")).total_seconds()

        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn đã ăn xin rồi, vui lòng thử lại sau {minutes} phút {seconds} giây.")
            return

    if user_data[user_id]['points'] < 100000:
        beg_amount = random.randint(0, 5000)
        user_data[user_id]['points'] += beg_amount
    else:
        await ctx.reply('giàu mà còn đi ăn xin đéo thấy nhục à')
        return
    
    user_data[user_id]['last_beg'] = now.strftime("%Y-%m-%d %H:%M:%S")

    save_user_data(user_data)

    await ctx.reply(f"Bạn đã nhận được {format_currency(beg_amount)} {coin} từ việc ăn xin!")

@bot.command(name="dn", help='`$dn <điểm> <người chơi>`\n> donate điểm cho người khác')
async def give(ctx, amount: int, member: discord.Member):
    if not await check_permission(ctx):
        return

    giver_id = str(ctx.author.id)
    receiver_id = str(member.id)

    if giver_id not in user_data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    if receiver_id not in user_data:
        await ctx.reply("Có vẻ đối tượng chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    giver_points = user_data[giver_id].get('points', 0)

    if amount <= 0:
        await ctx.reply(f"Số {coin} phải lớn hơn 0!")
        return

    if amount > giver_points:
        await ctx.reply(f"Bạn không đủ {coin} để tặng!")
        return

    user_data[giver_id]['points'] -= amount
    user_data[receiver_id]['points'] += amount

    save_user_data(user_data)

    await ctx.reply(f"Bạn đã tặng {format_currency(amount)} {coin} cho {member.mention}!")

@bot.command(name="?", aliases=["help"], help="Hiển thị danh sách lệnh hoặc thông tin chi tiết về một lệnh.")
async def help(ctx, command=None):
    """Provides detailed help for commands or a general list of commands."""

    if command is None:
        embed = discord.Embed(
            title="Danh sách lệnh",
            description=f"Lệnh tài khoản:\n> `$start`, `$lb`, `$dn`, `$cccd`, `$bag`\nLệnh mua bán:\n> `$mk`, `$ttsp`\nLệnh kiếm tiền:\n> `$daily`, `$prog`, `$hunt`\nLệnh tệ nạn:\n> `$ou`, `$thief`, `$othief`, `$slots`\nLệnh học vấn:\n> `$op`, `$study`\nLệnh cây cối:\n> `$plant`, `$mygarden`, `$harvest`",
            color=discord.Color.red()
            )
        
        await ctx.reply(embed=embed)
    else:  # Help for a specific command
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

    if robber_id not in user_data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")
        return

    if victim_id not in user_data:
        await ctx.reply("Nạn nhân không có trong dữ liệu của trò chơi.")
        return

    now = datetime.datetime.now()
    last_rob = user_data[robber_id].get('last_rob')
    
    if last_rob is not None:
        time_elapsed = (now - datetime.datetime.strptime(
            last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60

        if time_elapsed < cooldown_time:
            if user_data[robber_id]['items'].get(':fast_forward: Skip', 0) > 0:
                user_data[robber_id]['items'][':fast_forward: Skip'] -= 1
                await ctx.reply(f"Bạn đã sử dụng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                minutes, seconds = divmod(int(cooldown_time - time_elapsed),60)
                hours, minutes = divmod(minutes, 60)
                await ctx.reply(f"Bạn phải chờ {hours} giờ {minutes} phút {seconds} giây trước khi cướp lại.")
                return
            
    if status == discord.Status.online:
        await ctx.reply('Nó đang online đấy, cẩn thận không nó đấm!')
        return

    if victim_id == '1243079760062709854':
        await ctx.reply('Định làm gì với Admin Bot đấy?')
        return

    # Kiểm tra pet bảo vệ và pet trộm
    victim_has_guard_pet = user_data[victim_id]['items'].get(':dog: Pet bảo vệ', 0) > 0
    robber_has_thief_pet = user_data[robber_id]['items'].get(':cat: Pet trộm', 0) > 0

    # Kiểm tra Ổ khóa
    if user_data[victim_id]['items'].get(':lock: Ổ khóa', 0) > 0:
        tools = {
            "b": { "emoji": ":bomb: Bom", "chance": 0.75 },
            "w": { "emoji": ":wrench: Kìm", "chance": 0.5 },
            "c": { "emoji": "<:cleaner:1347560866291257385> máy hút bụi", "chance": 0.85 }
        }

        # Nếu người dùng chọn công cụ
        if tool:
            tool = tool.lower()
            if tool in tools and user_data[robber_id]['items'].get(tools[tool]["emoji"], 0) > 0:
                base_chance = tools[tool]["chance"]

                # Điều chỉnh tỷ lệ dựa trên pet
                if victim_has_guard_pet:
                    base_chance -= 0.10  # Giảm 10% nếu nạn nhân có pet bảo vệ
                if robber_has_thief_pet:
                    base_chance += 0.10  # Tăng 10% nếu người trộm có pet trộm

                success = random.random() < base_chance
                if success:
                    user_data[victim_id]['items'][':lock: Ổ khóa'] -= 1
                    user_data[robber_id]['items'][tools[tool]["emoji"]] -= 1

                    # Nếu dùng máy hút bụi, xóa ngẫu nhiên 2000 món
                    if tool == "c":
                        victim_items = user_data[victim_id]['items']
                        if victim_items:
                            random_item = random.choice(list(victim_items.keys()))
                            victim_items[random_item] = max(0, victim_items[random_item] - 2000)
                            await ctx.reply(f"Bạn đã dùng {tools[tool]['emoji']} và phá vỡ Ổ khóa của {member.mention}!\nBạn còn hút luôn 2000 {random_item} của họ! 😈")
                        else:
                            await ctx.reply(f"Bạn đã dùng {tools[tool]['emoji']} và phá vỡ Ổ khóa của {member.mention}, nhưng họ không có đồ gì để hút!")
                    else:
                        await ctx.reply(f"Bạn đã dùng {tools[tool]['emoji']} và phá vỡ Ổ khóa của {member.mention}! Thành công cướp!")
                else:
                    await ctx.reply(f"Bạn đã dùng {tools[tool]['emoji']} nhưng không phá được Ổ khóa!")
                    return
            else:
                await ctx.reply("Bạn không có hoặc đã nhập sai công cụ! Chọn `b` (bom), `w` (kìm) hoặc `c` (máy hút bụi).")
                return
        else:
            # Nếu không chọn, bot tự động chọn
            possible_tools = [":bomb: Bom", ":wrench: Kìm"]
            for tool_emoji in possible_tools:
                if user_data[robber_id]['items'].get(tool_emoji, 0) > 0:
                    base_chance = 0.75 if tool_emoji == ":bomb: Bom" else 0.5

                    # Điều chỉnh tỷ lệ dựa trên pet
                    if victim_has_guard_pet:
                        base_chance -= 0.10
                    if robber_has_thief_pet:
                        base_chance += 0.10

                    if random.random() < base_chance:
                        user_data[victim_id]['items'][':lock: Ổ khóa'] -= 1
                        user_data[robber_id]['items'][tool_emoji] -= 1
                        await ctx.reply(f"Bạn đã dùng {tool_emoji} và phá vỡ Ổ khóa của {member.mention}! Thành công cướp!")
                        break
            else:
                await ctx.reply(f"{member.name} đã bảo vệ tài khoản bằng Ổ khóa. Bạn không thể cướp!")
                return

    # Kiểm tra số điểm của nạn nhân
    victim_points = user_data[victim_id].get('points', 0)
    if victim_points <= 0:
        await ctx.reply(f"{member.name} không có {coin} để cướp!")
        return

    stolen_points = round(victim_points * 0.5)
    user_data[victim_id]['points'] -= stolen_points
    user_data[robber_id]['points'] += stolen_points

    user_data[robber_id]['last_rob'] = now.strftime("%Y-%m-%d %H:%M:%S")

    save_user_data(user_data)
    await ctx.reply(f"Bạn đã cướp được {format_currency(stolen_points)} {coin} từ {member.name}!")

@bot.command(name="hunt", help='`$hunt <weapon>`\n> đi săn kiếm tiền')
async def hunt(ctx, weapon: str):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    weapon_data = {
        "g": {"item": ":gun: Súng săn", "ammo": 1, "reward_range": (0, 50000)},
        "r": {"item": "<:RPG:1325750069189677087> RPG", "ammo": 10, "reward_range": (-2000000, 5000000)},
        "a": {"item": "<:Awm:1325747265045794857> Awm", "ammo": 1, "reward_range": (5000, 1000000)},
        "c": {"item": "<:cleaner:1347560866291257385> máy hút bụi", "ammo": 0, "reward_range": (3000000, 10000000)}
    }

    if weapon not in weapon_data:
        await ctx.reply("Vũ khí không hợp lệ!")
        return

    now = datetime.datetime.now()
    last_hunt = user_data[user_id].get('last_hunt')
    cooldown_time = 5 * 60

    if last_hunt:
        time_elapsed = (now - datetime.datetime.strptime(last_hunt, "%Y-%m-%d %H:%M:%S")).total_seconds()
        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn cần chờ {minutes} phút {seconds} giây trước khi có thể săn tiếp!")
            return

    weapon_info = weapon_data[weapon]

    # Kiểm tra số lượng vũ khí và đạn
    user_items = user_data[user_id].get('items', {})
    weapon_count = user_items.get(weapon_info["item"], 0)
    ammo_count = user_items.get(":bullettrain_side: Viên đạn", 0)

    if weapon_count < 1:
        await ctx.reply(f"Bạn cần có {weapon_info['item']} để đi săn!")
        return

    if ammo_count < weapon_info["ammo"]:
        await ctx.reply(f"Bạn cần có {weapon_info['ammo']} viên đạn để đi săn!")
        return
    
    if weapon == "c":
        del user_data[user_id]['items'][weapon_info["item"]]

    # Trừ đạn
    user_data[user_id]['items'][":bullettrain_side: Viên đạn"] -= weapon_info["ammo"]
    if user_data[user_id]['items'][":bullettrain_side: Viên đạn"] == 0:
        del user_data[user_id]['items'][":bullettrain_side: Viên đạn"]

    # Tính phần thưởng
    hunt_reward = random.randint(*weapon_info["reward_range"])
    user_data[user_id]['points'] += hunt_reward
    user_data[user_id]['last_hunt'] = now.strftime("%Y-%m-%d %H:%M:%S")

    save_user_data(user_data)
    await ctx.reply(f"Bạn đã săn thành công và kiếm được {format_currency(hunt_reward)} {coin}!")

@bot.command(name="in", help='`$in <số điểm>`\n> bơm tiền vào công ty')
async def invest(ctx, amount: int):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if ':office: Công ty' in user_data[user_id]['items']:
        if not get_user(user_id):
            await ctx.reply("Người chơi không tồn tại.")
            return

        if amount <= 0:
            await ctx.reply("Số điểm phải lớn hơn 0.")
            return

        if user_data[user_id]["points"] < amount:
            await ctx.reply(f"Bạn không có đủ {coin} để đầu tư.")
            return

        user_data[user_id]["points"] -= amount
        user_data[user_id]["company_balance"] += amount

        await ctx.reply(f"Bạn đã đầu tư {format_currency(amount)} {coin} vào công ty.")
        save_user_data(user_data)
    else:
        await ctx.reply(f"{ctx.autor.mention} Bạn làm đéo gì có :office: Công ty mà đầu tư :rofl:")

@bot.command(name="wi", help='`$wi <số điểm>`\n> rút tiền ra')
async def withdraw(ctx, amount: int):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not get_user(user_id):
        await ctx.reply("Người chơi không tồn tại.")
        return

    if amount <= 0:
        await ctx.reply("Số điểm phải lớn hơn 0.")
        return

    if user_data[user_id]["company_balance"] < amount:
        await ctx.reply(f"Công ty của bạn không có đủ {coin} để rút.")
        return

    user_data[user_id]["company_balance"] -= amount
    user_data[user_id]["points"] += amount

    await ctx.reply(f"Bạn đã rút {format_currency(amount)} {coin} từ công ty.")

@bot.command(name="othief", help='`$othief <người chơi>`\n> rút tiền từ công ty thằng bạn')
async def orob(ctx, member: discord.Member):
    if not await check_permission(ctx):
        return

    orobber_id = str(ctx.author.id)
    victim_id = str(member.id)
    status = member.status

    if orobber_id not in user_data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng `$start` để tạo tài khoản.")

    if victim_id not in user_data:
        await ctx.reply("Nạn nhân ko có trong dữ liệu của trò chơi.")
        return

    now = datetime.datetime.now()
    last_rob = user_data[orobber_id].get('last_rob')
    if last_rob is not None:
        time_elapsed = (now - datetime.datetime.strptime(
            last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60

        if time_elapsed < cooldown_time:
            if user_data[orobber_id]['items'].get(':fast_forward: Skip', 0) > 0:
                user_data[orobber_id]['items'][':fast_forward: Skip'] -= 1
                await ctx.reply(f"Bạn đã sử dụng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                minutes, seconds = divmod(int(cooldown_time - time_elapsed),60)
                hours, minutes = divmod(minutes, 60)
                await ctx.reply(f"Bạn phải chờ {hours} giờ {minutes} phút {seconds} giây trước khi cướp lại.")
                return

    if status == discord.Status.online:
        await ctx.reply('Nó đang on đếy, cẩn thận ko nó đấm')
        return
        
    if victim_id == "1243079760062709854":
        await ctx.reply('Định làm gì với công ty của Admin Bot đếy, mày cẩn thận')
        return
    
    if user_data[orobber_id]['items'].get(':credit_card: thẻ công ty giả', 0) > 0:
        user_data[orobber_id]['items'][':credit_card: thẻ công ty giả'] -= 1
        if random.random() < 0.25:
            await ctx.reply(f"Bạn đã sử dụng Thẻ giả để rút {coin} của {member.name} và đã thành công!")

            victim_points = user_data[victim_id].get('company_balance', 0)
            if victim_points <= 0:
                await ctx.reply(f"{member.name} không có {coin} để cướp!")
                return

            stolen_points = round(victim_points * 0.5)

            user_data[victim_id]['company_balance'] = round(user_data[victim_id]['company_balance'] - stolen_points)
            user_data[orobber_id]['points'] = round(user_data[orobber_id]['points'] + stolen_points)

            user_data[orobber_id]['last_rob'] = now.strftime("%Y-%m-%d %H:%M:%S")

            save_user_data(user_data)

            await ctx.reply(f"Bạn đã rút được {format_currency(stolen_points)} {coin} từ {member.name}!")
        else:
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

    if killer_id not in user_data:
        await ctx.reply("Có vẻ bạn chưa chơi lần nào trước đây vui lòng dùng $start để tạo tài khoản.")

    if victim_id not in user_data:
        await ctx.reply("Nạn nhân ko có trong dữ liệu của trò chơi.")
        return

    now = datetime.datetime.now()
    last_rob = user_data[killer_id].get('last_rob')
    if last_rob is not None:
        time_elapsed = (now - datetime.datetime.strptime(last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60

        if time_elapsed < cooldown_time:
            if user_data[killer_id]['items'].get(':fast_forward: Skip', 0) > 0:
                user_data[killer_id]['items'][':fast_forward: Skip'] -= 1
                await ctx.reply("Bạn đã sử dụng :fast_forward: Skip để bỏ qua thời gian chờ!")
            else:
                remaining_time = cooldown_time - time_elapsed
                hours, remainder = divmod(remaining_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                await ctx.reply(f"Bạn phải chờ {int(hours)} giờ {int(minutes)} phút {int(seconds)} giây trước khi săn lại.")
                return

    if user_data[killer_id]['items'].get(':bulb: Thông minh', 0) > 0:
        if victim_id == killer_id:
            await ctx.reply('mày tính tự solo à con, méo có đâu nhé :>')
        else:
            if user_data[killer_id]['items'].get('<:big_nao:1308790909353328640> siêu thông minh `Legendary`', 0) > 0:
                success += 0.5

            if random.random() < success:
                user_data[killer_id]['items'][':bulb: Thông minh'] -= 1
                await ctx.reply(f"Bạn đã sử dụng sự thông minh để ao trình {member.name} và đã thành công!")
                victim_points = user_data[victim_id].get('smart', 0)
                if victim_points <= 0:
                    await ctx.reply(f"{member.name} không có học vấn để húp!")
                    return

                stolen_points = round(victim_points * 0.1)

                user_data[victim_id]['smart'] = round(user_data[victim_id]['smart'] - stolen_points * 0.5)
                user_data[killer_id]['smart'] = round(user_data[killer_id]['smart'] + stolen_points)
                user_data[killer_id]['points'] = round(user_data[killer_id]['points'] + stolen_points)

                user_data[killer_id]['last_rob'] = now.strftime("%Y-%m-%d %H:%M:%S")

                save_user_data(user_data)

                await ctx.reply(f"Bạn đã húp được {format_currency(stolen_points)} {coin}, học vấn từ {member.name}!")
            else:
                await ctx.reply(f"Bạn đã sử dụng sự thông minh để ao trình {member.name} nhưng không thành công.")
                return
    else:
        await ctx.reply("Bạn làm đéo gì có sự thông minh :rofl:")

@bot.command(name="ping", help='`$ping`\n> xem độ trễ của bot')
async def ping(ctx):
    latency = bot.latency
    await ctx.reply(f'Ping : {latency * 1000:.2f}ms.')

@bot.command(name="lb", help='`$lb`\n> xem bảng xếp hạng')
async def lb(ctx, kind: str = "a"):
    if not await check_permission(ctx):
        return

    if not user_data:
        await ctx.reply("Không có dữ liệu để hiển thị bảng xếp hạng.")
        return

    kind_to_function = {
        "a": lambda data: create_leaderboard(data, "points"),
        "o": lambda data: create_leaderboard(data, "company_balance"),
        "s": lambda data: create_leaderboard(data, "smart"),
    }

    create_function = kind_to_function.get(kind)
    if not create_function:
        await ctx.reply(
            "Loại bảng xếp hạng không hợp lệ. Vui lòng sử dụng:\n"
            "`$lb a` - Tài khoản\n"
            "`$lb o` - Công ty\n"
            "`$lb s` - Học vấn."
        )
        return

    leaderboard = create_function(user_data)

    embed = discord.Embed(
        title="Bảng xếp hạng",
        description=leaderboard,
        color=discord.Color.red()
    )

    await ctx.reply(embed=embed)

@bot.command(name='gacha', help='`$gacha`\n> gacha ra những thứ hay ho')
async def gacha(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    user_roles = [role.name for role in ctx.author.roles]

    # Đảm bảo truyền user_id vào check_user_data
    if not await check_user_data(ctx, user_id):
        return

    # Kiểm tra cooldown
    now = datetime.datetime.now()
    last_gacha = user_data[user_id].get('last_gacha')
    
    if last_gacha:
        time_elapsed = (now - datetime.datetime.strptime(last_gacha, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60  # 1 giờ

        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn phải chờ {minutes} phút {seconds} giây trước khi quay gacha lại.")
            return

    # Kiểm tra quyền và số tiền người dùng có
    if "Trung học Phổ thông" in user_roles:
        if user_data[user_id].get('points', 0) < 10000000000:
            await ctx.reply(f'Bạn không đủ {coin} để gacha!')
            return
        
        # Trừ tiền và điểm thông minh khi gacha
        try:
            user_data[user_id]['points'] -= 10000000000
            user_data[user_id]['smart'] -= 1000000
        except KeyError as e:
            await ctx.reply("Có lỗi xảy ra trong quá trình trừ điểm.")
            return

        result = roll_gacha_from_pool()
        item_name = result.get("name", "Không có tên vật phẩm")
        rarity = result.get("rarity", "Không xác định")

        rarity_colors = {
            "tốt": discord.Color.green(),
            "hiếm": discord.Color.blue(),
            "sử thi": discord.Color.purple(),
            "huyền thoại": discord.Color.orange()
        }

        # Thêm item vào kho đồ
        user_data[user_id]["items"][item_name] = user_data[user_id]["items"].get(item_name, 0) + 1

        # Cập nhật thời gian gacha
        user_data[user_id]['last_gacha'] = now.strftime("%Y-%m-%d %H:%M:%S")
        save_user_data(user_data)

        # Hiển thị kết quả gacha với màu sắc theo độ hiếm
        embed = discord.Embed(
            title="🎲 Gacha Roll 🎲",
            description=f"Bạn đã quay được: **{item_name}**\n🔹 Độ hiếm: `{rarity.upper()}`",
            color=rarity_colors.get(rarity, discord.Color.gold())  # Mặc định màu vàng nếu lỗi
        )
        await ctx.reply(embed=embed)

@bot.command(name='slots', help='`$slots`\n> quay jackpot')
async def slots(ctx):
    if not await check_permission(ctx):
        return
    
    user_id = str(ctx.author.id)
    user_roles = [role.name for role in ctx.author.roles]

    if not await check_user_data(ctx, user_id):
        return

    now = datetime.datetime.now()
    last_rob = user_data[user_id].get('last_slots')
    if last_rob is not None:
        time_elapsed = (now - datetime.datetime.strptime(last_rob, "%Y-%m-%d %H:%M:%S")).total_seconds()
        cooldown_time = 60 * 60

        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed),60)
            hours, minutes = divmod(minutes, 60)
            await ctx.reply(f"Bạn phải chờ {hours} giờ {minutes} phút {seconds} giây trước khi quay slots tiếp lại.")
            return
        
    if "Trung học Phổ thông" in user_roles:
        if user_data[user_id]['points'] < 1000000000:
            await ctx.reply(f'Bạn ko đủ {coin} để gacha!')
            return

        user_data[user_id]['points'] -= 1000000000

        dice1, dice2, dice3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)

        if dice1 == dice2 == dice3:
            jackpot_amount = user_data['jackpot']
            user_data[user_id]['points'] += jackpot_amount
            user_data['jackpot'] = 1000000000
            save_user_data(user_data)
            await ctx.reply(f"`$$$` {dice_emojis[dice1]} `$$$`\n`$$`{dice_emojis[dice2]} {dice_emojis[dice3]}`$$`\nChúc mừng! Bạn đã thắng **Jackpot** trị giá {format_currency(jackpot_amount)} {coin}!")
        else:
            user_data['jackpot'] += 1000000000
            save_user_data(user_data)
            await ctx.reply(f"`$$$` {dice_emojis[dice1]} `$$$`\n`$$`{dice_emojis[dice2]} {dice_emojis[dice3]}`$$`\nOH NO! Bạn đã thua **Jackpot** trị giá 1000000000 {coin}!")
    else:
        await ctx.reply(f'Bạn chưa đạt trình độ `THPT (lớp 12)` để quay slots')

    user_data[user_id]['last_slots'] = now.strftime("%Y-%m-%d %H:%M:%S")

@bot.command(name='study', help='`$study`\n> Học tăng trình độ')
async def study(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)
    now = datetime.datetime.now()
    last_study = user_data.get(user_id,{}).get('last_study')

    if not await check_user_data(ctx, user_id):
        return

    if last_study is not None:
        cooldown_time = 5 * 60
        time_elapsed = (now - datetime.datetime.strptime(last_study, "%Y-%m-%d %H:%M:%S")).total_seconds()

        if time_elapsed < cooldown_time:
            minutes, seconds = divmod(int(cooldown_time - time_elapsed), 60)
            await ctx.reply(f"Bạn cần chờ {minutes} phút {seconds} giây trước khi có thể học tiếp!")
            return

    user_data.setdefault(user_id,{'smart':0,'points':0,'items':[],'company_balance':0})
    user_data[user_id]['smart'] += 10

    user_data[user_id]['last_study'] = now.strftime("%Y-%m-%d %H:%M:%S")

    save_user_data(user_data)

    await ctx.reply(f'Bạn vừa học xong ra chơi thôi!')

@bot.command(name="plant", help="`$plant`\n> Trồng cây nếu có hạt giống.")
async def plant(ctx):
    if not await check_permission(ctx):
        return

    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    if user_data[user_id]['items'].get(':seedling: Hạt giống', 0) < 1:
        await ctx.reply("🌱 Bạn không có :seedling: Hạt giống để trồng. Hãy mua ở cửa hàng!")
        return

    if user_data[user_id].get("garden", {}).get("plant"):
        await ctx.reply("🌱 Bạn đã có cây đang trồng rồi! Hãy thu hoạch trước khi trồng tiếp.")
        return

    class PlantChoiceView(View):
        def __init__(self):
            super().__init__(timeout=60)

        async def plant_tree(self, interaction, plant_type, time_minutes, min_reward, max_reward):
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            user_data[user_id]["garden"] = {
                "plant": plant_type,
                "planted_at": now,
                "time_required": time_minutes * 60,
                "min_reward": min_reward,
                "max_reward": max_reward
            }

            # Trừ hạt giống
            user_data[user_id]["items"][":seedling: Hạt giống"] -= 1
            if user_data[user_id]["items"][":seedling: Hạt giống"] <= 0:
                del user_data[user_id]["items"][":seedling: Hạt giống"]

            save_user_data(user_data)
            await interaction.response.edit_message(content=f"🌱 Bạn đã trồng **{plant_type}**!", view=None)

        @discord.ui.button(label="🍎 Táo (5 phút)", style=discord.ButtonStyle.success)
        async def apple(self, interaction: discord.Interaction, button: Button):
            await self.plant_tree(interaction, "Táo", 5, 100_000, 200_000)

        @discord.ui.button(label="🍉 Dưa (10 phút)", style=discord.ButtonStyle.primary)
        async def melon(self, interaction: discord.Interaction, button: Button):
            await self.plant_tree(interaction, "Dưa", 10, 100_000, 300_000)

        @discord.ui.button(label="🍐 Lê (20 phút)", style=discord.ButtonStyle.danger)
        async def pear(self, interaction: discord.Interaction, button: Button):
            await self.plant_tree(interaction, "Lê", 20, 100_000, 400_000)

    view = PlantChoiceView()
    await ctx.reply("🌿 Chọn loại cây bạn muốn trồng:", view=view)

@bot.command(name="mygarden", help="`$mygarden`\n> Xem thông tin cây bạn đang trồng.")
async def mygarden(ctx):
    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    garden = user_data[user_id].get("garden", {})
    if not garden or not garden.get("plant"):
        await ctx.reply("🌱 Bạn chưa trồng cây nào cả.")
        return

    planted_time = datetime.datetime.strptime(garden["planted_at"], "%Y-%m-%d %H:%M:%S")
    elapsed = datetime.datetime.now() - planted_time
    minutes = int(elapsed.total_seconds() // 60)

    await ctx.reply(f"🌿 Cây **{garden['plant']}** của bạn đã trồng được {minutes} phút.")

@bot.command(name="harvest", help="`$harvest`\n> Thu hoạch cây nếu đã đủ thời gian.")
async def harvest(ctx):
    if not await check_permission(ctx):
        return
    
    user_id = str(ctx.author.id)

    if not await check_user_data(ctx, user_id):
        return

    garden = user_data[user_id].get("garden", {})
    if not garden or not garden.get("plant"):
        await ctx.reply("🌱 Bạn chưa trồng cây nào để thu hoạch.")
        return

    planted_time = datetime.datetime.strptime(garden["planted_at"], "%Y-%m-%d %H:%M:%S")
    now = datetime.datetime.now()
    elapsed_seconds = (now - planted_time).total_seconds()

    required = garden.get("time_required", 300)
    if elapsed_seconds < required:
        remaining = int((required - elapsed_seconds) // 60)
        await ctx.reply(f"⏳ Cây **{garden['plant']}** chưa chín. Quay lại sau {remaining} phút nữa.")
        return

    reward = random.randint(garden["min_reward"], garden["max_reward"])
    user_data[user_id]["points"] += reward
    user_data[user_id]["garden"] = {}

    save_user_data(user_data)
    await ctx.reply(f"🌳 Bạn đã thu hoạch **{garden['plant']}** và nhận được {format_currency(reward)} {coin}!")

@bot.command(name="clear")
async def clear_messages(ctx, amount: int):
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.reply("Bạn không có quyền xóa tin nhắn!")
        return

    await ctx.channel.purge(limit=amount)

bot.run('MTM2MjMxNDk1NzcxNDIzMTMyNg.GcETUJ.gA-0RbkMw8SoySpbsnYP7UUoeJf9g6wGpQ5yPw')
