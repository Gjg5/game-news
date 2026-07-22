"""实时监控 → 存入新闻池（不直接进历史库）"""
import os, json, re, html, hashlib
from datetime import datetime, timezone, timedelta
import requests, feedparser

BJT = timezone(timedelta(hours=8))

# 28个游戏媒体RSS源
RSS_SOURCES = [
    {"url": "https://www.3dmgame.com/rss/news.xml", "source": "3DM"},
    {"url": "http://www.gamersky.com/rss/news.xml", "source": "游民星空"},
    {"url": "https://www.ithome.com/rss/", "source": "IT之家"},
    {"url": "http://www.gamelook.com.cn/feed/", "source": "GameLook"},
    {"url": "https://feedx.net/rss/17173.xml", "source": "17173"},
    {"url": "https://feeds.feedburner.com/ign/all", "source": "IGN"},
    {"url": "https://www.gamespot.com/feeds/mashup/", "source": "GameSpot"},
    {"url": "https://www.pcgamer.com/rss/", "source": "PC Gamer"},
    {"url": "https://www.gematsu.com/feed", "source": "Gematsu"},
    {"url": "https://www.vg247.com/feed", "source": "VG247"},
    {"url": "https://insider-gaming.com/feed/", "source": "Insider Gaming"},
    {"url": "https://www.4gamer.net/rss/index.xml", "source": "4gamer"},
]

POOL_FILE = "news_pool.json"

def fingerprint(title):
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "", title).lower().strip()
    return hashlib.md5(clean.encode("utf-8")).hexdigest()

def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', str(text)))

def translate(text):
    if not text or has_chinese(text):
        return text
    try:
        import random
        salt = str(random.randint(10000, 99999))
        raw = text[:500]
        sign = hashlib.md5(("0e6e7d1a4b7f3c2d" + raw + salt + "yG7dH2kL9pQ4wR8x").encode()).hexdigest()
        data = f"q={requests.utils.quote(raw)}&from=EN&to=zh-CHS&appKey=0e6e7d1a4b7f3c2d&salt={salt}&sign={sign}"
        resp = requests.post("https://openapi.youdao.com/api", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=5)
        j = resp.json()
        if j.get("errorCode") == "0" and j.get("translation"):
            t = j["translation"][0]
            if any('\u4e00' <= c <= '\u9fff' for c in t):
                return t
    except:
        pass
    return text

def load_pool():
    """读取新闻池"""
    if os.path.exists(POOL_FILE):
        try:
            with open(POOL_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_pool(items):
    """保存新闻池"""
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def load_history_fingerprints():
    """加载已发送历史的指纹"""
    if not os.path.exists("news_history.json"):
        return set()
    try:
        with open("news_history.json") as f:
            data = json.load(f)
        if "entries" in data:
            return set(data["entries"].keys())
    except:
        pass
    return set()

def send_email(items):
    pwd = os.environ.get("QQMAIL_PASSWORD", "")
    if not pwd:
        return
    from email.mime.text import MIMEText
    import smtplib
    now = datetime.now(BJT).strftime("%H:%M")
    body = f"🆕 {len(items)}条新游戏新闻 ({now})\n\n"
    for i, it in enumerate(items, 1):
        body += f"{i}. {it['title']}\n"
        body += f"   📡 {it['source']}"
        if it.get("link"): body += f"  🔗 {it['link']}"
        body += "\n\n"
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = "2586555901@qq.com"
    msg["To"] = "2586555901@qq.com"
    msg["Subject"] = f"【实时快报】{len(items)}条新闻 {now}"
    try:
        s = smtplib.SMTP_SSL("smtp.qq.com", 465)
        s.login("2586555901@qq.com", pwd)
        s.sendmail(msg["From"], [msg["To"]], msg.as_string())
        s.quit()
        print(f"  ✅ 已发邮件")
    except:
        pass

def main():
    now = datetime.now(BJT)
    print(f"🔍 {now.strftime('%Y-%m-%d %H:%M')} 扫描新闻...")

    pool = load_pool()
    pool_fps = {item["fp"] for item in pool}
    history_fps = load_history_fingerprints()
    new_items = []
    seen = set()

    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:2]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                fp = fingerprint(title)
                # 跳过已在池中 或 已发送过的
                if fp in pool_fps or fp in history_fps:
                    continue
                summary = re.sub(r'<[^>]+>', '', entry.get("summary","") or "")
                summary = html.unescape(summary)[:100]
                link = entry.get("link", "")
                title_cn = translate(title)
                summary_cn = translate(summary)
                item = {
                    "fp": fp,
                    "title": title_cn[:60],
                    "summary": summary_cn[:80],
                    "source": src["source"],
                    "link": link,
                    "date": now.strftime("%Y-%m-%d %H:%M")
                }
                new_items.append(item)
        except:
            pass

    if new_items:
        # 存入新闻池（最新在前）
        pool = new_items + pool
        save_pool(pool)
        print(f"\n🆕 {len(new_items)} 条 → 新闻池 (共{len(pool)}条)")
        send_email(new_items)
    else:
        print(f"  ✅ 无新新闻 (池中{len(pool)}条)")
        save_pool(pool)

if __name__ == "__main__":
    main()
