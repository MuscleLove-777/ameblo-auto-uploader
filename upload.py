# -*- coding: utf-8 -*-
"""
Ameba Blog (ameblo.jp) 画像自動投稿（GitHub Actions用）
公開Driveフォルダからgdownで画像取得 -> ランダム1枚をブログ記事として投稿 -> アップロード済みを記録
Selenium使用（Ameba公式APIなし）
"""
import sys
import json
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta

COOKIE_FILE = os.path.join(os.path.dirname(__file__), "ameblo_cookies.json")
AUTH_EXPIRED_EXIT_CODE = 20
DEFAULT_COOKIE_MIN_REMAINING_HOURS = 6
By = None
Keys = None
WebDriverWait = None
EC = None
create_driver = None
navigate_to_editor = None
human_delay = None
login_ameba = None


def load_selenium_helpers():
    """期限チェックだけの実行ではSeleniumを読み込まない。"""
    global By, Keys, WebDriverWait, EC
    global create_driver, navigate_to_editor, human_delay, login_ameba

    if By is not None:
        return

    from selenium.webdriver.common.by import By as SeleniumBy
    from selenium.webdriver.common.keys import Keys as SeleniumKeys
    from selenium.webdriver.support.ui import WebDriverWait as SeleniumWebDriverWait
    from selenium.webdriver.support import expected_conditions as SeleniumEC
    from ameblo_auth import create_driver as auth_create_driver
    from ameblo_auth import navigate_to_editor as auth_navigate_to_editor
    from ameblo_auth import human_delay as auth_human_delay
    from ameblo_auth import login_ameba as auth_login_ameba

    By = SeleniumBy
    Keys = SeleniumKeys
    WebDriverWait = SeleniumWebDriverWait
    EC = SeleniumEC
    create_driver = auth_create_driver
    navigate_to_editor = auth_navigate_to_editor
    human_delay = auth_human_delay
    login_ameba = auth_login_ameba


def cookie_auth_required():
    """CIではreCAPTCHAで止まるため、パスワードログインにフォールバックしない。"""
    return (
        os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
        or os.environ.get("AMEBLO_COOKIE_ONLY", "").lower() in ("1", "true", "yes")
    )


def check_cookie_freshness(min_remaining_hours=None):
    """Actions実行前にAmeba認証Cookieがまだ使えるかを軽く確認する。"""
    if min_remaining_hours is None:
        min_remaining_hours = int(
            os.environ.get("AMEBLO_COOKIE_MIN_REMAINING_HOURS", DEFAULT_COOKIE_MIN_REMAINING_HOURS)
        )

    if not os.path.exists(COOKIE_FILE):
        return False, "ameblo_cookies.json がありません"

    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            cookies = json.load(f)
    except Exception as e:
        return False, f"ameblo_cookies.json を読めません: {e}"

    if not isinstance(cookies, list) or not cookies:
        return False, "ameblo_cookies.json が空です"

    at_cookie = next((c for c in cookies if c.get("name") == "AT"), None)
    if not at_cookie:
        return False, "AT Cookie がありません。手動ログインでCookie再取得が必要です"

    expiry = at_cookie.get("expiry")
    if not expiry:
        return False, "AT Cookie に expiry がありません。手動ログインでCookie再取得が必要です"

    now = datetime.now(timezone.utc).timestamp()
    remaining_hours = (float(expiry) - now) / 3600
    expiry_jst = datetime.fromtimestamp(float(expiry), JST).strftime("%Y-%m-%d %H:%M JST")
    if remaining_hours < min_remaining_hours:
        return (
            False,
            f"AT Cookie 期限切れ/期限間近です。expiry={expiry_jst}, remaining={remaining_hours:.1f}h",
        )

    return True, f"AT Cookie OK: expiry={expiry_jst}, remaining={remaining_hours:.1f}h"


def login_with_cookies(driver):
    """保存済みCookieでログインする（reCAPTCHA回避）"""
    if not os.path.exists(COOKIE_FILE):
        print("Error: Cookie未保存。先に save_cookies.py を実行してください。")
        return False

    with open(COOKIE_FILE, "r") as f:
        cookies = json.load(f)

    # まずameba.jpにアクセスしてドメインを設定
    driver.get("https://www.ameba.jp/")
    human_delay(2, 3)

    # Cookieを追加
    for cookie in cookies:
        # sameSite属性の修正（Seleniumの互換性問題対策）
        if "sameSite" in cookie and cookie["sameSite"] not in ("Strict", "Lax", "None"):
            cookie["sameSite"] = "None"
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass  # ドメインが違うCookieはスキップ

    # blog.ameba.jpのCookieも設定
    driver.get("https://blog.ameba.jp/")
    human_delay(2, 3)
    for cookie in cookies:
        if "sameSite" in cookie and cookie["sameSite"] not in ("Strict", "Lax", "None"):
            cookie["sameSite"] = "None"
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass

    # ブログ管理ページにアクセスしてログイン確認
    driver.get("https://blog.ameba.jp/ucs/top.do")
    human_delay(3, 5)

    if "signin" in driver.current_url or "login" in driver.current_url or "auth.user.ameba" in driver.current_url:
        if cookie_auth_required():
            print("Error: Cookieログインに失敗しました。ActionsではreCAPTCHA回避のためパスワードログインを行いません。")
            print("save_cookies.py でCookieを再取得し、GitHub Secret AMEBLO_COOKIES を更新してください。")
            return False

        print("Warning: Cookieが期限切れです。パスワードログインを試行します...")
        username = os.environ.get("AMEBLO_USERNAME", "")
        password = os.environ.get("AMEBLO_PASSWORD", "")
        if username and password:
            try:
                if login_ameba(driver, username, password):
                    # ログイン成功後、まだ認証ページにいないことを再確認
                    current = driver.current_url
                    if "signin" in current or "auth.user.ameba" in current:
                        print("Error: login_ameba成功判定だがまだ認証ページ上。ログイン失敗。")
                        return False
                    print("パスワードログイン成功! 新しいCookieを保存します...")
                    new_cookies = driver.get_cookies()
                    with open(COOKIE_FILE, "w") as f:
                        json.dump(new_cookies, f, indent=2)
                    return True
                else:
                    print("Error: パスワードログインも失敗しました。")
                    return False
            except Exception as e:
                print(f"Error: パスワードログイン中にエラー: {e}")
                return False
        else:
            print("Error: AMEBLO_USERNAME/AMEBLO_PASSWORD が設定されていません。")
            print("save_cookies.py を再実行してください。")
            return False

    print("Cookieログイン成功!")
    return True

