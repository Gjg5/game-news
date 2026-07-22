"""实时监控 → 存入新闻池（仅收集，不发邮件，每日生成时统一发）"""
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

# 非游戏关键词过滤
NON_GAME_KW = ["手机","芯片","处理器","半导体","固态","硬盘","汽车","新能源","显示器",
               "笔记本","平板","耳机","音箱","充电","空调","冰箱","洗衣机","电视","投影",
               "路由器","操作系统","AI对话","大模型","评测","开箱","红包","优惠"]

GAME_KW = ["游戏","gam","play","电竞","PS5","Xbox","Switch","Steam","任天堂","索尼","微软",
           "腾讯","网易","米哈游","更新","版本","赛季","联动","上线","发售","测试",
           "收购","裁员","投资","主机","显卡","GPU","光追","虚幻","手游","端游",
           "赛事","战队","选手","IGN","评分","预告","皮肤","DLC","3A","大作"]

def is_gaming(text):
    t = (text or "").lower()
    for kw in NON_GAME_KW:
        if kw.lower() in t:
            return False
    for kw in GAME_KW:
        if kw.lower() in t:
            return True
    return False

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
    """不再实时发邮件，仅在每日8:00/20:00统一发送"""
    pass  # 已禁用，由 game_news_generator.py 在每日生成时发送

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
                # 非游戏内容过滤
                if not is_gaming(title):
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
