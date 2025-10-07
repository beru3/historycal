# サクソバンクAPI 次のステップガイド

## Step 1: Developer Portalでアプリケーション作成

### 1.1 アプリケーション作成画面へ
'''
1. Developer Portal（https://www.developer.saxo/）にログイン
2. 画面上部の "Application Management" をクリック
3. "Create Application" ボタンをクリック
'''

### 1.2 アプリケーション情報入力
'''
Application Name: FX Auto Trading System
Application Type: Server-side Application
Description: FX自動売買システム（学習・研究目的）
Redirect URI: http://localhost:8080/callback
Grant Types: Authorization Code
Scopes: openapi
'''

### 1.3 利用規約同意・作成
'''
Terms & Conditions に同意してアプリケーション作成
'''

## Step 2: 認証情報の取得

### 2.1 作成されたアプリケーションから以下を取得
'''
- Application Key (Client ID)
- Application Secret (Client Secret)  
- Redirect URI
'''

### 2.2 これらの情報をメモまたは安全な場所に保存

## Step 3: 24時間テストトークンの取得

### 3.1 Quick Start用のテストトークン
'''
1. Developer Portal内で "Get 24 Hour Token" を探す
2. テストトークンを生成
3. このトークンで基本的なAPI呼び出しをテスト
'''

## Step 4: 基本API接続テスト

### 4.1 設定ファイル作成 (config.py)
'''python
# config.py
CLIENT_ID = "your_application_key_here"
CLIENT_SECRET = "your_application_secret_here"
REDIRECT_URI = "http://localhost:8080/callback"
ENVIRONMENT = 'sim'  # 'sim' または 'live'

# 24時間テストトークン（最初のテスト用）
TEST_TOKEN = "your_24hour_token_here"
'''

### 4.2 基本接続テスト実行
'''python
# test_connection.py
from saxo_auth import SaxoBankAuth
from saxo_basic_api import SaxoBankAPI
import json

def test_basic_connection():
    # 設定読み込み
    from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TEST_TOKEN
    
    # 認証インスタンス作成
    auth = SaxoBankAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, environment='sim')
    
    # 24時間テストトークンを直接設定
    auth.access_token = TEST_TOKEN
    
    # API インスタンス作成
    api = SaxoBankAPI(auth)
    
    try:
        # ユーザー情報取得テスト
        print("=== ユーザー情報取得テスト ===")
        user_info = api.get_user_info()
        print(json.dumps(user_info, indent=2, ensure_ascii=False))
        
        # アカウント情報取得テスト
        print("\n=== アカウント情報取得テスト ===")
        accounts = api.get_accounts()
        print(json.dumps(accounts, indent=2, ensure_ascii=False))
        
        print("\n✅ 基本接続テスト成功!")
        return True
        
    except Exception as e:
        print(f"❌ 接続テスト失敗: {e}")
        return False

if __name__ == "__main__":
    test_basic_connection()
'''

## Step 5: エントリーポイント読み込み機能の実装

