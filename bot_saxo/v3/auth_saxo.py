#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
auth_saxo.py - Saxo Bank API 認証ヘルパー
OAuth 2.0フローを処理し、アクセストークンを提供
"""

import requests
import json
import time
import webbrowser
import base64
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

# ログ設定
logger = logging.getLogger(__name__)

# 認証情報（画像から取得）
APP_KEY = "5f19317941744e688ca30be6b2f53659"
APP_SECRET = "7e7f99b6a65343ebae16c915daddf80"
AUTH_ENDPOINT = "https://sim.logonvalidation.net/authorize"
TOKEN_ENDPOINT = "https://sim.logonvalidation.net/token"
REDIRECT_URL = "http://localhost:8080/callback"

# トークン保存パス
TOKEN_FILE = Path(__file__).parent / "token_data.json"

class CallbackHandler(BaseHTTPRequestHandler):
    """OAuth コールバックを処理するHTTPハンドラー"""
    
    def do_GET(self):
        """GETリクエスト処理"""
        # URLからコードを抽出
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if 'code' in params:
            self.server.auth_code = params['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            response_html = """
            <html>
            <body>
                <h1>認証成功!</h1>
                <p>トークンの取得に成功しました。このウィンドウは閉じて構いません。</p>
                <script>
                    // 5秒後に自動的にウィンドウを閉じる
                    setTimeout(function() {
                        window.close();
                    }, 5000);
                </script>
            </body>
            </html>
            """
            self.wfile.write(response_html.encode('utf-8'))
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            error_html = """
            <html>
            <body>
                <h1>認証エラー</h1>
                <p>認証コードが見つかりませんでした。</p>
                <script>
                    // 5秒後に自動的にウィンドウを閉じる
                    setTimeout(function() {
                        window.close();
                    }, 5000);
                </script>
            </body>
            </html>
            """
            self.wfile.write(error_html.encode('utf-8'))
        
    def log_message(self, format, *args):
        """HTTPサーバーログをカスタマイズ"""
        logger.debug(f"CallbackServer: {format % args}")

class SaxoAuthenticator:
    """Saxo Bank API 認証マネージャー"""
    
    def __init__(self):
        """初期化"""
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
    
    def get_auth_url(self):
        """認証URLを生成"""
        params = {
            'response_type': 'code',
            'client_id': APP_KEY,
            'redirect_uri': REDIRECT_URL,
            'state': 'state123',  # CSRF保護用のランダム値を実際には使用すべき
        }
        url = f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
        return url
    
    def run_auth_server(self):
        """認証コードを受け取るためのローカルサーバーを実行"""
        server = HTTPServer(('localhost', 8080), CallbackHandler)
        server.auth_code = None
        
        # タイムアウト付きでサーバーを実行
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        logger.info("認証コード受信待機中...")
        
        # タイムアウト
        timeout = time.time() + 120  # 2分
        while server.auth_code is None and time.time() < timeout:
            time.sleep(0.5)
            
        server.shutdown()
        server_thread.join()
        
        if server.auth_code is None:
            raise Exception("認証タイムアウト")
            
        return server.auth_code
    
    def exchange_code_for_token(self, auth_code):
        """認証コードをトークンと交換"""
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': REDIRECT_URL,
        }
        
        # クライアント認証のためのBasic認証ヘッダー
        auth_header = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(TOKEN_ENDPOINT, data=data, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"トークン取得エラー: {response.status_code}")
            logger.error(response.text)
            raise Exception(f"トークン取得失敗: {response.status_code}")
            
        token_data = response.json()
        
        # トークン情報を保存
        self.access_token = token_data['access_token']
        self.refresh_token = token_data['refresh_token']
        self.token_expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
        
        # ファイルに保存
        self._save_token_to_file(token_data)
        
        return token_data
    
    def refresh_access_token(self):
        """リフレッシュトークンを使用してアクセストークンを更新"""
        if not self.refresh_token:
            raise Exception("リフレッシュトークンがありません")
            
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
        }
        
        # クライアント認証のためのBasic認証ヘッダー
        auth_header = base64.b64encode(f"{APP_KEY}:{APP_SECRET}".encode()).decode()
        
        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(TOKEN_ENDPOINT, data=data, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"トークン更新エラー: {response.status_code}")
            logger.error(response.text)
            raise Exception(f"トークン更新失敗: {response.status_code}")
            
        token_data = response.json()
        
        # トークン情報を更新
        self.access_token = token_data['access_token']
        self.refresh_token = token_data['refresh_token']
        self.token_expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
        
        # ファイルに保存
        self._save_token_to_file(token_data)
        
        return token_data
    
    def _save_token_to_file(self, token_data):
        """トークンデータをファイルに保存"""
        token_data['expiry_time'] = (datetime.now() + timedelta(seconds=token_data['expires_in'])).timestamp()
        
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_data, f, indent=2)
            
        logger.debug(f"トークンデータを保存: {TOKEN_FILE}")
    
    def _load_token_from_file(self):
        """ファイルからトークンデータを読み込み"""
        if not TOKEN_FILE.exists():
            logger.debug("トークンファイルが存在しません")
            return None
            
        try:
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
                
            # 有効期限をチェック
            if 'expiry_time' in token_data:
                expiry_time = datetime.fromtimestamp(token_data['expiry_time'])
                if expiry_time <= datetime.now():
                    logger.debug("トークンの有効期限が切れています")
                    # トークンが期限切れの場合はリフレッシュトークンだけ保持
                    self.refresh_token = token_data.get('refresh_token')
                    return None
                    
                self.access_token = token_data['access_token']
                self.refresh_token = token_data['refresh_token']
                self.token_expiry = expiry_time
                
                logger.debug(f"トークン読み込み成功 (有効期限: {expiry_time})")
                return token_data
                
        except Exception as e:
            logger.error(f"トークンファイル読み込みエラー: {e}")
            return None
    
    def get_valid_token(self):
        """有効なアクセストークンを取得"""
        # ファイルから読み込み
        token_data = self._load_token_from_file()
        
        # アクセストークンがない、または期限切れの場合
        if not self.access_token:
            # リフレッシュトークンがある場合は更新を試みる
            if self.refresh_token:
                try:
                    logger.info("アクセストークンを更新しています...")
                    token_data = self.refresh_access_token()
                except Exception as e:
                    logger.error(f"トークン更新エラー: {e}")
                    self.refresh_token = None
                    token_data = None
            
            # それでもトークンがない場合は認証フローを開始
            if not self.access_token:
                logger.info("新しい認証フローを開始します...")
                auth_url = self.get_auth_url()
                logger.info(f"ブラウザで認証ページを開きます: {auth_url}")
                webbrowser.open(auth_url)
                
                auth_code = self.run_auth_server()
                token_data = self.exchange_code_for_token(auth_code)
        
        # トークンの有効期限を確認
        elif self.token_expiry and self.token_expiry < datetime.now() + timedelta(minutes=5):
            # 期限切れの5分前になったらリフレッシュ
            try:
                logger.info("アクセストークンを更新しています...")
                token_data = self.refresh_access_token()
            except Exception as e:
                logger.error(f"トークン更新エラー: {e}")
                # リフレッシュに失敗したら新規認証
                auth_url = self.get_auth_url()
                logger.info(f"ブラウザで認証ページを開きます: {auth_url}")
                webbrowser.open(auth_url)
                
                auth_code = self.run_auth_server()
                token_data = self.exchange_code_for_token(auth_code)
        
        return self.access_token

# シングルトンインスタンス
authenticator = SaxoAuthenticator()

def get_token():
    """有効なアクセストークンを取得する関数（外部からの呼び出し用）"""
    return authenticator.get_valid_token()

if __name__ == "__main__":
    # ロガー設定
    logging.basicConfig(level=logging.DEBUG, 
                       format='%(asctime)s - %(levelname)s - %(message)s')
    
    # トークン取得テスト
    print("Saxo Bank API 認証テスト")
    token = get_token()
    print(f"アクセストークン: {token[:20]}...")