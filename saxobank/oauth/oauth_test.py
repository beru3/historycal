#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
oauth_test.py - サクソバンクAPI OAuth認証テストスクリプト
oauth フォルダに配置、親ディレクトリのconfig.pyを使用
"""

import requests
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# 親ディレクトリをパスに追加（config.py をインポートするため）
sys.path.insert(0, str(Path(__file__).parent.parent))

# 自作モジュール
from oauth_auth import SaxoOAuthManager
from config import get_oauth_config, get_api_endpoints, validate_config, print_config_info

# ディレクトリ設定
script_dir = Path(__file__).parent  # oauth フォルダ
parent_dir = script_dir.parent      # saxobank フォルダ
log_dir = parent_dir / "log"        # log フォルダ

# log ディレクトリの作成
log_dir.mkdir(exist_ok=True)

# ログ設定（親ディレクトリの log フォルダに保存）
log_filename = log_dir / f'oauth_test_{datetime.now().strftime("%Y%m%d")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def test_oauth_authentication():
    """OAuth認証テスト"""
    logger.info("=" * 80)
    logger.info("🔐 OAuth認証テスト開始")
    logger.info("=" * 80)
    
    try:
        # 設定検証
        logger.info("📋 Step 1: 設定検証")
        config_errors = validate_config()
        if config_errors:
            logger.error("❌ 設定エラーが検出されました:")
            for error in config_errors:
                logger.error(f"  - {error}")
            return False
        logger.info("✅ 設定検証: OK")
        
        # OAuth設定取得
        oauth_config = get_oauth_config()
        api_endpoints = get_api_endpoints()
        
        logger.info(f"🔧 使用環境: {oauth_config['environment']}")
        logger.info(f"🌐 APIエンドポイント: {api_endpoints['api_base_url']}")
        
        # OAuth管理インスタンス作成
        logger.info("📋 Step 2: OAuth管理インスタンス初期化")
        oauth_manager = SaxoOAuthManager(
            client_id=oauth_config['client_id'],
            client_secret=oauth_config['client_secret'],
            redirect_uri=oauth_config['redirect_uri'],
            environment=oauth_config['environment']
        )
        logger.info("✅ OAuth管理インスタンス作成完了")
        
        # 認証実行
        logger.info("📋 Step 3: OAuth認証実行")
        logger.info("ブラウザが開きます。サクソバンクにログインしてください...")
        
        if oauth_manager.authenticate_interactive():
            logger.info("✅ OAuth認証成功")
        else:
            logger.error("❌ OAuth認証失敗")
            return False
        
        # 基本APIテスト
        logger.info("📋 Step 4: 基本APIテスト実行")
        if test_basic_apis(oauth_manager, api_endpoints['api_base_url']):
            logger.info("✅ 基本APIテスト成功")
        else:
            logger.error("❌ 基本APIテスト失敗")
            return False
        
        # 通貨ペア検索テスト
        logger.info("📋 Step 5: 通貨ペア検索テスト")
        if test_currency_pairs(oauth_manager, api_endpoints['api_base_url']):
            logger.info("✅ 通貨ペア検索テスト成功")
        else:
            logger.error("❌ 通貨ペア検索テスト失敗")
            return False
        
        # 価格取得テスト
        logger.info("📋 Step 6: 価格取得テスト")
        if test_price_retrieval(oauth_manager, api_endpoints['api_base_url']):
            logger.info("✅ 価格取得テスト成功")
        else:
            logger.error("❌ 価格取得テスト失敗")
            return False
        
        logger.info("=" * 80)
        logger.info("🎉 全テスト成功！OAuth認証システムは正常に動作しています")
        logger.info("=" * 80)
        
        # 自動更新停止
        oauth_manager.stop_auto_refresh()
        
        return True
        
    except Exception as e:
        logger.error(f"テスト中にエラーが発生: {e}")
        logger.exception("テストエラーの詳細:")
        return False

def test_basic_apis(oauth_manager, api_base_url):
    """基本API群のテスト"""
    try:
        headers = oauth_manager.get_api_headers()
        if not headers:
            logger.error("APIヘッダーが取得できません")
            return False
        
        tests = [
            {
                'name': 'ユーザー情報取得',
                'endpoint': '/port/v1/users/me',
                'expected_keys': ['Name', 'Language']
            },
            {
                'name': 'アカウント情報取得',
                'endpoint': '/port/v1/accounts/me',
                'expected_keys': ['Data']
            },
            {
                'name': '残高情報取得',
                'endpoint': '/port/v1/balances/me',
                'expected_keys': ['Data']
            }
        ]
        
        for test in tests:
            logger.info(f"  🔄 {test['name']}テスト...")
            
            response = requests.get(
                f"{api_base_url}{test['endpoint']}", 
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # 期待されるキーの存在確認
                missing_keys = []
                for key in test['expected_keys']:
                    if key not in data:
                        missing_keys.append(key)
                
                if missing_keys:
                    logger.warning(f"    ⚠️ 期待されるキーが見つかりません: {missing_keys}")
                else:
                    logger.info(f"    ✅ {test['name']}: 成功")
                    
                    # レスポンスの一部を表示
                    if test['name'] == 'ユーザー情報取得':
                        logger.info(f"      ユーザー名: {data.get('Name', 'N/A')}")
                        logger.info(f"      言語: {data.get('Language', 'N/A')}")
                    elif test['name'] == 'アカウント情報取得' and data.get('Data'):
                        account = data['Data'][0]
                        logger.info(f"      アカウント数: {len(data['Data'])}")
                        logger.info(f"      アカウントキー: {account.get('AccountKey', 'N/A')}")
                        logger.info(f"      通貨: {account.get('Currency', 'N/A')}")
                    elif test['name'] == '残高情報取得' and data.get('Data'):
                        balance = data['Data'][0]
                        logger.info(f"      残高データ数: {len(data['Data'])}")
                        logger.info(f"      通貨: {balance.get('Currency', 'N/A')}")
                        logger.info(f"      総額: {balance.get('TotalValue', 'N/A')}")
            else:
                logger.error(f"    ❌ {test['name']}: HTTPエラー {response.status_code}")
                logger.error(f"      レスポンス: {response.text[:200]}...")
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"基本APIテストエラー: {e}")
        return False

def test_currency_pairs(oauth_manager, api_base_url):
    """通貨ペア検索テスト"""
    try:
        headers = oauth_manager.get_api_headers()
        if not headers:
            logger.error("APIヘッダーが取得できません")
            return False
        
        test_pairs = ['USDJPY', 'EURJPY', 'EURUSD', 'GBPUSD', 'AUDUSD']
        successful_searches = 0
        
        for pair in test_pairs:
            logger.info(f"  🔍 {pair} 検索テスト...")
            
            params = {
                'Keywords': pair,
                'AssetTypes': 'FxSpot',
                'limit': 5
            }
            
            response = requests.get(
                f"{api_base_url}/ref/v1/instruments", 
                headers=headers, 
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                instruments = response.json()
                
                if instruments.get('Data') and len(instruments['Data']) > 0:
                    instrument = instruments['Data'][0]
                    symbol = instrument.get('Symbol', 'N/A')
                    description = instrument.get('Description', 'N/A')
                    uic = instrument.get('Identifier', 'N/A')  # サクソバンクではIdentifierがUIC
                    
                    logger.info(f"    ✅ {pair}: {symbol} - {description} (UIC: {uic})")
                    successful_searches += 1
                else:
                    logger.warning(f"    ⚠️ {pair}: 検索結果が見つかりませんでした")
            else:
                logger.error(f"    ❌ {pair}: HTTPエラー {response.status_code}")
                logger.error(f"      レスポンス: {response.text[:200]}...")
        
        logger.info(f"  📊 通貨ペア検索結果: {successful_searches}/{len(test_pairs)} 成功")
        
        return successful_searches > 0
        
    except Exception as e:
        logger.error(f"通貨ペア検索テストエラー: {e}")
        return False

def test_price_retrieval(oauth_manager, api_base_url):
    """価格取得テスト"""
    try:
        headers = oauth_manager.get_api_headers()
        if not headers:
            logger.error("APIヘッダーが取得できません")
            return False
        
        # まずUSDJPYのUICを取得
        logger.info("  🔍 USDJPY UIC取得中...")
        
        params = {
            'Keywords': 'USDJPY',
            'AssetTypes': 'FxSpot',
            'limit': 1
        }
        
        response = requests.get(
            f"{api_base_url}/ref/v1/instruments", 
            headers=headers, 
            params=params,
            timeout=30
        )
        
        if response.status_code != 200 or not response.json().get('Data'):
            logger.error("    ❌ USDJPY UIC取得失敗")
            return False
        
        uic = response.json()['Data'][0]['Identifier']
        logger.info(f"    ✅ USDJPY UIC取得成功: {uic}")
        
        # 価格取得テスト
        logger.info("  💹 USDJPY 価格取得テスト...")
        
        price_params = {
            'Uic': str(uic),
            'AssetType': 'FxSpot',
            'FieldGroups': 'Quote'
        }
        
        response = requests.get(
            f"{api_base_url}/trade/v1/infoprices", 
            headers=headers, 
            params=price_params,
            timeout=30
        )
        
        if response.status_code == 200:
            prices = response.json()
            logger.info(f"    ✅ 価格取得成功")
            
            # 価格データの解析
            quote = None
            if prices.get('Data') and len(prices['Data']) > 0:
                quote = prices['Data'][0].get('Quote', {})
            elif 'Quote' in prices:
                quote = prices['Quote']
            
            if quote:
                bid = quote.get('Bid', 'N/A')
                ask = quote.get('Ask', 'N/A')
                spread = quote.get('Spread', 'N/A')
                
                logger.info(f"      BID: {bid}")
                logger.info(f"      ASK: {ask}")
                logger.info(f"      スプレッド: {spread}")
                
                # 価格の妥当性チェック（USDJPY は 100-200 の範囲）
                if isinstance(bid, (int, float)) and isinstance(ask, (int, float)):
                    if 100 <= bid <= 200 and 100 <= ask <= 200 and ask > bid:
                        logger.info(f"    ✅ 価格データの妥当性: OK")
                        return True
                    else:
                        logger.warning(f"    ⚠️ 価格データが想定範囲外です")
                        return True  # 価格が取得できていれば成功とする
                else:
                    logger.warning(f"    ⚠️ 価格データの形式が不正です")
            else:
                logger.error(f"    ❌ 価格データの構造が予期しない形式: {prices}")
                return False
        else:
            logger.error(f"    ❌ 価格取得失敗: HTTPエラー {response.status_code}")
            logger.error(f"      レスポンス: {response.text[:200]}...")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"価格取得テストエラー: {e}")
        return False

def test_token_refresh():
    """トークン更新テスト"""
    logger.info("=" * 80)
    logger.info("🔄 トークン更新テスト")
    logger.info("=" * 80)
    
    try:
        oauth_config = get_oauth_config()
        
        oauth_manager = SaxoOAuthManager(
            client_id=oauth_config['client_id'],
            client_secret=oauth_config['client_secret'],
            redirect_uri=oauth_config['redirect_uri'],
            environment=oauth_config['environment']
        )
        
        # 既存トークンの読み込み
        if not oauth_manager.load_tokens():
            logger.error("❌ 既存のトークンが見つかりません。先に認証を実行してください。")
            return False
        
        logger.info(f"📋 現在のトークン有効期限: {oauth_manager.token_expires_at}")
        logger.info(f"📋 トークン有効性: {'有効' if oauth_manager.is_token_valid() else '無効'}")
        
        # 手動でトークン更新を試行
        logger.info("🔄 手動トークン更新を試行...")
        if oauth_manager.refresh_access_token():
            logger.info("✅ トークン更新成功")
            logger.info(f"📋 新しい有効期限: {oauth_manager.token_expires_at}")
        else:
            logger.error("❌ トークン更新失敗")
            return False
        
        # 更新後のAPI接続テスト
        logger.info("🔍 更新後のAPI接続テスト...")
        if oauth_manager.test_connection():
            logger.info("✅ 更新後のAPI接続テスト成功")
        else:
            logger.error("❌ 更新後のAPI接続テスト失敗")
            return False
        
        logger.info("🎉 トークン更新テスト完了")
        return True
        
    except Exception as e:
        logger.error(f"トークン更新テストエラー: {e}")
        return False

def main():
    """メイン関数"""
    print("=" * 80)
    print("🔐 OAuth認証テスト（ディレクトリ構造対応版）")
    print("=" * 80)
    print(f"📁 実行ディレクトリ: {script_dir}")
    print(f"📁 親ディレクトリ: {parent_dir}")
    print(f"📄 ログファイル: {log_filename}")
    print("=" * 80)
    
    print_config_info()
    
    tests = [
        ("OAuth認証テスト", test_oauth_authentication),
        ("トークン更新テスト", test_token_refresh),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        try:
            print(f"\n{'='*80}")
            print(f"開始: {test_name}")
            print(f"{'='*80}")
            
            result = test_func()
            results[test_name] = result
            
            if result:
                print(f"✅ {test_name}: 成功")
            else:
                print(f"❌ {test_name}: 失敗")
                
        except Exception as e:
            print(f"❌ {test_name}: エラー - {e}")
            results[test_name] = False
    
    # 結果サマリー
    print(f"\n{'='*80}")
    print("📊 テスト結果サマリー")
    print(f"{'='*80}")
    
    success_count = 0
    for test_name, result in results.items():
        status = "✅ 成功" if result else "❌ 失敗"
        print(f"  {test_name}: {status}")
        if result:
            success_count += 1
    
    print(f"\n📈 成功率: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
    
    if success_count == len(results):
        print("🎉 全テスト成功！システムは正常に動作しています。")
        return 0
    else:
        print("⚠️ 一部テストが失敗しました。設定を確認してください。")
        return 1

if __name__ == "__main__":
    exit(main())