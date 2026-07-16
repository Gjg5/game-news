# -*- coding: utf-8 -*-
"""
游戏新闻自动生成器 - 全自动版本
从多个游戏媒体RSS抓取最新新闻，生成公众号竖版长图
"""
import os, sys, json, re, html
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import requests
import feedparser

from PIL import Image, ImageDraw, ImageFont

# ============ 配置 ============
WIDTH = 750
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"
if not os.path.exists(FONT_PATH):
    FONT_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    FONT_BOLD_PATH = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
if not os.path.exists(FONT_PATH):
    # Try to find any CJK font
    import glob
    candidates = glob.glob("/usr/share/fonts/**/*.ttc", recursive=True) + \
                 glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    for c in candidates:
        if "cjk" in c.lower() or "noto" in c.lower() or "wqy" in c.lower() or "chinese" in c.lower():
            FONT_PATH = c
            FONT_BOLD_PATH = c
            break
    if not os.path.exists(FONT_PATH):
        FONT_PATH = candidates[0] if candidates else FONT_PATH
        FONT_BOLD_PATH = candidates[0] if candidates else FONT_BOLD_PATH

EDITION = "早报"

BJT = timezone(timedelta(hours=8))

OUTPUT_DIR = "outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# === RSS 新闻源 ===
RSS_SOURCES = [
    # 国内游戏媒体
    {"url": "https://www.3dmgame.com/rss/news.xml", "source": "3DM"},
    {"url": "http://www.gamersky.com/rss/news.xml", "source": "游民星空"},
    {"url": "https://www.ithome.com/rss/", "source": "IT之家"},
    {"url": "https://feed.smzdm.com/", "source": "什么值得买"},
    # 海外游戏媒体
    {"url": "https://feeds.feedburner.com/ign/all", "source": "IGN"},
    {"url": "https://www.gamespot.com/feeds/mashup/", "source": "GameSpot"},
    {"url": "https://www.pcgamer.com/rss/", "source": "PC Gamer"},
    {"url": "https://www.gematsu.com/feed", "source": "Gematsu"},
    {"url": "https://www.eurogamer.net/feed", "source": "Eurogamer"},
    {"url": "https://www.vg247.com/feed", "source": "VG247"},
]

# 颜色方案
BG_COLOR = (248, 248, 248)
CARD_BG = (255, 255, 255)
TITLE_COLOR = (26, 26, 26)
TEXT_COLOR = (89, 89, 89)
ACCENT_COLOR = (208, 2, 27)
HEADER_TEXT = (255, 255, 255)
CATEGORY_BG = (255, 240, 240)
LINE_COLOR = (230, 230, 230)
DATE_COLOR = (180, 180, 180)

# 分类关键词
CATEGORY_KEYWORDS = {
    "🔥 重磅头条": ["发布", "公布", "官宣", "首发", "上线", "发售", "launch", "announce", "release", "reveal",
                       "重磅", "突发", "头条", "首曝", "正式", "公测", "开服"],
    "🎮 新游动态": ["新游", "新作", "预告", "试玩", "demo", "DLC", "资料片", "更新", "版本", "expansion",
                       "new game", "preview", "beta", "测试", "试玩", "前瞻", "体验"],
    "🏢 行业风云": ["收购", "裁员", "关停", "破产", "财报", "收入", "起诉", "和解", "投资", "上市",
                       "acquisition", "layoff", "closure", "revenue", "lawsuit", "投资", "融资", "合作"],
    "📡 技术与平台": ["显卡", "GPU", "主机", "PS5", "Xbox", "Switch", "Steam", "Epic", "引擎", "AI",
                        "技术", "平台", "虚幻", "Unity", "鸿蒙", "云游戏", "串流"],
}


