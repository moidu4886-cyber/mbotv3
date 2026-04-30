import asyncio
import os
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant, FloodWait
from aiohttp import web

# --- CONFIG ---
API_ID    = int(os.environ.get("API_ID", "18063763"))
API_HASH  = os.environ.get("API_HASH", "f8bbe42c559b4c7dbddda61b7f0481bb")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID  = 7207674086

from database import users, files, plans, demo_media

app = Client("bot", bot_token=BOT_TOKEN, api_id=API_ID, api_hash=API_HASH)

# In-memory state dicts
user_wait  = {}   # user_id -> plan_id  (waiting for unlock code)
edit_state = {}   # user_id -> state string (admin waiting for input)


# ─────────────────────────────────────────────────────────────
# WEB SERVER  (keeps bot alive on Koyeb / Railway)
# ─────────────────────────────────────────────────────────────
async def handle_web(request):
    return web.Response(text="Bot Status: Online")

async def web_server():
    server = web.Application()
    server.add_routes([web.get("/", handle_web)])
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8000).start()


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────
async def is_subscribed(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    settings = await plans.find_one({"plan_id": "settings"})
    channel  = settings.get("channel_id") if settings else None
    if not channel:
        return True
    try:
        member = await app.get_chat_member(channel, user_id)
        return member.status.name not in ("LEFT", "BANNED", "KICKED")
    except UserNotParticipant:
        return False
    except Exception:
        return True


def admin_panel_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Manage Plans",           callback_data="manage_plans")],
        [InlineKeyboardButton("🎬 Manage Demo",             callback_data="manage_demo")],
        [InlineKeyboardButton("📊 Stats & Contents",        callback_data="full_stats")],
        [InlineKeyboardButton("📢 Broadcast",               callback_data="broadcast_msg")],
        [InlineKeyboardButton("🔗 Index from Channel/Group",callback_data="adv_index_menu")],
        [InlineKeyboardButton("🛠 Settings (QR / Channel)", callback_data="bot_settings")],
    ])


def home_text(mention):
    return (
        f"👋 Welcome {mention}!\n✨ This is an Adults Only Video Bot.\n"
        "🎬 Premium contents & exclusive access  \n"
        "👉 Click Watch Now to view available plans\n"
        "━━━━━━━━━━━━━━\n"
        "⚠️ Disclaimer  \n"
        "🔞 ഈ ബോട്ട് 18 വയസിന് മുകളിലുള്ളവർക്ക് മാത്രം  \n"
        "🚫 Under 18 – Do not use\n"
        "━━━━━━━━━━━━━━\n"
        "Choose an option below:"
    )


def home_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 Open Videos",  callback_data="watch")],
        [InlineKeyboardButton("🔍 Demo Preview", callback_data="demo_view_0")],
        [InlineKeyboardButton("🆘 Support",      callback_data="support_info")],
    ])


# ─────────────────────────────────────────────────────────────
# DEMO SENDER
# ─────────────────────────────────────────────────────────────
async def send_demo_item(client, chat_id, index: int, old_message=None):
    """Send demo item at given index with navigation. Deletes old_message if given."""
    total = await demo_media.count_documents({})

    if total == 0:
        text = "📭 No demo content available yet. Check back later!"
        kb   = InlineKeyboardMarkup([[InlineKeyboardButton("💎 View Plans", callback_data="watch")]])
        if old_message:
            try:
                await old_message.edit_text(text, reply_markup=kb)
            except Exception:
                await client.send_message(chat_id, text, reply_markup=kb)
        else:
            await client.send_message(chat_id, text, reply_markup=kb)
        return

    index = max(0, min(index, total - 1))
    item  = await demo_media.find({}).skip(index).limit(1).next()

    nav_row = []
    if index > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"demo_view_{index - 1}"))
    if index < total - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"demo_view_{index + 1}"))

    kb = InlineKeyboardMarkup(
        ([nav_row] if nav_row else []) +
        [[InlineKeyboardButton(f"📄 {index + 1} / {total}", callback_data="noop")]] +
        [[InlineKeyboardButton("💎 View Plans", callback_data="watch")]]
    )

    caption = item.get("caption", "") or f"🎬 Demo {index + 1} of {total}\n\n💎 Unlock full content — tap View Plans!"
    fid     = item["file_id"]
    ftype   = item["file_type"]  # "photo" or "video"

    # Delete the old text/nav message before sending the new media
    if old_message:
        try:
            await old_message.delete()
        except Exception:
            pass

    if ftype == "photo":
        await client.send_photo(chat_id, fid, caption=caption, has_spoiler=True, reply_markup=kb)
    elif ftype == "video":
        await client.send_video(chat_id, fid, caption=caption, has_spoiler=True, reply_markup=kb)
    else:
        await client.send_document(chat_id, fid, caption=caption, reply_markup=kb)


