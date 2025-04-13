import os
import asyncio
import json
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.getenv("BOT_TOKEN", "8053400424:AAFTX80K4pdRicyKJlNKlb2TNFEjiunljTk")
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
        [InlineKeyboardButton("Filter Settings", callback_data="filters")],
        [InlineKeyboardButton("My Alerts", callback_data="alerts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to SciffoniBot! 🚀", reply_markup=reply_markup)

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
            txs = await resp.json()
            for tx in txs[-5:]:
                coin_data = await parse_pumpfun_data({"params": {"result": tx}}, session)
                if coin_data and apply_filters(coin_data):
                    text = format_coin_alert(coin_data)
                    for chat_id in app.subscribed_chats:
                        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
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
                                        await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
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
                        async with session.get(
                            f"https://api.helius.xyz/v0/tokens/metadata?api-key={HELIUS_API_KEY}",
                            params={"mintAccounts": [mint_address] if mint_address else []}
                        ) as resp:
                            metadata = await resp.json()
                            if metadata:
                                metadata = metadata[0]
                                return {
                                    "name": metadata.get("name", "Unknown"),
                                    "symbol": metadata.get("symbol", "UNK"),
                                    "address": mint_address or "unknown",
                                    "liquidity": metadata.get("liquidity", "0 SOL"),
                                    "market_cap": metadata.get("marketCap", "$0"),
                                    "cost": metadata.get("price", 0.0),
                                    "dev_holding": metadata.get("topHolders", [{}])[0].get("percentage", "0%"),
                                    "mint_revoked": metadata.get("mintAuthority", None) is None,
                                    "freeze_revoked": metadata.get("freezeAuthority", None) is None,
                                    "links": metadata.get("socials", []),
                                    "bonding_curve": "linear",
                                    "chart_url": f"https://dexscreener.com/solana/{mint_address or 'unknown'}"
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
        f"<b>{data['name']} ({data['symbol']})</b>\n"
        f"CA: <code>{data['address']}</code>\n"
        f"Liquidity: {data['liquidity']}\n"
        f"Market Cap: {data['market_cap']}\n"
        f"Cost: {data['cost']} SOL\n"
        f"Dev Holding: {data['dev_holding']}\n"
        f"Bonding Curve: {data['bonding_curve']}\n"
        f"Mint Revoked: {'✅' if data['mint_revoked'] else '❌'}\n"
        f"Freeze Revoked: {'✅' if data['freeze_revoked'] else '❌'}\n"
        f"Links: {' | '.join(data['links']) if data['links'] else 'None'}\n"
        f"<a href='{data['chart_url']}'>Chart</a>"
    )

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.subscribed_chats = set()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    async def set_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        app.subscribed_chats.add(chat_id)
        await context.bot.send_message(chat_id=chat_id, text="Registered for alerts! 📢")

    app.add_handler(CommandHandler("register", set_chat_id))

    print("SciffoniBot running...")
    # Create a task for detect_meme_coins using asyncio
    loop = asyncio.get_event_loop()
    loop.create_task(detect_meme_coins(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
