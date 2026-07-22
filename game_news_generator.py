# -*- coding: utf-8 -*-
"""
游戏新闻自动生成器 - 全自动版本
从多个游戏媒体RSS抓取最新新闻，生成公众号竖版长图
"""
import os, sys, json, re, html, smtplib, hashlib
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

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

# === RSS 新闻源（国内 + 海外英文源，英文会自动翻译成中文）===
RSS_SOURCES = [
    # 国内游戏媒体
    {"url": "https://www.3dmgame.com/rss/news.xml", "source": "3DM"},
    {"url": "http://www.gamersky.com/rss/news.xml", "source": "游民星空"},
    {"url": "https://www.ithome.com/rss/", "source": "IT之家", "filter_game": True},
    {"url": "http://www.gamelook.com.cn/feed/", "source": "GameLook"},
    # 海外游戏媒体（英文自动翻译中文）
    {"url": "https://feeds.feedburner.com/ign/all", "source": "IGN"},
    {"url": "https://www.gamespot.com/feeds/mashup/", "source": "GameSpot"},
    {"url": "https://www.pcgamer.com/rss/", "source": "PC Gamer"},
    {"url": "https://www.gematsu.com/feed", "source": "Gematsu"},
    {"url": "https://www.vg247.com/feed", "source": "VG247"},
]

# 非游戏关键词（含这些词的标题直接排除）
NON_GAME_KEYWORDS = [
    "手机", "芯片", "处理器", "半导体", "固态", "硬盘", "内存条", "DDR",
    "摄像头", "传感器", "汽车", "新能源", "自动驾驶", "显示器", "笔记本",
    "平板", "耳机", "音箱", "充电", "电池", "快充", "数码", "家电",
    "空调", "冰箱", "洗衣机", "电视", "投影", "路由器", "WiFi",
    "操作系统", "鸿蒙OS", "iOS", "Android", "系统更新", "大模型",
    "AI绘画", "AI写作", "AI对话", "ChatGPT", "大语言模型",
    "评测", "开箱", "体验", "壁纸", "红包", "优惠", "折扣",
    "deal", "sale", "discount", "coupon", "review",
]

# 游戏相关关键词（标题或摘要必须包含至少一个才算游戏新闻）
GAME_REQUIRED_KEYWORDS = [
    "游戏", "gam", "play", "游", "电竞", "e-sport", "console",
    "PS5", "PS4", "Xbox", "Switch", "Steam", "Epic", "PC",
    "任天堂", "索尼", "微软", "腾讯", "网易", "米哈游",
    "Nintendo", "Sony", "Microsoft", "PlayStation",
    "更新", "版本", "赛季", "联动", "上线", "发售", "测试",
    "update", "patch", "season", "release", "launch",
    "DLC", "DLC", "资料片", "expansion",
    "收购", "裁员", "投资", "并购", "acquisition", "layoff", "invest",
    "主机", "显卡", "GPU", "光追", "虚幻", "Unreal", "Unity",
    "手游", "端游", "页游", "MMO", "RPG", "FPS", "ARPG",
    "赛事", "比赛", "冠军", "战队", "选手", "tournament",
    "IGN", "评分", "评测", "review", "score",
    "预告", "trailer", "实机", "gameplay", "演示",
    "角色", "皮肤", "武器", "地图", "mode", "模式",
    "独立", "indie", "3A", "大作",
]

# 英文→中文翻译缓存
_translation_cache = {}