# ─────────────────────────────────────────────────────────────
# 1. ADMIN COMMANDS
# ─────────────────────────────────────────────────────────────
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID) & filters.private)
async def admin_panel(client, message: Message):
    await message.reply("👑 **Admin Control Panel**", reply_markup=admin_panel_markup())


@app.on_message(filters.command("init") & filters.user(ADMIN_ID) & filters.private)
async def init_db(client, message: Message):
    for i in range(1, 5):
        await plans.update_one(
            {"plan_id": i},
            {"$setOnInsert": {"plan_id": i, "text": f"Plan {i}", "price": "0", "codes": []}},
            upsert=True,
        )
    await plans.update_one(
        {"plan_id": "settings"},
        {"$setOnInsert": {"support_id": "@Admin", "channel_id": "", "qr_file_id": ""}},
        upsert=True,
    )
    await message.reply("✅ Database initialised successfully!")


@app.on_message(filters.command("index") & filters.user(ADMIN_ID) & filters.private)
async def index_file(client, message: Message):
    if not message.reply_to_message or len(message.command) < 2:
        return await message.reply("❗ Reply to a file and specify plan number:\n`/index 1`")
    try:
        pid = int(message.command[1])
        if pid not in range(1, 5):
            raise ValueError
    except ValueError:
        return await message.reply("❗ Plan number must be between 1 and 4.")
    await files.insert_one({
        "plan":       pid,
        "chat_id":    message.reply_to_message.chat.id,
        "message_id": message.reply_to_message.id,
    })
    await message.reply(f"✅ File saved to Plan {pid}.")


@app.on_message(filters.command("stats") & filters.user(ADMIN_ID) & filters.private)
async def stats_cmd(client, message: Message):
    total_u    = await users.count_documents({})
    demo_count = await demo_media.count_documents({})
    text = f"📊 **Bot Statistics**\n\n👥 Total Users: `{total_u}`\n🎬 Demo Items: `{demo_count}`\n\n**Content per Plan:**\n"
    for i in range(1, 5):
        count = await files.count_documents({"plan": i})
        text += f"▪️ Plan {i}: `{count}` items\n"
    await message.reply(text)


# ─────────────────────────────────────────────────────────────
# 2. /start
# ─────────────────────────────────────────────────────────────
@app.on_message(filters.command("start") & filters.private)
async def start(client, message: Message):
    user_id = message.from_user.id
    await users.update_one({"user_id": user_id}, {"$set": {"active": True}}, upsert=True)

    if not await is_subscribed(user_id):
        settings     = await plans.find_one({"plan_id": "settings"})
        channel      = (settings or {}).get("channel_id", "")
        channel_link = f"https://t.me/{channel.lstrip('@')}" if channel else "https://t.me"
        btn = [
            [InlineKeyboardButton("📢 Join Channel",              url=channel_link)],
            [InlineKeyboardButton("🔄 I've Joined — Check Again", callback_data="back_home")],
        ]
        return await message.reply(
            "⚠️ Please join our channel first to use this bot!",
            reply_markup=InlineKeyboardMarkup(btn),
        )

    await message.reply(home_text(message.from_user.mention), reply_markup=home_markup())


