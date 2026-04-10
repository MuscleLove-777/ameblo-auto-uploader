# -*- coding: utf-8 -*-
"""
Ameba Blog (ameblo.jp) Selenium認証ヘルパー
ブラウザ自動化でログインし、認証済みドライバーを返す
"""
import os
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- 定数 ---
AMEBA_LOGIN_URL = "https://www.ameba.jp/"
AMEBA_BLOG_EDITOR_URL = "https://blog.ameba.jp/ucs/entry/srventryinsertinput.do"

# リアルなUser-Agentリスト
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]


def human_delay(min_sec=2, max_sec=5):
    """人間らしいランダム遅延"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)
    return delay


def create_driver(headless=True):
    """Chrome WebDriverを作成（検出回避設定付き）"""
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    # 検出回避
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")

    # webdriver検出を回避
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)

    # navigator.webdriver を隠す
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['ja', 'en-US', 'en'],
            });
        """
    })

    return driver


def login_ameba(driver, username=None, password=None):
    """
    Amebaにログインする

    Args:
        driver: Selenium WebDriver
        username: Amebaユーザー名（Noneの場合は環境変数から取得）
        password: Amebaパスワード（Noneの場合は環境変数から取得）

    Returns:
        bool: ログイン成功したらTrue
    """
    username = username or os.environ.get("AMEBLO_USERNAME", "")
    password = password or os.environ.get("AMEBLO_PASSWORD", "")

    if not username or not password:
        print("Error: AMEBLO_USERNAME / AMEBLO_PASSWORD が未設定です")
        return False

    print(f"Amebaにログイン中... (user: {username[:3]}***)")

    try:
        # ログインページへ移動
        driver.get(AMEBA_LOGIN_URL)
        human_delay(3, 6)

        # Amebaのログインフォームを探す
        # パターン1: 直接ログインフォームがある場合
        # パターン2: ログインボタンをクリックしてフォームを表示する場合
        # トップページから「ログイン」ボタンをクリック
        try:
            login_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, "ログイン"))
            )
            login_link.click()
            human_delay(3, 5)
            print(f"ログインページ: {driver.current_url}")
        except TimeoutException:
            # 直接ログインURLを試す
            login_urls = [
                "https://auth.user.ameba.jp/login",
                "https://dauth.user.ameba.jp/login/ameba",
            ]
            for url in login_urls:
                driver.get(url)
                human_delay(2, 4)
                if "login" in driver.current_url:
                    break

        # メールアドレス/ユーザー名入力欄を探す
        email_selectors = [
            'input[name="accountId"]',
            'input[name="username"]',
            'input[name="email"]',
            'input[name="loginId"]',
            'input[type="email"]',
            'input[id="accountId"]',
            '#ameba-id',
            'input[placeholder*="ID"]',
            'input[placeholder*="メール"]',
        ]

        email_input = None
        for selector in email_selectors:
            try:
                email_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                if email_input.is_displayed():
                    break
                email_input = None
            except TimeoutException:
                continue

        if not email_input:
            # フォールバック: すべてのinput要素から探す
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                inp_type = inp.get_attribute("type") or ""
                if inp_type in ("text", "email") and inp.is_displayed():
                    email_input = inp
                    break

        if not email_input:
            print("Error: ユーザー名入力欄が見つかりません")
            print(f"Current URL: {driver.current_url}")
            print(f"Page title: {driver.title}")
            return False

        # ユーザー名を入力（人間らしくゆっくり）
        email_input.clear()
        for char in username:
            email_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))
        human_delay(1, 2)

        # パスワード入力欄を探す
        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            'input[id="password"]',
        ]

        password_input = None
        for selector in password_selectors:
            try:
                password_input = driver.find_element(By.CSS_SELECTOR, selector)
                if password_input.is_displayed():
                    break
                password_input = None
            except NoSuchElementException:
                continue

        if not password_input:
            print("Error: パスワード入力欄が見つかりません")
            return False

        # パスワードを入力
        password_input.clear()
        for char in password:
            password_input.send_keys(char)
            time.sleep(random.uniform(0.05, 0.15))
        human_delay(1, 2)

        # ログインボタンをクリック
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button[class*="login"]',
            'button[class*="submit"]',
            '[data-action="submit"]',
            '.loginBtn',
            'button[id*="login"]',
        ]

        submit_btn = None
        for selector in submit_selectors:
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, selector)
                if submit_btn.is_displayed() and submit_btn.is_enabled():
                    break
                submit_btn = None
            except NoSuchElementException:
                continue

        if not submit_btn:
            # フォールバック: ボタン要素から探す
            buttons = driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                text = btn.text.strip()
                if text in ("ログイン", "Login", "Sign in", "サインイン") and btn.is_displayed():
                    submit_btn = btn
                    break

        if not submit_btn:
            print("Error: ログインボタンが見つかりません")
            return False

        # reCAPTCHA v3トークン生成（invisible reCAPTCHA対応）
        try:
            recaptcha_field = driver.find_elements(By.CSS_SELECTOR, 'input[name="reCaptchaToken"]')
            if recaptcha_field:
                print("  reCAPTCHA検出 - トークン生成を試行...")
                # サイトキーを取得（grecaptchaスクリプトまたはdata-sitekeyから）
                token = driver.execute_script("""
                    // 方法1: grecaptcha.execute() で直接トークン取得
                    if (typeof grecaptcha !== 'undefined' && grecaptcha.execute) {
                        // サイトキーを探す
                        var siteKey = null;
                        // data-sitekey属性から取得
                        var el = document.querySelector('[data-sitekey]');
                        if (el) siteKey = el.getAttribute('data-sitekey');
                        // scriptのsrc URLから取得
                        if (!siteKey) {
                            var scripts = document.querySelectorAll('script[src*="recaptcha"]');
                            for (var s of scripts) {
                                var m = s.src.match(/render=([^&]+)/);
                                if (m) { siteKey = m[1]; break; }
                            }
                        }
                        if (siteKey && siteKey !== 'explicit') {
                            try {
                                return new Promise(function(resolve) {
                                    grecaptcha.ready(function() {
                                        grecaptcha.execute(siteKey, {action: 'login'}).then(function(token) {
                                            resolve(token);
                                        });
                                    });
                                });
                            } catch(e) { return 'error:' + e.message; }
                        }
                        return 'no_sitekey';
                    }
                    return 'no_grecaptcha';
                """)
                if token and not str(token).startswith(('no_', 'error:')):
                    driver.execute_script(
                        "document.querySelector('input[name=\"reCaptchaToken\"]').value = arguments[0];",
                        token
                    )
                    print(f"  reCAPTCHAトークン設定完了 (len={len(str(token))})")
                else:
                    print(f"  reCAPTCHAトークン取得失敗: {token}")
                    # フォームのsubmitイベント経由でトークンが自動設定される場合もあるため続行
        except Exception as e:
            print(f"  reCAPTCHA処理エラー: {e}")

        # ボタンクリックの代わりにJS経由でフォームsubmit（reCAPTCHAのonsubmitハンドラ発火のため）
        try:
            js_submitted = driver.execute_script("""
                var form = document.querySelector('form');
                if (form) {
                    // submitイベントを発火させてからsubmit
                    var event = new Event('submit', {bubbles: true, cancelable: true});
                    var cancelled = !form.dispatchEvent(event);
                    if (!cancelled) form.submit();
                    return 'form_submit';
                }
                return 'no_form';
            """)
            print(f"  フォームsubmit: {js_submitted}")
        except Exception:
            # フォールバック: 通常のボタンクリック
            submit_btn.click()

        # ログイン後のリダイレクト完了を待つ（URLがsigninから変わるまで最大30秒）
        pre_url = driver.current_url
        for _ in range(15):
            time.sleep(2)
            current_url = driver.current_url
            if current_url != pre_url and "signin" not in current_url and "login" not in current_url.lower():
                break
        else:
            # タイムアウト - まだログインページにいる場合
            current_url = driver.current_url

        print(f"ログイン後URL: {current_url}")

        # まだログインページ/認証ページにいる場合は失敗
        if "signin" in current_url or "login" in current_url.lower() or "auth.user.ameba" in current_url:
            # CAPTCHA検出
            try:
                page_source = driver.page_source
                if any(kw in page_source.lower() for kw in ["recaptcha", "hcaptcha", "g-recaptcha", "h-captcha", "captcha"]):
                    print("Warning: CAPTCHAが検出されました。手動ログインしてCookieを更新してください。")
            except Exception:
                pass

            # 同意ボタンやCAPTCHAチェック（「確認」は除外 - Cookie同意バナーの誤クリック防止）
            try:
                for btn in driver.find_elements(By.CSS_SELECTOR, "button, a, input[type='submit']"):
                    btn_text = (btn.text or "").strip()
                    btn_val = (btn.get_attribute("value") or "").strip()
                    combined = btn_text + btn_val
                    if any(kw in combined for kw in ["許可", "同意", "Allow", "Accept", "続行", "次へ"]):
                        if btn.is_displayed() and btn.is_enabled():
                            print(f"  同意ボタン検出: '{combined}' → クリック")
                            btn.click()
                            human_delay(5, 8)
                            current_url = driver.current_url
                            print(f"  クリック後URL: {current_url}")
                            # クリック後にsigninから抜けたかチェック
                            if "signin" not in current_url and "login" not in current_url.lower() and "auth.user.ameba" not in current_url:
                                # リダイレクト先が無関係なページでないかチェック
                                if any(bad in current_url for bad in ["/staff/", "/entry-"]):
                                    print(f"  Warning: 無関係なページにリダイレクトされました: {current_url}")
                                    print("  ログイン失敗と判定します")
                                    # ログインページに戻す試行はしない（無限ループ防止）
                                else:
                                    print(f"  signinページから抜けました")
                            break
            except Exception as e:
                print(f"  同意ボタン探索エラー: {e}")

        # 最終判定: まだ認証ページにいたら失敗
        current_url = driver.current_url
        if "signin" in current_url or "auth.user.ameba" in current_url:
            print(f"Error: ログインページから抜け出せません: {current_url}")
            # デバッグ情報強化
            _dump_debug_info(driver)
            return False

        # 無関係なページへのリダイレクト検出
        if any(bad in current_url for bad in ["/staff/", "/entry-"]):
            print(f"Error: 無関係なページにリダイレクトされました: {current_url}")
            _dump_debug_info(driver)
            return False

        # ログイン成功の判定（厳密化）
        SUCCESS_PATTERNS = ["blog.ameba.jp/ucs", "ameba.jp/home", "ameba.jp/mypage", "blog.ameba.jp/"]
        FAILURE_PATTERNS = ["/staff/", "/entry-", "signin", "login", "auth.user.ameba"]

        if any(pat in current_url for pat in SUCCESS_PATTERNS):
            if not any(bad in current_url for bad in FAILURE_PATTERNS):
                print("ログイン成功!")
                return True

        # Cookie確認（ただしログインページでないことが前提）
        cookies = driver.get_cookies()
        session_cookies = [c for c in cookies if any(
            name in c["name"].lower() for name in ["session", "token", "auth", "login"]
        )]
        if session_cookies:
            print("ログイン成功! (セッションCookie確認)")
            return True

        # ページ内容でログイン確認
        try:
            page_source = driver.page_source
            if any(keyword in page_source for keyword in ["ログアウト", "マイページ", "ブログを書く"]):
                print("ログイン成功! (ページ内容確認)")
                return True
        except Exception:
            pass

        print("Warning: ログイン状態が確認できません")
        print(f"URL: {current_url}")
        _dump_debug_info(driver)
        return False

    except Exception as e:
        print(f"ログインエラー: {e}")
        return False


