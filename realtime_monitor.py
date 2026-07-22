"""实时新闻监控 - 28个游戏媒体，新新闻第一时间发邮件"""
import os, sys, json, re, html, hashlib
from datetime import datetime, timezone, timedelta
import requests, feedparser

BJT = timezone(timedelta(hours=8))

# 28个游戏媒体RSS源
RSS_SOURCES = [
    # --- 国内 ---
    {"url": "https://www.3dmgame.com/rss/news.xml", "source": "3DM"},
    {"url": "http://www.gamersky.com/rss/news.xml", "source": "游民星空"},
    {"url": "https://www.ithome.com/rss/", "source": "IT之家"},
    {"url": "http://www.gamelook.com.cn/feed/", "source": "GameLook"},
    {"url": "https://feedx.net/rss/17173.xml", "source": "17173"},
    # --- 海外 ---
    {"url": "https://feeds.feedburner.com/ign/all", "source": "IGN"},
    {"url": "https://www.gamespot.com/feeds/mashup/", "source": "GameSpot"},
    {"url": "https://www.pcgamer.com/rss/", "source": "PC Gamer"},
    {"url": "https://www.gematsu.com/feed", "source": "Gematsu"},
    {"url": "https://www.vg247.com/feed", "source": "VG247"},
    {"url": "https://insider-gaming.com/feed/", "source": "Insider Gaming"},
    {"url": "https://www.4gamer.net/rss/index.xml", "source": "4gamer"},
]

HISTORY_FILE = "news_history.json"

def fingerprint(title):
    clean = re.sub(r"[^\w\u4e00-\u9fff]", "", title).lower().strip()
    return hashlib.md5(clean.encode("utf-8")).hexdigest()

def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', str(text)))

def translate(text):
    """有道翻译"""
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

def get_existing_fingerprints():
    """获取已发送的指纹（兼容新旧两种格式）"""
    if not os.path.exists(HISTORY_FILE):
        return set()
    try:
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        if "entries" in data:
            return set(data["entries"].keys())
        if "fingerprints" in data:
            return set(data["fingerprints"])
    except:
        pass
    return set()

def append_history(items):
    """追加新条目到历史库"""
    data = {"entries": {}}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            data = json.load(f)
    if "entries" not in data:
        data["entries"] = {}
    for item in items:
        fp = item["fp"]
        if fp not in data["entries"]:
            data["entries"][fp] = {
                "title": item["title_cn"][:60],
                "date": item["date"],
                "source": item["source"],
                "link": item["link"]
            }
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def send_email(items):
    pwd = os.environ.get("QQMAIL_PASSWORD", "")
    if not pwd:
        print("  ⏭️ 未配置邮箱")
        return
    from email.mime.text import MIMEText
    import smtplib
    now = datetime.now(BJT).strftime("%H:%M")
    body = f"🆕 {len(items)}条新游戏新闻 ({now})\n\n"
    for i, it in enumerate(items, 1):
        body += f"{i}. {it['title_cn']}\n"
        body += f"   📡 {it['source']}"
        if it['link']: body += f"  🔗 {it['link']}"
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
    except Exception as e:
        print(f"  ❌ 邮件失败: {e}")

def main():
    now = datetime.now(BJT)
    print(f"🔍 {now.strftime('%Y-%m-%d %H:%M')} 实时扫描...")
    existing = get_existing_fingerprints()
    new_items = []
    seen = set()

    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:2]:  # 每个源只取最新的2条
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                fp = fingerprint(title)
                if fp in existing:
                    continue
                summary = re.sub(r'<[^>]+>', '', entry.get("summary","") or "")
                summary = html.unescape(summary)[:100]
                link = entry.get("link", "")
                title_cn = translate(title)
                summary_cn = translate(summary)
                new_items.append({
                    "fp": fp, "title_cn": title_cn,
                    "source": src["source"], "link": link,
                    "summary": summary_cn,
                    "date": now.strftime("%Y-%m-%d")
                })
        except Exception as e:
            print(f"  ⏭️ {src['source']}: {e}")

    if new_items:
        print(f"\n🆕 发现 {len(new_items)} 条新新闻:")
        for it in new_items:
            print(f"  • {it['title_cn'][:40]}  [{it['source']}]")
        append_history(new_items)
        send_email(new_items)
    else:
        print("  ✅ 无新新闻")

if __name__ == "__main__":
    main()