### 5.1 step3のCSVファイル読み込み
'''python
# fx_entry_system.py
import pandas as pd
from datetime import datetime
import os

class FXAutoEntrySystem:
    def __init__(self, api_instance):
        self.api = api_instance
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.entry_dir = os.path.join(self.base_dir, "entrypoint_fx")
    
    def get_latest_entrypoint_file(self):
        """最新のエントリーポイントファイルを取得"""
        import glob
        files = glob.glob(os.path.join(self.entry_dir, "entrypoints_*.csv"))
        
        if not files:
            print("エントリーポイントファイルが見つかりません")
            return None
        
        # 最新ファイルを取得
        latest_file = max(files, key=lambda x: os.path.basename(x).split('_')[1].split('.')[0])
        print(f"最新のエントリーポイントファイル: {latest_file}")
        return latest_file
    
    def load_entry_points(self):
        """エントリーポイントを読み込み"""
        latest_file = self.get_latest_entrypoint_file()
        if not latest_file:
            return None
        
        try:
            df = pd.read_csv(latest_file, encoding='utf-8-sig')
            print(f"エントリーポイントを読み込みました: {len(df)}件")
            print("カラム:", df.columns.tolist())
            return df
            
        except Exception as e:
            print(f"ファイル読み込みエラー: {e}")
            return None
    
    def get_currency_uic(self, currency_pair):
        """通貨ペアのUICを検索・取得"""
        try:
            # サクソバンクAPIで通貨ペアを検索
            result = self.api.search_instruments(currency_pair, ['FxSpot'])
            
            if result and 'Data' in result and result['Data']:
                uic = result['Data'][0]['Uic']
                print(f"{currency_pair} のUIC: {uic}")
                return uic
            else:
                print(f"{currency_pair} のUICが見つかりませんでした")
                return None
                
        except Exception as e:
            print(f"UIC取得エラー: {e}")
            return None
    
    def check_current_time_entries(self, entry_points):
        """現在時刻にマッチするエントリーポイントをチェック"""
        current_time = datetime.now().strftime('%H:%M:%S')
        print(f"現在時刻: {current_time}")
        
        # 現在時刻と一致するエントリーをフィルタ
        matching_entries = entry_points[entry_points['Entry'] == current_time]
        
        if not matching_entries.empty:
            print(f"現在時刻のエントリーポイント: {len(matching_entries)}件")
            return matching_entries
        else:
            print("現在時刻にマッチするエントリーポイントはありません")
            return pd.DataFrame()
    
    def simulate_entry_process(self):
        """エントリープロセスのシミュレーション"""
        print("=== FX自動エントリーシステム開始 ===")
        
        # エントリーポイント読み込み
        entry_points = self.load_entry_points()
        if entry_points is None:
            return
        
        # サンプルエントリーポイントを表示
        print("\n=== エントリーポイント一覧 ===")
        print(entry_points.head().to_string())
        
        # 通貨ペアのUIC取得テスト
        print("\n=== 通貨ペアUIC取得テスト ===")
        for currency_pair in entry_points['通貨ペア'].unique():
            uic = self.get_currency_uic(currency_pair)
        
        # 現在時刻チェック（実際の運用では定期実行）
        print("\n=== 現在時刻エントリーチェック ===")
        current_entries = self.check_current_time_entries(entry_points)
        
        if not current_entries.empty:
            print("エントリー実行対象:")
            print(current_entries.to_string())
            print("※ シミュレーション環境のため実際の注文は行いません")

def main():
    """メイン実行関数"""
    try:
        # 設定読み込み
        from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TEST_TOKEN
        
        # 認証・API初期化
        auth = SaxoBankAuth(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, environment='sim')
        auth.access_token = TEST_TOKEN
        api = SaxoBankAPI(auth)
        
        # 自動エントリーシステム実行
        entry_system = FXAutoEntrySystem(api)
        entry_system.simulate_entry_process()
        
    except Exception as e:
        print(f"システムエラー: {e}")

if __name__ == "__main__":
    main()
'''

## Step 6: 本番環境への移行準備

### 6.1 本番アプリケーション申請の条件
'''
1. サクソバンクの直接顧客であること
2. SIMアプリケーションでの十分なテスト実行
3. アプリケーションの動作が安定していること
4. 取引頻度や取引対象の明確化
'''

### 6.2 本番申請時の必要情報
'''
- アプリケーションの詳細説明
- 取引頻度の予定
- 取引対象の金融商品
- リスク管理の方針
'''

## 重要な注意事項

### セキュリティ
'''
- 認証情報は絶対に公開しない
- config.pyは.gitignoreに追加
- 本番環境では十分なテストを実施
'''

### リスク管理
'''
- 最初は小額での動作確認
- 損失限度額の設定
- 緊急停止機能の実装
'''

### 法的コンプライアンス
'''
- 自動売買に関する規制の確認
- 税務処理の準備
- 取引記録の保存
'''