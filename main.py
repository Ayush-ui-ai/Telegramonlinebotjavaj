import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, ContextTypes
)
from telethon.errors import SessionPasswordNeededError
from telethon import TelegramClient
from telethon.sessions import StringSession
import database as db
from account_manager import AccountManager

# ---------- CONFIG ----------
BOT_TOKEN = "8603582567:AAE5VvKblyMRbHhsCD1s1MtaGOonGjL1uUk"   # CHANGE
API_ID = 33534748                  # CHANGE
API_HASH = "0b37ba2e1964b43999dc834ccf9b1a1b"      # CHANGE
OWNER_ID = 6871652449           # CHANGE

account_manager = AccountManager(API_ID, API_HASH)

# Conversation states
LINK, DELAY, COUNT = range(3)
PHONE, CODE, PASSWORD = range(3, 6)
ENGAGE_CHOICE, ENGAGE_LINK, ENGAGE_MSG_ID, ENGAGE_EMOJI = range(6, 10)

# ---------- TASK QUEUE (only one join at a time) ----------
task_queue = asyncio.Queue()
is_processing = False

# ---------- AUTHORIZATION (fixes callback timeout) ----------
def authorized_only(func):
    async def wrapper(update, context):
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except:
                pass
        uid = update.effective_user.id
        if await db.is_authorized(uid):
            return await func(update, context)
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text("⛔ Unauthorized.")
            except:
                pass
        else:
            await update.message.reply_text("⛔ Unauthorized.")
        return
    return wrapper

def owner_only(func):
    async def wrapper(update, context):
        uid = update.effective_user.id
        owner = await db.get_owner()
        if uid == owner:
            return await func(update, context)
        await update.message.reply_text("⛔ Owner only.")
    return wrapper

# ---------- HELPERS ----------
async def send_long_message(target, text):
    if not text:
        return
    if hasattr(target, 'message'):
        reply = target.message.reply_text
    elif hasattr(target, 'reply_text'):
        reply = target.reply_text
    else:
        return
    for i in range(0, len(text), 4000):
        await reply(text[i:i+4000])

async def update_progress_message(message, current, total, success, failed):
    percent = int((current / total) * 100) if total else 0
    bar_length = 20
    filled = int(bar_length * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_length - filled)
    new_text = (
        f"🔄 **Processing Task...**\n"
        f"`[{bar}] {percent}%`\n\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}\n"
        f"⚡ Accounts are being forced Online.\n"
        f"📌 Progress: {current}/{total}"
    )
    if message.text.strip() != new_text.strip():
        try:
            await message.edit_text(new_text, parse_mode="Markdown")
        except Exception:
            pass

async def process_queue():
    global is_processing
    is_processing = True
    while not task_queue.empty():
        update, link, delay, count, original_msg = await task_queue.get()
        try:
            progress_msg = await original_msg.reply_text("🔄 Starting join requests...")
            success_count = 0
            failed_count = 0
            current = 0

            async def progress_callback(cur, total, succ, fail):
                nonlocal current, success_count, failed_count
                current = cur
                success_count = succ
                failed_count = fail
                await update_progress_message(progress_msg, current, total, success_count, failed_count)

            result_list, success_phones = await account_manager.join_and_go_online(
                link, delay, count, progress_callback
            )
            full_text = "\n".join(result_list)
            await send_long_message(update, full_text)
        except Exception as e:
            try:
                await update.message.reply_text(f"❌ Task failed: {str(e)}")
            except:
                pass
    is_processing = False

