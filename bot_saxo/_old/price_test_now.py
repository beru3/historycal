#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
price_test_now.py - 現在の価格取得テスト
修正されたパラメータで価格取得をテスト
"""

import requests
import json
import sys
import os

# config.py から設定を読み込み
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import TEST_TOKEN_24H, BASE_URL

def test_price_api_now():
    """現在の価格取得API テスト"""
    
    print("🔍 サクソバンク価格取得APIテスト")
    print("=" * 50)
    
    headers = {
        'Authorization': f'Bearer {TEST_TOKEN_24H}',
        'Content-Type': 'application/json'
    }
    
    # UICマッピング（システムから取得済み）
    currency_mapping = {
        'USDJPY': 42,
        'EURJPY': 18,
        'GBPJPY': 26,
        'AUDJPY': 2,
        'CHFJPY': 8,
        'EURUSD': 21,
        'GBPUSD': 31,
        'AUDUSD': 4
    }
    
    print(f"📊 テスト対象通貨ペア: {len(currency_mapping)}件")
    print(f"🔑 トークン: {'設定済み' if TEST_TOKEN_24H else '未設定'}")
    print(f"🌐 エンドポイント: {BASE_URL}")
    
    success_count = 0
    total_count = len(currency_mapping)
    
    for currency_pair, uic in currency_mapping.items():
        print(f"\n--- {currency_pair} (UIC: {uic}) ---")
        
        try:
            # 修正されたパラメータ（UicsではなくUic）
            params = {
                'Uic': str(uic),  # 修正: Uics → Uic
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            
            print(f"   リクエストパラメータ: {params}")
            
            response = requests.get(
                f"{BASE_URL}/trade/v1/infoprices", 
                headers=headers, 
                params=params,
                timeout=10
            )
            
            print(f"   ステータスコード: {response.status_code}")
            
            # ...existing code...
            if response.status_code == 200:
                data = response.json()
                # Dataキーがある場合（複数通貨ペア取得時）
                if 'Data' in data and data['Data']:
                    price_info = data['Data'][0]
                    if 'Quote' in price_info:
                        quote = price_info['Quote']
                        # ...（省略）...
                # Dataキーがなく、直接Quoteがある場合（単一通貨ペア取得時）
                elif 'Quote' in data:
                    quote = data['Quote']
                    bid = quote.get('Bid')
                    ask = quote.get('Ask')
                    spread = quote.get('Spread')
                    print(f"   ✅ 価格取得成功:")
                    print(f"      BID: {bid}")
                    print(f"      ASK: {ask}")
                    print(f"      スプレッド: {spread}")
                    success_count += 1
                else:
                    print(f"   ⚠️  価格情報が見つかりません: {json.dumps(data, indent=4)}")
            # ...existing code...
            
            elif response.status_code == 400:
                print(f"   ❌ Bad Request (400): パラメータエラー")
                print(f"   レスポンス: {response.text}")
            elif response.status_code == 401:
                print(f"   ❌ Unauthorized (401): 認証エラー")
                print(f"   トークンを確認してください")
            elif response.status_code == 404:
                print(f"   ❌ Not Found (404): エンドポイントまたはUICが無効")
            elif response.status_code == 429:
                print(f"   ❌ Rate Limited (429): APIレート制限")
            else:
                print(f"   ❌ エラー: {response.status_code}")
                print(f"   レスポンス: {response.text}")
                
        except requests.exceptions.Timeout:
            print(f"   ❌ タイムアウト: 10秒以内に応答なし")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ リクエストエラー: {e}")
        except Exception as e:
            print(f"   ❌ 予期しないエラー: {e}")
    
    # 結果サマリー
    print(f"\n" + "=" * 50)
    print(f"📊 テスト結果サマリー:")
    print(f"   成功: {success_count}/{total_count} ({success_count/total_count*100:.1f}%)")
    print(f"   失敗: {total_count - success_count}/{total_count}")
    
    if success_count > 0:
        print(f"\n✅ 価格取得は正常に動作しています！")
        print(f"   システムの価格取得関数を修正すれば解決します")
    else:
        print(f"\n❌ 価格取得に問題があります")
        print(f"   以下を確認してください:")
        print(f"   1. トークンの有効期限")
        print(f"   2. APIエンドポイントの変更")
        print(f"   3. パラメータ形式の変更")
    
    return success_count > 0

def test_alternative_endpoints():
    """代替エンドポイントのテスト"""
    
    print(f"\n🔄 代替エンドポイントテスト")
    print("=" * 30)
    
    headers = {
        'Authorization': f'Bearer {TEST_TOKEN_24H}',
        'Content-Type': 'application/json'
    }
    
    # USDJPY (UIC: 42) でテスト
    uic = 42
    currency_pair = "USDJPY"
    
    alternative_approaches = [
        {
            'name': 'InfoPrices (複数UIC形式)',
            'endpoint': '/trade/v1/infoprices',
            'params': {
                'Uics': str(uic),  # 複数形
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
        },
        {
            'name': 'InfoPrices (単数UIC形式)',
            'endpoint': '/trade/v1/infoprices',
            'params': {
                'Uic': str(uic),  # 単数形
                'AssetType': 'FxSpot', 
                'FieldGroups': 'Quote'
            }
        },
        {
            'name': 'Prices エンドポイント',
            'endpoint': '/trade/v1/prices',
            'params': {
                'Uics': str(uic),
                'AssetType': 'FxSpot'
            }
        },
        {
            'name': '楽器詳細情報',
            'endpoint': f'/ref/v1/instruments/details/{uic}',
            'params': {}
        }
    ]
    
    for approach in alternative_approaches:
        print(f"\n--- {approach['name']} ---")
        
        try:
            if approach['params']:
                response = requests.get(
                    f"{BASE_URL}{approach['endpoint']}", 
                    headers=headers, 
                    params=approach['params'],
                    timeout=10
                )
            else:
                response = requests.get(
                    f"{BASE_URL}{approach['endpoint']}", 
                    headers=headers,
                    timeout=10
                )
            
            print(f"   ステータス: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ 成功: {list(data.keys())}")
                
                # 価格情報を探す
                if 'Data' in data and data['Data'] and isinstance(data['Data'], list):
                    item = data['Data'][0]
                    if 'Quote' in item:
                        quote = item['Quote']
                        print(f"   価格: BID={quote.get('Bid')}, ASK={quote.get('Ask')}")
                elif isinstance(data, dict):
                    # 楽器詳細の場合
                    print(f"   詳細: {data.get('Description', 'N/A')}")
            else:
                print(f"   ❌ 失敗: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ エラー: {e}")

if __name__ == "__main__":
    print("🚀 サクソバンク価格取得テストツール")
    print(f"実行時刻: {__import__('datetime').datetime.now()}")
    print("=" * 60)
    
    # メイン価格取得テスト
    main_test_success = test_price_api_now()
    
    # 代替エンドポイントテスト
    test_alternative_endpoints()
    
    print(f"\n🎯 推奨対応:")
    if main_test_success:
        print(f"1. fx_auto_entry_system.py の get_current_price 関数を修正")
        print(f"2. パラメータを 'Uics' → 'Uic' に変更")
        print(f"3. 17:17:00 の CHFJPY Long エントリーで再テスト")
    else:
        print(f"1. 24時間トークンの有効期限確認")
        print(f"2. 新しい24時間トークンを取得")
        print(f"3. config.py のTEST_TOKEN_24H を更新")