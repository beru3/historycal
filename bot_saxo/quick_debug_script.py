#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
クイックデバッグ - Chart API の問題を特定
"""

import requests
import json

TOKEN_FILE = "token_live.json"
GATEWAY_URL = "https://gateway.saxobank.com/openapi"

def load_token():
    """保存済みトークンを読み込み"""
    try:
        with open(TOKEN_FILE, "r") as f:
            tokens = json.load(f)
        return tokens.get("access_token")
    except Exception as e:
        print(f"トークン読み込みエラー: {e}")
        return None

def debug_chart_api():
    """Chart API の詳細デバッグ"""
    access_token = load_token()
    
    if not access_token:
        print("アクセストークンがありません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    print("=== Chart API デバッグ ===")
    
    # Step 1: 現在の設定でテスト
    print("\n1. 現在のUIC=42でテスト")
    
    chart_url = f"{GATEWAY_URL}/chart/v1/charts"
    params = {
        'Uic': 42,
        'AssetType': 'FxSpot',
        'Horizon': 1440,  # 日次
        'Mode': 'UpTo',
        'Time': '2025-05-29T00:00:00Z',
        'Count': 1,
        'FieldGroups': 'Data'
    }
    
    print(f"リクエストURL: {chart_url}")
    print(f"パラメータ: {params}")
    
    resp = requests.get(chart_url, headers=headers, params=params)
    print(f"応答ステータス: {resp.status_code}")
    print(f"応答ヘッダー: {dict(resp.headers)}")
    print(f"応答ボディ: {resp.text}")
    
    # Step 2: 別のUICでテスト
    print("\n2. 別のUIC=21 (EURUSD) でテスト")
    
    params['Uic'] = 21
    resp2 = requests.get(chart_url, headers=headers, params=params)
    print(f"応答ステータス: {resp2.status_code}")
    print(f"応答ボディ: {resp2.text}")
    
    # Step 3: 現在価格APIでテスト
    print("\n3. 現在価格API でテスト")
    
    price_url = f"{GATEWAY_URL}/trade/v1/infoprices"
    price_params = {
        'Uic': 42,
        'AssetType': 'FxSpot',
        'FieldGroups': 'Quote'
    }
    
    price_resp = requests.get(price_url, headers=headers, params=price_params)
    print(f"価格API応答ステータス: {price_resp.status_code}")
    print(f"価格API応答ボディ: {price_resp.text}")

def check_environment():
    """環境設定確認"""
    print("\n=== 環境設定確認 ===")
    
    access_token = load_token()
    
    if not access_token:
        print("アクセストークンがありません")
        return
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # ユーザー情報確認
    user_url = f"{GATEWAY_URL}/port/v1/users/me"
    resp = requests.get(user_url, headers=headers)
    
    print(f"ユーザー情報API: {resp.status_code}")
    if resp.status_code == 200:
        user_data = resp.json()
        print(f"ユーザー名: {user_data.get('Name', 'N/A')}")
        print(f"言語: {user_data.get('Language', 'N/A')}")
        print(f"環境: {user_data.get('Environment', 'N/A')}")
    else:
        print(f"エラー: {resp.text}")

if __name__ == "__main__":
    print("Chart API クイックデバッグ開始")
    
    # 環境確認
    check_environment()
    
    # Chart API デバッグ
    debug_chart_api()
    
    print("\nデバッグ完了")