# ---------- MAIN MENU ----------
@authorized_only
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    owner = await db.get_owner()
    is_owner = (uid == owner)
    active = await account_manager.get_active_sessions()
    admins = await db.list_admins()
    admin_count = len(admins)

    status = (
        "🤖 **AUTO REQUEST TOOLS**\n\n"
        "**Manager Bot Pro**\n"
        f"• Active Sessions: `{active}`\n"
        f"• Database: `Connected`\n"
        f"• Admins: `{admin_count}`\n"
        "• Developer: `SYNAX NXT`\n"
    )
    if is_owner:
        admin_list = "\n".join([f"• `{aid}` ({uname or '?'})" for aid, uname in admins])
        status += f"\n👑 **Owner Panel**\n{admin_list}\n/addadmin <id> – /rmadmin <id>"

    keyboard = [
        [InlineKeyboardButton("➕ Add New Account", callback_data="add_account")],
        [
            InlineKeyboardButton("🔗 Joiner Mode", callback_data="joiner_mode"),
            InlineKeyboardButton("🚪 Leaver Mode", callback_data="leaver_mode")
        ],
        [
            InlineKeyboardButton("📋 List Accounts", callback_data="list_accounts"),
            InlineKeyboardButton("📜 Activity Log", callback_data="activity_log")
        ],
        [
            InlineKeyboardButton("💬 Engagement", callback_data="engagement"),
            InlineKeyboardButton("⚡ Start Mass", callback_data="start_mass")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(status, reply_markup=reply_markup, parse_mode="Markdown")

# ---------- BUTTON HANDLER ----------
@authorized_only
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "add_account":
        await query.message.reply_text("Send phone number (e.g., +1234567890):")
        return PHONE
    elif data == "joiner_mode":
        await query.message.reply_text(
            "**Step 1: Send the Channel/Group Link**\n"
            "Example: `https://t.me/+abc123` or `@username`",
            parse_mode="Markdown"
        )
        return LINK
    elif data == "leaver_mode":
        await query.message.reply_text(
            "Send command:\n"
            "• `/leave <channel_link>` – leave a specific channel\n"
            "• `/leave` – leave **all** channels (every channel/group)",
            parse_mode="Markdown"
        )
        return
    elif data == "list_accounts":
        accs = await account_manager.get_accounts_list()
        txt = "📱 Logged-in accounts:\n" + "\n".join(accs) if accs else "No accounts."
        await send_long_message(query.message, txt)
    elif data == "activity_log":
        logs = await db.get_activity_log(10)
        if logs:
            txt = "📜 Last 10 activities:\n" + "\n".join(f"{ts} | {action} | {target}" for ts, action, target, _ in logs)
        else:
            txt = "No activity yet."
        await send_long_message(query.message, txt)
    elif data == "engagement":
        keyboard = [
            [InlineKeyboardButton("❤️ React to Post", callback_data="engage_react")],
            [InlineKeyboardButton("📡 Join Live Stream", callback_data="engage_live")]
        ]
        await query.message.reply_text(
            "**Engagement Options**\nChoose an action:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return
    elif data == "start_mass":
        await query.message.reply_text(
            "⚡ Use **Joiner Mode** (the button above) to start a step‑by‑step mass join.\n"
            "You'll be asked for link, delay, and number of accounts."
        )
    return

# ---------- ENGAGEMENT SUBMENU ----------
@authorized_only
async def engagement_submenu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data == "engage_react":
        context.user_data['engage_action'] = 'react'
        await query.message.reply_text(
            "**React to a Post**\n"
            "Send the channel link (or username):\nExample: `https://t.me/somechannel` or `@somechannel`"
        )
        return ENGAGE_LINK
    elif data == "engage_live":
        context.user_data['engage_action'] = 'live'
        await query.message.reply_text(
            "**Join Live Stream**\n"
            "Send the live stream link (or channel username where the stream is happening):\nExample: `https://t.me/somechannel`"
        )
        return ENGAGE_LINK
    return

@authorized_only
async def engage_get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['engage_link'] = update.message.text.strip()
    action = context.user_data.get('engage_action')
    if action == 'react':
        await update.message.reply_text(
            "Send the **message ID** of the post to react to.\n"
            "Tip: Forward the post to `@getidsbot` to get the message ID."
        )
        return ENGAGE_MSG_ID
    elif action == 'live':
        link = context.user_data['engage_link']
        await update.message.reply_text(f"⏳ Joining live stream {link} for all accounts...")
        results = await account_manager.join_live_stream(link)
        full = "\n".join(results)
        await send_long_message(update, full)
        return ConversationHandler.END
    return ConversationHandler.END

@authorized_only
async def engage_get_msg_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg_id = int(update.message.text.strip())
        context.user_data['engage_msg_id'] = msg_id
    except:
        await update.message.reply_text("❌ Invalid message ID. Please enter a number.")
        return ENGAGE_MSG_ID
    await update.message.reply_text(
        "Send the **emoji** to react with (e.g., 👍, ❤️, 🎉).\n"
        "Default is 👍 if not specified."
    )
    return ENGAGE_EMOJI

@authorized_only
async def engage_get_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip()
    if not emoji:
        emoji = "👍"
    context.user_data['engage_emoji'] = emoji
    link = context.user_data['engage_link']
    msg_id = context.user_data['engage_msg_id']
    await update.message.reply_text(f"⏳ Reacting to post {msg_id} in {link} with {emoji}...")
    results = await account_manager.react_to_post(link, msg_id, emoji)
    full = "\n".join(results)
    await send_long_message(update, full)
    return ConversationHandler.END

# ---------- JOINER MODE CONVERSATION ----------
@authorized_only
async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['link'] = update.message.text.strip()
    await update.message.reply_text(
        "**Step 2: Set Delay**\nEnter delay in seconds between each join request (e.g., 10 or 30):",
        parse_mode="Markdown"
    )
    return DELAY

@authorized_only
async def get_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        delay = int(update.message.text.strip())
        if delay < 0:
            raise ValueError
        context.user_data['delay'] = delay
    except:
        await update.message.reply_text("❌ Invalid delay. Please enter a positive number (e.g., 10).")
        return DELAY
    await update.message.reply_text(
        "**Step 3: Custom Amount**\nEnter the number of accounts to use:",
        parse_mode="Markdown"
    )
    return COUNT

@authorized_only
async def get_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            raise ValueError
        context.user_data['count'] = count
    except:
        await update.message.reply_text("❌ Invalid count. Please enter a positive integer.")
        return COUNT

    link = context.user_data['link']
    delay = context.user_data['delay']
    count = context.user_data['count']

    total_available = await account_manager.get_active_sessions()
    if count > total_available:
        await update.message.reply_text(f"⚠️ Only {total_available} accounts available. Using {total_available}.")
        count = total_available

    # Queue the task
    await task_queue.put((update, link, delay, count, update.message))
    global is_processing
    if not is_processing:
        asyncio.create_task(process_queue())

    await update.message.reply_text(
        "✅ **Task queued!**\n"
        "I'll start processing soon. You will receive the results here when done.\n"
        "Other users can still use the bot normally.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_joiner(update: Update, context):
    await update.message.reply_text("❌ Operation cancelled.")
    return ConversationHandler.END

# ---------- ADD ACCOUNT CONVERSATION ----------
@authorized_only
async def add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data['phone'] = phone
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        await client.send_code_request(phone)
        context.user_data['temp_client'] = client
        await update.message.reply_text("Verification code sent. Enter it:")
        return CODE
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return ConversationHandler.END

@authorized_only
async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    client = context.user_data['temp_client']
    phone = context.user_data['phone']
    try:
        await client.sign_in(phone, code)
        session_str = client.session.save()
        await account_manager.add_new_account(phone, session_str)
        await update.message.reply_text(f"✅ Account {phone} added. Now idle.")
        await client.disconnect()
        return ConversationHandler.END
    except SessionPasswordNeededError:
        await update.message.reply_text("2FA enabled. Enter your password:")
        return PASSWORD
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return ConversationHandler.END

@authorized_only
async def add_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pwd = update.message.text.strip()
    client = context.user_data['temp_client']
    phone = context.user_data['phone']
    try:
        await client.sign_in(password=pwd)
        session_str = client.session.save()
        await account_manager.add_new_account(phone, session_str)
        await update.message.reply_text(f"✅ Account {phone} added (2FA).")
        await client.disconnect()
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"2FA error: {e}")
        return ConversationHandler.END

async def cancel(update: Update, context):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ---------- LEAVE COMMANDS ----------
@authorized_only
async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        target = context.args[0]
        await update.message.reply_text(f"⏳ Leaving {target}...")
        results = await account_manager.leave_specific(target)
    else:
        await update.message.reply_text("⏳ Leaving **ALL** channels and groups. This may take a while...")
        results = await account_manager.leave_all_channels()
    full_text = "\n".join(results)
    await send_long_message(update, full_text)

# ---------- OWNER COMMANDS ----------
@owner_only
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id> [username]")
        return
    uid = int(context.args[0])
    uname = context.args[1] if len(context.args) > 1 else None
    await db.add_admin(uid, uname)
    await update.message.reply_text(f"Admin {uid} added.")

@owner_only
async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /rmadmin <user_id>")
        return
    uid = int(context.args[0])
    await db.remove_admin(uid)
    await update.message.reply_text(f"Admin {uid} removed.")

# ---------- START ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await db.get_owner():
        await db.set_owner(OWNER_ID)
        await db.add_admin(OWNER_ID, "Owner")
    if await db.is_authorized(update.effective_user.id):
        await main_menu(update, context)
    else:
        await update.message.reply_text("⛔ Unauthorized. Only owner/admins can use this bot.")

# ---------- MAIN ----------
async def main():
    await db.init_db()
    await account_manager.start_all_accounts()
    app = Application.builder().token(BOT_TOKEN).build()

    join_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^joiner_mode$")],
        states={
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_link)],
            DELAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delay)],
            COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel_joiner)],
    )
    add_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^add_account$")],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_code)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    engage_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(engagement_submenu, pattern="^engage_")],
        states={
            ENGAGE_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, engage_get_link)],
            ENGAGE_MSG_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, engage_get_msg_id)],
            ENGAGE_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, engage_get_emoji)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(join_conv)
    app.add_handler(add_conv)
    app.add_handler(engage_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("leave", leave_command))
    app.add_handler(CommandHandler("addadmin", add_admin_command))
    app.add_handler(CommandHandler("rmadmin", remove_admin_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(engagement_submenu, pattern="^engage_"))

    print("🤖 Bot running...")
    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()
    asyncio.get_event_loop().run_until_complete(main())
