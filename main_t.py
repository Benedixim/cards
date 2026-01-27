import asyncio
import sys
import logging

from aiogram import Dispatcher, Bot, html
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import TOKEN
from app.handlers.card import router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()



async def main() -> None:
    bot = Bot(token = TOKEN, default = DefaultBotProperties(parse_mode = ParseMode.HTML))
    dp.include_router(router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())