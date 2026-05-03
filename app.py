from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient,
    ReplyMessageRequest, TextMessage,
    QuickReply, QuickReplyItem, MessageAction
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


def get_context_id(event):
    group_id = get_group_id(event)

    if group_id:
        return group_id

    return f"private:{event.source.user_id}"


def is_private_chat(event):
    return get_group_id(event) is None


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


def add_poop(context_id, user_id, user_name):
    now = datetime.now(TZ)

    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO poops (group_id, user_id, user_name, created_at)
        VALUES (%s, %s, %s, %s)
        """,
        (context_id, user_id, user_name, now)
    )
    conn.commit()
    c.close()
    conn.close()


def undo_latest_poop(context_id, user_id):
    conn = get_conn()
    c = conn.cursor()

    c.execute(
        """
        DELETE FROM poops
        WHERE id = (
            SELECT id
            FROM poops
            WHERE group_id = %s
            AND user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        )
        RETURNING user_name, created_at
        """,
        (context_id, user_id)
    )

    row = c.fetchone()
    conn.commit()
    c.close()
    conn.close()

    return row


def count_user_today(context_id, user_id):
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
        (context_id, user_id, today_start, tomorrow_start)
    )
    count = c.fetchone()[0]
    c.close()
    conn.close()
    return count


def month_ranking(context_id):
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
    """, (context_id, month_start, next_month_start))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def week_champion(context_id):
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
    """, (context_id, week_start))
    row = c.fetchone()
    c.close()
    conn.close()
    return row


def constipation_king(context_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT user_name, MAX(created_at) as last_time
        FROM poops
        WHERE group_id = %s
        GROUP BY user_id, user_name
        ORDER BY last_time ASC
        LIMIT 1
    """, (context_id,))
    row = c.fetchone()
    c.close()
    conn.close()

    if not row:
        return None

    name, last_time = row
    last_date = last_time.astimezone(TZ).date()
    days = (datetime.now(TZ).date() - last_date).days
    return name, days


