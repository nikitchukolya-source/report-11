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
    "Липка",
    "Молокова"
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


def parse_call_time(value):
    if not value:
        return None

    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        return None


def build_report():
    now = datetime.now()
    today = now.date()

    date_from = datetime.combine(today, time(0, 0))
    fifteen = datetime.combine(today, time(15, 0))
    seventeen = datetime.combine(today, time(17, 0))
    date_to = min(now, seventeen)

    managers = get_managers()
    calls = get_calls(date_from, date_to)

    counts_15 = {line: 0 for line in managers}
    counts_17 = {line: 0 for line in managers}

    for call in calls:
        if call.get("direction") != "OUT":
            continue

        manager_line = str(call.get("from") or "")

        if manager_line not in managers:
            continue

        talk_seconds = int(
            call.get("secondsTalk", 0) or 0
        )

        if talk_seconds < 45:
            continue

        call_time = parse_call_time(
            call.get("date")
        )

        if call_time is None:
            continue

        # Станом на 17:00:
        # усі дзвінки >=45 сек від початку дня до 17:00.
        if call_time < seventeen:
            counts_17[manager_line] += 1

        # Станом на 15:00:
        # усі дзвінки >=45 сек від початку дня до 15:00.
        if call_time < fifteen:
            counts_15[manager_line] += 1

    rows = [
        (
            name,
            counts_15[line],
            counts_17[line],
        )
        for line, name in managers.items()
    ]

    # Сортуємо за показником на 17:00,
    # далі за показником на 15:00.
    rows.sort(
        key=lambda row: (
            -row[2],
            -row[1],
            row[0].lower(),
        )
    )

    text = (
        f"📞 <b>На 17:00, &gt;45 сек</b>\n"
        f"<b>{today.strftime('%d.%m.%Y')}</b>\n\n"
        f"<pre>"
        f"{'Менеджер':<18} {'на 15':>5} {'на 17':>5}\n"
        f"{'-' * 30}\n"
    )

    for name, count_15, count_17 in rows:
        text += (
            f"{html.escape(name):<18} "
            f"{count_15:>5} "
            f"{count_17:>5}\n"
        )

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