JST = timezone(timedelta(hours=9))

# --- 環境変数 ---
GDRIVE_FOLDER_ID = os.environ.get("GDRIVE_FOLDER_ID_AMEBLO", "")

PATREON_LINK = "https://www.patreon.com/c/MuscleLove?utm_source=ameblo"
X_LINK = "https://x.com/MuscleGirlLove7?utm_source=ameblo"
X_HANDLE = "@MuscleGirlLove7"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
UPLOADED_LOG = "uploaded_ameblo.json"

# --- MuscleLove バックリンクプール（フィットネス系のみ。ameblo規約配慮でアダルト系は除外） ---
ML_BACKLINK_POOL_FITNESS = [
    ("https://musclelove-777.github.io/muscle-meal-girls/", "筋肉女子のマッスルメシ"),
    ("https://musclelove-777.github.io/runners-lab/", "ランナーラボ"),
    ("https://musclelove-777.github.io/armwrestling-girls-navi/", "腕相撲女子ナビ"),
    ("https://musclelove-777.github.io/physique-girls-navi/", "フィジーク女子ナビ"),
    ("https://musclelove-777.github.io/fighting-girls-navi/", "格闘技女子ナビ"),
    ("https://musclelove-777.github.io/joshi-prowrestling-navi/", "女子プロレスナビ"),
    ("https://musclelove-777.github.io/female-physique-queens/", "Female Physique Queens"),
    ("https://musclelove-777.github.io/network/fitness/", "全Fitness Network 15サイト一覧"),
    ("https://musclelove-777.github.io/network/academy/", "MuscleLove Academy 77サイト"),
]


def build_backlink_block():
    """MuscleLoveフィットネス系サイトへのバックリンクHTMLブロックを生成（ランダム3件）"""
    k = min(3, len(ML_BACKLINK_POOL_FITNESS))
    selected = random.sample(ML_BACKLINK_POOL_FITNESS, k=k)
    items = " | ".join([f'<a href="{u}" target="_blank" rel="noopener">{n}</a>' for u, n in selected])
    return (
        "\n<br/><br/>\n"
        "<!-- ML_BACKLINK -->\n"
        f'<small style="color:#888;">💡 関連サイト：{items}</small>\n'
        "<!-- /ML_BACKLINK -->\n"
    )


def build_x_cta_block():
    """X(Twitter)フォロー導線。全記事に常時付与（CLAUDE.md: X+Patreon CTA必須）。"""
    return (
        "\n<br/>\n"
        "<!-- ML_X_CTA -->\n"
        '<p style="text-align:center; font-size:15px; margin:14px 0;">\n'
        f'🐦 X(旧Twitter)で最新情報・先行画像 → '
        f'<a href="{X_LINK}" target="_blank" rel="noopener" '
        f'style="color:#1da1f2; font-weight:bold; text-decoration:none;">{X_HANDLE}</a>\n'
        "</p>\n"
        "<!-- /ML_X_CTA -->\n"
    )


# FANZA(eronavi)導線。Amebaはアダルトアフィリ禁止＝アカBANリスクのため既定オフ。
# 有効化する場合のみ環境変数 AMEBLO_ENABLE_FANZA=1 を設定（ユーザー判断）。
FANZA_ENABLED = os.environ.get("AMEBLO_ENABLE_FANZA", "0") == "1"
ERONAVI_LINK = "https://musclelove-777.github.io/eronavi/?utm_source=ameblo&utm_medium=fanza_cta"


def build_fanza_cta_block():
    """FANZA(eronavi経由)誘導ブロック。18禁・PR明記。AMEBLO_ENABLE_FANZA=1 のときのみ付与。"""
    if not FANZA_ENABLED:
        return ""
    return (
        "\n<br/>\n"
        "<!-- ML_FANZA_CTA -->\n"
        '<div style="text-align:center; margin:16px auto; max-width:420px;">\n'
        '<p style="font-size:11px; color:#999; margin:0 0 6px;">※18歳以上向けリンクを含みます／PR・アフィリエイトを含みます</p>\n'
        f'<a href="{ERONAVI_LINK}" target="_blank" rel="noopener nofollow sponsored" '
        f'style="display:inline-block; padding:9px 16px; background:#7c3aed; color:#fff; '
        f'border-radius:6px; font-weight:bold; text-decoration:none; font-size:14px;">'
        f'筋肉美女のFANZA系まとめ（18+）</a>\n'
        "</div>\n"
        "<!-- /ML_FANZA_CTA -->\n"
    )


# --- タグマッピング ---
CONTENT_TAG_MAP = {
    'training': ['筋トレ', 'ワークアウト', 'トレーニング', 'ジム', 'フィットネス'],
    'workout': ['筋トレ', 'ワークアウト', 'トレーニング', 'ジム', 'フィットネス'],
    'pullups': ['懸垂', 'プルアップ', 'バックワークアウト', 'カリステニクス'],
    'posing': ['ポージング', 'ボディビル', 'フィジーク'],
    'flex': ['フレックス', 'マッスル', 'ボディビル'],
    'muscle': ['筋肉', 'マッスル', 'フィットネス'],
    'bicep': ['上腕二頭筋', 'バイセップ', '腕トレ'],
    'abs': ['腹筋', 'シックスパック', 'コアトレ'],
    'leg': ['脚トレ', 'レッグデイ', 'スクワット'],
    'back': ['背中', 'バックデイ', '広背筋'],
    'squat': ['スクワット', '脚トレ', 'レッグデイ'],
    'deadlift': ['デッドリフト', 'パワーリフティング'],
    'bench': ['ベンチプレス', '胸トレ'],
    'bikini': ['ビキニ', 'ビキニフィットネス', 'フィギュア'],
    'competition': ['大会', 'コンテスト', 'ボディビル'],
}

