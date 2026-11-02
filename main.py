import asyncio
import os
import sys
import traceback

import database as db
from config import TOKEN
from handlers import bot

async def start_health_server():
    try:
        port = int(os.environ.get("PORT") or 0)
    except ValueError:
        port = 0
    if not port:
        return None

    async def handle_client(reader, writer):
        try:
            await reader.read(4096)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 2\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b"OK"
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    print(f"Health-check сервер слушает порт {port}", flush=True)
    return server

async def check_token():
    try:
        await bot.api.messages.get_conversations(count=1)
    except Exception as error:
        print(
            "ОШИБКА: токен сообщества не работает.\n"
            f"  {type(error).__name__}: {error}\n"
            "Проверь переменную окружения VK_TOKEN и права ключа доступа "
            "(Настройки сообщества -> Работа с API -> ключ доступа, права «Сообщения»).",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)

async def run_bot():
    delay = 5
    while True:
        try:
            await bot.run_polling()
            print("Polling неожиданно завершился", flush=True)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception:
            traceback.print_exc()
        print(f"Перезапуск polling через {delay} сек...", flush=True)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)

async def main():
    if not TOKEN:
        print("ОШИБКА: не задан токен сообщества.\nСоздай переменную окружения VK_TOKEN.", file=sys.stderr, flush=True)
        sys.exit(1)

    await db.init_db()
    await start_health_server()
    await check_token()

    print("Бот запущен в режиме LongPoll", flush=True)
    await run_bot()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен", flush=True)
