import asyncio
import logging
import os

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from config import TOKEN, PROXY_RU
from app.handlers.card import router

logging.basicConfig(level=logging.INFO)


# ---------- KeepAlive ----------
async def keep_alive():
    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    if not hostname:
        logging.warning("-! KeepAlive disabled (local run)")
        return

    url = f"https://{hostname}/health"
    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(url) as resp:
                    logging.info(f"[KeepAlive] Ping → {resp.status}")
            except Exception as e:
                logging.error(f"[KeepAlive] Error: {e}")

            await asyncio.sleep(240)  # 4 минуты



async def health(request):
    return web.json_response({"status": "ok"})



async def on_startup(app: web.Application):
    bot: Bot = app["bot"]

    hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")

    if hostname:
        webhook_url = f"https://{hostname}/webhook"
        await bot.set_webhook(webhook_url)
        logging.info(f"✅ Webhook set: {webhook_url}")
    else:
        logging.warning("-! RENDER_EXTERNAL_HOSTNAME not set — webhook skipped")

    app["keep_alive_task"] = asyncio.create_task(keep_alive())


async def on_shutdown(app: web.Application):
    bot: Bot = app["bot"]

    try:
        await bot.delete_webhook()
    except Exception:
        pass

    task = app.get("keep_alive_task")
    if task:
        task.cancel()

    logging.info("!!! Shutdown completed")


async def main():
    bot = Bot(
        token=TOKEN,
        proxy=PROXY_RU,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()
    dp.include_router(router)

    app = web.Application()
    app["bot"] = bot


    app.router.add_get("/", health)
    app.router.add_get("/health", health)


    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_in_background=True,
    ).register(app, path="/webhook")

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logging.info(f"🚀 Server started on port {port}")

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