BASE_TAGS = [
    '筋肉女子', '筋トレ女子', 'フィットネス', 'ボディメイク',
    '筋トレ', 'ワークアウト', '美ボディ', '筋肉美',
]

AMEBLO_POPULAR_TAGS = [
    'ダイエット', '美容', '健康', '自分磨き', 'トレーニング',
    'ジム', '腹筋', '腹筋女子', 'くびれ', '体幹',
    '姿勢改善', '健康美', 'モチベーション', 'ジム女子',
    '宅トレ', '筋トレ初心者', 'ボディライン', 'フィジーク',
    'ボディビル', 'パーソナルトレーニング',
]

AMEBLO_TAG_DENYLIST = {
    'ありがとう', '感謝', 'おはよう', 'こんにちは', 'こんばんは',
    '日記', 'ブログ', '今日の出来事', 'ランチ', '晩ごはん',
    'お弁当', '料理', 'カフェ', '旅行', '花', '空',
    '猫', '犬', '子育て', '育児', 'トレンド', 'ニュース',
    'テレビ', 'ドラマ', '映画', 'アニメ', '推し', '誕生日',
    'おめでとう',
}

AMEBLO_SAFE_GENERAL_TREND_TAGS = [
    'ありがとう',
]

AMEBLO_TAG_ALLOW_KEYWORDS = (
    '筋', 'トレ', 'ジム', 'フィット', 'ボディ', 'マッスル',
    '腹筋', 'くびれ', '体幹', '健康', '美容', 'ダイエット',
    '姿勢', 'ワークアウト', 'フィジーク', 'ボディビル',
    'アスリート', 'ウェルネス', '自分磨き', '宅トレ',
    'fitness', 'workout', 'gym', 'training', 'muscle', 'body',
)

TAN_KEYWORDS = {
    'tan', 'tanned', 'darktan', 'dark-tan', 'brown', 'bronze',
    '褐色', '小麦肌', '日焼け', '黒ギャル',
}

GLOSSY_KEYWORDS = {
    'sweat', 'sweaty', 'wet', 'glossy', 'oil', 'oiled',
    '汗', 'テカテカ', 'オイル',
}

ABS_KEYWORDS = {
    'abs', 'ab', 'sixpack', 'six-pack', '腹筋',
}

ARMPIT_KEYWORDS = {
    'waki', 'armpit', 'underarm', 'ワキ', '脇',
}


def _normalized_name(image_name):
    stem = os.path.splitext(os.path.basename(image_name))[0].lower()
    return re.sub(r'[\s_\-()（）\[\]【】]+', ' ', stem)


def _name_has_any(name_lower, keywords):
    tokens = set(name_lower.split())
    compact_name = name_lower.replace(" ", "")
    for keyword in keywords:
        key = keyword.lower().replace("_", " ").strip()
        compact_key = key.replace(" ", "").replace("-", "")
        if key in tokens or compact_key in tokens:
            return True
        # tan/ab など短い英字は誤爆しやすいので、単語一致だけにする。
        if re.search(r'[a-z]', key) and len(compact_key) <= 3:
            continue
        if key in name_lower or compact_key in compact_name:
            return True
    return False


def clean_tag(tag):
    """Amebaへ入れる前に、#や空白を取り除いた短いタグ名へ正規化する。"""
    tag = str(tag or "").strip()
    tag = re.sub(r'^[#＃]+', '', tag)
    tag = re.sub(r'\s+', '', tag)
    tag = tag.strip('、。,.!！?？/\\|:：;；"\'「」『』()（）[]【】<>＜＞')
    return tag


def _curated_ameblo_tag_set():
    curated = set(BASE_TAGS) | set(AMEBLO_POPULAR_TAGS)
    for keyword_tags in CONTENT_TAG_MAP.values():
        curated.update(keyword_tags)
    curated.update([
        '褐色美女', '小麦肌', '日焼け', '肩トレ', '腕トレ',
        '上半身トレ', 'シックスパック', 'コアトレ',
    ])
    return curated


def is_relevant_ameblo_tag(tag):
    """汎用人気タグではなく、MuscleLove投稿に寄せられるタグだけ通す。"""
    clean = clean_tag(tag)
    if not clean:
        return False
    key = clean.lower()
    denied = {t.lower() for t in AMEBLO_TAG_DENYLIST}
    if key in denied:
        return False
    if len(clean) > 30 or 'http' in key or any(mark in clean for mark in ('@', '#', '＃')):
        return False
    if clean in _curated_ameblo_tag_set():
        return True
    return any(keyword.lower() in key for keyword in AMEBLO_TAG_ALLOW_KEYWORDS)


def is_safe_general_trend_tag(tag):
    """Amebaで流行中なら最後に1つだけ混ぜてもよい汎用タグ。"""
    return clean_tag(tag) in AMEBLO_SAFE_GENERAL_TREND_TAGS


def normalize_ameblo_tags(candidates, max_tags=None, allow_safe_general=False):
    """重複・無関係タグを除去して、Ameba向けのタグリストに整える。"""
    seen = set()
    tags = []
    for candidate in candidates:
        tag = clean_tag(candidate)
        key = tag.lower()
        allowed = is_relevant_ameblo_tag(tag) or (allow_safe_general and is_safe_general_trend_tag(tag))
        if not tag or key in seen or not allowed:
            continue
        tags.append(tag)
        seen.add(key)
        if max_tags and len(tags) >= max_tags:
            break
    return tags