# ─────────────────────────────────────────────────────────────
# 3. CALLBACK HANDLER
# ─────────────────────────────────────────────────────────────
@app.on_callback_query()
async def cb_handler(client, query):
    data    = query.data
    user_id = query.from_user.id

    if data == "noop":
        return await query.answer()

    # ── Admin callbacks ───────────────────────────────────────
    if user_id == ADMIN_ID:

        if data == "manage_plans":
            btns = [[InlineKeyboardButton(f"📁 Plan {i}", callback_data=f"setup_p_{i}")] for i in range(1, 5)]
            btns.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
            return await query.message.edit_text("Select a plan to manage:", reply_markup=InlineKeyboardMarkup(btns))

        if data == "manage_demo":
            count = await demo_media.count_documents({})
            btns = [
                [InlineKeyboardButton("➕ Add Photo/Video", callback_data="demo_add")],
                [InlineKeyboardButton("🗑 Clear All Demo",  callback_data="demo_clear_confirm")],
                [InlineKeyboardButton("👁 Preview Demo",    callback_data="demo_preview")],
                [InlineKeyboardButton("🔙 Back",            callback_data="admin_back")],
            ]
            return await query.message.edit_text(
                f"🎬 **Demo Management**\n\n📦 Current demo items: `{count}`\n\n"
                "Add photos/videos — they show with spoiler effect.\n"
                "Users navigate with Prev/Next buttons.",
                reply_markup=InlineKeyboardMarkup(btns),
            )

        if data == "demo_add":
            edit_state[user_id] = "demo_add"
            await query.answer()
            return await query.message.reply(
                "📸 Send a **photo** or **video** to add to demo gallery.\n"
                "You can include a caption. Send multiple one by one."
            )

        if data == "demo_clear_confirm":
            return await query.message.edit_text(
                "⚠️ Are you sure you want to delete ALL demo items?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Yes, Clear All", callback_data="demo_clear_do")],
                    [InlineKeyboardButton("❌ Cancel",         callback_data="manage_demo")],
                ])
            )

        if data == "demo_clear_do":
            await demo_media.delete_many({})
            await query.answer("✅ All demo items cleared!", show_alert=True)
            query.data = "manage_demo"
            return await cb_handler(client, query)

        if data == "demo_preview":
            await query.answer()
            await send_demo_item(client, query.message.chat.id, 0)
            return

        # ── Advanced indexer ─────────────────────────────────
        if data == "adv_index_menu":
            btns = [
                [InlineKeyboardButton(f"📁 Index → Plan {i}", callback_data=f"adv_idx_{i}")] for i in range(1, 5)
            ]
            btns.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
            return await query.message.edit_text(
                "🔗 **Advanced Channel/Group Indexer**\n\n"
                "Choose target plan, then send the channel/group link.\n\n"
                "Supported formats:\n"
                "• `https://t.me/+InviteHash` (private)\n"
                "• `@username` (public)\n\n"
                "Bot will auto-join and index all media.",
                reply_markup=InlineKeyboardMarkup(btns),
            )

        if data.startswith("adv_idx_"):
            pid = int(data.split("_")[2])
            edit_state[user_id] = f"adv_idx_{pid}"
            await query.answer()
            return await query.message.reply(
                f"🔗 Send the channel/group link for **Plan {pid}**:\n\n"
                "`https://t.me/+AbCdEfGhIjKl`  ← private\n"
                "`@mychannelname`  ← public"
            )

        if data == "full_stats":
            total_u    = await users.count_documents({})
            demo_count = await demo_media.count_documents({})
            text = f"📊 **Bot Statistics**\n\n👥 Total Users: `{total_u}`\n🎬 Demo Items: `{demo_count}`\n\n**Content per Plan:**\n"
            for i in range(1, 5):
                count = await files.count_documents({"plan": i})
                text += f"▪️ Plan {i}: `{count}` items\n"
            return await query.message.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]),
            )

        if data.startswith("setup_p_"):
            pid           = int(data.split("_")[2])
            p             = await plans.find_one({"plan_id": pid})
            cnt           = await files.count_documents({"plan": pid})
            codes_preview = ", ".join(p.get("codes", [])[:5]) or "None"
            text = (
                f"⚙️ **Plan {pid}**\n\n"
                f"📄 Items: `{cnt}`\n"
                f"💰 Price: ₹`{p['price']}`\n"
                f"📝 Description: {p['text']}\n"
                f"🔑 Codes: {codes_preview}"
            )
            btns = [
                [
                    InlineKeyboardButton("✏️ Edit Text",       callback_data=f"edit_txt_{pid}"),
                    InlineKeyboardButton("💰 Edit Price",      callback_data=f"edit_prc_{pid}"),
                ],
                [
                    InlineKeyboardButton("➕ Add Code",        callback_data=f"add_cd_{pid}"),
                    InlineKeyboardButton("🗑 Clear All Codes", callback_data=f"clr_cd_{pid}"),
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="manage_plans")],
            ]
            return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))

        if data == "bot_settings":
            btns = [
                [
                    InlineKeyboardButton("📸 Update QR Code", callback_data="set_qr"),
                    InlineKeyboardButton("📢 Set Channel",    callback_data="set_ch"),
                ],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
            ]
            return await query.message.edit_text("🛠 **Bot Settings:**", reply_markup=InlineKeyboardMarkup(btns))

        if data == "broadcast_msg":
            edit_state[user_id] = "broadcast"
            await query.answer()
            return await query.message.reply("📢 Send the message (text or photo) to broadcast to all users:")

        if data == "set_qr":
            edit_state[user_id] = "set_qr"
            await query.answer()
            return await query.message.reply("📸 Send the new QR Code image:")

        if data == "set_ch":
            edit_state[user_id] = "set_ch"
            await query.answer()
            return await query.message.reply("📢 Send the channel username (e.g. @mychannel):")

        if data.startswith("edit_txt_"):
            pid = int(data.split("_")[2])
            edit_state[user_id] = f"edit_txt_{pid}"
            await query.answer()
            return await query.message.reply(f"✏️ Send the new description for Plan {pid}:")

        if data.startswith("edit_prc_"):
            pid = int(data.split("_")[2])
            edit_state[user_id] = f"edit_prc_{pid}"
            await query.answer()
            return await query.message.reply(f"💰 Send the new price for Plan {pid}:")

        if data.startswith("add_cd_"):
            pid = int(data.split("_")[2])
            edit_state[user_id] = f"add_cd_{pid}"
            await query.answer()
            return await query.message.reply(f"🔑 Send the new unlock code for Plan {pid}:")

        if data.startswith("clr_cd_"):
            pid = int(data.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$set": {"codes": []}})
            await query.answer("✅ All codes cleared!", show_alert=True)
            query.data = f"setup_p_{pid}"
            return await cb_handler(client, query)

        if data == "admin_back":
            return await query.message.edit_text("👑 **Admin Control Panel**", reply_markup=admin_panel_markup())

    # ── User callbacks ────────────────────────────────────────

    if data == "back_home":
        if not await is_subscribed(user_id):
            return await query.answer("❗ You haven't joined the channel yet!", show_alert=True)
        return await query.message.edit_text(
            home_text(query.from_user.mention),
            reply_markup=home_markup(),
        )

    if data == "support_info":
        await query.answer()
        return await query.message.reply(
            "🆘 Need help? Contact our admin:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Contact Admin", url="https://t.me/boss_0963")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_home")],
            ])
        )

    # ── Demo navigation ───────────────────────────────────────
    if data.startswith("demo_view_"):
        await query.answer()
        index = int(data.split("_")[2])
        await send_demo_item(client, query.message.chat.id, index, old_message=query.message)
        return

    if data == "watch":
        if not await is_subscribed(user_id):
            return await query.answer("❗ Please join our channel first!", show_alert=True)
        btns = [
            [InlineKeyboardButton("🥈 Basic Plan",    callback_data="u_plan_1")],
            [InlineKeyboardButton("🥇 Standard Plan", callback_data="u_plan_2")],
            [InlineKeyboardButton("💎 Premium Plan",  callback_data="u_plan_3")],
            [InlineKeyboardButton("👑 VIP Plan",      callback_data="u_plan_4")],
            [InlineKeyboardButton("🔙 Back",          callback_data="back_home")],
        ]
        return await query.message.edit_text("📋 Select your plan:", reply_markup=InlineKeyboardMarkup(btns))

    if data.startswith("u_plan_"):
        pid = int(data.split("_")[2])
        p   = await plans.find_one({"plan_id": pid})
        text = f"📋 **{p['text']}**\n\n💰 Price: ₹{p['price']}"
        btns = [
            [
                InlineKeyboardButton("💳 Pay Now", callback_data=f"u_pay_{pid}"),
                InlineKeyboardButton("🔓 Unlock",  callback_data=f"u_unl_{pid}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="watch")],
        ]
        return await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))

    if data.startswith("u_pay_"):
        pid = int(data.split("_")[2])
        p   = await plans.find_one({"plan_id": pid})
        s   = await plans.find_one({"plan_id": "settings"})
        if s and s.get("qr_file_id"):
            await query.message.reply_photo(
                s["qr_file_id"],
                caption=(
                    f"💳 **Payment for Plan {pid}**\n\n"
                    f"Amount: ₹{p['price']}\n\n"
                    "Scan the QR code and complete payment.\n"
                    "Then press 🔓 Unlock and enter your code."
                ),
            )
        else:
            await query.answer("❗ QR Code not configured by Admin yet.", show_alert=True)
        return

    if data.startswith("u_unl_"):
        pid = int(data.split("_")[2])
        user_wait[user_id] = pid
        await query.answer()
        return await query.message.reply("🔑 Please send your unlock code:")

    await query.answer()


