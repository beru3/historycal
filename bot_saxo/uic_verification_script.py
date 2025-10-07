#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UIC確認スクリプト - 正しい通貨ペアUICを取得
"""

import requests
import json

# 設定 (fx_auto_multi_dates.pyから引用)
CLIENT_ID = "67a87ac462994c4b805a0811aa966a50"
CLIENT_SECRET = "950d065d7a3145c5800abd730ff43eaf"
GATEWAY_URL = "https://gateway.saxobank.com/openapi"
TOKEN_FILE = "token_live.json"

# 現在のUIC設定
KNOWN_UICS = {
    "USDJPY": 42,  # 米ドル/円
    "EURJPY": 18,  # ユーロ/円
    "EURUSD": 21,  # ユーロ/米ドル
    "GBPJPY": 26,  # 英ポンド/円
    "AUDJPY": 2,   # 豪ドル/円
    "CHFJPY": 8,   # スイスフラン/円
    "CADJPY": 6,   # カナダドル/円
}

def load_token():
    """保存済みトークンを読み込み"""
    try:
        with open(TOKEN_FILE, "r") as f:
            tokens = json.load(f)
        return tokens.get("access_token")
    except Exception as e:
        print(f"トークン読み込みエラー: {e}")
        return None

def verify_uic_mapping():
    """UICマッピングをAPIで確認"""
    access_token = load_token()
    
    if not access_token:
        print("有効なアクセストークンがありません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    print("=== UIC確認結果 ===")
    
    # 通貨ペア検索
    for currency_pair in KNOWN_UICS.keys():
        try:
            print(f"\n{currency_pair} の検索中...")
            
            search_url = f"{GATEWAY_URL}/ref/v1/instruments"
            params = {
                'Keywords': currency_pair,
                'AssetTypes': 'FxSpot',
                'limit': 10
            }
            
            resp = requests.get(search_url, headers=headers, params=params)
            
            if resp.status_code == 200:
                data = resp.json()
                print(f"  API応答: {resp.status_code} - 検索結果数: {len(data.get('Data', []))}")
                
                if "Data" in data and data["Data"]:
                    for i, instrument in enumerate(data["Data"]):
                        uic = instrument.get("Uic")
                        symbol = instrument.get("Symbol", "")
                        description = instrument.get("Description", "")
                        
                        print(f"  [{i+1}] UIC={uic}, Symbol={symbol}")
                        print(f"      Description: {description}")
                        
                        # 現在の設定と比較
                        if uic == KNOWN_UICS.get(currency_pair):
                            print(f"      ✅ 現在の設定と一致")
                        else:
                            print(f"      ❌ 現在の設定={KNOWN_UICS[currency_pair]}, 実際={uic}")
                else:
                    print(f"  ❌ {currency_pair}: 検索結果なし")
            else:
                print(f"  ❌ {currency_pair}: API エラー {resp.status_code}")
                print(f"      レスポンス: {resp.text}")
                
        except Exception as e:
            print(f"  ❌ {currency_pair}: エラー {e}")

def test_chart_api_with_correct_uic():
    """正しいUICでChart APIをテスト"""
    access_token = load_token()
    
    if not access_token:
        print("有効なアクセストークンがありません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    print("\n=== Chart API テスト ===")
    
    # USDJPY のテスト
    test_pairs = ["USDJPY", "EURUSD"]
    
    for currency_pair in test_pairs:
        print(f"\n{currency_pair} Chart API テスト:")
        
        # まず正しいUICを取得
        search_url = f"{GATEWAY_URL}/ref/v1/instruments"
        params = {
            'Keywords': currency_pair,
            'AssetTypes': 'FxSpot',
            'limit': 1
        }
        
        resp = requests.get(search_url, headers=headers, params=params)
        
        if resp.status_code == 200:
            data = resp.json()
            if "Data" in data and data["Data"]:
                correct_uic = data["Data"][0].get("Uic")
                print(f"  正しいUIC: {correct_uic}")
                
                # Chart APIテスト
                chart_url = f"{GATEWAY_URL}/chart/v1/charts"
                chart_params = {
                    'Uic': correct_uic,
                    'AssetType': 'FxSpot',
                    'Horizon': 1440,  # 日次データでテスト
                    'Mode': 'UpTo',
                    'Time': '2025-05-29T00:00:00Z',  # 昨日
                    'Count': 1,
                    'FieldGroups': 'Data'
                }
                
                chart_resp = requests.get(chart_url, headers=headers, params=chart_params)
                print(f"  Chart API応答: {chart_resp.status_code}")
                
                if chart_resp.status_code == 200:
                    chart_data = chart_resp.json()
                    print(f"  ✅ Chart API成功")
                    print(f"      データキー: {list(chart_data.keys())}")
                    
                    if "Data" in chart_data and chart_data["Data"]:
                        candle = chart_data["Data"][0]
                        print(f"      サンプルデータ: {candle}")
                    else:
                        print(f"      データなし: {chart_data}")
                else:
                    print(f"  ❌ Chart API失敗: {chart_resp.status_code}")
                    print(f"      レスポンス: {chart_resp.text}")
            else:
                print(f"  ❌ {currency_pair}: UIC取得失敗")

def generate_corrected_uic_dict():
    """正しいUIC辞書を生成"""
    access_token = load_token()
    
    if not access_token:
        print("有効なアクセストークンがありません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    print("\n=== 正しいUIC辞書 ===")
    
    corrected_uics = {}
    
    for currency_pair in KNOWN_UICS.keys():
        try:
            search_url = f"{GATEWAY_URL}/ref/v1/instruments"
            params = {
                'Keywords': currency_pair,
                'AssetTypes': 'FxSpot',
                'limit': 1
            }
            
            resp = requests.get(search_url, headers=headers, params=params)
            
            if resp.status_code == 200:
                data = resp.json()
                if "Data" in data and data["Data"]:
                    correct_uic = data["Data"][0].get("Uic")
                    corrected_uics[currency_pair] = correct_uic
                    
        except Exception as e:
            print(f"{currency_pair}: エラー {e}")
    
    print("KNOWN_UICS = {")
    for pair, uic in corrected_uics.items():
        print(f'    "{pair}": {uic},  # {pair}')
    print("}")
    
    return corrected_uics

if __name__ == "__main__":
    print("UIC確認スクリプト開始")
    
    # 1. UICマッピング確認
    verify_uic_mapping()
    
    # 2. Chart APIテスト
    test_chart_api_with_correct_uic()
    
    # 3. 正しいUIC辞書生成
    generate_corrected_uic_dict()
    
    print("\nUIC確認完了")