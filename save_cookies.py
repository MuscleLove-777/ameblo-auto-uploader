# -*- coding: utf-8 -*-
"""
アメブロ Cookie取得スクリプト(対話 + 完全自動化版)

起動するとブラウザが開き、ユーザーが手動でログイン。
ログイン完了を検知したら:
  1. ameblo_cookies.json に保存
  2. base64化して gh CLI で GitHub Secrets(AMEBLO_COOKIES) を上書き
  3. .last_refresh を更新(ローカルrefresh系との整合)
  4. gh workflow run で当日のAmeba Blog Auto Postを即時実行

手動操作は「ブラウザログイン」の 1 回のみ。その後の Secrets 反映〜
当日投稿リカバリまで完全自動。
"""
import base64
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from ameblo_auth import create_driver

SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = SCRIPT_DIR / "ameblo_cookies.json"
LAST_REFRESH_FILE = SCRIPT_DIR / ".last_refresh"

REPO = "MuscleLove-777/ameblo-auto-uploader"
SECRET_NAME = "AMEBLO_COOKIES"
WORKFLOW_FILE = "ameblo-post.yml"

GH_CANDIDATES = [
    "gh",
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
]


def find_gh() -> str | None:
    for candidate in GH_CANDIDATES:
        try:
            r = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def push_secret(gh_path: str) -> bool:
    with open(COOKIE_FILE, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    print(f"→ gh secret set {SECRET_NAME} (size={len(b64)}B)")
    r = subprocess.run(
        [gh_path, "secret", "set", SECRET_NAME, "--repo", REPO],
        input=b64, capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        print(f"  FAILED rc={r.returncode} stderr={r.stderr[:300]}")
        return False
    print(f"  OK: Secrets更新完了")
    return True


def trigger_workflow(gh_path: str) -> bool:
    print(f"→ gh workflow run {WORKFLOW_FILE}")
    r = subprocess.run(
        [gh_path, "workflow", "run", WORKFLOW_FILE, "--repo", REPO],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        print(f"  FAILED rc={r.returncode} stderr={r.stderr[:300]}")
        return False
    print(f"  OK: Amebaワークフロー即時実行を発火")
    return True


def main():
    print("=== アメブロ Cookie取得 + Secrets完全自動更新 ===")
    print("ブラウザが開きます。90秒以内にログインしてください。")

    gh_path = find_gh()
    if not gh_path:
        print("ERROR: gh CLI が見つかりません。インストールしてください")
        return 10
    print(f"gh検出: {gh_path}")

    driver = create_driver(headless=False)
    try:
        driver.get("https://www.ameba.jp/")
        time.sleep(3)

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

        print("ブラウザでログインしてください...")
        print("残り: ", end="", flush=True)
        for i in range(90, 0, -5):
            current = driver.current_url
            if "ameba.jp" in current and "signin" not in current and "login" not in current and "auth" not in current:
                if any(kw in driver.page_source for kw in ["ログアウト", "マイページ", "ブログ管理"]):
                    print(f"\nログイン検出!")
                    break
            print(f"{i}s ", end="", flush=True)
            time.sleep(5)
        print()

        print("ブログ管理ページに移動...")
        driver.get("https://blog.ameba.jp/ucs/top.do")
        time.sleep(8)

        if "signin" in driver.current_url:
            print("ブログ管理の再ログインが必要です。ブラウザで操作してください...")
            for i in range(60, 0, -5):
                if "blog.ameba.jp" in driver.current_url and "signin" not in driver.current_url:
                    print(f"\nブログ管理ログイン検出!")
                    break
                print(f"{i}s ", end="", flush=True)
                time.sleep(5)
            print()

        cookies = driver.get_cookies()
        if len(cookies) == 0:
            print("ERROR: Cookieが0個。ログイン失敗の可能性")
            return 11

        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print(f"\nCookie保存完了! ({len(cookies)}個) -> {COOKIE_FILE.name}")
        print(f"最終URL: {driver.current_url}")
    except Exception as e:
        print(f"Error during browser phase: {e}")
        return 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    # ここから完全自動フェーズ(ブラウザ閉じたあと)
    if not push_secret(gh_path):
        print("⚠ Secrets更新に失敗。手動で `gh secret set AMEBLO_COOKIES` を")
        return 22

    LAST_REFRESH_FILE.write_text(datetime.now().isoformat(), encoding="utf-8")
    print(f".last_refresh 更新完了")

    if not trigger_workflow(gh_path):
        print("⚠ ワークフロー即時実行に失敗(Secretsは更新済み。明日の定期実行で回復します)")
        return 23

    print("\n=== すべて完了 ===")
    print("今日分のAmeba投稿がGitHub Actionsで走ります。数分後に Actions タブで確認してください:")
    print(f"  https://github.com/{REPO}/actions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
