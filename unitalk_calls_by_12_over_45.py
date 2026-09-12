from __future__ import annotations

import html
import os
from datetime import datetime, time

import requests


UNITALK_API_KEY = os.environ.get("UNITALK_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = [
    int(x.strip())
    for x in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
    if x.strip()
]

BASE_URL = "https://api.unitalk.cloud/api"
USERS_URL = f"{BASE_URL}/users/list"
HISTORY_URL = f"{BASE_URL}/history/get"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

EXCLUDED_MANAGERS = {
    "Рябініна",
    "Грабчук",
    "Кіндякова",
    "Терлик",
    "Ковальчук",
    "Матенька",
    "Тимошенко",
}


def headers():
    return {
        "Authorization": f"Bearer {UNITALK_API_KEY}",
        "Content-Type": "application/json",
    }


def get_managers():
    response = requests.post(
        USERS_URL,
        headers=headers(),
        json={},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        users = data
    else:
        users = []
        for key in ("items", "data", "list", "result"):
            if isinstance(data.get(key), list):
                users = data[key]
                break

    managers = {}

    for user in users:
        line = user.get("line")
        if line is None:
            continue

        first_name = str(user.get("firstName") or "").strip()
        last_name = str(user.get("lastName") or "").strip()

        if last_name in EXCLUDED_MANAGERS:
            continue

        full_name = " ".join(
            x for x in (last_name, first_name) if x
        )

        managers[str(line)] = full_name or f"Лінія {line}"

    return managers


def get_calls(date_from, date_to):
    calls = []
    offset = 0

    while True:
        response = requests.post(
            HISTORY_URL,
            headers=headers(),
            json={
                "dateFrom": date_from.strftime(DATE_FORMAT),
                "dateTo": date_to.strftime(DATE_FORMAT),
                "limit": 1000,
                "offset": offset,
                "filter": {"direction": "OUT"},
            },
            timeout=30,
        )
        response.raise_for_status()

        batch = response.json().get("calls", [])

        if not batch:
            break

        calls.extend(batch)

        if len(batch) < 1000:
            break

        offset += 1000

    return calls


def build_report():
    now = datetime.now()
    today = now.date()

    date_from = datetime.combine(today, time(0, 0))
    twelve = datetime.combine(today, time(12, 0))
    date_to = min(now, twelve)

    managers = get_managers()
    calls = get_calls(date_from, date_to)

    counts = {
        line: 0
        for line in managers
    }

    for call in calls:
        if call.get("direction") != "OUT":
            continue

        manager_line = str(call.get("from") or "")

        if manager_line not in counts:
            continue

        talk_seconds = int(
            call.get("secondsTalk", 0) or 0
        )

        # Рахуємо тільки вихідні дзвінки,
        # де фактична розмова тривала 45 секунд або більше.
        if talk_seconds >= 45:
            counts[manager_line] += 1

    rows = [
        (name, counts[line])
        for line, name in managers.items()
    ]

    rows.sort(
        key=lambda row: (-row[1], row[0].lower())
    )

    text = (
        f"📞 <b>На 12:00, &gt;45 сек</b>\n"
        f"<b>{today.strftime('%d.%m.%Y')}</b>\n\n"
        f"<pre>"
        f"{'Менеджер':<28} {'на 12':>5}\n"
        f"{'-' * 34}\n"
    )

    for name, count in rows:
        text += f"{html.escape(name):<28} {count:>5}\n"

    text += "</pre>"

    return text


def send_telegram(text):
    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    for chat_id in TELEGRAM_CHAT_IDS:
        response = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=15,
        )
        response.raise_for_status()


def main():
    if not UNITALK_API_KEY:
        raise RuntimeError("Не задано UNITALK_API_KEY")

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Не задано TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_IDS:
        raise RuntimeError("Не задано TELEGRAM_CHAT_IDS")

    report = build_report()

    print(report)
    send_telegram(report)


if __name__ == "__main__":
    main()