class NewsHistory:
    """已发送新闻历史记录，用于去重和展示"""

    def __init__(self, filepath="news_history.json"):
        self.filepath = filepath
        self.entries = {}  # fingerprint -> {"title": str, "date": str, "source": str}
        self._load()

    def _fingerprint(self, title):
        """对标题生成唯一指纹（归一化后MD5）"""
        clean = re.sub(r"[^\w\u4e00-\u9fff]", "", title).lower().strip()
        return hashlib.md5(clean.encode("utf-8")).hexdigest()

    def _load(self):
        """加载历史记录"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 清除旧格式（只有MD5指纹，没有实际标题）
                if "fingerprints" in data:
                    print(f"  🧹 清除旧格式数据（{len(data['fingerprints'])} 条无标题指纹）")
                    self.entries = {}
                    return
                self.entries = data.get("entries", {})
                print(f"  📚 已加载 {len(self.entries)} 条历史新闻")
            except Exception as e:
                print(f"  ⚠️ 历史记录加载失败: {e}")
                self.entries = {}

    def is_duplicate(self, title):
        """检查是否已发过"""
        return self._fingerprint(title) in self.entries

    def add(self, title, date_str="", source="", link=""):
        """标记为已发送"""
        fp = self._fingerprint(title)
        if fp not in self.entries:
            self.entries[fp] = {"title": title[:60], "date": date_str, "source": source, "link": link}

    def add_batch(self, entries_list, date_str="", source="", link=""):
        """批量标记"""
        for item in entries_list:
            t = item if isinstance(item, str) else item.get("title", "")
            s = source or (item.get("source", "") if not isinstance(item, str) else "")
            l = link or (item.get("link", "") if not isinstance(item, str) else "")
            self.add(t, date_str, s, l)

    def save(self):
        """保存到文件"""
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump({"entries": self.entries}, f, ensure_ascii=False, indent=2)
        print(f"  💾 已保存 {len(self.entries)} 条新闻到 {self.filepath}")

    def generate_history_html(self, output_path="history.html"):
        """生成历史记录展示页"""
        now = datetime.now(BJT).strftime("%Y-%m-%d %H:%M")
        rows = sorted(self.entries.items(), key=lambda x: x[1]["date"], reverse=True)

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>游戏新闻 · 已发送历史</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "PingFang SC", sans-serif; background:#f5f5f5; padding:20px; }}
.header {{ text-align:center; padding:24px; background:linear-gradient(135deg,#d0021b,#a00015); color:white; border-radius:12px; margin-bottom:20px; }}
.header h1 {{ font-size:22px; }} .header p {{ font-size:13px; opacity:0.8; margin-top:4px; }}
table {{ width:100%; border-collapse:collapse; background:white; border-radius:8px; overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
th {{ background:#d0021b; color:white; padding:10px 12px; text-align:left; font-size:13px; }}
td {{ padding:10px 12px; border-bottom:1px solid #eee; font-size:13px; color:#333; }}
tr:hover td {{ background:#fff5f5; }}
.date {{ color:#999; font-size:12px; white-space:nowrap; }}
.num {{ color:#bbb; font-size:12px; width:40px; text-align:center; }}
.source {{ color:#d0021b; font-size:12px; }}
.footer {{ text-align:center; color:#bbb; font-size:12px; padding:20px; }}
</style></head>
<body>
<div class="header"><h1>📚 游戏新闻 · 已发送历史</h1><p>共 {len(self.entries)} 条 · 更新于 {now}</p></div>
<table>
<tr><th class="num">#</th><th>新闻标题</th><th>来源</th><th>日期</th></tr>"""
        for i, (fp, info) in enumerate(rows, 1):
            title = info.get("title", fp)
            date = info.get("date", "?")
            source = info.get("source", "?")
            link = info.get("link", "")
            title_cell = f'<a href="{link}" target="_blank" rel="noopener">{title}</a>' if link else title
            html += f'<tr><td class="num">{i}</td><td>{title_cell}</td><td class="source">{source}</td><td class="date">{date}</td></tr>\n'
        html += """</table>
<div class="footer">GitHub Actions 自动生成 · 每日8:00/20:00更新</div>
</body></html>"""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  🌐 历史页面已生成: {output_path}")

    def count(self):
        return len(self.entries)