def select_ameblo_tags(candidates, max_tags=15, allow_safe_general=False):
    """安全な汎用トレンドがある場合は最後の1枠として残す。"""
    if not allow_safe_general:
        return normalize_ameblo_tags(candidates, max_tags=max_tags)

    safe_general = []
    for candidate in candidates:
        tag = clean_tag(candidate)
        if tag and is_safe_general_trend_tag(tag):
            safe_general.append(tag)

    reserve = 1 if safe_general and max_tags else 0
    normal_limit = max_tags - reserve if reserve else max_tags
    tags = normalize_ameblo_tags(candidates, max_tags=normal_limit)

    seen = {t.lower() for t in tags}
    for tag in safe_general:
        if tag.lower() not in seen:
            tags.append(tag)
            break
    return tags[:max_tags] if max_tags else tags


def enrich_tags_with_trends(base_tags, trend_tags=None, max_tags=15):
    """固定タグ、関連トレンド、人気寄りタグを混ぜて毎回少し変える。"""
    candidates = list(base_tags)
    safe_general_trends = list(AMEBLO_SAFE_GENERAL_TREND_TAGS)

    for tag in trend_tags or []:
        if is_relevant_ameblo_tag(tag):
            candidates.append(tag)
        elif is_safe_general_trend_tag(tag) and clean_tag(tag) not in safe_general_trends:
            safe_general_trends.append(clean_tag(tag))

    popular_pool = list(AMEBLO_POPULAR_TAGS)
    random.shuffle(popular_pool)
    candidates.extend(popular_pool)

    candidates.extend(safe_general_trends)
    return select_ameblo_tags(candidates, max_tags=max_tags, allow_safe_general=True)


def detect_image_traits(image_name):
    """ファイル名から言及してよい属性を保守的に判定する。"""
    name_lower = _normalized_name(image_name)
    return {
        "tan": _name_has_any(name_lower, TAN_KEYWORDS),
        "glossy": _name_has_any(name_lower, GLOSSY_KEYWORDS),
        "abs": _name_has_any(name_lower, ABS_KEYWORDS),
        "armpit": _name_has_any(name_lower, ARMPIT_KEYWORDS),
    }


def generic_category(image_name):
    """ファイル名の固有名詞や日付を出さず、投稿向けの汎用ラベルへ丸める。"""
    traits = detect_image_traits(image_name)
    if traits["abs"] and traits["armpit"]:
        return "腹筋と腕上げポーズの筋肉女子"
    if traits["abs"]:
        return "腹筋が映える筋肉女子"
    if traits["armpit"]:
        return "腕上げポーズの筋肉女子"
    if traits["tan"]:
        return "小麦肌の筋肉女子"
    return "筋肉女子"


# ブログタイトルテンプレート（ランダム選択）
TITLE_TEMPLATES = [
    "✨ しょーがないなぁ、特別に見せてあげる♡ 今日の{category}",
    "💪 今日の{category}、ポージングの存在感が強い",
    "🔥 視線とシルエットで魅せる{category}",
    "♡ {category}、かわいさと強さのバランスが良すぎる",
    "✨ ふ〜ん…この{category}、ちょっと見入っちゃうでしょ",
    "💪 本日の一枚：{category}",
]

CONDITIONAL_TITLE_TEMPLATES = {
    "tan": [
        "🔥 小麦肌が映える{category}。この存在感、強い",
        "💪 褐色ボディラインで魅せる{category}",
    ],
    "glossy": [
        "✨ 汗のツヤまで映える{category}",
        "🔥 光を拾う{category}、仕上がりが強い",
    ],
    "abs": [
        "💪 腹筋ラインが主役の{category}",
        "🔥 鍛えた腹筋で魅せる{category}",
    ],
    "armpit": [
        "♡ ワキ見せポージングの{category}",
        "💪 腕上げラインがきれいな{category}",
    ],
}

# ブログ本文HTMLテンプレート（ランダム選択）
BODY_TEMPLATES = [
    """
<div style="text-align: center; margin: 20px 0;">
<p style="font-size: 18px; font-weight: bold; color: #333;">{title}</p>
{image_html}
<p style="font-size: 14px; color: #555; line-height: 1.8;">
{caption}
</p>
<br/>
<p style="font-size: 14px; color: #666;">
{hashtags}
</p>
<br/>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;" />
<p style="font-size: 16px; font-weight: bold; color: #e74c3c;">
Patreonで限定コンテンツ配信中!
</p>
<p style="font-size: 15px;">
<a href="{patreon_link}" style="color: #e74c3c; text-decoration: underline; font-weight: bold;">
{patreon_link}
</a>
</p>
<p style="font-size: 13px; color: #888;">
ここでしか見れない筋肉美女のコンテンツを毎日更新中
</p>
</div>
""",
    """
<div style="text-align: center; margin: 20px 0;">
<h3 style="color: #2c3e50;">{title}</h3>
{image_html}
<p style="font-size: 14px; color: #555; line-height: 1.8;">
{caption}
</p>
<br/>
<p style="font-size: 14px; color: #666;">
{hashtags}
</p>
<br/>
<div style="background: linear-gradient(135deg, #e74c3c, #c0392b); padding: 20px; border-radius: 10px; margin: 20px auto; max-width: 400px;">
<p style="color: white; font-size: 16px; font-weight: bold; margin: 0;">
Patreonで限定コンテンツ公開中!
</p>
<p style="margin: 10px 0 0;">
<a href="{patreon_link}" style="color: #fff; text-decoration: underline; font-size: 14px;">
MuscleLove Patreon
</a>
</p>
</div>
</div>
""",
    """
<div style="text-align: center; margin: 20px 0;">
<p style="font-size: 20px; font-weight: bold; color: #2c3e50; border-bottom: 3px solid #e74c3c; display: inline-block; padding-bottom: 5px;">
{title}
</p>
{image_html}
<p style="font-size: 14px; color: #555; line-height: 1.8;">
{caption}
</p>
<br/>
<p style="font-size: 14px; color: #666;">
{hashtags}
</p>
<br/>
<table style="margin: 20px auto; border: 2px solid #e74c3c; border-radius: 8px; padding: 15px;">
<tr><td style="text-align: center; padding: 15px;">
<p style="font-size: 16px; font-weight: bold; color: #e74c3c; margin: 0;">
More exclusive content on Patreon
</p>
<p style="margin: 8px 0 0;">
<a href="{patreon_link}" style="color: #e74c3c; font-size: 14px; font-weight: bold;">
{patreon_link}
</a>
</p>
</td></tr>
</table>
</div>
""",
]

