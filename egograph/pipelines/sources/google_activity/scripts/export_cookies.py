"""Google Cookie エクスポートスクリプト。

GoogleアカウントのCookieを取得し、GitHub Secretsに登録するための
JSONファイルを生成します。
"""

import argparse
import json
import re
import sys

from playwright.sync_api import sync_playwright


def _sanitize_account(account: str) -> str:
    """アカウント識別子をサニタイズする。

    Args:
        account: アカウント識別子（例: account1, account2）

    Returns:
        サニタイズされたアカウント識別子（英数字とアンダースコアのみ）

    Raises:
        ValueError: サニタイズ結果が空の場合
    """
    # GitHub Actionsシークレット名はA-Z、0-9、アンダースコアのみ許可されるため、
    # ハイフンもアンダースコアに置換する
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", account).strip("_").replace("-", "_")
    if not sanitized:
        raise ValueError(f"Invalid account identifier: {account}")
    return sanitized


def export_cookies(account: str) -> None:
    """Playwrightを使用してGoogle Cookieをエクスポートする。

    Args:
        account: アカウント識別子（例: account1, account2）
    """
    sanitized_account = _sanitize_account(account)
    print(f"🚀 Starting browser for {sanitized_account}...")
    print("📝 Please login to Google in the browser that opens")
    print("⏸️  After login, press Enter here to extract cookies...")

    with sync_playwright() as p:
        # Googleの自動化検出を回避するための設定
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
        )
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
        context = browser.new_context(
            user_agent=ua,
            viewport={"width": 1280, "height": 720},
        )

        page = context.new_page()
        # navigator.webdriverを完全に隠すためのスクリプト
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page.goto("https://accounts.google.com/ServiceLogin")

        # Enterキーを待つ
        input()

        # Cookieを取得
        cookies = context.cookies()

        # ブラウザを閉じる
        browser.close()

    # Cookieを保存
    filename = f"cookies_{sanitized_account}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    print(f"✅ Cookies saved to {filename}")

    # GitHub Secrets登録手順を表示
    print("\n" + "=" * 60)
    print("📋 GitHub Secrets Registration Instructions:")
    print("=" * 60)
    print(f"\n1. Copy content of {filename}")
    print("2. Go to your GitHub repository settings:")
    print("   https://github.com/<your-org>/<your-repo>/settings/secrets/actions")
    print("\n3. Create a new secret:")
    print(f"   Name: GOOGLE_COOKIE_{sanitized_account.upper()}")
    print(f"   Value: [Paste JSON content from {filename}]")
    print("\n4. Click 'Add secret'")
    print("\n" + "=" * 60)
    print("✅ Setup complete! The secret is now ready for GitHub Actions.")


def main() -> int:
    """エントリーポイント。"""
    parser = argparse.ArgumentParser(
        description="Export Google cookies for YouTube data collection"
    )
    parser.add_argument(
        "--account",
        type=str,
        required=True,
        help="Account identifier (e.g., account1, account2)",
    )
    args = parser.parse_args()

    try:
        export_cookies(args.account)
        return 0
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