def translate_to_chinese(text):
    """将英文文本翻译成中文（直接请求，不依赖第三方库），带缓存"""
    if not text or has_chinese(text):
        return text
    if text in _translation_cache:
        return _translation_cache[text]

    # 1. 有道翻译 Web API（免费，国内网络好）
    try:
        import hashlib, urllib.request, urllib.parse, random
        app_key = "0e6e7d1a4b7f3c2d"  # 公共测试key
        salt = str(random.randint(10000, 99999))
        sign_str = app_key + text[:500] + salt + "yG7dH2kL9pQ4wR8x"
        sign = hashlib.md5(sign_str.encode()).hexdigest()
        data = urllib.parse.urlencode({
            "q": text[:500], "from": "EN", "to": "zh-CHS",
            "appKey": app_key, "salt": salt, "sign": sign
        }).encode()
        req = urllib.request.Request(
            "https://openapi.youdao.com/api", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
        if resp.get("errorCode") == "0" and resp.get("translation"):
            t = resp["translation"][0]
            if any('\u4e00' <= c <= '\u9fff' for c in t):
                _translation_cache[text] = t
                return t
    except Exception:
        pass

    # 2. Google翻译（备用）
    for attempt in range(2):
        try:
            from deep_translator import GoogleTranslator
            translated = GoogleTranslator(source="en", target="zh-CN").translate(text[:500])
            if translated and any('\u4e00' <= c <= '\u9fff' for c in translated):
                _translation_cache[text] = translated
                return translated
        except Exception:
            import time as _t
            _t.sleep(1)

    return text  # 翻译失败则保留原文

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


def is_gaming_related(title, summary):
    """判断内容是否与游戏相关"""
    text = (title + " " + summary).lower()
    # 先排除明显非游戏内容
    for kw in NON_GAME_KEYWORDS:
        if kw.lower() in text:
            return False
    # 必须有游戏关键词
    for kw in GAME_REQUIRED_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


def has_chinese(text):
    """判断是否包含中文字符"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def fetch_news(history=None):
    """从RSS源获取最新游戏新闻，英文自动翻译，跳过已发送的重复内容"""
    all_entries = []
    seen_titles = set()
    skip_count = 0

    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:10]:
                title = entry.get("title", "").strip()
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)

                # 非游戏内容过滤
                if not is_gaming_related(title, ""):
                    continue

                # IT之家等综合站需要严格过滤
                if src.get("filter_game") and not has_chinese(title):
                    continue

                # 去重检查
                if history and history.is_duplicate(title):
                    skip_count += 1
                    continue

                summary = entry.get("summary", entry.get("description", "")).strip()
                summary = re.sub(r'<[^>]+>', '', summary)
                summary = html.unescape(summary)[:120]

                # 英文标题和摘要翻译成中文
                title_cn = translate_to_chinese(title)
                summary_cn = translate_to_chinese(summary)

                published = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_time = None
                if published:
                    from time import mktime
                    pub_time = datetime.fromtimestamp(mktime(published), tz=timezone.utc)

                all_entries.append({
                    "title": title_cn,
                    "summary": summary_cn,
                    "source": src["source"],
                    "time": pub_time,
                    "link": entry.get("link", ""),
                    "title_raw": title,  # 保存原始标题用于去重
                })
        except Exception as e:
            print(f"  [跳过] {src['source']}: {e}")
            continue

    if skip_count > 0:
        print(f"  🔄 跳过 {skip_count} 条已发送过的新闻")

    # 按时间排序
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

    # 补充未分类条目
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

    # 同时也复制一份到根目录（供GitHub Pages部署使用）
    now_bj = datetime.now(BJT)
    filename = f"game_news_{now_bj.strftime('%Y%m%d_%H%M')}.png"
    filepath = os.path.join(OUTPUT_DIR, filename)
    img.save(filepath, "PNG")
    root_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    import shutil
    shutil.copy2(filepath, root_path)
    print(f"✅ 图片已保存: {filepath}")
    print(f"   根目录副本: {root_path}")
    print(f"   尺寸: {WIDTH}x{total_height}")
    return filepath, root_path


def send_email(filepath, edition, date_str):
    """通过QQ邮箱SMTP发送新闻图片"""
    password = os.environ.get("QQMAIL_PASSWORD", "")
    if not password:
        print("  ⏭️ 未设置QQMAIL_PASSWORD环境变量，跳过邮件发送")
        return

    receiver = "2586555901@qq.com"
    sender = "2586555901@qq.com"

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = f"【游戏{edition}】{date_str}"

    body = f"您好，以下是今日游戏{edition}，请查收附件图片。"
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(filepath, "rb") as f:
        attachment = MIMEBase("application", "octet-stream")
        attachment.set_payload(f.read())
        encoders.encode_base64(attachment)
        attachment.add_header("Content-Disposition", f"attachment; filename={os.path.basename(filepath)}")
        msg.attach(attachment)

    try:
        import smtplib
        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(sender, password)
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print(f"  ✅ 邮件已发送至 {receiver}")
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")


def main():
    now_bj = datetime.now(BJT)
    hour = now_bj.hour
    edition = "早报" if hour < 14 else "晚报"
    date_str = now_bj.strftime("%Y年%m月%d日")
    weekday_map = {0: "星期一", 1: "星期二", 2: "星期三", 3: "星期四", 4: "星期五", 5: "星期六", 6: "星期日"}
    date_weekday = weekday_map[now_bj.weekday()]

    print(f"🕐 {date_str} {date_weekday} {edition}")
    print("📦 正在从新闻池读取...")

    # 读取新闻池
    pool_file = "news_pool.json"
    if not os.path.exists(pool_file):
        print("  ⏭️ 新闻池为空")
        return
    with open(pool_file, "r", encoding="utf-8") as f:
        pool = json.load(f)

    if not pool:
        print("  ⏭️ 新闻池为空")
        return

    print(f"  📦 池中共 {len(pool)} 条新闻")

    # 取最新最多20条
    entries = pool[:20]
    print(f"  📰 本次使用 {len(entries)} 条")

    # 分类（从fetch_news移过来的分类逻辑）
    categorized = categorize_news([
        {"title": e["title"], "summary": e.get("summary", ""),
         "source": e.get("source", ""), "link": e.get("link", "")}
        for e in entries
    ])

    # 组装 news_data
    category_order = ["🔥 重磅头条", "🎮 新游动态", "🏢 行业风云", "📡 技术与平台"]
    news_data = {"category_order": [], "categories": {}}
    for cat in category_order:
        items = categorized.get(cat, [])
        if items:
            news_data["category_order"].append(cat)
            news_data["categories"][cat] = [(item["title"][:30], item["summary"][:50]) for item in items]

    if not news_data["categories"]:
        print("  ⏭️ 无可用的新闻分类")
        return

    all_sources = list(dict.fromkeys(e.get("source", "") for e in entries))
    footer_sources = "、".join(all_sources[:10])

    print(f"📊 分类: {', '.join(f'{k}:{len(v)}条' for k,v in news_data['categories'].items())}")
    print("🎨 生成图片...")

    filepath, root_path = generate_image(news_data, edition, date_str, date_weekday, footer_sources)

    print("📧 发送邮件...")
    send_email(filepath, edition, date_str)

    # 已用新闻 → 移入历史库
    used_fps = {e.get("fp", "") for e in entries if e.get("fp")}
    history_path = "news_history.json" if os.environ.get("GITHUB_ACTIONS") else ".workbuddy/news_history.json"
    history = NewsHistory(history_path)

    date_short = now_bj.strftime("%Y-%m-%d")
    for e in entries:
        title = e.get("title", "")
        source = e.get("source", edition)
        link = e.get("link", "")
        history.add(title, date_short, source, link)
    history.save()
    history.generate_history_html("history.html")

    # 从新闻池中删除已用的
    if used_fps:
        remaining = [item for item in pool if item.get("fp") not in used_fps]
        with open(pool_file, "w", encoding="utf-8") as f:
            json.dump(remaining, f, ensure_ascii=False, indent=2)
        print(f"  🗑️ 从新闻池移除 {len(entries)} 条，剩余 {len(remaining)} 条")

    # 更新池展示页
    try:
        import subprocess
        subprocess.run(["python", "realtime_monitor.py", "--generate-pool-only"],
                       capture_output=True)
    except:
        pass

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
<img src="{os.path.basename(filepath)}" alt="游戏新闻">
<div class="footer">资讯来源：{footer_sources}<br>GitHub Actions 自动生成</div>
</body></html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ index.html 已更新")


if __name__ == "__main__":
    main()
