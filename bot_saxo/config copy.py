# config.py - 設定ファイル
"""
サクソバンクAPI設定
注意: このファイルは.gitignoreに追加してください
"""

# アプリケーション認証情報
CLIENT_ID = "5f19317941744e688ca30be6b2f53659"
CLIENT_SECRET = "7e7f99b6a65343ebae16c915daddff80"  # または a83b3a8b9a85464ba600f63565d644d9
REDIRECT_URI = "http://localhost:8080/callback"

# 環境設定
ENVIRONMENT = 'sim'  # 'sim' または 'live'

# エンドポイント (Simulation環境)
BASE_URL = "https://gateway.saxobank.com/sim/openapi"
AUTH_URL = "https://sim.logonvalidation.net"

# 24時間テストトークン（Developer Portalで取得後に設定）
TEST_TOKEN_24H = "eyJhbGciOiJFUzI1NiIsIng1dCI6IjI3RTlCOTAzRUNGMjExMDlBREU1RTVCOUVDMDgxNkI2QjQ5REEwRkEifQ.eyJvYWEiOiI3Nzc3NSIsImlzcyI6Im9hIiwiYWlkIjoiMTA5IiwidWlkIjoiYm18dEhmdk5nWHNOMlZrQ3YyZGNhdz09IiwiY2lkIjoiYm18dEhmdk5nWHNOMlZrQ3YyZGNhdz09IiwiaXNhIjoiRmFsc2UiLCJ0aWQiOiIyMDAyIiwic2lkIjoiZGNkNDNhMmQ0YjgwNDA2Yzg1MGU1NGI2NmRiOWM2MzUiLCJkZ2kiOiI4NCIsImV4cCI6IjE3NDg3NDA1NzEiLCJvYWwiOiIxRiIsImlpZCI6ImFlNDRlZjZlYTFmODQzMjcxZmY4MDhkZDg2NGRhNmRmIn0.ZtrfRVsuZ6DvX2KYvki6MrBz-3CXSdO4vjUxk8WHQoqyQezEvNAyU6CH468j-mjeshSIJSI2XTrAi5qubdou4A"  # ここに24時間トークンを貼り付け

# ==========================================
# quick_test.py - 簡易テストスクリプト
# ==========================================

import requests
import json
from config import TEST_TOKEN_24H, BASE_URL

def test_24hour_token():
    """24時間トークンでの基本接続テスト"""
    
    if TEST_TOKEN_24H == "your_24hour_token_here":
        print("❌ TEST_TOKEN_24H を設定してください")
        return False
    
    headers = {
        'Authorization': f'Bearer {TEST_TOKEN_24H}',
        'Content-Type': 'application/json'
    }
    
    print("=== 24時間トークンテスト開始 ===")
    
    try:
        # 1. ユーザー情報取得テスト
        print("1. ユーザー情報取得テスト...")
        response = requests.get(f"{BASE_URL}/port/v1/users/me", headers=headers)
        
        if response.status_code == 200:
            user_info = response.json()
            print(f"✅ ユーザー情報取得成功")
            print(f"   ユーザー名: {user_info.get('Name', 'N/A')}")
            print(f"   言語: {user_info.get('Language', 'N/A')}")
        else:
            print(f"❌ ユーザー情報取得失敗: {response.status_code}")
            print(f"   レスポンス: {response.text}")
            return False
        
        # 2. アカウント情報取得テスト
        print("\n2. アカウント情報取得テスト...")
        response = requests.get(f"{BASE_URL}/port/v1/accounts/me", headers=headers)
        
        if response.status_code == 200:
            accounts = response.json()
            print(f"✅ アカウント情報取得成功")
            print(f"   アカウント数: {len(accounts.get('Data', []))}")
            
            if accounts.get('Data'):
                account = accounts['Data'][0]
                print(f"   アカウントキー: {account.get('AccountKey', 'N/A')}")
                print(f"   通貨: {account.get('Currency', 'N/A')}")
        else:
            print(f"❌ アカウント情報取得失敗: {response.status_code}")
            return False
        
        # 3. 残高情報取得テスト
        print("\n3. 残高情報取得テスト...")
        if accounts.get('Data'):
            account_key = accounts['Data'][0]['AccountKey']
            response = requests.get(f"{BASE_URL}/port/v1/accounts/{account_key}/balances", headers=headers)
            
            if response.status_code == 200:
                balances = response.json()
                print(f"✅ 残高情報取得成功")
                
                # 主要な残高情報を表示
                for balance in balances.get('Data', []):
                    currency = balance.get('Currency', 'N/A')
                    cash = balance.get('CashBalance', 0)
                    total = balance.get('TotalValue', 0)
                    print(f"   {currency}: 現金残高={cash:,.2f}, 総額={total:,.2f}")
            else:
                print(f"❌ 残高情報取得失敗: {response.status_code}")
        
        # 4. USDJPY検索テスト
        print("\n4. USDJPY検索テスト...")
        params = {
            'Keywords': 'USDJPY',
            'AssetTypes': 'FxSpot',
            'limit': 5
        }
        response = requests.get(f"{BASE_URL}/ref/v1/instruments", headers=headers, params=params)
        
        if response.status_code == 200:
            instruments = response.json()
            print(f"✅ 通貨ペア検索成功")
            
            for instrument in instruments.get('Data', []):
                symbol = instrument.get('Symbol', 'N/A')
                description = instrument.get('Description', 'N/A')
                uic = instrument.get('Uic', 'N/A')
                print(f"   {symbol}: {description} (UIC: {uic})")
        else:
            print(f"❌ 通貨ペア検索失敗: {response.status_code}")
        
        print("\n🎉 24時間トークンテスト完了！")
        return True
        
    except Exception as e:
        print(f"❌ テスト中にエラーが発生しました: {e}")
        return False

