"""
Запуск бота в тестовой среде (вызывается из start_test.bat).

1. Создаёт .venv, если его нет
2. Ставит библиотеки из requirements.txt
3. Если нет .env.test — копирует из .env.test.example и открывает в Блокноте
4. Запускает bot.py с ENV_FILE=.env.test
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
ENV_TEST = ROOT / ".env.test"
ENV_TEST_EXAMPLE = ROOT / ".env.test.example"


def run(cmd: list[str], **kwargs) -> None:
    result = subprocess.run(cmd, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        raise SystemExit(
            "\nЧто-то пошло не так — скопируй текст ошибки выше и пришли его."
        )


def main() -> None:
    if not VENV_PY.exists():
        print("[1/3] Создаю виртуальное окружение .venv ...")
        run([sys.executable, "-m", "venv", str(ROOT / ".venv")])
    else:
        print("[1/3] Окружение .venv уже есть")

    print("[2/3] Проверяю библиотеки...")
    run(
        [
            str(VENV_PY), "-m", "pip", "install", "-q",
            "--disable-pip-version-check", "-r", "requirements.txt",
        ]
    )

    if not ENV_TEST.exists():
        shutil.copy(ENV_TEST_EXAMPLE, ENV_TEST)
        print(
            "\nСоздан файл .env.test — сейчас он откроется в Блокноте.\n"
            "Впиши BOT_TOKEN тестового бота и свой Telegram ID,\n"
            "сохрани, закрой и запусти start_test.bat ещё раз."
        )
        if os.name == "nt":
            subprocess.run(["notepad", str(ENV_TEST)])
        return

    print("[3/3] Запускаю бота в ТЕСТОВОМ режиме (.env.test). Остановить: Ctrl+C\n")
    env = dict(os.environ, ENV_FILE=str(ENV_TEST))
    try:
        subprocess.run([str(VENV_PY), "bot.py"], cwd=ROOT, env=env)
    except KeyboardInterrupt:
        pass
    print("\nБот остановлен.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено.")