# ─────────────────────────────────────────────────────────────
# 4. MESSAGE HANDLER
# ─────────────────────────────────────────────────────────────
@app.on_message(
    filters.private
    & ~filters.command(["start", "admin", "init", "index", "stats"])
)
async def handle_all(client, message: Message):
    user_id = message.from_user.id

    # ── Admin state machine ───────────────────────────────────
    if user_id == ADMIN_ID and user_id in edit_state:
        state = edit_state.pop(user_id)

        if state == "set_qr":
            if message.photo:
                await plans.update_one(
                    {"plan_id": "settings"},
                    {"$set": {"qr_file_id": message.photo.file_id}},
                    upsert=True,
                )
                return await message.reply("✅ QR Code updated!")
            return await message.reply("❗ Please send a photo.")

        if state == "set_ch":
            await plans.update_one(
                {"plan_id": "settings"},
                {"$set": {"channel_id": message.text.strip()}},
                upsert=True,
            )
            return await message.reply("✅ Channel ID updated!")

        if state.startswith("edit_txt_"):
            pid = int(state.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$set": {"text": message.text}})
            return await message.reply(f"✅ Plan {pid} description updated!")

        if state.startswith("edit_prc_"):
            pid = int(state.split("_")[2])
            await plans.update_one({"plan_id": pid}, {"$set": {"price": message.text.strip()}})
            return await message.reply(f"✅ Plan {pid} price updated!")

        if state.startswith("add_cd_"):
            pid  = int(state.split("_")[2])
            code = message.text.strip().upper()
            existing = await plans.find_one({"plan_id": pid, "codes": code})
            if existing:
                return await message.reply(f"⚠️ Code `{code}` already exists in Plan {pid}.")
            await plans.update_one({"plan_id": pid}, {"$push": {"codes": code}})
            return await message.reply(f"✅ Code `{code}` added to Plan {pid}.")

        if state == "demo_add":
            if message.photo:
                fid, ftype = message.photo.file_id, "photo"
            elif message.video:
                fid, ftype = message.video.file_id, "video"
            else:
                return await message.reply("❗ Please send a photo or video.")
            caption = message.caption or ""
            await demo_media.insert_one({"file_id": fid, "file_type": ftype, "caption": caption})
            count = await demo_media.count_documents({})
            # Keep state so admin can keep adding
            edit_state[user_id] = "demo_add"
            return await message.reply(
                f"✅ Added! Total demo items: `{count}`\n"
                "Send another to keep adding, or use /admin to exit."
            )

        if state.startswith("adv_idx_"):
            pid  = int(state.split("_")[2])
            link = (message.text or "").strip()
            if not link:
                return await message.reply("❗ Send a valid link or @username.")
            await message.reply(
                f"🔄 Starting index for **Plan {pid}** from:\n`{link}`\n\n"
                "⏳ This runs in the background. You'll get updates every 200 messages."
            )
            asyncio.create_task(index_from_channel(client, message, link, pid))
            return

        if state == "broadcast":
            total   = await users.count_documents({})
            success = 0
            fail    = 0
            async for user in users.find({}):
                try:
                    uid = user["user_id"]
                    if message.photo:
                        await client.send_photo(uid, message.photo.file_id, caption=message.caption or "")
                    elif message.text:
                        await client.send_message(uid, message.text)
                    success += 1
                    await asyncio.sleep(0.05)
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception:
                    fail += 1
            return await message.reply(
                f"📢 **Broadcast Complete**\n\n"
                f"✅ Sent:   `{success}`\n"
                f"❌ Failed: `{fail}`\n"
                f"👥 Total:  `{total}`"
            )

        return

    # ── User unlock code ──────────────────────────────────────
    if user_id in user_wait and message.text:
        pid  = user_wait[user_id]
        code = message.text.strip().upper()
        plan = await plans.find_one({"plan_id": pid, "codes": code})
        if plan:
            del user_wait[user_id]
            await message.reply("✅ Code accepted! Sending your files now…")
            count = 0
            async for f in files.find({"plan": pid}):
                try:
                    await client.copy_message(user_id, f["chat_id"], f["message_id"])
                    count += 1
                    await asyncio.sleep(0.1)
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                    await client.copy_message(user_id, f["chat_id"], f["message_id"])
                    count += 1
                except Exception:
                    pass
            await message.reply(f"✅ Done! {count} file(s) sent.")
        else:
            await message.reply("❌ Invalid code. Please check and try again.")


# ─────────────────────────────────────────────────────────────
# ADVANCED CHANNEL INDEXER
# ─────────────────────────────────────────────────────────────
async def index_from_channel(client, report_msg: Message, link: str, plan_id: int):
    """Auto-join a channel/group and index all media into the given plan."""
    chat = None

    # Step 1: resolve / join
    try:
        if "t.me/+" in link or link.startswith("+"):
            chat = await client.join_chat(link)
        else:
            username = link.lstrip("@").lstrip("https://t.me/")
            try:
                chat = await client.get_chat(f"@{username}")
            except Exception:
                chat = await client.join_chat(f"@{username}")
    except Exception as e:
        return await report_msg.reply(
            f"❌ **Could not join/access chat.**\n\n`{e}`\n\n"
            "• Check the link is correct\n"
            "• Bot must not be banned there\n"
            "• Use full `https://t.me/+...` for private groups"
        )

    chat_id   = chat.id
    chat_title = getattr(chat, "title", str(chat_id))
    await report_msg.reply(f"✅ Joined **{chat_title}**\n📥 Scanning messages…")

    indexed = 0
    scanned = 0

    try:
        async for msg in client.get_chat_history(chat_id):
            scanned += 1

            has_media = any([
                msg.photo, msg.video, msg.document,
                msg.audio, msg.voice, msg.video_note, msg.animation,
            ])

            if has_media:
                exists = await files.find_one({"chat_id": chat_id, "message_id": msg.id})
                if not exists:
                    await files.insert_one({
                        "plan":       plan_id,
                        "chat_id":    chat_id,
                        "message_id": msg.id,
                    })
                    indexed += 1

            if scanned % 200 == 0:
                await report_msg.reply(
                    f"⏳ Scanned `{scanned}` msgs — indexed `{indexed}` new items so far…"
                )

            await asyncio.sleep(0.02)

    except FloodWait as fw:
        await asyncio.sleep(fw.value)
    except Exception as e:
        await report_msg.reply(
            f"⚠️ Stopped early — `{e}`\n"
            f"Indexed so far: `{indexed}` items"
        )
        return

    await report_msg.reply(
        f"🎉 **Indexing Complete!**\n\n"
        f"📢 Source: **{chat_title}**\n"
        f"📁 Plan: **{plan_id}**\n"
        f"✅ New items indexed: `{indexed}`\n"
        f"📨 Total messages scanned: `{scanned}`"
    )


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
async def main():
    await web_server()
    await app.start()
    print("🚀 Bot is live!")
    await idle()
    await app.stop()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