def test_entry_point_integration():
    """エントリーポイントファイル読み込みテスト"""
    print("\n=== エントリーポイント統合テスト ===")
    
    import pandas as pd
    import os
    import glob
    
    try:
        # step3のアウトプットファイルを探す
        base_dir = os.path.dirname(os.path.abspath(__file__))
        entry_dir = os.path.join(base_dir, "entrypoint_fx")
        
        if not os.path.exists(entry_dir):
            print(f"❌ エントリーポイントディレクトリが見つかりません: {entry_dir}")
            return False
        
        # 最新のエントリーポイントファイルを取得
        files = glob.glob(os.path.join(entry_dir, "entrypoints_*.csv"))
        
        if not files:
            print(f"❌ エントリーポイントファイルが見つかりません")
            return False
        
        latest_file = max(files, key=lambda x: os.path.basename(x).split('_')[1].split('.')[0])
        print(f"✅ 最新ファイル発見: {os.path.basename(latest_file)}")
        
        # ファイル読み込み
        df = pd.read_csv(latest_file, encoding='utf-8-sig')
        print(f"✅ エントリーポイント読み込み成功: {len(df)}件")
        
        # データ構造確認
        print(f"   カラム: {df.columns.tolist()}")
        print(f"   通貨ペア: {df['通貨ペア'].unique()}")
        print(f"   エントリー時間範囲: {df['Entry'].min()} - {df['Entry'].max()}")
        
        # サンプルデータ表示
        print("\n   サンプルデータ（先頭3件）:")
        print(df.head(3).to_string(index=False))
        
        return True
        
    except Exception as e:
        print(f"❌ エントリーポイント統合テストエラー: {e}")
        return False

if __name__ == "__main__":
    # 24時間トークンテスト
    token_test_result = test_24hour_token()
    
    # エントリーポイント統合テスト
    entry_test_result = test_entry_point_integration()
    
    # 総合結果
    print("\n" + "="*50)
    print("総合テスト結果:")
    print(f"24時間トークンテスト: {'✅ 成功' if token_test_result else '❌ 失敗'}")
    print(f"エントリーポイント統合: {'✅ 成功' if entry_test_result else '❌ 失敗'}")
    
    if token_test_result and entry_test_result:
        print("\n🎉 全テスト成功！次のステップに進む準備ができました。")
    else:
        print("\n⚠️  一部テストが失敗しました。設定を確認してください。")

# ==========================================
# .gitignore ファイルに追加すべき内容
# ==========================================
"""
以下を .gitignore に追加してください:

# サクソバンク認証情報
config.py
saxo_tokens.json
*.token

# 一時ファイル
__pycache__/
*.pyc
*.pyo
"""