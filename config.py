import os
from pathlib import Path

def _load_dotenv(path: str | None = None) -> None:
    file = Path(path) if path else Path(__file__).resolve().parent / ".env"
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_dotenv()

def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"Переменная окружения {name} должна быть целым числом, получено: {raw!r}")

TOKEN = (os.environ.get("VK_TOKEN") or "").strip()
GROUP_ID = _int_env("VK_GROUP_ID", 242833873)
DB_PATH = (os.environ.get("DB_PATH") or "bot.db").strip()