def _dump_debug_info(driver):
    """ログイン失敗時のデバッグ情報をダンプする"""
    try:
        print(f"  [Debug] Page title: {driver.title}")
        print(f"  [Debug] Current URL: {driver.current_url}")

        # Cookies
        cookies = driver.get_cookies()
        cookie_names = [c["name"] for c in cookies]
        print(f"  [Debug] Cookies ({len(cookies)}): {cookie_names[:10]}")

        # input要素一覧
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"  [Debug] Input elements ({len(inputs)}):")
        for inp in inputs[:15]:
            inp_type = inp.get_attribute("type") or ""
            inp_name = inp.get_attribute("name") or ""
            inp_id = inp.get_attribute("id") or ""
            visible = inp.is_displayed()
            print(f"    type={inp_type}, name={inp_name}, id={inp_id}, visible={visible}")

        # button要素一覧
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"  [Debug] Button elements ({len(buttons)}):")
        for btn in buttons[:10]:
            btn_text = (btn.text or "").strip()[:50]
            visible = btn.is_displayed()
            print(f"    text='{btn_text}', visible={visible}")

        # CAPTCHA検出
        page_source = driver.page_source
        if any(kw in page_source.lower() for kw in ["recaptcha", "hcaptcha", "g-recaptcha", "h-captcha", "captcha"]):
            print("  [Debug] CAPTCHA detected in page source!")

        # スクリーンショット保存
        try:
            screenshot_path = "login_debug.png"
            driver.save_screenshot(screenshot_path)
            print(f"  [Debug] Screenshot saved: {screenshot_path}")
        except Exception as ss_err:
            print(f"  [Debug] Screenshot failed: {ss_err}")

    except Exception as e:
        print(f"  [Debug] Debug dump error: {e}")


