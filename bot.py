import os
import asyncio
import json
import aiohttp
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

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
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

FILTERS = {
    "min_cost": 0.0000000023,
    "max_cost": 0.006,
    "require_mint_revoked": True,
    "require_freeze_revoked": True,
    "require_links": True,
    "pools": ["pumpfun"]
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "filters":
        await query.edit_message_text("Filter settings coming soon! 🛠️")
    elif query.data == "alerts":
        await query.edit_message_text("You will receive meme coin alerts! 📡")

async def check_missed_tokens(app, session):
    try:
        async with session.get(
            f"https://api.helius.xyz/v0/transactions?api-key={HELIUS_API_KEY}",
            params={"programId": PUMP_PROGRAM_ID, "type": "CREATE"}
        ) as resp:
            if resp.status != 200:
                print(f"Helius API error: {resp.status} - {await resp.text()}")
                return
            txs = await resp.json()
            for tx in txs[-5:]:
                coin_data = await parse_pumpfun_data({"params": {"result": tx}}, session)
                if coin_data and apply_filters(coin_data):
                    text = format_coin_alert(coin_data)
                    for chat_id in app.subscribed_chats:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            parse_mode="HTML"
                        )
                        print(f"Missed token alert sent to chat {chat_id}: {text}")
    except Exception as e:
        print(f"Error checking missed tokens: {e}")

async def detect_meme_coins(app):
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await check_missed_tokens(app, session)
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
                                continue
                            coin_data = await parse_pumpfun_data(data, session)
                            if coin_data and apply_filters(coin_data):
                                text = format_coin_alert(coin_data)
                                for chat_id in app.subscribed_chats:
                                    try:
                                        await app.bot.send_message(
                                            chat_id=chat_id,
                                            text=text,
                                            parse_mode="HTML"
                                        )
                                        print(f"Alert sent to chat {chat_id}: {text}")
                                    except Exception as e:
                                        print(f"Error sending to {chat_id}: {e}")
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
                        # Fallback mint_address if not found
                        if not mint_address:
                            mint_address = "unknown_mint_address"
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
                                return {
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
        return None
    except Exception as e:
        print(f"Error parsing data: {e}")
        return None

def apply_filters(coin_data):
    if not coin_data:
        return False
    if coin_data["cost"] < FILTERS["min_cost"] or coin_data["cost"] > FILTERS["max_cost"]:
        return False
    if FILTERS["require_mint_revoked"] and not coin_data["mint_revoked"]:
        return False
    if FILTERS["require_freeze_revoked"] and not coin_data["freeze_revoked"]:
        return False
    if FILTERS["require_links"] and not coin_data["links"]:
        return False
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
    
    async def set_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        app.subscribed_chats.add(chat_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text="Registered for alerts! 📢\n\nYou will now receive notifications for new meme coins on Pump.fun! 🚀",
            parse_mode="HTML"
        )

    app.add_handler(CommandHandler("register", set_chat_id))
    
    print("SciffoniBot running...")
    # Start meme coin detection in a background task
    asyncio.create_task(detect_meme_coins(app))
    # Start the Telegram bot
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    # Keep the bot running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(run_bot())
