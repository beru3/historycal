from playwright.sync_api import sync_playwright
import time
import os
from datetime import datetime, timedelta
import zipfile
import shutil

def login_and_download(username, password, output_dir, currency_pairs):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        try:
            # ログインページにアクセス
            page.goto("https://sec-sso.click-sec.com/loginweb/sessionInvalidate")

            # ログイン情報を入力
            page.fill("#j_username", username)
            page.fill("#j_password", password)

            # ログインボタンをクリック
            page.click("button[name='LoginForm']")
            page.wait_for_load_state("networkidle")
            print("ログインに成功しました。")

            # --- ダウンロード対象月を定義 ---
            today = datetime.now()
            months_to_download = []
            for i in range(12): # 過去12ヶ月分
                target_date = today - timedelta(days=30*i) # 約30日*iで月を遡る
                months_to_download.append((target_date.year, target_date.month))
            
            # 重複を排除し、古い順にソート
            months_to_download = sorted(list(set(months_to_download)))

            # --- 月ごとにループしてダウンロード ---
            for target_year, target_month in months_to_download:
                print(f"\n--- 年月: {target_year}年 {target_month}月 の処理を開始 ---")

                # 正しい年のページに遷移
                # サイトの仕様上、現在の年でない場合は年を指定してURLにアクセスする必要がある
                if target_year != today.year:
                    print(f"{target_year}年のデータページに移動します。")
                    page.goto(f"https://tb.click-sec.com/fx/historical/historicalDataList.do?y={target_year}")
                else:
                    page.goto("https://tb.click-sec.com/fx/historical/historicalDataList.do")
                page.wait_for_load_state("networkidle")

                # --- 通貨ペアごとにループしてダウンロード ---
                for currency_code, pair_info in currency_pairs.items():
                    selector = f"a[href*='c={pair_info['code']}&n={currency_code}'][href*='m={target_month:02d}']"
                    download_link = page.query_selector(selector)

                    if download_link:
                        print(f"  Downloading {pair_info['name']} ({currency_code}) for {target_year}-{target_month:02d}")
                        with page.expect_download() as download_info:
                            download_link.click()
                        download = download_info.value
                        
                        original_filename = download.suggested_filename
                        file_path = os.path.join(output_dir, original_filename)
                        download.save_as(file_path)
                        print(f"  > ファイルを保存しました: {file_path}")
                    else:
                        print(f"  {currency_code} ({target_year}-{target_month:02d}) のリンクが見つかりませんでした。")
                    
                    time.sleep(2) # サーバー負荷軽減のための待機

        except Exception as e:
            print(f"エラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
        finally:
            print("\n全ての処理が完了しました。ブラウザを閉じます。")
            browser.close()

# 使用例
if __name__ == "__main__":
    username = "227556297"
    password = "@Akky0942!"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 月次zipファイルの保存先
    input_dir = os.path.join(script_dir, "input")
    if not os.path.exists(input_dir):
        os.makedirs(input_dir)

    print(f"月次zip保存先: {input_dir}")

    currency_pairs = {
        "USDJPY": {"code": "21", "name": "米ドル/円"},
        "EURJPY": {"code": "22", "name": "ユーロ/円"},
        "GBPJPY": {"code": "23", "name": "ポンド/円"},
        "AUDJPY": {"code": "24", "name": "豪ドル/円"},
        "EURUSD": {"code": "31", "name": "ユーロ/米ドル"}
    }

    login_and_download(username, password, input_dir, currency_pairs)