# キャプションテンプレート
CAPTION_TEMPLATES = [
    "💪 今日の一枚、ポージングとシルエットの説得力がいい。強さとかわいさのバランスが刺さる♡",
    "✨ 画面越しでも存在感が伝わるショット。表情とボディラインの見せ方がうまいんだよね。",
    "🔥 余裕ある雰囲気なのに、フィットネス感もしっかりある。このバランスがいい。",
    "♡ 派手に言いすぎなくても伝わるタイプの一枚。ポーズ、表情、全体のラインがきれい。",
    "💪 しょーがないなぁ、今日はこの一枚。見れば見るほどボディメイクの魅力が出てくるやつ。",
    "✨ 筋肉美女らしい存在感と、やわらかい雰囲気が同居してる。今日の投稿にちょうどいい仕上がり♡",
]

CONDITIONAL_CAPTION_TEMPLATES = {
    "tan": [
        "🔥 小麦肌のトーンが全体の雰囲気を引き締めていて、ポージングの強さがさらに映えてる♡",
        "💪 褐色のボディラインが光を拾って、フィットネスアートとしての存在感がかなり強い。",
    ],
    "glossy": [
        "✨ 汗のツヤ感まで含めて、トレーニング後っぽい空気が出てる。こういう質感、いいよね。",
        "🔥 光の入り方でボディラインがきれいに見える一枚。仕上がりの臨場感がある。",
    ],
    "abs": [
        "💪 腹筋ラインがちゃんと主役になってる。鍛えてきた説得力が画面から伝わるやつ。",
        "🔥 腹筋まわりの引き締まり方がいい。強さと色気のバランスが絶妙。",
    ],
    "armpit": [
        "♡ 腕上げポーズのラインがきれい。ワキから肩にかけての見せ方がかなり刺さる。",
        "💪 ワキ見せの構図が自然で、肩まわりのフィットネス感もしっかり出てる。",
    ],
}


# ===== 公開Driveフォルダ =====

def list_gdrive_images(folder_id):
    """gdownで画像一覧を取得"""
    return _list_via_gdown(folder_id)