def daily_chart(context_id):
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
    """, (context_id, month_start, next_month_start))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows


def roast(today_count):
    normal_roasts = [
        "腸胃很認真上班欸。",
        "這不是大便，這是每日任務。",
        "你是不是跟馬桶簽約了？",
        "尊重，今天又有產量。",
        "大便超人已為你記上一筆豐功偉業。",
        "這個頻率，馬桶應該認識你了。",
        "你今天的腸道 KPI 達標了。",
        "這坨我先幫你登記，歷史會記住你的。",
        "你的腸胃比我上班還準時。",
        "很好，內臟沒有擺爛。",
        "今日排放成功，地球少了一份壓力。",
        "馬桶：又是你？",
        "你不是在大便，你是在更新人生進度。",
        "腸道通暢，人生順暢。",
        "這一刻，你與馬桶達成了和解。",
        "大便超人收到，這坨有被尊重。",
        "你的身體正在進行系統清理。",
        "恭喜完成今日人體版本更新。",
        "這個產量，值得頒一張腸胃優良獎。",
        "你今天不是普通人，是排放型人才。",
        "馬桶已收到你的誠意。",
        "腸胃：我今天有上班，不要扣薪。",
        "這不是屎，這是你的努力結晶。",
        "好，這筆我幫你寫進大便史。",
        "恭喜你，成功把壓力轉化成實體。",
        "便意來得快，紀錄不能慢。",
        "你的腸道正在用行動證明自己。",
        "今天的你，很有出口。",
        "這波排放，穩。",
        "馬桶表示：已處理。"
    ]

    many_roasts = [
        "今天有點高產，馬桶辛苦了。",
        "你是不是兜不住屎？",
        "這個頻率，馬桶應該要幫你辦會員卡。",
        "你今天是不是跟廁所綁定了？",
        "腸胃上班上到加班，太敬業了吧。",
        "這不是排便，這是連續劇。",
        "馬桶今天看到你應該會嘆氣。",
        "你是不是把廁所當辦公室？",
        "大便超人合理懷疑你今天兜不住。",
        "這個產量，已經不是普通人類了。"
    ]

    extreme_roasts = [
        "你今天真的兜不住屎欸，馬桶都快被你打卡打到熟了。",
        "第 5 坨以上了，人體印鈔機是吧？只是印出來的是屎。",
        "你這不是腸胃蠕動，你這是腸胃暴走。",
        "馬桶：我只是個馬桶，不是你的心理諮商師。",
        "你今天的屁股是不是開自動連發？",
        "先暫停一下，你的腸道好像在開演唱會。",
        "這個排放量，環保局都想來關心你。",
        "你是不是吃飯不用消化，直接轉單給馬桶？"
    ]

    legendary_roasts = [
        "你今天第 7 坨以上了欸，馬桶要不要幫你報工時？",
        "這已經不是兜不住屎，是屎在追著你跑。",
        "你的腸胃今天是不是開外掛？",
        "馬桶現在應該想封鎖你。",
        "大便超人宣布：你今天是人體排放傳奇。",
        "你再拉下去，馬桶要成立工會了。",
        "這個頻率，屁股應該要申請勞健保。",
        "我合理懷疑你不是人在大便，是大便在做人。"
    ]

    if today_count >= 7:
        return random.choice(legendary_roasts)
    elif today_count >= 5:
        return random.choice(extreme_roasts)
    elif today_count >= 3:
        return random.choice(many_roasts)
    else:
        return random.choice(normal_roasts)


def quick_reply_menu():
    return QuickReply(
        items=[
            QuickReplyItem(
                action=MessageAction(label="💩 記錄", text="💩")
            ),
            QuickReplyItem(
                action=MessageAction(label="↩️ 收回", text="/收回")
            ),
            QuickReplyItem(
                action=MessageAction(label="🏆 排行", text="/排行")
            ),
            QuickReplyItem(
                action=MessageAction(label="👑 本週", text="/本週")
            ),
            QuickReplyItem(
                action=MessageAction(label="🚨 便秘", text="/便秘")
            ),
            QuickReplyItem(
                action=MessageAction(label="📊 統計", text="/統計")
            ),
            QuickReplyItem(
                action=MessageAction(label="⏰ 起床", text="/起床")
            ),
            QuickReplyItem(
                action=MessageAction(label="ℹ️ 說明", text="/說明")
            ),
        ]
    )


def reply_to_line(event, reply):
    with ApiClient(configuration) as api_client:
        api = MessagingApi(api_client)
        api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=reply,
                        quick_reply=quick_reply_menu()
                    )
                ]
            )
        )


@app.route("/", methods=["GET"])
def home():
    return "Poop bot is running!"


@app.route("/wake", methods=["GET"])
def wake():
    return "大便超人醒了！可以回 LINE 傳 /起床 或 /說明 測試。"


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
    context_id = get_context_id(event)
    private_chat = is_private_chat(event)

    commands = [
        "💩",
        "/排行",
        "/本週",
        "/便秘",
        "/統計",
        "/說明",
        "/起床",
        "/收回",
        "收回",
        "/取消"
    ]

    undo_commands = ["/收回", "收回", "/取消"]

    if text == "/起床":
        if private_chat:
            reply = (
                "大便超人醒了 💩\n"
                "一對一模式已啟動。\n\n"
                "如果我剛睡醒，第一則可能只是叫醒我。\n"
                "請等約 1 分鐘後再傳一次指令。"
            )
        else:
            reply = (
                "大便超人醒了 💩\n"
                "群組馬桶系統已啟動。\n\n"
                "如果我剛睡醒，第一則可能只是叫醒我。\n"
                "請等約 1 分鐘後再傳一次指令。"
            )

        reply_to_line(event, reply)
        return

    if text == "/說明":
        if private_chat:
            place_text = "目前是一對一模式，紀錄只會算你自己的，不會跟群組混在一起。"
        else:
            place_text = "目前是群組模式，每個群組會分開統計，不會混在一起。"

        reply = (
            "大便超人指令表 💩\n\n"
            "傳 💩：記錄一次\n"
            "/收回：收回自己最新一筆 💩\n"
            "/排行：本月排行榜\n"
            "/本週：本週冠軍\n"
            "/便秘：誰最久沒大\n"
            "/統計：每日統計圖\n"
            "/起床：確認機器人有沒有醒\n\n"
            f"{place_text}\n\n"
            "補充說明：\n"
            "機器人 15 分鐘沒使用可能會睡著。\n"
            "剛睡醒時，第一則訊息可能只是叫醒它。\n"
            "請等大約 1 分鐘後再傳一次，通常就會正常回覆。\n"
            "也可以先傳 /起床 測試大便超人有沒有在運作。\n\n"
            "資料只保留本月 + 上個月，更久以前會自動沖掉。"
        )
        reply_to_line(event, reply)
        return

    if text not in commands:
        return

    maybe_cleanup_old_months()

    if text == "💩":
        user_name = get_user_name(event)

        add_poop(context_id, user_id, user_name)
        today_count = count_user_today(context_id, user_id)

        if private_chat:
            reply = (
                f"已記錄你的 💩\n"
                f"今天第 {today_count} 坨\n\n"
                f"{roast(today_count)}"
            )
        else:
            reply = (
                f"已記錄 {user_name} 的 💩\n"
                f"今天第 {today_count} 坨\n\n"
                f"{roast(today_count)}"
            )

    elif text in undo_commands:
        row = undo_latest_poop(context_id, user_id)

        if not row:
            if private_chat:
                reply = "你目前沒有可以收回的 💩。"
            else:
                reply = "你在這個群組目前沒有可以收回的 💩。"
        else:
            user_name, deleted_time = row
            today_count = count_user_today(context_id, user_id)

            if private_chat:
                reply = (
                    "已收回你最新一筆 💩\n"
                    f"今天剩下 {today_count} 坨。\n\n"
                    "這坨就當作被時光馬桶沖掉了。"
                )
            else:
                reply = (
                    f"已收回 {user_name} 最新一筆 💩\n"
                    f"今天剩下 {today_count} 坨。\n\n"
                    "這坨就當作被時光馬桶沖掉了。"
                )

    elif text == "/排行":
        rows = month_ranking(context_id)

        if not rows:
            reply = "本月還沒有人大便。"
        else:
            month = datetime.now(TZ).month

            if private_chat:
                msg = f"🏆 你的 {month} 月大便紀錄\n\n"
            else:
                msg = f"🏆 {month}月大便排行榜\n\n"

            for i, (name, total) in enumerate(rows, start=1):
                if private_chat:
                    msg += f"{i}. 你 - {total} 坨\n"
                else:
                    msg += f"{i}. {name} - {total} 坨\n"

            reply = msg.strip()

    elif text == "/本週":
        row = week_champion(context_id)

        if not row:
            reply = "本週還沒有人大便。"
        else:
            name, total = row

            if private_chat:
                reply = f"👑 你本週已經 {total} 坨 💩"
            else:
                reply = f"👑 本週大便王：{name}\n本週已經 {total} 坨 💩"

    elif text == "/便秘":
        result = constipation_king(context_id)

        if not result:
            reply = "目前還沒有紀錄，腸胃狀態仍是謎。"
        else:
            name, days = result

            if private_chat:
                if days == 0:
                    reply = "你今天有大便，暫時安全。"
                else:
                    reply = f"⚠️ 你已經 {days} 天沒大便了。"
            else:
                if days == 0:
                    reply = f"{name} 今天有大便，暫時安全。"
                else:
                    reply = f"⚠️ {name} 已經 {days} 天沒大便了。"

    elif text == "/統計":
        rows = daily_chart(context_id)

        if not rows:
            reply = "本月還沒有統計資料。"
        else:
            if private_chat:
                msg = "📊 你本月每日大便統計\n\n"
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
    ensure_db_ready()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
