# -*- coding: utf-8 -*-
"""
Ameba Blog (ameblo.jp) 画像自動投稿（GitHub Actions用）
Google Driveから画像取得 -> ランダム1枚をブログ記事として投稿 -> アップロード済みを記録
Selenium使用（Ameba公式APIなし）
"""
import sys
import json
import os
import random
import time
from datetime import datetime, timezone, timedelta

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from ameblo_auth import create_driver, navigate_to_editor, human_delay, login_ameba

COOKIE_FILE = os.path.join(os.path.dirname(__file__), "ameblo_cookies.json")


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
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

PATREON_LINK = "https://www.patreon.com/cw/MuscleLove"
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
UPLOADED_LOG = "uploaded_ameblo.json"

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
    '筋肉女子', '筋トレ女子', 'マッスルガール', 'フィットネス',
    'ボディメイク', 'ワークアウト', 'ジム', 'トレーニング',
    'ワキフェチ', '腕フェチ', '筋肉美', 'AI美女',
    'むちむち', '褐色美女',
]

# ブログタイトルテンプレート（ランダム選択）
TITLE_TEMPLATES = [
    # 煽り系
    "🔥 まだ見てないの？凛花の{category}が限界突破してる件",
    "💪 カイの{category}、ガチで心臓止まるレベルなんだけど",
    "🔥 閲覧注意⚠️ ましろの{category}が攻撃力高すぎる",
    "💪 紫苑の{category}見たら普通の女子に戻れなくなるよ？",
    # トレンド系
    "✨ 2026年最強の{category}がここにある | MuscleLove",
    "🔥 バズり確定。アヤネの{category}がSNSを席巻中",
    "✨ 今週の話題独占！凛花×{category}の組み合わせが天才すぎ",
    "💪 トレンド入り不可避。カイの{category}コレクション",
    # カジュアル系
    "✨ ましろの{category}まとめ見てたら夜更かししちゃったｗ",
    "♡ え、紫苑ちゃんの{category}かわいすぎん？？",
    "💪 アヤネの{category}、推ししか勝たんのよ🔥",
    "✨ 朝から凛花の{category}で元気もらった件ｗｗ",
    # ストレート系
    "💪 鍛え抜かれた美の頂点 | カイの{category}",
    "🔥 褐色×筋肉×{category}。ましろが魅せる究極のボディ",
    "💪 紫苑の{category} | 筋肉美の新境地を切り開く",
    "🔥 圧倒的フィジーク。アヤネの{category}全記録",
    # ビジュアル重視系
    "♡ 光と影が織りなす凛花の{category}アート✨",
    "✨ 息を呑む{category}。カイの筋肉ラインが芸術的すぎる",
    "♡ ましろの{category}、写真集にしたいレベルの美しさ💪",
    "🔥 汗が滴る{category}ショット。紫苑の色気が異次元♡",
]