def navigate_to_editor(driver):
    """
    ブログ記事エディタページに移動する

    Args:
        driver: ログイン済みWebDriver

    Returns:
        bool: エディタページに移動できたらTrue
    """
    print("ブログエディタに移動中...")
    human_delay(2, 4)

    # エディタURLパターン（新旧両方試す）
    editor_urls = [
        AMEBA_BLOG_EDITOR_URL,
        "https://blog.ameba.jp/ucs/entry/srventryinsertinput.do",
        "https://blog.ameba.jp/entry/new",
    ]

    for url in editor_urls:
        try:
            driver.get(url)
            human_delay(3, 5)

            current_url = driver.current_url
            # ブログ管理は別SSOなので再ログインが必要な場合がある
            if "signin" in current_url or "login" in current_url.lower():
                print(f"  ブログ管理の再ログインが必要 - ログイン実行中...")
                username = os.environ.get("AMEBLO_USERNAME", "")
                password = os.environ.get("AMEBLO_PASSWORD", "")
                # メール/ID入力欄を探す
                try:
                    email_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR,
                            'input[type="email"], input[type="text"], input[name="accountId"], input[name="username"]'
                        ))
                    )
                    email_input.clear()
                    for char in username:
                        email_input.send_keys(char)
                        time.sleep(random.uniform(0.05, 0.15))
                    human_delay(1, 2)

                    pw_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
                    pw_input.clear()
                    for char in password:
                        pw_input.send_keys(char)
                        time.sleep(random.uniform(0.05, 0.15))
                    human_delay(1, 2)

                    submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
                    submit.click()
                    # リダイレクト完了を待つ
                    pre_url = driver.current_url
                    for _ in range(15):
                        time.sleep(2)
                        current_url = driver.current_url
                        if current_url != pre_url and "signin" not in current_url and "login" not in current_url.lower():
                            break
                    current_url = driver.current_url
                    print(f"  再ログイン後URL: {current_url}")
                except Exception as e:
                    print(f"  再ログイン失敗: {e}")
                    continue

            # まだログインページにいる場合はスキップ
            current_url = driver.current_url
            if "signin" in current_url or "login" in current_url.lower() or "auth.user.ameba" in current_url:
                print(f"  ログインページから抜け出せません: {current_url}")
                continue

            # エディタページが表示されたか確認
            page_source = driver.page_source
            if any(keyword in page_source for keyword in [
                "entry_title", "entryTitle",
                "entry_body", "entryBody",
                "cke_editor", "entry/new",
                "EntryEditor", "blog-entry", "ブログを書く",
            ]):
                print(f"エディタページ到達: {current_url}")
                return True

            # URLにentry/newが含まれていればエディタ
            if "entry" in current_url and "blog.ameba.jp" in current_url:
                print(f"エディタページ到達（URL判定）: {current_url}")
                return True

        except Exception as e:
            print(f"  {url} -> エラー: {e}")
            continue

    print("Error: エディタページに移動できません")
    return False


if __name__ == "__main__":
    print("=== Ameba Blog ログインテスト ===")
    print("環境変数 AMEBLO_USERNAME, AMEBLO_PASSWORD を設定してください")
    print()

    driver = create_driver(headless=False)  # テスト時はheadless=False
    try:
        success = login_ameba(driver)
        if success:
            print("\nログイン成功! エディタに移動します...")
            navigate_to_editor(driver)
            input("Enterキーで終了...")
        else:
            print("\nログイン失敗")
    finally:
        driver.quit()
