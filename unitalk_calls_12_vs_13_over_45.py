from __future__ import annotations

import html
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

import requests


# =====================================================================
# ЧАСОВИЙ ПОЯС
# =====================================================================

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# =====================================================================
# КОНФІГУРАЦІЯ
# =====================================================================

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
    "Молокова",
}


# =====================================================================
# API
# =====================================================================

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
    """
    Беремо всі дзвінки — і IN, і OUT.
    Фільтр direction не задаємо.
    """
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


# =====================================================================
# ПІДРАХУНОК
# =====================================================================

def call_targets(call):
    raw = call.get("to", [])

    if isinstance(raw, list):
        return [
            str(item)
            for item in raw
            if item is not None
        ]

    if raw is None:
        return []

    return [str(raw)]


def manager_lines_for_call(call, managers):
    """
    OUT:
      менеджер визначається по внутрішній лінії у полі from.

    IN:
      менеджери визначаються по внутрішніх лініях у полі to.

    Якщо один менеджер зустрічається в маршруті одного дзвінка
    кілька разів — цей дзвінок зараховується йому лише один раз.
    """

    direction = call.get("direction")

    if direction == "OUT":
        line = str(call.get("from") or "")
        return [line] if line in managers else []

    if direction == "IN":
        result = []
        seen = set()

        for target in call_targets(call):
            line = str(target)

            if line in managers and line not in seen:
                result.append(line)
                seen.add(line)

        return result

    return []


def count_calls_over_45(calls, managers):
    """
    Рахуємо всі вхідні та вихідні дзвінки,
    де фактична розмова тривала БІЛЬШЕ 45 секунд.
    """

    counts = {
        line: 0
        for line in managers
    }

    for call in calls:
        talk_seconds = int(
            call.get("secondsTalk", 0) or 0
        )

        # Саме > 45 секунд.
        if talk_seconds <= 45:
            continue

        for line in manager_lines_for_call(
            call,
            managers,
        ):
            counts[line] += 1

    return counts


# =====================================================================
# ЗВІТ 12 VS 13
# =====================================================================

def build_report():
    # Явно використовуємо київський час,
    # незалежно від timezone хмарної пісочниці.
    now = datetime.now(KYIV_TZ)
    today = now.date()

    date_from = datetime.combine(
        today,
        time(0, 0),
        tzinfo=KYIV_TZ,
    )

    twelve = datetime.combine(
        today,
        time(12, 0),
        tzinfo=KYIV_TZ,
    )

    thirteen = datetime.combine(
        today,
        time(13, 0),
        tzinfo=KYIV_TZ,
    )

    managers = get_managers()

    # ВАЖЛИВО:
    # для кожної колонки робимо окремий запит до UniTalk.

    # Станом на 12:00
    calls_12 = get_calls(
        date_from,
        min(now, twelve),
    )

    # Станом на 13:00
    calls_13 = get_calls(
        date_from,
        min(now, thirteen),
    )

    counts_12 = count_calls_over_45(
        calls_12,
        managers,
    )

    counts_13 = count_calls_over_45(
        calls_13,
        managers,
    )

    rows = [
        (
            name,
            counts_12[line],
            counts_13[line],
        )
        for line, name in managers.items()
    ]

    rows.sort(
        key=lambda row: (
            -row[2],
            -row[1],
            row[0].lower(),
        )
    )

    text = (
        f"📞 <b>На 13:00, &gt;45 сек</b>\n"
        f"<b>{today.strftime('%d.%m.%Y')}</b>\n\n"
        f"<pre>"
        f"{'Менеджер':<18} {'на 12':>5} {'на 13':>5}\n"
        f"{'-' * 30}\n"
    )

    for name, count_12, count_13 in rows:
        text += (
            f"{html.escape(name):<18} "
            f"{count_12:>5} "
            f"{count_13:>5}\n"
        )

    text += "</pre>"

    return text


# =====================================================================
# TELEGRAM
# =====================================================================

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


# =====================================================================
# MAIN
# =====================================================================

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