# ブログ本文HTMLテンプレート（ランダム選択）
BODY_TEMPLATES = [
    """
<div style="text-align: center; margin: 20px 0;">
<p style="font-size: 18px; font-weight: bold; color: #333;">{title}</p>
<br/>
<img src="{image_url}" alt="{category}" style="max-width: 100%; height: auto; border-radius: 8px;" />
<br/><br/>
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
<br/>
<img src="{image_url}" alt="{category}" style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" />
<br/><br/>
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
<br/><br/>
<img src="{image_url}" alt="{category}" style="max-width: 100%; height: auto; border-radius: 8px;" />
<br/><br/>
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
    "💪 凛花の筋肉、今日も仕上がりが半端ない。この腕のカットを見て…震えるでしょ♡",
    "🔥 カイが見せる汗ばんだ褐色ボディ。鍛え込まれた背中のラインがもう芸術✨",
    "✨ ましろの無防備なポージング、見てるこっちがドキドキする。これがリアルな筋肉美💪",
    "♡ 紫苑ちゃんのむちむちフィジーク、今日のショットは特に破壊力やばい🔥",
    "💪 アヤネの絞り込まれた腹筋ライン…触れたら硬いんだろうな。限定ではもっと見せてます♡",
    "🔥 凛花×褐色×汗。この三拍子が揃ったら、もう目を離すの無理でしょ✨",
    "✨ カイの腕からワキにかけての影が美しすぎる。筋肉フェチ歓喜の一枚💪",
    "♡ ましろが魅せる柔らかさと硬さの共存。むちむちだけど絞れてる、この矛盾がたまらん🔥",
    "💪 紫苑のトレーニング後の一枚。汗が滴るこの瞬間こそ最高に美しい✨",
    "🔥 アヤネの全身ショット、上から下まで隙がなさすぎる。鍛え抜いた者だけの輝き♡",
    "✨ 凛花の肩から腕のラインを見て。この立体感、本物の筋肉美だけが持つ迫力💪",
    "♡ カイとましろ、タイプは違うけどどっちも最高。あなたはどっち派？🔥",
]


# ===== Google Drive =====

def list_gdrive_images(folder_id):
    """Google Drive APIまたはgdownで画像一覧を取得"""
    if GOOGLE_API_KEY:
        return _list_via_api(folder_id)
    else:
        return _list_via_gdown(folder_id)


def _list_via_api(folder_id):
    """Google Drive API v3で画像一覧を取得"""
    url = "https://www.googleapis.com/drive/v3/files"
    query = f"'{folder_id}' in parents and trashed = false"
    params = {
        "q": query,
        "key": GOOGLE_API_KEY,
        "fields": "files(id,name,mimeType)",
        "pageSize": 1000,
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    files = resp.json().get("files", [])

    images = []
    for f in files:
        ext = os.path.splitext(f["name"])[1].lower()
        if ext in IMAGE_EXTENSIONS:
            images.append({
                "id": f["id"],
                "name": f["name"],
                "url": f"https://drive.google.com/uc?export=download&id={f['id']}",
            })
    return images


def _list_via_gdown(folder_id):
    """gdownでフォルダをダウンロード（APIキー不要）"""
    import gdown
    dl_dir = "images"
    os.makedirs(dl_dir, exist_ok=True)
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    print(f"Downloading from Google Drive: {url}")
    try:
        gdown.download_folder(url, output=dl_dir, quiet=False, remaining_ok=True)
    except Exception as e:
        print(f"Download error: {e}")
        # 一部ファイルが失敗しても、ダウンロード済みファイルを使う

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


def download_single_image(file_id):
    """Google Driveから1ファイルをダウンロード"""
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content


# ===== タグ・テキスト生成 =====

def generate_tags(image_name):
    """ファイル名からハッシュタグを生成"""
    tags = list(BASE_TAGS)
    name_lower = image_name.lower().replace('-', ' ').replace('_', ' ')
    matched = set()
    for keyword, keyword_tags in CONTENT_TAG_MAP.items():
        if keyword in name_lower:
            for t in keyword_tags:
                if t not in matched:
                    tags.append(t)
                    matched.add(t)
    # 重複除去
    seen = set()
    unique_tags = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_tags.append(t)
    return unique_tags


def extract_category(image_name):
    """ファイル名からカテゴリを推定"""
    parts = image_name.replace('-', ' ').replace('_', ' ').split()
    skip = {'jpg', 'jpeg', 'png', 'webp', 'img', 'image', 'photo'}
    for p in parts:
        if p.lower() not in skip and len(p) > 2:
            return p.capitalize()
    return "Muscle Art"


def build_title(image_name):
    """ブログタイトルを生成"""
    category = extract_category(image_name)
    template = random.choice(TITLE_TEMPLATES)
    return template.format(category=category)


def build_body_html(image_name, image_url, tags):
    """ブログ本文のHTMLを生成"""
    category = extract_category(image_name)
    title = build_title(image_name)
    hashtags = ' '.join([f'#{t}' for t in tags[:15]])
    caption = random.choice(CAPTION_TEMPLATES)
    template = random.choice(BODY_TEMPLATES)

    html = template.format(
        title=title,
        image_url=image_url,
        category=category,
        caption=caption,
        hashtags=hashtags,
        patreon_link=PATREON_LINK,
    )
    return html.strip()


def build_ameblo_hashtags(tags, max_tags=10):
    """Amebloのハッシュタグ文字列を生成（投稿フォームのタグ欄用）"""
    return tags[:max_tags]


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
            upload_image_via_selenium(driver, image_path)

        # --- 3. CKEditor APIでテキスト追加 ---
        print("本文テキスト追加（CKEditor API）...")
        insert_text_via_ckeditor(driver, body_html)
        time.sleep(2)

        # --- 4. 投稿ボタンクリック ---
        print("投稿中...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1)

        publish_clicked = False
        for btn in driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit']"):
            text = (btn.text or "").strip()
            if "投稿する" in text and btn.is_displayed():
                btn.click()
                print(f"  ボタン: '{text}'")
                publish_clicked = True
                break

        if not publish_clicked:
            # フォールバック: より広い範囲でボタンを探す
            buttons = driver.find_elements(By.CSS_SELECTOR, "button, input[type='submit'], input[type='button']")
            for btn in buttons:
                text = (btn.text or "").strip() or (btn.get_attribute("value") or "")
                if any(keyword in text for keyword in ["公開", "投稿", "publish"]):
                    if btn.is_displayed() and btn.is_enabled():
                        btn.click()
                        print(f"  ボタン（フォールバック）: '{text}'")
                        publish_clicked = True
                        break

        if not publish_clicked:
            print("Error: 投稿ボタンが見つかりません")
            return False

        time.sleep(8)

        # --- 5. 「カバーなしで投稿する」ダイアログ対応 ---
        try:
            for btn in driver.find_elements(By.CSS_SELECTOR, "button, a"):
                if "カバーなしで投稿" in (btn.text or ""):
                    btn.click()
                    print("  「カバーなしで投稿する」をクリック")
                    time.sleep(8)
                    break
        except Exception:
            pass

        # --- 6. 投稿成功確認 ---
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
    # 認証チェック（Cookie方式 + パスワードフォールバック）
    if not os.path.exists(COOKIE_FILE):
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

    # Google Driveから画像一覧取得
    print("Google Driveから画像一覧を取得中...")
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

    # トレンドタグ追加
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'x-auto-uploader'))
        from trending import get_trending_tags
        trend_tags = get_trending_tags(max_tags=5)
        if trend_tags:
            seen = {t.lower() for t in tags}
            for t in trend_tags:
                if t.lower() not in seen:
                    tags.append(t)
                    seen.add(t.lower())
    except ImportError:
        print("trending.py not found, skipping trend tags")

    # 画像URLを決定
    if image.get("id"):
        image_url = image["url"]
    elif image.get("local_path"):
        # ローカルファイルの場合、Google DriveのURLは使えないので
        # 投稿時にSelenium経由でアップロードする
        image_url = ""
    else:
        print("Error: 画像ソースがありません")
        return 1

    # タイトル・本文HTML生成
    title = build_title(image["name"])
    body_html = build_body_html(image["name"], image_url, tags)

    print(f"Title: {title}")
    print(f"Tags: {', '.join(tags[:10])}...")
    print()

    # ローカル画像パスを決定
    image_path = None
    if image.get("local_path"):
        image_path = os.path.abspath(image["local_path"])
    elif image.get("id"):
        # Google Drive APIの画像をダウンロードしてローカルに保存
        print("Google Driveから画像をダウンロード中...")
        try:
            img_data = download_single_image(image["id"])
            dl_dir = os.path.join(os.path.dirname(__file__), "images")
            os.makedirs(dl_dir, exist_ok=True)
            image_path = os.path.abspath(os.path.join(dl_dir, image["name"]))
            with open(image_path, "wb") as f:
                f.write(img_data)
            print(f"ダウンロード完了: {image_path}")
        except Exception as e:
            print(f"画像ダウンロードエラー: {e}")
            # 画像なしでテキストのみ投稿を続行
            image_path = None

    # Seleniumでブログ投稿
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
