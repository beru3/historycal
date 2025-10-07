#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
価格取得エラー修正版
サクソバンクAPI価格取得の問題を修正
"""

import requests
import json
import time
from config import TEST_TOKEN_24H, BASE_URL

def debug_price_api():
    """価格取得APIのデバッグ"""
    
    headers = {
        'Authorization': f'Bearer {TEST_TOKEN_24H}',
        'Content-Type': 'application/json'
    }
    
    # USDJPY のUIC = 42 (前回のテストで確認済み)
    uic = 42
    
    print("🔍 価格取得APIデバッグ開始")
    print("=" * 50)
    
    # 1. 基本的な価格取得テスト
    print(f"1. 基本価格取得テスト (UIC: {uic})")
    params = {
        'Uics': str(uic),
        'AssetType': 'FxSpot',
        'FieldGroups': 'Quote'
    }
    
    try:
        response = requests.get(f"{BASE_URL}/trade/v1/infoprices", headers=headers, params=params)
        print(f"   ステータス: {response.status_code}")
        print(f"   レスポンス: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ 成功: {json.dumps(data, indent=2)}")
        else:
            print(f"   ❌ 失敗: {response.status_code}")
            
    except Exception as e:
        print(f"   ❌ エラー: {e}")
    
    # 2. 異なるFieldGroupsでテスト
    print(f"\n2. 異なるFieldGroupsでテスト")
    field_groups = ['Quote', 'PriceInfo', 'Quote,PriceInfo']
    
    for fg in field_groups:
        try:
            params = {
                'Uics': str(uic),
                'AssetType': 'FxSpot',
                'FieldGroups': fg
            }
            response = requests.get(f"{BASE_URL}/trade/v1/infoprices", headers=headers, params=params)
            print(f"   {fg}: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if 'Data' in data and data['Data']:
                    quote_data = data['Data'][0]
                    print(f"     データキー: {list(quote_data.keys())}")
                    if 'Quote' in quote_data:
                        quote = quote_data['Quote']
                        print(f"     BID: {quote.get('Bid')}, ASK: {quote.get('Ask')}")
        except Exception as e:
            print(f"   {fg}: エラー {e}")
    
    # 3. 代替エンドポイントテスト
    print(f"\n3. 代替エンドポイントテスト")
    alternative_endpoints = [
        "/trade/v1/infoprices",
        "/trade/v1/prices",
        "/ref/v1/instruments/details"
    ]
    
    for endpoint in alternative_endpoints:
        try:
            if endpoint == "/ref/v1/instruments/details":
                # 詳細情報取得
                url = f"{BASE_URL}{endpoint}/{uic}"
                response = requests.get(url, headers=headers)
            else:
                # 価格情報取得
                params = {'Uics': str(uic), 'AssetType': 'FxSpot'}
                response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params)
            
            print(f"   {endpoint}: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"     キー: {list(data.keys()) if isinstance(data, dict) else 'リスト'}")
            
        except Exception as e:
            print(f"   {endpoint}: エラー {e}")

def improved_get_current_price(currency_pair, currency_uic_mapping):
    """改良版価格取得関数"""
    
    headers = {
        'Authorization': f'Bearer {TEST_TOKEN_24H}',
        'Content-Type': 'application/json'
    }
    
    try:
        uic = currency_uic_mapping.get(currency_pair)
        if not uic:
            print(f"❌ UICが見つかりません: {currency_pair}")
            return None
        
        print(f"🔍 価格取得開始: {currency_pair} (UIC: {uic})")
        
        # 複数のアプローチを試行
        approaches = [
            # アプローチ1: 基本的な価格取得
            {
                'endpoint': '/trade/v1/infoprices',
                'params': {
                    'Uics': str(uic),
                    'AssetType': 'FxSpot',
                    'FieldGroups': 'Quote'
                }
            },
            # アプローチ2: より詳細な情報を含む
            {
                'endpoint': '/trade/v1/infoprices',
                'params': {
                    'Uics': str(uic),
                    'AssetType': 'FxSpot',
                    'FieldGroups': 'Quote,PriceInfo'
                }
            },
            # アプローチ3: 異なるエンドポイント
            {
                'endpoint': '/trade/v1/prices',
                'params': {
                    'Uics': str(uic),
                    'AssetType': 'FxSpot'
                }
            }
        ]
        
        for i, approach in enumerate(approaches, 1):
            try:
                print(f"   アプローチ{i}: {approach['endpoint']}")
                
                response = requests.get(
                    f"{BASE_URL}{approach['endpoint']}", 
                    headers=headers, 
                    params=approach['params'],
                    timeout=10  # タイムアウト設定
                )
                
                print(f"   ステータス: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"   レスポンス構造: {list(data.keys())}")
                    
                    if 'Data' in data and data['Data']:
                        price_data = data['Data'][0]
                        print(f"   価格データ: {list(price_data.keys())}")
                        
                        # Quote情報を抽出
                        if 'Quote' in price_data:
                            quote = price_data['Quote']
                            bid = quote.get('Bid')
                            ask = quote.get('Ask')
                            spread = quote.get('Spread')
                            
                            if bid and ask:
                                print(f"   ✅ 価格取得成功: BID={bid}, ASK={ask}, Spread={spread}")
                                return {
                                    'bid': bid,
                                    'ask': ask,
                                    'spread': spread
                                }
                        
                        # 他の価格情報を探す
                        for key in price_data.keys():
                            if 'price' in key.lower() or 'quote' in key.lower():
                                print(f"   価格関連データ: {key} = {price_data[key]}")
                
                elif response.status_code == 429:
                    print(f"   ⚠️  レート制限: 2秒待機後に次のアプローチを試行")
                    time.sleep(2)
                    continue
                else:
                    print(f"   ❌ 失敗: {response.text}")
                    
            except requests.exceptions.Timeout:
                print(f"   ⚠️  タイムアウト: 次のアプローチを試行")
                continue
            except Exception as e:
                print(f"   ❌ エラー: {e}")
                continue
        
        print(f"❌ 全てのアプローチで価格取得に失敗: {currency_pair}")
        return None
        
    except Exception as e:
        print(f"❌ 価格取得エラー: {e}")
        return None

def test_improved_price_function():
    """改良版価格取得関数のテスト"""
    
    print("🧪 改良版価格取得関数テスト")
    print("=" * 50)
    
    # UICマッピング（前回のテスト結果から）
    currency_uic_mapping = {
        'USDJPY': 42,
        'EURJPY': 18,
        'GBPJPY': 26,
        'AUDJPY': 2
    }
    
    # 各通貨ペアでテスト
    for currency_pair in ['USDJPY', 'EURJPY']:
        print(f"\n--- {currency_pair} テスト ---")
        result = improved_get_current_price(currency_pair, currency_uic_mapping)
        
        if result:
            print(f"✅ {currency_pair}: {result}")
        else:
            print(f"❌ {currency_pair}: 価格取得失敗")

if __name__ == "__main__":
    print("🔧 サクソバンク価格取得API修正ツール")
    print("=" * 60)
    
    # 1. APIデバッグ実行
    debug_price_api()
    
    print("\n" + "=" * 60)
    
    # 2. 改良版関数テスト
    test_improved_price_function()