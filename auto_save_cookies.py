# -*- coding: utf-8 -*-
"""
アメブロ Cookie自動取得スクリプト
ブラウザを最前面に表示 → ID/パスワード自動入力 → CAPTCHA手動解決 → Cookie保存
"""
import json
import time
import sys
import os
import subprocess
import base64
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

COOKIE_FILE = "ameblo_cookies.json"
WAIT_TIMEOUT = 300  # 5分待つ


def create_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1200,900")
    options.add_argument("--window-position=100,100")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    })
    return driver


def bring_to_front(driver):
    """ウィンドウを最前面に持ってくる"""
    try:
        driver.minimize_window()
        time.sleep(0.5)
        driver.maximize_window()
        time.sleep(0.5)
        driver.set_window_size(1200, 900)
        driver.set_window_position(200, 100)
        driver.switch_to.window(driver.current_window_handle)
    except Exception:
        pass


def is_logged_in(driver):
    """ログイン済みかどうか判定"""
    url = driver.current_url.lower()
    if "signin" in url or "login" in url or "auth.user.ameba" in url:
        return False
    try:
        src = driver.page_source
        if any(kw in src for kw in ["ログアウト", "マイページ", "ブログ管理", "ブログを書く"]):
            return True
    except Exception:
        pass
    return "ameba.jp" in url and "auth" not in url


def main():
    username = os.environ.get("AMEBLO_USERNAME", "")
    password = os.environ.get("AMEBLO_PASSWORD", "")
    if not username or not password:
        print("Error: 環境変数 AMEBLO_USERNAME / AMEBLO_PASSWORD を設定してください")
        print("  PowerShell例: $env:AMEBLO_USERNAME='you@example.com'; $env:AMEBLO_PASSWORD='****'")
        sys.exit(1)

    print("=== Cookie自動取得 ===")
    print("ブラウザが開きます。CAPTCHAが出たら手動で解決してください。")
    print(f"最大{WAIT_TIMEOUT}秒待ちます。")
    print()

    driver = create_driver()

    try:
        # ウィンドウを最前面に
        bring_to_front(driver)

        # Step 1: ログインページ
        print("[1/5] Amebaトップへ...")
        driver.get("https://www.ameba.jp/")
        time.sleep(4)
        bring_to_front(driver)

        try:
            login_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, "ログイン"))
            )
            login_link.click()
            time.sleep(4)
        except Exception:
            driver.get("https://auth.user.ameba.jp/signin")
            time.sleep(4)

        bring_to_front(driver)
        print(f"  ログインページ: {driver.current_url}")

        # Step 2: ID/パスワード自動入力
        print("[2/5] ID/パスワード入力中...")
        try:
            email_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    'input[name="accountId"], input[name="username"], input[name="email"], input[type="email"], input[type="text"]'
                ))
            )
            email_input.clear()
            email_input.send_keys(username)
            time.sleep(1.5)

            pw_input = driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pw_input.clear()
            pw_input.send_keys(password)
            time.sleep(1.5)

            submit = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            submit.click()
            print("  送信完了!")
            time.sleep(6)
        except Exception as e:
            print(f"  自動入力失敗: {e}")

        bring_to_front(driver)

        # Step 3: ログイン完了を待つ
        print(f"[3/5] ログイン完了を待機中...")
        print("  *** CAPTCHAが表示されていたら、ブラウザで解決してください ***")
        for i in range(WAIT_TIMEOUT, 0, -10):
            if is_logged_in(driver):
                print(f"\n  ログイン成功! URL: {driver.current_url}")
                break
            if i % 30 == 0:
                print(f"  残り {i}秒...")
                bring_to_front(driver)
            time.sleep(10)
        else:
            print("\n  タイムアウト。")
            print(f"  現在のURL: {driver.current_url}")

        # Step 4: ブログ管理ページへ
        print("[4/5] ブログ管理ページへ...")
        driver.get("https://blog.ameba.jp/ucs/top.do")
        time.sleep(5)

        if "signin" in driver.current_url or "auth" in driver.current_url:
            print("  ブログ管理でも認証が必要。待機中...")
            print("  *** ブラウザでログインしてください ***")
            bring_to_front(driver)
            for i in range(WAIT_TIMEOUT, 0, -10):
                url = driver.current_url
                if "blog.ameba.jp" in url and "signin" not in url and "auth" not in url:
                    print(f"\n  ブログ管理ログイン成功! URL: {url}")
                    break
                if i % 30 == 0:
                    print(f"  残り {i}秒...")
                time.sleep(10)

        # Step 5: Cookie保存
        print("[5/5] Cookie保存中...")
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"  Cookie保存完了! ({len(cookies)}個)")
        print(f"  最終URL: {driver.current_url}")

        # ログイン成功しているか最終チェック
        final_url = driver.current_url
        if "signin" in final_url or "auth.user.ameba" in final_url:
            print("\n  WARNING: ログインできていません。Cookieは無効です。")
            print("  ブラウザでCAPTCHAを解決できなかった可能性があります。")
            return 1

        # GitHub Secret更新
        cookie_b64 = base64.b64encode(json.dumps(cookies).encode()).decode()
        result = subprocess.run(
            ["gh", "secret", "set", "AMEBLO_COOKIES",
             "--repo", "MuscleLove-777/ameblo-auto-uploader",
             "--body", cookie_b64],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("\n  GitHub Secret (AMEBLO_COOKIES) 更新完了!")
        else:
            print(f"\n  GitHub Secret更新失敗: {result.stderr}")

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