def _list_via_gdown(folder_id):
    """gdownでフォルダをダウンロード（APIキー不要）"""
    import gdown
    dl_dir = "images"
    os.makedirs(dl_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{folder_id}"

    # ダウンロード前の既存ファイル数を記録
    before = set()
    for root, dirs, filenames in os.walk(dl_dir):
        for fname in filenames:
            before.add(os.path.join(root, fname))
    print(f"Downloading from Google Drive: {url}")
    print(f"  Files already in '{dl_dir}/': {len(before)}")

    try:
        gdown.download_folder(url, output=dl_dir, quiet=False, remaining_ok=True)
    except Exception as e:
        print(f"Download error (partial download may exist): {e}")

    # ダウンロード後のファイル数を集計
    after = set()
    for root, dirs, filenames in os.walk(dl_dir):
        for fname in filenames:
            after.add(os.path.join(root, fname))
    new_files = len(after - before)
    print(f"  Files after download: {len(after)} (newly downloaded: {new_files})")

    images = []
    for root, dirs, filenames in os.walk(dl_dir):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                fpath = os.path.join(root, fname)
                images.append({
                    "id": None,
                    "name": fname,
                    "local_path": fpath,
                })
    return images


# ===== タグ・テキスト生成 =====

def generate_tags(image_name):
    """ファイル名からハッシュタグを生成"""
    tags = list(BASE_TAGS)
    popular_pool = list(AMEBLO_POPULAR_TAGS)
    random.shuffle(popular_pool)
    tags.extend(popular_pool[:8])

    traits = detect_image_traits(image_name)
    if traits["tan"]:
        tags.extend(['褐色美女', '小麦肌', '日焼け'])
    if traits["abs"]:
        tags.extend(['腹筋', '腹筋女子', 'シックスパック', '体幹', 'くびれ'])
    if traits["armpit"]:
        tags.extend(['肩トレ', '腕トレ', '上半身トレ'])

    name_lower = image_name.lower().replace('-', ' ').replace('_', ' ')
    matched = set()
    for keyword, keyword_tags in CONTENT_TAG_MAP.items():
        if keyword in name_lower:
            for t in keyword_tags:
                if t not in matched:
                    tags.append(t)
                    matched.add(t)
    return normalize_ameblo_tags(tags, max_tags=15)


def extract_category(image_name):
    """投稿表示用カテゴリを返す。日付・ファイル名・キャラ名は出さない。"""
    return generic_category(image_name)


def build_title(image_name):
    """ブログタイトルを生成"""
    category = extract_category(image_name)
    traits = detect_image_traits(image_name)
    templates = list(TITLE_TEMPLATES)
    for trait_name, trait_templates in CONDITIONAL_TITLE_TEMPLATES.items():
        if traits.get(trait_name):
            templates.extend(trait_templates)
    template = random.choice(templates)
    return template.format(category=category)


def build_caption(image_name):
    """画像名から安全なキャプション候補を選ぶ。"""
    traits = detect_image_traits(image_name)
    templates = list(CAPTION_TEMPLATES)
    for trait_name, trait_templates in CONDITIONAL_CAPTION_TEMPLATES.items():
        if traits.get(trait_name):
            templates.extend(trait_templates)
    return random.choice(templates)


def build_body_html(image_name, image_url, tags, title=None, include_image=True):
    """ブログ本文のHTMLを生成"""
    category = extract_category(image_name)
    title = title or build_title(image_name)
    hashtags = ' '.join([f'#{t}' for t in select_ameblo_tags(tags, max_tags=15, allow_safe_general=True)])
    caption = build_caption(image_name)
    template = random.choice(BODY_TEMPLATES)
    image_html = ""
    if include_image and image_url:
        image_html = (
            '\n<br/>\n'
            f'<img src="{image_url}" alt="{category}" style="max-width: 100%; height: auto; border-radius: 8px;" />\n'
            '<br/><br/>\n'
        )

    html = template.format(
        title=title,
        image_url=image_url,
        image_html=image_html,
        category=category,
        caption=caption,
        hashtags=hashtags,
        patreon_link=PATREON_LINK,
    )
    # 末尾CTA: X(常時) → FANZA(AMEBLO_ENABLE_FANZA=1のときのみ) → 関連サイト（冪等マーカー付き）
    html = html.rstrip() + build_x_cta_block() + build_fanza_cta_block() + build_backlink_block()
    return html.strip()


def build_ameblo_hashtags(tags, max_tags=10):
    """Amebloのハッシュタグ文字列を生成（投稿フォームのタグ欄用）"""
    return select_ameblo_tags(tags, max_tags=max_tags, allow_safe_general=True)


# ===== Selenium ブログ投稿 =====

def upload_image_via_selenium(driver, image_path):
    """
    Seleniumでエディタに画像をアップロードし、サムネイルクリックで本文に挿入する

    Args:
        driver: ログイン済みWebDriver（エディタページ）
        image_path: ローカル画像ファイルの絶対パス

    Returns:
        bool: 画像挿入成功したらTrue
    """
    try:
        abs_path = os.path.abspath(image_path)

        # input[type="file"] で画像をアップロード
        file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
        file_input.send_keys(abs_path)
        print(f"画像アップロード中: {os.path.basename(abs_path)}")
        time.sleep(8)  # アップロード完了まで待機

        # サムネイルをクリックして本文に挿入（背景画像にuser_imagesを含む要素を探す）
        result = driver.execute_script("""
        var btns = document.querySelectorAll('button, a, li, div');
        for (var i = 0; i < btns.length; i++) {
            var el = btns[i];
            var bg = window.getComputedStyle(el).backgroundImage || '';
            if (bg.indexOf('user_images') > -1) {
                el.click();
                return 'clicked';
            }
        }
        return 'not found';
        """)
        print(f"  サムネイルクリック: {result}")
        time.sleep(3)

        if result == 'clicked':
            print("画像を本文に挿入しました")
            return True
        else:
            print("Warning: アップロード済み画像のサムネイルが見つかりません")
            return False

    except Exception as e:
        print(f"画像アップロードエラー: {e}")
        return False


def insert_text_via_ckeditor(driver, extra_html):
    """
    CKEditor APIを使ってエディタにHTMLテキストを追加する（実証済みの方法）

    Args:
        driver: WebDriver
        extra_html: 追加するHTML文字列

    Returns:
        bool: 挿入成功したらTrue
    """
    # CKEditor API経由でテキストを追加
    insert_result = driver.execute_script("""
    // 方法1: CKEDITOR.instances経由
    if (typeof CKEDITOR !== 'undefined' && CKEDITOR.instances) {
        var keys = Object.keys(CKEDITOR.instances);
        if (keys.length > 0) {
            var editor = CKEDITOR.instances[keys[0]];
            var currentData = editor.getData();
            editor.setData(currentData + arguments[0]);
            return 'ckeditor_setData: ' + keys[0];
        }
    }

    // 方法2: tinyMCE経由（フォールバック）
    if (typeof tinyMCE !== 'undefined' && tinyMCE.activeEditor) {
        var content = tinyMCE.activeEditor.getContent();
        tinyMCE.activeEditor.setContent(content + arguments[0]);
        return 'tinymce';
    }

    return 'no editor API found';
    """, extra_html)
    print(f"  CKEditor API結果: {insert_result}")

    if "no editor" in str(insert_result):
        # フォールバック: HTML表示モードのtextarea経由
        print("  フォールバック: HTML表示モード経由...")
        try:
            html_links = driver.find_elements(By.CSS_SELECTOR, 'a, span, label')
            for link in html_links:
                text = (link.text or "").strip()
                if text == "HTML表示":
                    link.click()
                    time.sleep(2)
                    print("    HTML表示に切り替え")
                    break

            textareas = driver.find_elements(By.TAG_NAME, 'textarea')
            for ta in textareas:
                if ta.is_displayed():
                    current = ta.get_attribute("value") or ""
                    new_value = current + extra_html
                    driver.execute_script(
                        "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input'));",
                        ta, new_value
                    )
                    time.sleep(1)
                    print(f"    textarea更新: {len(new_value)}文字")
                    break

            # 通常表示に戻す
            for link in driver.find_elements(By.CSS_SELECTOR, 'a, span, label'):
                text = (link.text or "").strip()
                if text == "通常表示":
                    link.click()
                    time.sleep(2)
                    break
            return True
        except Exception as e:
            print(f"    フォールバック失敗: {e}")
            return False

    return True


def set_ameblo_hashtags(driver, tags):
    """Ameba投稿フォームのタグ欄が見つかる場合だけ、公式タグ欄にも入れる。"""
    tag_names = build_ameblo_hashtags(tags, max_tags=10)
    if not tag_names:
        return False

    selectors = [
        'input[placeholder*="ハッシュタグ"]',
        'textarea[placeholder*="ハッシュタグ"]',
        'input[aria-label*="ハッシュタグ"]',
        'textarea[aria-label*="ハッシュタグ"]',
        'input[name*="tag"]',
        'textarea[name*="tag"]',
        'input[id*="tag"]',
        'textarea[id*="tag"]',
    ]

    for selector in selectors:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                if not element.is_displayed() or not element.is_enabled():
                    continue
                element.click()
                current = element.get_attribute("value") or ""
                if current:
                    element.clear()
                for tag in tag_names:
                    element.send_keys(tag)
                    element.send_keys(Keys.ENTER)
                    time.sleep(0.2)
                print(f"ハッシュタグ欄へ入力: {', '.join(tag_names)}")
                return True
            except Exception:
                continue

    # React系の入力欄でsend_keysが効かない場合の軽いフォールバック。
    result = driver.execute_script("""
    const tags = arguments[0];
    const value = tags.map((tag) => '#' + tag).join(' ');
    const nodes = Array.from(document.querySelectorAll('input, textarea'));
    for (const el of nodes) {
      const hint = [
        el.placeholder || '',
        el.getAttribute('aria-label') || '',
        el.name || '',
        el.id || ''
      ].join(' ').toLowerCase();
      if (!hint.includes('tag') && !hint.includes('ハッシュタグ')) continue;
      if (el.offsetParent === null || el.disabled || el.readOnly) continue;
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return value;
    }
    return '';
    """, tag_names)

    if result:
        print(f"ハッシュタグ欄へ入力(JS): {', '.join(tag_names)}")
        return True

    print("ハッシュタグ欄は見つからず（本文内タグのみ使用）")
    return False


def post_blog_entry(driver, title, body_html, image_path, tags):
    """
    ブログ記事を投稿する（CKEditor API使用の実証済みフロー）

    Args:
        driver: ログイン済み・エディタページのWebDriver
        title: 記事タイトル
        body_html: 記事本文HTML（画像の後に追加されるテキスト部分）
        image_path: アップロードする画像のローカルパス（Noneなら画像なし）
        tags: タグのリスト

    Returns:
        bool: 投稿成功したらTrue
    """
    try:
        # --- 1. タイトル入力 ---
        title_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder*="タイトル"]'))
        )
        # send_keysはBMP外の文字（絵文字）を扱えないためJavaScriptで入力
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            title_input, title
        )
        human_delay(1, 2)
        print(f"タイトル入力: {title}")

        # --- 2. 画像アップロード＆本文挿入 ---
        if image_path:
            if not upload_image_via_selenium(driver, image_path):
                print("Error: 画像を本文に挿入できなかったため投稿を中止します")
                return False

        # --- 3. CKEditor APIでテキスト追加 ---
        print("本文テキスト追加（CKEditor API）...")
        insert_text_via_ckeditor(driver, body_html)
        time.sleep(2)

        # --- 4. ハッシュタグ欄がある場合は入力 ---
        set_ameblo_hashtags(driver, tags)
        time.sleep(1)

        # --- 5. 投稿ボタンクリック ---
        print("投稿中...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        from selenium.common.exceptions import StaleElementReferenceException

        def _click_publish_button(max_attempts=3):
            keywords_primary = ["投稿する"]
            keywords_fallback = ["公開", "投稿", "publish"]
            for attempt in range(max_attempts):
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], input[type='button']")
                    for btn in btns:
                        try:
                            text = (btn.text or "").strip() or (btn.get_attribute("value") or "")
                        except StaleElementReferenceException:
                            continue
                        if any(k in text for k in keywords_primary):
                            try:
                                if btn.is_displayed():
                                    btn.click()
                                    print(f"  ボタン: '{text}'")
                                    return True
                            except StaleElementReferenceException:
                                break
                    for btn in btns:
                        try:
                            text = (btn.text or "").strip() or (btn.get_attribute("value") or "")
                        except StaleElementReferenceException:
                            continue
                        if any(k in text for k in keywords_fallback):
                            try:
                                if btn.is_displayed() and btn.is_enabled():
                                    btn.click()
                                    print(f"  ボタン（フォールバック）: '{text}'")
                                    return True
                            except StaleElementReferenceException:
                                break
                except StaleElementReferenceException:
                    pass
                if attempt < max_attempts - 1:
                    print(f"  StaleElement再試行 ({attempt + 1}/{max_attempts})...")
                    time.sleep(1)
            return False

        publish_clicked = _click_publish_button()

        if not publish_clicked:
            print("Error: 投稿ボタンが見つかりません")
            return False

        time.sleep(8)

        # --- 6. 「カバーなしで投稿する」ダイアログ対応 ---
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, "button, a"):
                try:
                    if "カバーなしで投稿" in (btn.text or ""):
                        btn.click()
                        print("  「カバーなしで投稿する」をクリック")
                        time.sleep(8)
                        break
                except StaleElementReferenceException:
                    pass
        except Exception:
            pass

        # --- 7. 投稿成功確認 ---
        current_url = driver.current_url
        print(f"最終URL: {current_url}")

        if "entrylist" in current_url or "entry_ym" in current_url:
            print("投稿成功! (記事一覧ページに遷移)")
            return True

        page_source = driver.page_source
        success_indicators = [
            "投稿が完了", "記事を公開しました", "entry_id",
            "entrydetail", "posted", "success",
            "記事の編集", "ブログを見る",
        ]

        if any(indicator in page_source for indicator in success_indicators):
            print("投稿成功! (ページ内容確認)")
            return True

        # URLが変わっていれば成功とみなす
        if "insert" not in current_url.lower() and "edit" not in current_url.lower():
            print(f"投稿完了 (URL変化: {current_url})")
            return True

        print(f"Warning: 投稿結果が確認できません (URL: {current_url})")
        return True

    except Exception as e:
        print(f"投稿エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


# ===== アップロードログ =====

def load_uploaded_log():
    if os.path.exists(UPLOADED_LOG):
        with open(UPLOADED_LOG, 'r') as f:
            return json.load(f)
    return []


def save_uploaded_log(log):
    with open(UPLOADED_LOG, 'w') as f:
        json.dump(log, f, indent=2)


# ===== メイン =====

def main():
    if "--check-auth-only" in sys.argv:
        ok, message = check_cookie_freshness()
        if ok:
            print(message)
            return 0
        print(f"Error: {message}")
        print("ローカルで save_cookies.py を実行して、GitHub Secret AMEBLO_COOKIES を更新してください。")
        return AUTH_EXPIRED_EXIT_CODE

    # 認証チェック（Cookie方式 + パスワードフォールバック）
    if cookie_auth_required():
        ok, message = check_cookie_freshness()
        if not ok:
            print(f"Error: {message}")
            print("Actionsではパスワードログインを使わず停止します。Cookieを更新してください。")
            return AUTH_EXPIRED_EXIT_CODE
        print(message)
    elif not os.path.exists(COOKIE_FILE):
        username = os.environ.get("AMEBLO_USERNAME", "")
        password = os.environ.get("AMEBLO_PASSWORD", "")
        if not username or not password:
            print("Error: Cookie未保存かつ AMEBLO_USERNAME/AMEBLO_PASSWORD も未設定です。")
            print("save_cookies.py を実行するか、環境変数を設定してください。")
            return 1
        else:
            print("Cookie未保存ですが、パスワードログインで試行します...")

    if not GDRIVE_FOLDER_ID:
        print("Error: GDRIVE_FOLDER_ID_AMEBLO が未設定です")
        return 1

    now_jst = datetime.now(JST)
    print("=" * 50)
    print("Ameba Blog Auto Uploader")
    print(f"Time: {now_jst.strftime('%Y-%m-%d %H:%M JST')}")
    print("=" * 50)
    print()

    # 公開Driveフォルダから画像一覧取得
    print("公開Driveフォルダから画像一覧を取得中...")
    images = list_gdrive_images(GDRIVE_FOLDER_ID)
    if not images:
        print("No images found!")
        return 0

    # 未アップロード画像をフィルタ
    uploaded_log = load_uploaded_log()
    available = [img for img in images if img["name"] not in uploaded_log]
    if not available:
        print("All images already uploaded!")
        return 0

    print(f"Available: {len(available)} / Total: {len(images)}")

    # ランダムに1枚選択
    image = random.choice(available)
    print(f"Selected: {image['name']}")

    # タグ生成
    tags = generate_tags(image["name"])

    # 関連するトレンドタグだけ追加（汎用人気タグは除外）
    trend_tags = []
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'x-auto-uploader'))
        from trending import get_trending_tags
        trend_tags = get_trending_tags(max_tags=8)
    except ImportError:
        print("trending.py not found, skipping trend tags")
    tags = enrich_tags_with_trends(tags, trend_tags=trend_tags, max_tags=15)

    # gdownで取得したローカル画像をSelenium経由でアップロードする
    image_url = ""
    if not image.get("local_path"):
        print("Error: 画像ソースがありません")
        return 1

    image_path = os.path.abspath(image["local_path"])

    # タイトル・本文HTML生成
    # Seleniumで画像を挿入できる場合、本文HTML側の<img>は省き、重複・空画像を防ぐ。
    title = build_title(image["name"])
    include_inline_image = image_path is None and bool(image_url)
    body_html = build_body_html(
        image["name"],
        image_url,
        tags,
        title=title,
        include_image=include_inline_image,
    )

    print(f"Title: {title}")
    print(f"Tags: {', '.join(tags[:10])}...")
    print(f"Inline image in body: {include_inline_image}")
    print()

    # Seleniumでブログ投稿
    load_selenium_helpers()
    driver = None
    try:
        print("Chromeブラウザを起動中...")
        driver = create_driver(headless=True)

        # Cookieログイン（reCAPTCHA回避）+ パスワードフォールバック
        login_success = False
        if os.path.exists(COOKIE_FILE):
            login_success = login_with_cookies(driver)
        else:
            print("Cookie未保存。パスワードログインを直接試行します...")

        if not login_success:
            if cookie_auth_required():
                print("ログイン失敗! AMEBLO_COOKIES を更新してください。")
                return AUTH_EXPIRED_EXIT_CODE

            # パスワードログインを試行
            username = os.environ.get("AMEBLO_USERNAME", "")
            password = os.environ.get("AMEBLO_PASSWORD", "")
            if username and password:
                print("パスワードログインを試行中...")
                if login_ameba(driver, username, password):
                    print("パスワードログイン成功! 新しいCookieを保存します...")
                    new_cookies = driver.get_cookies()
                    with open(COOKIE_FILE, "w") as f:
                        json.dump(new_cookies, f, indent=2)
                    login_success = True

            if not login_success:
                print("ログイン失敗! AMEBLO_USERNAME/AMEBLO_PASSWORD を確認してください。")
                return 1

        human_delay(2, 4)

        # エディタに移動
        if not navigate_to_editor(driver):
            print("エディタに移動できません!")
            return 1

        human_delay(2, 4)

        # ブログ記事を投稿（CKEditor APIフロー）
        if post_blog_entry(driver, title, body_html, image_path, tags):
            print()
            print("=" * 50)
            print("BLOG POST SUCCESS!")
            print("=" * 50)

            # 成功 -> ログ保存
            uploaded_log.append(image["name"])
            save_uploaded_log(uploaded_log)
            print(f"Remaining: {len(available) - 1}")
            return 0
        else:
            print("投稿失敗!")
            return 1

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        if driver:
            try:
                driver.quit()
                print("ブラウザ終了")
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