def fetch_news():
    """从RSS源获取最新游戏新闻"""
    all_entries = []
    seen_titles = set()

    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:8]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r'<[^>]+>', '', summary)
                summary = html.unescape(summary)[:100]

                published = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_time = None
                if published:
                    from time import mktime
                    pub_time = datetime.fromtimestamp(mktime(published), tz=timezone.utc)

                all_entries.append({
                    "title": title,
                    "summary": summary,
                    "source": src["source"],
                    "time": pub_time,
                    "link": entry.get("link", ""),
                })
        except Exception as e:
            print(f"  [跳过] {src['source']}: {e}")
            continue

    # 按时间排序，取最新的
    all_entries.sort(key=lambda x: x["time"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return all_entries[:40]


def categorize_news(entries, max_per_cat=5):
    """将新闻按关键词分类"""
    categories = defaultdict(list)
    categorized_titles = set()

    for entry in entries:
        title_lower = entry["title"].lower()
        text = title_lower + " " + entry["summary"].lower()

        best_cat = None
        best_score = 0

        for cat, keywords in CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.lower() in text)
            if score > best_score:
                best_score = score
                best_cat = cat

        if best_cat and len(categories[best_cat]) < max_per_cat:
            categories[best_cat].append(entry)
            categorized_titles.add(entry["title"])

    # 补充：未分类的归入"新游动态"或"行业风云"
    misc_cats = ["🎮 新游动态", "🏢 行业风云"]
    for entry in entries:
        if entry["title"] not in categorized_titles:
            for mc in misc_cats:
                if len(categories[mc]) < max_per_cat:
                    categories[mc].append(entry)
                    categorized_titles.add(entry["title"])
                    break

    return categories


def draw_rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def wrap_text(text, font, max_width, draw):
    if not text:
        return []
    lines = []
    remaining = text
    while remaining:
        low, high = 0, len(remaining)
        best = 0
        while low <= high:
            mid = (low + high) // 2
            line = remaining[:mid]
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
            if w <= max_width:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        if best == 0:
            best = 1
        lines.append(remaining[:best])
        remaining = remaining[best:]
    return lines


def generate_image(news_data, edition, date_str, date_weekday, footer_sources):
    """生成新闻长图"""
    # 临时图片取字体尺寸
    temp_img = Image.new("RGB", (WIDTH, 100), BG_COLOR)
    temp_draw = ImageDraw.Draw(temp_img)

    try:
        fonts = {
            "title": ImageFont.truetype(FONT_BOLD_PATH, 36),
            "date": ImageFont.truetype(FONT_PATH, 22),
            "category": ImageFont.truetype(FONT_BOLD_PATH, 28),
            "card_title": ImageFont.truetype(FONT_BOLD_PATH, 24),
            "card_summary": ImageFont.truetype(FONT_PATH, 20),
            "footer": ImageFont.truetype(FONT_PATH, 18),
        }
    except:
        fonts = {
            "title": ImageFont.load_default(),
            "date": ImageFont.load_default(),
            "category": ImageFont.load_default(),
            "card_title": ImageFont.load_default(),
            "card_summary": ImageFont.load_default(),
            "footer": ImageFont.load_default(),
        }

    # 计算高度
    header_height = 180
    padding = 20
    section_gap = 25
    card_gap = 12
    bottom_padding = 50
    footer_height = 60
    card_w = WIDTH - 50
    text_max_w = card_w - 40
    line_title_h = 30
    line_summary_h = 26

    total_height = header_height + padding + 10
    card_heights = []

    for cat_name in news_data["category_order"]:
        items = news_data["categories"].get(cat_name, [])
        total_height += 55
        for title, summary in items:
            tl = wrap_text(title, fonts["card_title"], text_max_w, temp_draw)[:1]
            sl = wrap_text(summary, fonts["card_summary"], text_max_w, temp_draw)[:3]
            content_h = 12 + len(tl) * line_title_h + 6 + len(sl) * line_summary_h + 12
            ch = max(70, content_h)
            card_heights.append((ch, tl, sl))
            total_height += ch + card_gap
        total_height += section_gap - card_gap

    total_height += bottom_padding + footer_height

    # 创建最终图片
    img = Image.new("RGB", (WIDTH, total_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 头部
    draw.rectangle([0, 0, WIDTH, 180], fill=ACCENT_COLOR)
    title_text = f"游戏{edition}"
    bbox = draw.textbbox((0, 0), title_text, font=fonts["title"])
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 45), title_text, fill=HEADER_TEXT, font=fonts["title"])

    date_text = f"{date_str} · {date_weekday}"
    bbox = draw.textbbox((0, 0), date_text, font=fonts["date"])
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 110), date_text, fill=(255, 200, 200), font=fonts["date"])

    sub_text = "今日游戏圈新动态一览"
    bbox = draw.textbbox((0, 0), sub_text, font=fonts["date"])
    draw.text(((WIDTH - (bbox[2] - bbox[0])) // 2, 142), sub_text, fill=(255, 220, 220), font=fonts["date"])

    # 内容
    y = 180 + 30
    card_idx = 0
    card_gap_actual = 12

    for cat_name in news_data["category_order"]:
        items = news_data["categories"].get(cat_name, [])
        if not items:
            continue

        # 分类标签
        cat_bbox = draw.textbbox((0, 0), cat_name, font=fonts["category"])
        tag_px = 12
        tag_x = 30
        draw_rounded_rect(draw, (tag_x, y, tag_x + (cat_bbox[2] - cat_bbox[0]) + tag_px * 2, y + 40), radius=6, fill=CATEGORY_BG)
        draw.text((tag_x + tag_px, y + 5), cat_name, fill=ACCENT_COLOR, font=fonts["category"])
        y += 55

        for title, summary in items:
            ch, title_lines, summary_lines = card_heights[card_idx]
            cx = 25
            cw = WIDTH - 50

            draw_rounded_rect(draw, (cx, y, cx + cw, y + ch), radius=10, fill=CARD_BG)
            draw_rounded_rect(draw, (cx, y + 10, cx + 5, y + ch - 10), radius=3, fill=ACCENT_COLOR)

            tx = cx + 22
            ty = y + 12
            for line in title_lines:
                draw.text((tx, ty), line, fill=TITLE_COLOR, font=fonts["card_title"])
                ty += line_title_h
            ty += 6
            for line in summary_lines:
                draw.text((tx, ty), line, fill=TEXT_COLOR, font=fonts["card_summary"])
                ty += line_summary_h

            y += ch + card_gap_actual
            card_idx += 1

        y += 25 - card_gap_actual

    # 底部
    y += 10
    draw.line([(100, y), (WIDTH - 100, y)], fill=LINE_COLOR, width=1)
    y += 20
    ft = f"资讯来源：{footer_sources}"
    fb = draw.textbbox((0, 0), ft, font=fonts["footer"])
    draw.text(((WIDTH - (fb[2] - fb[0])) // 2, y), ft, fill=DATE_COLOR, font=fonts["footer"])

    now_bj = datetime.now(BJT)
    filename = f"game_news_{now_bj.strftime('%Y%m%d_%H%M')}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    img.save(filepath, "PNG")
    print(f"✅ 图片已保存: {filepath}")
    print(f"   尺寸: {WIDTH}x{total_height}")
    return filepath


def main():
    now_bj = datetime.now(BJT)
    hour = now_bj.hour
    edition = "早报" if hour < 14 else "晚报"
    date_str = now_bj.strftime("%Y年%m月%d日")
    weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
    date_weekday = weekday_map[now_bj.weekday()]

    print(f"🕐 {date_str} {date_weekday} {edition}")
    print("📡 正在抓取最新游戏新闻...")

    entries = fetch_news()
    print(f"   获取到 {len(entries)} 条新闻")

    categorized = categorize_news(entries)

    # 组装 news_data
    category_order = ["🔥 重磅头条", "🎮 新游动态", "🏢 行业风云", "📡 技术与平台"]
    news_data = {"category_order": [], "categories": {}}

    for cat in category_order:
        items = categorized.get(cat, [])
        if items:
            news_data["category_order"].append(cat)
            news_data["categories"][cat] = [(item["title"][:30], item["summary"][:50]) for item in items]

    # 统计来源
    all_sources = list(dict.fromkeys(e["source"] for e in entries if e.get("source")))
    footer_sources = "、".join(all_sources[:10])

    print(f"📊 分类统计: {', '.join(f'{k}:{len(v)}条' for k,v in news_data['categories'].items())}")
    print("🎨 正在生成图片...")

    filepath = generate_image(news_data, edition, date_str, date_weekday, footer_sources)

    # 生成 index.html
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>游戏新闻 {edition} - {date_str}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "PingFang SC", sans-serif; background:#f5f5f5; padding:16px; }}
.header {{ text-align:center; padding:24px; background:linear-gradient(135deg,#d0021b,#a00015); color:white; border-radius:12px; margin-bottom:16px; }}
.header h1 {{ font-size:22px; }} .header p {{ font-size:13px; opacity:0.8; margin-top:4px; }}
img {{ width:100%; border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,0.1); }}
.footer {{ text-align:center; color:#bbb; font-size:12px; padding:16px; }}
</style></head>
<body>
<div class="header"><h1>🎮 游戏{edition}</h1><p>{date_str} · {date_weekday}</p></div>
<img src="outputs/{os.path.basename(filepath)}" alt="游戏新闻">
<div class="footer">资讯来源：{footer_sources}<br>GitHub Actions 自动生成</div>
</body></html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ index.html 已更新")


if __name__ == "__main__":
    main()
