# -*- coding: utf-8 -*-
"""
アメブロ Cookie取得スクリプト
ブラウザが開く → 90秒以内に手動でログイン → Cookie自動保存
"""
import json
import time
import sys
from ameblo_auth import create_driver

COOKIE_FILE = "ameblo_cookies.json"


def main():
    print("=== アメブロ Cookie取得 ===")
    print("ブラウザが開きます。90秒以内にログインしてください。")

    driver = create_driver(headless=False)
    try:
        # ログインページへ
        driver.get("https://www.ameba.jp/")
        time.sleep(3)

        # ログインボタンをクリック
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        try:
            login_link = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.LINK_TEXT, "ログイン"))
            )
            login_link.click()
        except Exception:
            pass

        # 90秒待つ（その間に手動でログイン）
        print("ブラウザでログインしてください...")
        print("残り: ", end="", flush=True)
        for i in range(90, 0, -5):
            # ログイン完了チェック
            current = driver.current_url
            if "ameba.jp" in current and "signin" not in current and "login" not in current and "auth" not in current:
                if any(kw in driver.page_source for kw in ["ログアウト", "マイページ", "ブログ管理"]):
                    print(f"\nログイン検出!")
                    break
            print(f"{i}s ", end="", flush=True)
            time.sleep(5)
        print()

        # ブログ管理ページにもアクセス
        print("ブログ管理ページに移動...")
        driver.get("https://blog.ameba.jp/ucs/top.do")
        time.sleep(8)

        # ブログ管理でも再ログインが必要な場合は待つ
        if "signin" in driver.current_url:
            print("ブログ管理の再ログインが必要です。ブラウザで操作してください...")
            for i in range(60, 0, -5):
                if "blog.ameba.jp" in driver.current_url and "signin" not in driver.current_url:
                    print(f"\nブログ管理ログイン検出!")
                    break
                print(f"{i}s ", end="", flush=True)
                time.sleep(5)
            print()

        # Cookie保存
        cookies = driver.get_cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        print(f"\nCookie保存完了! ({len(cookies)}個)")
        print(f"保存先: {COOKIE_FILE}")
        print(f"最終URL: {driver.current_url}")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        driver.quit()


if __name__ == "__main__":
    sys.exit(main())
