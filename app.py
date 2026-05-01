from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import os
import random
import psycopg2
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

handler = WebhookHandler(CHANNEL_SECRET)
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

TZ = timezone(timedelta(hours=8))

DB_READY = False
LAST_CLEANUP_DATE = None


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS poops (
            id SERIAL PRIMARY KEY,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    conn.commit()
    c.close()
    conn.close()


def ensure_db_ready():
    global DB_READY

    if not DB_READY:
        init_db()
        DB_READY = True


def cleanup_old_months():
    now = datetime.now(TZ)

    current_month_start = now.replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    if current_month_start.month == 1:
        keep_from = current_month_start.replace(
            year=current_month_start.year - 1,
            month=12
        )
    else:
        keep_from = current_month_start.replace(
            month=current_month_start.month - 1
        )

    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        DELETE FROM poops
        WHERE created_at < %s
        """,
        (keep_from,)
    )
    conn.commit()
    c.close()
    conn.close()


def maybe_cleanup_old_months():
    global LAST_CLEANUP_DATE

    today = datetime.now(TZ).date()

    if LAST_CLEANUP_DATE == today:
        return

    ensure_db_ready()
    cleanup_old_months()
    LAST_CLEANUP_DATE = today


def get_group_id(event):
    return getattr(event.source, "group_id", None)


def get_user_name(event):
    user_id = event.source.user_id
    group_id = get_group_id(event)

    try:
        with ApiClient(configuration) as api_client:
            api = MessagingApi(api_client)

            if group_id:
                profile = api.get_group_member_profile(group_id, user_id)
            else:
                profile = api.get_profile(user_id)

            return profile.display_name
    except:
        return "神秘便士"


def add_poop(group_id, user_id, user_name):
    now = datetime.now(TZ)

    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO poops (group_id, user_id, user_name, created_at)
        VALUES (%s, %s, %s, %s)
        """,
        (group_id, user_id, user_name, now)
    )
    conn.commit()
    c.close()
    conn.close()


def count_user_today(group_id, user_id):
    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT COUNT(*)
        FROM poops
        WHERE group_id = %s
        AND user_id = %s
        AND created_at >= %s
        AND created_at < %s
        """,
        (group_id, user_id, today_start, tomorrow_start)
    )
    count = c.fetchone()[0]
    c.close()
    conn.close()
    return count


def month_ranking(group_id):
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if now.month == 12:
        next_month_start = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=now.month + 1)

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_name, COUNT(*) as total
        FROM poops
        WHERE group_id = %s
        AND created_at >= %s
        AND created_at < %s
        GROUP BY user_id, user_name
        ORDER BY total DESC
    """, (group_id, month_start, next_month_start))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def week_champion(group_id):
    now = datetime.now(TZ)
    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_name, COUNT(*) as total
        FROM poops
        WHERE group_id = %s
        AND created_at >= %s
        GROUP BY user_id, user_name
        ORDER BY total DESC
        LIMIT 1
    """, (group_id, week_start))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def constipation_king(group_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_name, MAX(created_at) as last_time
        FROM poops
        WHERE group_id = %s
        GROUP BY user_id, user_name
        ORDER BY last_time ASC
        LIMIT 1
    """, (group_id,))
    row = c.fetchone()
    c.close()
    conn.close()

    if not row:
        return None

    name, last_time = row
    last_date = last_time.astimezone(TZ).date()
    days = (datetime.now(TZ).date() - last_date).days
    return name, days


def daily_chart(group_id):
    now = datetime.now(TZ)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if now.month == 12:
        next_month_start = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=now.month + 1)

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT DATE(created_at AT TIME ZONE 'Asia/Taipei') as day, COUNT(*)
        FROM poops
        WHERE group_id = %s
        AND created_at >= %s
        AND created_at < %s
        GROUP BY day
        ORDER BY day
    """, (group_id, month_start, next_month_start))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def roast(today_count):
    roasts = [
        "腸胃很認真上班欸。",
        "這不是大便，這是每日任務。",
        "你是不是跟馬桶簽約了？",
        "尊重，今天又有產量。",
        "大便超人已為你記上一筆豐功偉業。",
        "這個頻率，馬桶應該認識你了。",
        "你今天的腸道 KPI 達標了。"
    ]

    if today_count >= 5:
        return "你今天第 5 坨以上了欸，人體印鈔機是吧？"
    elif today_count >= 3:
        return "今天有點高產，馬桶辛苦了。"
    else:
        return random.choice(roasts)


def reply_to_line(event, reply):
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )


@app.route("/", methods=["GET"])
def home():
    return "Poop bot is running!"


@app.route("/wake", methods=["GET"])
def wake():
    return "大便超人醒了！可以回 LINE 傳 /說明 測試。"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    group_id = get_group_id(event)

    commands = ["💩", "/排行", "/本週", "/便秘", "/統計", "/說明", "/起床"]

    if not group_id:
        if text == "/起床":
            reply = "大便超人醒了，但這裡是私訊，不會記錄 💩"
        elif text in commands:
            reply = "這裡是私訊，不會記錄 💩\n請在群組裡使用。"
        else:
            return

        reply_to_line(event, reply)
        return

    if text == "/起床":
        reply = "大便超人醒了 💩\n馬桶系統已啟動。"
        reply_to_line(event, reply)
        return

    if text == "/說明":
        reply = (
            "大便超人指令表 💩\n\n"
            "傳 💩：記錄一次\n"
            "/排行：本月排行榜\n"
            "/本週：本週冠軍\n"
            "/便秘：誰最久沒大\n"
            "/統計：每日統計圖\n"
            "/起床：叫醒機器人\n\n"
            "注意：每個群組會分開統計，不會混在一起。\n"
            "資料只保留本月 + 上個月，更久以前會自動沖掉。"
        )
        reply_to_line(event, reply)
        return

    if text not in commands:
        return

    maybe_cleanup_old_months()

    if text == "💩":
        user_name = get_user_name(event)

        add_poop(group_id, user_id, user_name)
        today_count = count_user_today(group_id, user_id)

        reply = (
            f"已記錄 {user_name} 的 💩\n"
            f"今天第 {today_count} 坨\n\n"
            f"{roast(today_count)}"
        )

    elif text == "/排行":
        rows = month_ranking(group_id)

        if not rows:
            reply = "本月這個群組還沒有人大便。"
        else:
            month = datetime.now(TZ).month
            msg = f"🏆 {month}月大便排行榜\n\n"
            for i, (name, total) in enumerate(rows, start=1):
                msg += f"{i}. {name} - {total} 坨\n"
            reply = msg.strip()

    elif text == "/本週":
        row = week_champion(group_id)

        if not row:
            reply = "本週這個群組還沒有人大便。"
        else:
            name, total = row
            reply = f"👑 本週大便王：{name}\n本週已經 {total} 坨 💩"

    elif text == "/便秘":
        result = constipation_king(group_id)

        if not result:
            reply = "目前這個群組沒有紀錄，大家都還很神秘。"
        else:
            name, days = result
            if days == 0:
                reply = f"{name} 今天有大便，暫時安全。"
            else:
                reply = f"⚠️ {name} 已經 {days} 天沒大便了。"

    elif text == "/統計":
        rows = daily_chart(group_id)

        if not rows:
            reply = "本月這個群組還沒有統計資料。"
        else:
            msg = "📊 本月每日大便統計\n\n"
            for day, total in rows:
                day_text = day.strftime("%m-%d")
                bar = "💩" * min(total, 10)
                msg += f"{day_text}：{bar} {total}\n"
            reply = msg.strip()

    else:
        return

    reply_to_line(event, reply)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
