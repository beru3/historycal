#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
direct_auth.py - Saxo Bank API直接認証
適切なAPIトークンを提供
"""

import requests
import logging
import json
import base64
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 認証情報（画像から）
APP_KEY = "5f19317941744e688ca30be6b2f53659"
APP_SECRET = "7e7f99b6a65343ebae16c915daddf80"  # 最初のシークレット
ALT_APP_SECRET = "a83b3a8b9a85464ba600f63565d644d9"  # 代替シークレット
AUTH_ENDPOINT = "https://sim.logonvalidation.net/authorize"
TOKEN_ENDPOINT = "https://sim.logonvalidation.net/token"
BASE_URL = "https://gateway.saxobank.com/sim/openapi"

# トークン保存先ファイル
TOKEN_FILE = Path(__file__).parent / "token.json"

# 手動で取得したトークン
# これはブラウザで認証後に開発者ツールで確認した値を使用
# TODO: 以下の値をSaxoBankのアカウントでログイン後に取得した実際のトークンに更新してください
MANUAL_TOKEN = "YOUR_MANUAL_TOKEN_HERE"

def get_token():
    """
    トークンを取得する関数
    1. ファイルからトークンを読み込み
    2. ファイルがなければ手動設定したトークンを返す
    3. トークンが期限切れならシミュレーションデータを返す
    """
    try:
        # 1. ファイルからトークン読み込み
        if TOKEN_FILE.exists():
            logger.debug("トークンファイルから読み込みます")
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token_data = json.load(f)
            
            # 有効期限をチェック
            if "expires_at" in token_data:
                expires_at = datetime.fromtimestamp(token_data["expires_at"])
                if expires_at > datetime.now():
                    logger.debug(f"有効なトークンが見つかりました（期限: {expires_at}）")
                    return token_data["access_token"]
                logger.debug(f"トークンの期限切れ（期限: {expires_at}）")
        
        # 2. 手動設定したトークンを確認
        if MANUAL_TOKEN != "YOUR_MANUAL_TOKEN_HERE":
            logger.debug("手動設定されたトークンを使用します")
            return MANUAL_TOKEN
            
        # 3. 上記いずれもなければエラーメッセージを表示してデモトークンを返す
        logger.error("有効なトークンが見つかりません。以下のいずれかを実行してください：")
        logger.error("1. ブラウザでSaxo Bankにログインし、開発者ツールでトークンを取得して MANUAL_TOKEN に設定")
        logger.error("2. プログラムでの認証プロセスを実装")
        
        # NOTE: この空のトークンは失敗します。実際のトークンに置き換えが必要です
        return "eyJhbGciOiJFUzI1NiIsIng1dCI6IkQ2QzQ5MEM2ODI5RDFCMUJDNTdEQUY0RDlDQUVCREJEOEQ2QkM1RTdCQjFDQUEwQjVCRTlCN0I5QjVCRkFGRSJ9.eyJvYWEiOiI3Nzc3NSIsImlzcyI6Im9hIiwiYWlkIjoiMTEwIiwiaWlkIjoiZjYzOTljYWYtOTEwMS00YTUzLWI4ZGItMWUwN2QwYjg2MzM4IiwiaWIiOiJwciIsInRsIjoibzZtZ2M6cCIsInRscyI6IlJPIiwic2QiOiJEZW1vIiwidWsiOiIyMzEzODgzNCIsInVuIjoiQW5kcmV3IiwiYXQiOiJiYmMiLCJhZCI6ImV5SmhiR2NpT2lKa1pXTmpJaXdpYTJsa0lqb2lUbWxqYkV0a1QxWm1VM0IyVkV0eVUxWmpaRWRJTkRKek9GcE9PVVJEVFdzdmFGRkVhM2N3YldGSVRVcEdlVkpwWld3NU1qWm1hMVZLTm1KdU1VUlpkbGhLYUU1aGMzUkJTVlphUlRBaWZRLmV5SnBZWFFpT2pFMk9UQTRNekk0TVRVNU9EUXNJbTVpWmlJNk1UWTVNRGd6TWpneE5UazRORGdzSW1Ob1lXbHVJanBiSW1GMVpDSmRmUS5lNzJtUXJ6dXh3bXh2ZGdFSURfR01uSWk0cF9TakdFT2duNWs3LXdvb0NwRnMyLUE2c0lwR0EyQTdzRXNrS3RqYjJNUG41WFBGWi02M2QtM3RwNGV1USIsImFhIjoiRGdnY01DQk1NQ3dRSUVad01Id1FYREFjYUdob1lEZ2xjRUNBc0tnNGZCZ3FFRVJ3UE9BZ3lPQ3AyRWpCSSIsIm5iZiI6MTY5MDgzMjgxNSwiZXhwIjoxNjkwODMzNzE1fQ.RbXyYtbfag0t608luHPvyqqLzmoc3hVbG7CnDO_PUbeM0pGJTRkmxoA7SBcYcjRlspq2WXLhxz0PemWsyD2xZA"
                
    except Exception as e:
        logger.error(f"トークン取得エラー: {str(e)}")
        return None

def save_token(access_token, expires_in):
    """トークンをファイルに保存"""
    try:
        token_data = {
            "access_token": access_token,
            "expires_at": (datetime.now() + timedelta(seconds=expires_in)).timestamp()
        }
        
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=4)
            
        logger.debug(f"トークンを保存しました: {TOKEN_FILE}")
        
    except Exception as e:
        logger.error(f"トークン保存エラー: {str(e)}")