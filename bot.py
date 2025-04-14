import os
import asyncio
import json
import aiohttp
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# Dummy HTTP Server to satisfy Render's port binding requirement
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"SciffoniBot is running!")

def run_dummy_server():
    server = HTTPServer(("", 8000), DummyHandler)
    server.serve_forever()

# Start the dummy server in a separate thread
threading.Thread(target=run_dummy_server, daemon=True).start()

# Bot token (already updated in Render environment)
BOT_TOKEN = os.getenv("BOT_TOKEN")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "b0b224fa-0850-4e15-8068-e48184260227")
HELIUS_WS_URL = f"wss://ws-mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"  # Confirmed Pump.fun program ID

# Default filters (user-specific filters will override these)
DEFAULT_FILTERS = {
    "min_cost": 0.0000000023,
    "max_cost": 0.006,
    "require_mint_revoked": True,
    "require_freeze_revoked": True,
    "require_links": True,
    "pools": ["pumpfun"]
}

# Store user-specific filters (in-memory for now)
USER_FILTERS = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("Received /start command")
    keyboard = [
        [InlineKeyboardButton("Filter Settings ⚙️", callback_data="filters")],
        [InlineKeyboardButton("My Alerts 📩", callback_data="alerts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to SciffoniBot! 🚀\n\nI will notify you about new meme coins on Pump.fun that match your filters! 🎉",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    print("Sent welcome message with buttons")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    if query.data == "filters":
        print("Filter Settings button clicked")
        keyboard = [
            [InlineKeyboardButton("Set Min Cost 💸", callback_data="set_min_cost")],
            [InlineKeyboardButton("Set Max Cost 💰", callback_data="set_max_cost")],
            [InlineKeyboardButton("Toggle Mint Revoked ✅", callback_data="toggle_mint_revoked")],
            [InlineKeyboardButton("Toggle Freeze Revoked ❄️", callback_data="toggle_freeze_revoked")],
            [InlineKeyboardButton("Toggle Require Links 🔗", callback_data="toggle_require_links")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS)
        filter_summary = (
            f"Current Filter Settings:\n\n"
            f"💸 Min Cost: {user_filters['min_cost']} SOL\n"
            f"💰 Max Cost: {user_filters['max_cost']} SOL\n"
            f"✅ Mint Revoked: {'Yes' if user_filters['require_mint_revoked'] else 'No'}\n"
            f"❄️ Freeze Revoked: {'Yes' if user_filters['require_freeze_revoked'] else 'No'}\n"
            f"🔗 Require Links: {'Yes' if user_filters['require_links'] else 'No'}\n\n"
            f"Select an option to update your filters:"
        )
        await query.edit_message_text(filter_summary, reply_markup=reply_markup, parse_mode="HTML")
    elif query.data == "alerts":
        print("My Alerts button clicked")
        await query.edit_message_text("You will receive meme coin alerts! 📡")
    elif query.data.startswith("set_"):
        # Handle filter setting inputs
        setting = query.data.split("_")[1]  # e.g., "min_cost" or "max_cost"
        await query.edit_message_text(f"Please enter the {setting.replace('_', ' ')} (in SOL):")
        context.user_data["setting"] = setting
    elif query.data.startswith("toggle_"):
        # Handle toggle settings
        setting = query.data.split("_")[1] + "_" + query.data.split("_")[2]  # e.g., "mint_revoked"
        user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS.copy())
        user_filters[f"require_{setting}"] = not user_filters.get(f"require_{setting}", DEFAULT_FILTERS[f"require_{setting}"])
        USER_FILTERS[chat_id] = user_filters
        print(f"Updated {setting} for chat {chat_id}: {user_filters[f'require_{setting}']}")
        # Show updated filters
        keyboard = [
            [InlineKeyboardButton("Set Min Cost 💸", callback_data="set_min_cost")],
            [InlineKeyboardButton("Set Max Cost 💰", callback_data="set_max_cost")],
            [InlineKeyboardButton("Toggle Mint Revoked ✅", callback_data="toggle_mint_revoked")],
            [InlineKeyboardButton("Toggle Freeze Revoked ❄️", callback_data="toggle_freeze_revoked")],
            [InlineKeyboardButton("Toggle Require Links 🔗", callback_data="toggle_require_links")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        filter_summary = (
            f"Current Filter Settings:\n\n"
            f"💸 Min Cost: {user_filters['min_cost']} SOL\n"
            f"💰 Max Cost: {user_filters['max_cost']} SOL\n"
            f"✅ Mint Revoked: {'Yes' if user_filters['require_mint_revoked'] else 'No'}\n"
            f"❄️ Freeze Revoked: {'Yes' if user_filters['require_freeze_revoked'] else 'No'}\n"
            f"🔗 Require Links: {'Yes' if user_filters['require_links'] else 'No'}\n\n"
            f"Select an option to update your filters:"
        )
        await query.edit_message_text(filter_summary, reply_markup=reply_markup, parse_mode="HTML")

async def handle_filter_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if "setting" not in context.user_data:
        return
    setting = context.user_data["setting"]
    try:
        value = float(update.message.text)
        user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS.copy())
        user_filters[setting] = value
        USER_FILTERS[chat_id] = user_filters
        print(f"Updated {setting} for chat {chat_id}: {value}")
        await update.message.reply_text(f"{setting.replace('_', ' ').title()} updated to {value} SOL!")
    except ValueError:
        await update.message.reply_text("Please enter a valid number (in SOL).")
    finally:
        # Show updated filters
        keyboard = [
            [InlineKeyboardButton("Set Min Cost 💸", callback_data="set_min_cost")],
            [InlineKeyboardButton("Set Max Cost 💰", callback_data="set_max_cost")],
            [InlineKeyboardButton("Toggle Mint Revoked ✅", callback_data="toggle_mint_revoked")],
            [InlineKeyboardButton("Toggle Freeze Revoked ❄️", callback_data="toggle_freeze_revoked")],
            [InlineKeyboardButton("Toggle Require Links 🔗", callback_data="toggle_require_links")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS)
        filter_summary = (
            f"Current Filter Settings:\n\n"
            f"💸 Min Cost: {user_filters['min_cost']} SOL\n"
            f"💰 Max Cost: {user_filters['max_cost']} SOL\n"
            f"✅ Mint Revoked: {'Yes' if user_filters['require_mint_revoked'] else 'No'}\n"
            f"❄️ Freeze Revoked: {'Yes' if user_filters['require_freeze_revoked'] else 'No'}\n"
            f"🔗 Require Links: {'Yes' if user_filters['require_links'] else 'No'}\n\n"
            f"Select an option to update your filters:"
        )
        await update.message.reply_text(filter_summary, reply_markup=reply_markup, parse_mode="HTML")
        del context.user_data["setting"]

async def check_missed_tokens(app, session):
    try:
        print("Checking missed tokens via Helius API...")
        async with session.get(
            f"https://api.helius.xyz/v0/transactions?api-key={HELIUS_API_KEY}",
            params={"programId": PUMP_PROGRAM_ID, "type": "CREATE"}
        ) as resp:
            if resp.status != 200:
                print(f"Helius API error: {resp.status} - {await resp.text()}")
                return
            txs = await resp.json()
            print(f"Found {len(txs)} transactions in missed tokens check.")
            for tx in txs[-5:]:
                coin_data = await parse_pumpfun_data({"params": {"result": tx}}, session)
                if coin_data:
                    for chat_id in app.subscribed_chats:
                        user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS)
                        if apply_filters(coin_data, user_filters):
                            text = format_coin_alert(coin_data)
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=text,
                                parse_mode="HTML"
                            )
                            print(f"Missed token alert sent to chat {chat_id}: {text}")
                        else:
                            print(f"Coin rejected for chat {chat_id} due to filters.")
                else:
                    print("No coin data matched filters in missed tokens check.")
    except Exception as e:
        print(f"Error checking missed tokens: {e}")

async def detect_meme_coins(app):
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await check_missed_tokens(app, session)
                print(f"Connecting to WebSocket: {HELIUS_WS_URL}")
                async with session.ws_connect(HELIUS_WS_URL, timeout=30) as ws:
                    subscription = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [{"mentions": [PUMP_PROGRAM_ID]}, {"commitment": "confirmed"}]
                    }
                    await ws.send_json(subscription)
                    print("WebSocket subscription sent, waiting for messages...")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if "result" in data:
                                print("Received subscription confirmation.")
                                continue
                            print("Received WebSocket message, parsing data...")
                            coin_data = await parse_pumpfun_data(data, session)
                            if coin_data:
                                for chat_id in app.subscribed_chats:
                                    user_filters = USER_FILTERS.get(chat_id, DEFAULT_FILTERS)
                                    if apply_filters(coin_data, user_filters):
                                        text = format_coin_alert(coin_data)
                                        try:
                                            await app.bot.send_message(
                                                chat_id=chat_id,
                                                text=text,
                                                parse_mode="HTML"
                                            )
                                            print(f"Alert sent to chat {chat_id}: {text}")
                                        except Exception as e:
                                            print(f"Error sending to {chat_id}: {e}")
                                    else:
                                        print(f"Coin rejected for chat {chat_id} due to filters.")
                            else:
                                print("No coin data matched filters in WebSocket message.")
                        await asyncio.sleep(0.1)
        except Exception as e:
            print(f"WebSocket error: {e}. Retrying in 10 seconds...")
            await asyncio.sleep(10)

async def parse_pumpfun_data(data, session):
    try:
        logs = data.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
        for log in logs:
            if "Instruction: Create" in log:
                mint_address = None
                for subsequent_log in logs[logs.index(log):]:
                    if "Program data:" in subsequent_log:
                        mint_address = subsequent_log.split()[-1] if not mint_address else mint_address
                        if not mint_address:
                            mint_address = "unknown_mint_address"
                        print(f"Fetching metadata for mint address: {mint_address}")
                        async with session.get(
                            f"https://api.helius.xyz/v0/tokens/metadata?api-key={HELIUS_API_KEY}",
                            params={"mintAccounts": [mint_address]}
                        ) as resp:
                            if resp.status != 200:
                                print(f"Helius metadata API error: {resp.status} - {await resp.text()}")
                                return None
                            metadata = await resp.json()
                            if metadata and isinstance(metadata, list) and len(metadata) > 0:
                                metadata = metadata[0]
                                coin_data = {
                                    "name": metadata.get("name", "Unknown"),
                                    "symbol": metadata.get("symbol", "UNK"),
                                    "address": mint_address,
                                    "liquidity": metadata.get("liquidity", "0 SOL"),
                                    "market_cap": metadata.get("marketCap", "$0"),
                                    "cost": metadata.get("price", 0.0),
                                    "dev_holding": metadata.get("topHolders", [{}])[0].get("percentage", "0%"),
                                    "mint_revoked": metadata.get("mintAuthority", None) is None,
                                    "freeze_revoked": metadata.get("freezeAuthority", None) is None,
                                    "links": metadata.get("socials", []),
                                    "bonding_curve": "linear",
                                    "chart_url": f"https://dexscreener.com/solana/{mint_address}"
                                }
                                print(f"Parsed coin data: {coin_data}")
                                return coin_data
        print("No relevant logs found for coin creation.")
        return None
    except Exception as e:
        print(f"Error parsing data: {e}")
        return None

def apply_filters(coin_data, filters):
    if not coin_data:
        return False
    if coin_data["cost"] < filters["min_cost"] or coin_data["cost"] > filters["max_cost"]:
        print(f"Coin rejected: Cost {coin_data['cost']} outside range {filters['min_cost']}-{filters['max_cost']}")
        return False
    if filters["require_mint_revoked"] and not coin_data["mint_revoked"]:
        print("Coin rejected: Mint not revoked")
        return False
    if filters["require_freeze_revoked"] and not coin_data["freeze_revoked"]:
        print("Coin rejected: Freeze not revoked")
        return False
    if filters["require_links"] and not coin_data["links"]:
        print("Coin rejected: No links provided")
        return False
    print("Coin passed all filters!")
    return True

def format_coin_alert(data):
    return (
        f"🎉 <b>New Meme Coin Alert: {data['name']} ({data['symbol']})</b> 🎉\n\n"
        f"📍 <b>CA:</b> <code>{data['address']}</code>\n"
        f"💧 <b>Liquidity:</b> {data['liquidity']}\n"
        f"📈 <b>Market Cap:</b> {data['market_cap']}\n"
        f"💸 <b>Cost:</b> {data['cost']} SOL\n"
        f"👨‍💻 <b>Dev Holding:</b> {data['dev_holding']}\n"
        f"📉 <b>Bonding Curve:</b> {data['bonding_curve']}\n"
        f"✅ <b>Mint Revoked:</b> {'Yes' if data['mint_revoked'] else 'No'}\n"
        f"❄️ <b>Freeze Revoked:</b> {'Yes' if data['freeze_revoked'] else 'No'}\n"
        f"🔗 <b>Links:</b> {' | '.join(data['links']) if data['links'] else 'None'}\n"
        f"📊 <a href='{data['chart_url']}'>View Chart on Dexscreener</a>"
    )

async def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.subscribed_chats = set()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_filter_input))
    
    async def set_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        app.subscribed_chats.add(chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Registered for alerts! 📢\n\nYou will now receive notifications for new meme coins on Pump.fun! 🚀",
            parse_mode="HTML"
        )
        print(f"User registered for alerts, chat ID: {chat_id}")

    app.add_handler(CommandHandler("register", set_chat_id))
    
    print("SciffoniBot running...")
    # Start meme coin detection in a background task
    asyncio.create_task(detect_meme_coins(app))
    # Start the Telegram bot with polling
    await app.initialize()
    await app.start()
    try:
        await app.updater.start_polling(drop_pending_updates=True)  # Drop pending updates to avoid conflicts
        # Keep the bot running
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(run_bot())
