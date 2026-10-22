# -*- coding: utf-8 -*-
"""
Ameba Cookie 自動リフレッシュ(Stage 1: Cookie Touch のみ)

戦略:
  1. 既存の ameblo_cookies.json を新しいChromeに注入
  2. https://blog.ameba.jp/ucs/top.do を訪問してセッションを touch
  3. サーバー側が sliding expiration でセッション延命 → 新しいCookie を取得
  4. ameblo_cookies.json を上書き保存
  5. base64化して gh CLI 経由で AMEBLO_COOKIES シークレットを更新
  6. .last_refresh にタイムスタンプを記録

失敗時(Cookieハード失効など)はログだけ残して終了。
翌日のGitHub Actionsが既存LINE通知機構で失敗を知らせてくれる。

パスワード認証は一切行わないので reCAPTCHA リスクゼロ。
"""
import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ameblo_auth import create_driver


def at_cookie_alive(cookies, min_remaining_hours: int = 12) -> tuple[bool, str]:
    """
    AT Cookie(Ameba認証JWT)の exp を見て実戦で使えるか判定する。
    GitHub Actions 側で使う時に死んでいてはならないので、最低 12 時間の猶予を要求する。
    戻り値: (生きているか, 説明文)
    """
    for c in cookies:
        if c.get("name") == "AT":
            exp = c.get("expiry")
            if not exp:
                return False, "AT Cookie に expiry 無し"
            now = datetime.now(timezone.utc).timestamp()
            remaining_h = (exp - now) / 3600
            if remaining_h < min_remaining_hours:
                return False, "AT Cookie の有効期間が不足"
            return True, "AT Cookie 有効"
    return False, "AT Cookie が無い"

SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = SCRIPT_DIR / "ameblo_cookies.json"
LAST_REFRESH_FILE = SCRIPT_DIR / ".last_refresh"
LOG_FILE = SCRIPT_DIR / "refresh.log"

REPO = "MuscleLove-777/ameblo-auto-uploader"
SECRET_NAME = "AMEBLO_COOKIES"

# gh CLI のフルパス候補(PATH未通過の scheduled task からも動かすため)
GH_CANDIDATES = [
    "gh",
    r"C:\Program Files\GitHub CLI\gh.exe",
    r"C:\Program Files (x86)\GitHub CLI\gh.exe",
]


def log(msg: str) -> None:
    """コンソールとログファイルの両方に出力"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def find_gh() -> str | None:
    """利用可能な gh 実行ファイルを探す"""
    for candidate in GH_CANDIDATES:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def touch_session(driver) -> bool:
    """
    既存Cookieを注入してブログ管理ページを訪問する。
    成功すれば driver の状態でセッション生存、get_cookies() で新鮮なCookieが取れる。
    """
    if not COOKIE_FILE.exists():
        log("ERROR: ameblo_cookies.json が見つからない")
        return False

    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    log("既存Cookieをロード")

    # Step 1: ドメイン設定のため ameba.jp にアクセス
    driver.get("https://www.ameba.jp/")
    time.sleep(2)
    _inject(driver, cookies)

    # Step 2: blog.ameba.jp にアクセスして別ドメインCookieも注入
    driver.get("https://blog.ameba.jp/")
    time.sleep(2)
    _inject(driver, cookies)

    # Step 3: ブログ管理ページを叩いてセッション touch
    driver.get("https://blog.ameba.jp/ucs/top.do")
    time.sleep(5)

    current = driver.current_url
    log("管理ページへの遷移を確認")

    if "signin" in current or "login" in current.lower() or "auth.user.ameba" in current:
        log("Cookie touch 失敗: signin にリダイレクトされた(Cookie死亡の可能性)")
        return False

    return True


def _inject(driver, cookies) -> None:
    """Cookieを安全に注入(sameSite補正+ドメイン不一致はスキップ)"""
    for c in cookies:
        fixed = dict(c)
        if "sameSite" in fixed and fixed["sameSite"] not in ("Strict", "Lax", "None"):
            fixed["sameSite"] = "None"
        try:
            driver.add_cookie(fixed)
        except Exception:
            # ドメイン違いの Cookie はスキップ
            pass


def push_to_github_secret(gh_path: str) -> bool:
    """ameblo_cookies.json を base64 化して gh secret set で上書き"""
    with open(COOKIE_FILE, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")

    log("GitHub Secrets更新を実行")
    result = subprocess.run(
        [gh_path, "secret", "set", SECRET_NAME, "--repo", REPO],
        input=b64,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        log(f"gh secret set 失敗: rc={result.returncode}")
        return False
    log("AMEBLO_COOKIES シークレット更新成功")
    return True


def main() -> int:
    log("=" * 50)
    log("Auto cookie refresh 開始")

    # gh が見つからないと何も進められない
    gh_path = find_gh()
    if not gh_path:
        log("ERROR: gh CLI が見つからない。PATH または既定の場所を確認")
        return 10
    log("gh 検出完了")

    if not COOKIE_FILE.exists():
        log("ERROR: ameblo_cookies.json が無い。先に save_cookies.py を実行して")
        return 11

    driver = None
    try:
        driver = create_driver(headless=True)
        log("Chrome (headless) 起動")

        # touch前にAT Cookie(JWT)の生存を確認。死んでるなら touch しても無駄。
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            pre_cookies = json.load(f)
        alive, msg = at_cookie_alive(pre_cookies)
        log("Pre-touch AT check: 有効" if alive else "Pre-touch AT check: 無効")
        if not alive:
            log("=== 失敗: AT Cookieがハード失効 ===")
            log("→ save_cookies.py を実行してブラウザで1回だけ再ログインが必要")
            return 23

        if not touch_session(driver):
            log("=== 失敗: Cookie touch 不可 ===")
            log("→ save_cookies.py を実行してブラウザで1回だけ再ログインが必要")
            return 20

        # セッション生存確認できたので、新鮮なCookieを取得して保存
        new_cookies = driver.get_cookies()
        log("Touch後のCookie取得完了")

        if len(new_cookies) == 0:
            log("WARNING: Cookieを取得できず保存スキップ")
            return 21

        # touch後も AT が有効期限を更新できたか確認
        alive_after, msg_after = at_cookie_alive(new_cookies)
        log("Post-touch AT check: 有効" if alive_after else "Post-touch AT check: 無効")
        if not alive_after:
            log("WARNING: touch後も AT が更新されなかった。Secrets反映スキップ")
            return 24

        with open(COOKIE_FILE, "w", encoding="utf-8") as f:
            json.dump(new_cookies, f, indent=2, ensure_ascii=False)
        log("Cookieを上書き保存")

        if not push_to_github_secret(gh_path):
            log("=== 失敗: GitHub シークレット更新失敗 ===")
            return 22

        # 成功マーカー
        LAST_REFRESH_FILE.write_text(
            datetime.now().isoformat(), encoding="utf-8"
        )
        log("=== 成功 ===")
        return 0

    except Exception as e:
        log(f"Exception: {type(e).__name__}")
        return 30
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        log("終了")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"処理失敗: {type(e).__name__}")
        sys.exit(1)
