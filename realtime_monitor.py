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

# 非游戏关键词过滤（含这些词直接排除）
NON_GAME_KW = ["手机","芯片","处理器","半导体","固态","硬盘","汽车","新能源","显示器",
               "笔记本","平板","耳机","音箱","充电","空调","冰箱","洗衣机","电视","投影",
               "路由器","操作系统","AI对话","大模型","评测","开箱","红包","优惠",
               "传感器","合资","半导体","物流","快递","发货","退款","英特尔","酷睿",
               "AMD","CPU","内存","SSD","NAS","5G","6G","WiFi","蓝牙","USB",
               "电动汽车","自动驾驶","激光雷达","光伏","锂电","电池","充电桩",
               "Mac","macOS","iOS","Android","鸿蒙","Claude","Copilot",
               "视觉传感器","制造业","工业","制造","投资","股票","基金","理财",
               "家电","空调","冰箱","洗衣机","扫地机","吸尘器","厨房"]

GAME_KW = ["游戏","gam","play","电竞","PS5","Xbox","Switch","Steam","任天堂","索尼","微软",
           "腾讯","网易","米哈游","更新","版本","赛季","联动","上线","发售","测试",
           "收购","裁员","投资","主机","显卡","GPU","光追","虚幻","手游","端游",
           "赛事","战队","选手","IGN","评分","预告","皮肤","DLC","3A","大作",
           "PlayStation","Nintendo","PC","console","trailer","gameplay",
           "评测","角色","武器","地图","皮肤","武器","战斗","动作","冒险",
           "RPG","FPS","ARPG","MMO","MOBA","格斗","射击","竞速","模拟",
           "Steam Deck","Switch 2","PS4","PS5 Pro","Xbox Series"]

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

def generate_pool_html(items):
    """生成新闻池展示页"""
    now = datetime.now(BJT).strftime("%m/%d %H:%M")
    rows = """"""
    for i, item in enumerate(items, 1):
        title = item.get("title", "")
        source = item.get("source", "")
        link = item.get("link", "")
        date = item.get("date", "")
        title_cell = f'<a href="{link}" target="_blank">{title}</a>' if link else title
        rows += f'<tr><td class="num">{i}</td><td>{title_cell}</td><td class="src">{source}</td><td class="date">{date}</td></tr>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>游戏新闻 · 待发池</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,"PingFang SC",sans-serif; background:#f5f5f5; padding:20px; }}
.header {{ text-align:center; padding:24px; background:linear-gradient(135deg,#1a73e8,#0d47a1); color:white; border-radius:12px; margin-bottom:20px; }}
.header h1 {{ font-size:22px; }} .header p {{ font-size:13px; opacity:0.8; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
th {{ background:#1a73e8; color:white; padding:10px 12px; text-align:left; font-size:13px; }}
td {{ padding:10px 12px; border-bottom:1px solid #eee; font-size:13px; color:#333; }}
tr:hover td {{ background:#e8f0fe; }}
.date {{ color:#999; font-size:12px; white-space:nowrap; }}
.num {{ color:#bbb; font-size:12px; width:40px; text-align:center; }}
.src {{ color:#1a73e8; font-size:12px; }}
.footer {{ text-align:center; color:#bbb; font-size:12px; padding:20px; }}
a {{ color:#333; text-decoration:none; }} a:hover {{ color:#1a73e8; text-decoration:underline; }}
.badge {{ display:inline-block; background:#1a73e8; color:white; border-radius:10px; padding:2px 8px; font-size:11px; }}
</style></head>
<body>
<div class="header"><h1>📦 游戏新闻 · 待发池</h1><p>共 {len(items)} 条 · 更新于 {now} · 每日8:00/20:00生成长图后清空</p></div>
<table>
<tr><th class="num">#</th><th>新闻标题</th><th>来源</th><th>入库时间</th></tr>
{rows}</table>
<div class="footer">GitHub Actions 实时监控每30分钟更新</div>
</body></html>"""
    with open("pool.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  🌐 pool.html 已更新")

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
                # 非游戏内容过滤（IT之家等综合站严格过滤）
                if not is_gaming(title):
                    continue
                # IT之家只有标题明显有游戏关键词才收
                if src["source"] == "IT之家" and not has_chinese(title):
                    continue
                if src["source"] == "IT之家" and not any(kw in (title or "") for kw in ["游戏","PS5","Xbox","Switch","Steam","电竞","Steam Deck","PS4","Xbox Series"]):
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
        pool = new_items + pool
        save_pool(pool)
        print(f"\n🆕 {len(new_items)} 条 → 新闻池 (共{len(pool)}条)")
    else:
        print(f"  ✅ 无新新闻 (池中{len(pool)}条)")
        save_pool(pool)
    generate_pool_html(pool)

if __name__ == "__main__":
    import sys
    if "--generate-pool-only" in sys.argv:
        # 仅重新生成 pool.html（被每日生成器调用）
        pool = load_pool()
        generate_pool_html(pool)
    else:
        main()
