"""
Щоденний звіт по ВИХІДНИХ спробах дзвінків UniTalk -> Telegram.

Показує дзвінки менеджерів за ПОТОЧНИЙ календарний день:
від 00:00:00 до 11:00:00.

Якщо скрипт запускається раніше 11:00 — бере дані до моменту запуску.
Якщо після 11:00 — бере тільки дзвінки до 11:00.

Враховуються ВСІ вихідні спроби менеджерів:
- успішні (ANSWER);
- недодзвони / неуспішні спроби (усі інші state).

Не враховуються менеджери з EXCLUDED_MANAGERS.
"""

from __future__ import annotations

import html
import os
import sys
from datetime import datetime, time

import requests


# =====================================================================
# КОНФІГУРАЦІЯ
# =====================================================================

UNITALK_API_KEY = os.environ.get(
    "UNITALK_API_KEY",
    ""
)

TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_IDS = [
    int(chat_id.strip())
    for chat_id in os.environ.get(
        "TELEGRAM_CHAT_IDS",
        ""
    ).split(",")
    if chat_id.strip()
]

UNITALK_BASE_URL = "https://api.unitalk.cloud/api"

USERS_URL = f"{UNITALK_BASE_URL}/users/list"
HISTORY_URL = f"{UNITALK_BASE_URL}/history/get"

PAGE_LIMIT = 1000
CALL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


# =====================================================================
# ВИКЛЮЧЕННЯ — ЗАЛИШЕНІ ТАКИМИ Ж, ЯК У ПОПЕРЕДНЬОМУ СКРИПТІ
# =====================================================================

EXCLUDED_MANAGERS = {
    "Рябініна",
    "Грабчук",
    "Кіндякова",
    "Терлик",
    "Ковальчук",
    "Матенька",
    "Тимошенко",
}


# =====================================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# =====================================================================

def get_unitalk_headers() -> dict:
    if not UNITALK_API_KEY:
        raise RuntimeError(
            "Не задано UNITALK_API_KEY у змінних середовища."
        )

    return {
        "Authorization": f"Bearer {UNITALK_API_KEY}",
        "Content-Type": "application/json",
    }


def parse_call_time(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            CALL_TIME_FORMAT,
        )
    except ValueError:
        return None


def get_report_range() -> tuple[datetime, datetime, str]:
    """
    Поточний день:
    від 00:00:00
    до 11:00:00.

    Якщо скрипт запущено раніше 11:00,
    date_to = поточний момент.
    """

    now = datetime.now()
    today = now.date()

    date_from = datetime.combine(
        today,
        time(0, 0, 0),
    )

    eleven_am = datetime.combine(
        today,
        time(11, 0, 0),
    )

    date_to = min(
        now,
        eleven_am,
    )

    return (
        date_from,
        date_to,
        today.strftime("%d.%m.%Y"),
    )


def normalize_phone(value) -> str:
    return "".join(
        character
        for character in str(value or "")
        if character.isdigit()
    )


def call_targets(call: dict) -> list[str]:
    raw = call.get(
        "to",
        []
    )

    if isinstance(raw, list):
        return [
            str(item)
            for item in raw
            if item is not None
        ]

    if raw is None:
        return []

    return [str(raw)]


def format_duration(
    seconds: int | float | None,
) -> str:

    total = max(
        int(seconds or 0),
        0,
    )

    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{secs:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{secs:02d}"
    )


# =====================================================================
# МЕНЕДЖЕРИ
# =====================================================================

def fetch_managers() -> dict[str, str]:
    """
    Результат:

    {
        "8309": "Іван Петренко",
        "3610": "Олександр Сидоренко"
    }

    ключ = внутрішня SIP-лінія
    """

    response = requests.post(
        USERS_URL,
        headers=get_unitalk_headers(),
        json={},
        timeout=30,
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        users = data

    elif isinstance(data, dict):
        users = []

        for key in (
            "items",
            "data",
            "list",
            "result",
        ):
            if isinstance(
                data.get(key),
                list,
            ):
                users = data[key]
                break
    else:
        users = []

    managers = {}

    for user in users:
        if not isinstance(
            user,
            dict,
        ):
            continue

        line = user.get(
            "line"
        )

        if line is None:
            continue

        first_name = str(
            user.get(
                "firstName"
            )
            or ""
        ).strip()

        last_name = str(
            user.get(
                "lastName"
            )
            or ""
        ).strip()

        # Виключення перевіряємо саме за прізвищем.
        if last_name in EXCLUDED_MANAGERS:
            continue

        full_name = " ".join(
            part
            for part in (
                first_name,
                last_name,
            )
            if part
        )

        if not full_name:
            full_name = f"Лінія {line}"

        managers[
            str(line)
        ] = full_name

    return managers


def manager_name(
    line: str | None,
    managers: dict[str, str],
) -> str:

    if not line:
        return "—"

    return managers.get(
        str(line),
        f"Лінія {line}",
    )


# =====================================================================
# ОТРИМАННЯ ІСТОРІЇ
# =====================================================================

def fetch_call_history(
    date_from: datetime,
    date_to: datetime,
    direction: str | None = None,
) -> list[dict]:

    all_calls = []
    offset = 0

    while True:
        payload = {
            "dateFrom": date_from.strftime(
                CALL_TIME_FORMAT
            ),
            "dateTo": date_to.strftime(
                CALL_TIME_FORMAT
            ),
            "limit": PAGE_LIMIT,
            "offset": offset,
        }

        if direction:
            payload["filter"] = {
                "direction": direction
            }

        response = requests.post(
            HISTORY_URL,
            headers=get_unitalk_headers(),
            json=payload,
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()

        calls = data.get(
            "calls",
            []
        )

        if not isinstance(
            calls,
            list,
        ):
            break

        if not calls:
            break

        all_calls.extend(
            calls
        )

        print(
            f"[debug] {direction}: "
            f"отримано {len(calls)}, "
            f"всього {len(all_calls)}",
            file=sys.stderr,
        )

        if len(calls) < PAGE_LIMIT:
            break

        offset += PAGE_LIMIT

    return all_calls


# =====================================================================
# ВИХІДНІ ДЗВІНКИ
# =====================================================================

def outgoing_manager_line(
    call: dict,
    managers: dict[str, str],
) -> str | None:
    """
    Для OUT поле `from`
    містить внутрішню лінію менеджера.

    Якщо лінії немає у managers —
    дзвінок не враховується.
    Це автоматично прибирає і виключених менеджерів.
    """

    source = str(
        call.get(
            "from",
            ""
        )
    )

    if source in managers:
        return source

    return None


def outgoing_client_phone(
    call: dict,
) -> str:
    """
    У OUT шукаємо зовнішній номер
    серед значень поля `to`.

    Внутрішня SIP-лінія зазвичай коротка,
    номер клієнта — довший.
    """

    for target in call_targets(
        call
    ):
        phone = normalize_phone(
            target
        )

        if len(phone) >= 9:
            return phone

    return ""


def build_report_rows(
    outgoing_calls: list[dict],
    managers: dict[str, str],
) -> list[dict]:

    rows = []

    calls = sorted(
        (
            call
            for call in outgoing_calls
            if call.get(
                "direction"
            ) == "OUT"
        ),
        key=lambda call: (
            parse_call_time(
                call.get(
                    "date"
                )
            )
            or datetime.min
        ),
    )

    for call in calls:
        manager_line = outgoing_manager_line(
            call,
            managers,
        )

        # Не менеджер або менеджер із виключень.
        if not manager_line:
            continue

        call_time = parse_call_time(
            call.get(
                "date"
            )
        )

        answered = (
            call.get(
                "state"
            )
            == "ANSWER"
        )

        rows.append(
            {
                "call_time": call_time,
                "manager_line": manager_line,
                "manager": manager_name(
                    manager_line,
                    managers,
                ),
                "client_phone": outgoing_client_phone(
                    call
                ),
                "answered": answered,
                "state": call.get(
                    "state"
                ),
                "talk_seconds": int(
                    call.get(
                        "secondsTalk",
                        0
                    )
                    or 0
                ),
                "full_seconds": int(
                    call.get(
                        "secondsFullTime",
                        0
                    )
                    or 0
                ),
            }
        )

    return rows


# =====================================================================
# СТАТИСТИКА ПО МЕНЕДЖЕРАХ
# =====================================================================

def build_manager_stats(
    rows: list[dict],
    managers: dict[str, str],
) -> list[dict]:

    stats = {}

    # Додаємо всіх активних менеджерів,
    # навіть якщо в них 0 дзвінків.
    for line, name in managers.items():
        stats[line] = {
            "manager_line": line,
            "manager": name,
            "attempts": 0,
            "answered": 0,
            "missed": 0,
        }

    for row in rows:
        line = row["manager_line"]

        if line not in stats:
            continue

        stats[line]["attempts"] += 1

        if row["answered"]:
            stats[line]["answered"] += 1
        else:
            stats[line]["missed"] += 1

    result = list(
        stats.values()
    )

    # Спочатку ті, в кого більше спроб.
    # При однаковій кількості — за ім'ям.
    result.sort(
        key=lambda item: (
            -item["attempts"],
            item["manager"].lower(),
        )
    )

    return result


# =====================================================================
# TELEGRAM — ДЕТАЛІ ОДНОГО ДЗВІНКА
# =====================================================================

def format_phone(
    phone: str,
) -> str:

    if not phone:
        return "—"

    return f"+{phone}"


def format_report_item(
    number: int,
    row: dict,
) -> str:

    if row["call_time"]:
        call_time = row[
            "call_time"
        ].strftime(
            "%H:%M:%S"
        )
    else:
        call_time = "—"

    if row["answered"]:
        status = "✅ Успішний"
    else:
        status = "❌ Недодзвон"

    lines = [
        (
            f"<b>{number}. "
            f"{call_time}</b> "
            f"☎️ "
            f"{html.escape(format_phone(row['client_phone']))}"
        ),
        (
            "Менеджер: "
            f"{html.escape(row['manager'])}"
        ),
        (
            f"Статус: {status}"
        ),
    ]

    if row["answered"]:
        lines.append(
            "Розмова: "
            f"{format_duration(row['talk_seconds'])}"
        )

    return "\n".join(
        lines
    )


# =====================================================================
# TELEGRAM — ПОВНИЙ ЗВІТ
# =====================================================================

def build_telegram_messages(
    rows: list[dict],
    manager_stats: list[dict],
    report_date: str,
    report_to: datetime,
) -> list[str]:

    answered_count = sum(
        1
        for row in rows
        if row["answered"]
    )

    missed_count = (
        len(rows)
        - answered_count
    )

    cutoff_text = report_to.strftime(
        "%H:%M"
    )

    header = (
        f"📞 <b>Вихідні спроби дзвінків "
        f"за {report_date}</b>\n"
        f"Період: <b>00:00–{cutoff_text}</b>\n\n"
        f"Всього спроб: "
        f"<b>{len(rows)}</b>\n"
        f"Успішних: "
        f"<b>{answered_count}</b>\n"
        f"Недодзвонів: "
        f"<b>{missed_count}</b>"
    )

    stats_lines = [
        "",
        "👥 <b>По менеджерах:</b>",
    ]

    for item in manager_stats:
        stats_lines.append(
            (
                f"• {html.escape(item['manager'])}: "
                f"<b>{item['attempts']}</b> спроб "
                f"(✅ {item['answered']} / "
                f"❌ {item['missed']})"
            )
        )

    summary = (
        header
        + "\n"
        + "\n".join(
            stats_lines
        )
    )

    messages = []

    # Якщо зведення завелике,
    # Telegram все одно має ліміт,
    # тому ріжемо акуратно.
    if len(summary) <= 3500:
        current = summary
    else:
        # Дуже малоймовірно, але безпечний варіант.
        current = header

        for line in stats_lines:
            candidate = (
                current
                + "\n"
                + line
            )

            if len(candidate) > 3500:
                messages.append(
                    current
                )
                current = (
                    f"👥 <b>Продовження статистики "
                    f"{report_date}</b>\n"
                    f"{line}"
                )
            else:
                current = candidate

    if not rows:
        current += (
            "\n\n"
            "Вихідних спроб дзвінків "
            "за цей період немає."
        )

        messages.append(
            current
        )

        return messages

    for number, row in enumerate(
        rows,
        start=1,
    ):
        item = format_report_item(
            number,
            row,
        )

        candidate = (
            current
            + "\n\n"
            + item
        )

        if len(candidate) > 3500:
            messages.append(
                current
            )

            current = (
                f"📞 <b>Продовження "
                f"{report_date}</b>\n\n"
                f"{item}"
            )
        else:
            current = candidate

    if current:
        messages.append(
            current
        )

    return messages


# =====================================================================
# TELEGRAM SEND
# =====================================================================

def send_telegram_message(
    chat_id: int,
    text: str,
) -> None:

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "Не задано TELEGRAM_BOT_TOKEN."
        )

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        "sendMessage"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    response = requests.post(
        url,
        json=payload,
        timeout=15,
    )

    if not response.ok:
        print(
            f"[ERROR] Telegram "
            f"chat_id={chat_id}: "
            f"{response.status_code} "
            f"{response.text}",
            file=sys.stderr,
        )

        response.raise_for_status()


# =====================================================================
# MAIN
# =====================================================================

def main() -> None:

    if not UNITALK_API_KEY:
        raise RuntimeError(
            "Не задано UNITALK_API_KEY."
        )

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "Не задано TELEGRAM_BOT_TOKEN."
        )

    if not TELEGRAM_CHAT_IDS:
        raise RuntimeError(
            "Не задано TELEGRAM_CHAT_IDS."
        )

    (
        report_from,
        report_to,
        report_date,
    ) = get_report_range()

    print(
        f"[info] формую звіт "
        f"за {report_date}, "
        f"{report_from.strftime('%H:%M:%S')}–"
        f"{report_to.strftime('%H:%M:%S')}"
    )

    # -------------------------------------------------------------
    # МЕНЕДЖЕРИ
    # -------------------------------------------------------------

    managers = fetch_managers()

    print(
        f"[info] активних менеджерів "
        f"після виключень: "
        f"{len(managers)}"
    )

    # -------------------------------------------------------------
    # ВИХІДНІ СПРОБИ
    # -------------------------------------------------------------

    outgoing_calls = fetch_call_history(
        report_from,
        report_to,
        direction="OUT",
    )

    print(
        f"[info] OUT отримано: "
        f"{len(outgoing_calls)}"
    )

    # -------------------------------------------------------------
    # ФОРМУЄМО ДАНІ
    # -------------------------------------------------------------

    rows = build_report_rows(
        outgoing_calls,
        managers,
    )

    manager_stats = build_manager_stats(
        rows,
        managers,
    )

    print(
        f"[info] OUT менеджерів "
        f"після фільтрів: "
        f"{len(rows)}"
    )

    # -------------------------------------------------------------
    # TELEGRAM
    # -------------------------------------------------------------

    messages = build_telegram_messages(
        rows,
        manager_stats,
        report_date,
        report_to,
    )

    # -------------------------------------------------------------
    # КОНСОЛЬ
    # -------------------------------------------------------------

    for message in messages:
        print(
            "\n" + message
        )

    # -------------------------------------------------------------
    # ВІДПРАВКА
    # -------------------------------------------------------------

    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            for message in messages:
                send_telegram_message(
                    chat_id,
                    message,
                )

            print(
                f"[info] звіт надіслано "
                f"в chat_id={chat_id}"
            )

        except Exception as exc:
            print(
                f"[ERROR] не вдалося "
                f"надіслати звіт "
                f"в chat_id={chat_id}: "
                f"{exc}",
                file=sys.stderr,
            )


# =====================================================================
# START
# =====================================================================

if __name__ == "__main__":
    main()
