#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
oauth_auth.py - サクソバンクAPI OAuth認証モジュール
oauth フォルダに配置、トークンファイルは親ディレクトリに保存
"""

import requests
import json
import base64
import urllib.parse
import webbrowser
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import hashlib
import secrets
import socket
import os
import sys

logger = logging.getLogger(__name__)

class SaxoOAuthManager:
    """サクソバンクOAuth認証管理クラス"""
    
    def __init__(self, client_id, client_secret, redirect_uri, environment='sim'):
        """
        OAuth認証管理の初期化
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.environment = environment
        
        # 環境別エンドポイント設定
        if environment == 'sim':
            self.auth_base_url = "https://sim.logonvalidation.net"
            self.api_base_url = "https://gateway.saxobank.com/sim/openapi"
        else:
            self.auth_base_url = "https://logonvalidation.net"
            self.api_base_url = "https://gateway.saxobank.com/openapi"
        
        # ディレクトリ設定
        script_dir = Path(__file__).parent  # oauth フォルダ
        parent_dir = script_dir.parent      # saxobank フォルダ
        
        # 呼び出し元のスクリプトの場所を確認
        if hasattr(sys, '_getframe'):
            # 呼び出し元のスクリプトのディレクトリを取得
            try:
                caller_frame = sys._getframe(1)
                caller_file = caller_frame.f_globals.get('__file__')
                if caller_file:
                    caller_dir = Path(caller_file).parent
                    # 呼び出し元が oauth フォルダ内の場合は親ディレクトリ、それ以外は呼び出し元のディレクトリ
                    if caller_dir.name == 'oauth':
                        self.token_file = caller_dir.parent / "saxo_tokens.json"
                    else:
                        self.token_file = caller_dir / "saxo_tokens.json"
                else:
                    # 親ディレクトリをデフォルトとする
                    self.token_file = parent_dir / "saxo_tokens.json"
            except:
                # フレーム情報が取得できない場合は親ディレクトリ
                self.token_file = parent_dir / "saxo_tokens.json"
        else:
            # フレーム情報が取得できない場合は親ディレクトリ
            self.token_file = parent_dir / "saxo_tokens.json"
        
        logger.debug(f"トークンファイルパス: {self.token_file}")
        
        # 現在のトークン情報
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
        # OAuth認証用
        self.authorization_code = None
        self.code_verifier = None
        self.code_challenge = None
        
        # 自動更新用スレッド
        self.refresh_thread = None
        self.is_running = False
        
        logger.info(f"OAuth管理初期化完了 (環境: {environment})")
    
    def _check_port_available(self, port):
        """指定ポートが使用可能かチェック"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def _find_available_port(self, start_port=8080):
        """利用可能なポートを見つける"""
        for port in range(start_port, start_port + 10):
            if self._check_port_available(port):
                logger.info(f"利用可能ポート発見: {port}")
                return port
        raise Exception("利用可能なポートが見つかりません")
    
    def _generate_pkce_params(self):
        """PKCE (Proof Key for Code Exchange) パラメータ生成"""
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        challenge_bytes = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        logger.debug(f"PKCE パラメータ生成完了")
    
    def get_authorization_url(self):
        """認証URLを生成"""
        self._generate_pkce_params()
        
        state = secrets.token_urlsafe(32)
        
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': 'openapi',
            'state': state,
            'code_challenge': self.code_challenge,
            'code_challenge_method': 'S256'
        }
        
        auth_url = f"{self.auth_base_url}/authorize?" + urllib.parse.urlencode(params)
        logger.info(f"認証URL生成完了")
        
        return auth_url, state
    
    def start_callback_server(self, port=None):
        """コールバックサーバー開始"""
        self.authorization_code = None
        
        # ポート自動検出
        if port is None:
            # redirect_uriからポートを抽出
            try:
                parsed_uri = urllib.parse.urlparse(self.redirect_uri)
                port = parsed_uri.port or 8080
            except:
                port = 8080
        
        # 利用可能ポートを確認
        if not self._check_port_available(port):
            logger.warning(f"ポート {port} は使用中です。別のポートを探します...")
            port = self._find_available_port(port)
            # redirect_uriを動的に更新
            self.redirect_uri = f"http://localhost:{port}/callback"
            logger.info(f"リダイレクトURIを更新: {self.redirect_uri}")
        
        server_running = threading.Event()
        server_stopped = threading.Event()
        
        class CallbackHandler(BaseHTTPRequestHandler):
            def __init__(self, oauth_manager, server_events, *args, **kwargs):
                self.oauth_manager = oauth_manager
                self.server_running, self.server_stopped = server_events
                super().__init__(*args, **kwargs)
            
            def do_GET(self):
                parsed_url = urllib.parse.urlparse(self.path)
                query_params = urllib.parse.parse_qs(parsed_url.query)
                
                if 'code' in query_params:
                    self.oauth_manager.authorization_code = query_params['code'][0]
                    logger.info("✅ 認証コード取得成功")
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    success_html = """
                    <html>
                    <head><title>認証成功</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 100px;">
                        <h2 style="color: green;">✅ 認証成功</h2>
                        <p>サクソバンクAPIの認証が完了しました。</p>
                        <p>このウィンドウを閉じて、アプリケーションに戻ってください。</p>
                        <p style="color: gray; font-size: 12px;">ウィンドウは自動で閉じられません。手動で閉じてください。</p>
                    </body>
                    </html>
                    """
                    self.wfile.write(success_html.encode('utf-8'))
                elif 'error' in query_params:
                    error = query_params['error'][0]
                    logger.error(f"認証エラー: {error}")
                    
                    self.send_response(400)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    error_html = f"""
                    <html>
                    <head><title>認証エラー</title></head>
                    <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 100px;">
                        <h2 style="color: red;">❌ 認証エラー</h2>
                        <p>エラー: {error}</p>
                        <p>アプリケーションに戻って再試行してください。</p>
                    </body>
                    </html>
                    """
                    self.wfile.write(error_html.encode('utf-8'))
                
                # サーバー停止をスケジュール
                def delayed_stop():
                    time.sleep(2)
                    self.server_stopped.set()
                
                threading.Thread(target=delayed_stop, daemon=True).start()
            
            def log_message(self, format, *args):
                # HTTPサーバーのログを抑制
                pass
        
        # サーバー作成
        try:
            handler = lambda *args, **kwargs: CallbackHandler(self, (server_running, server_stopped), *args, **kwargs)
            server = HTTPServer(('localhost', port), handler)
            
            def run_server():
                logger.info(f"🌐 コールバックサーバー起動: http://localhost:{port}")
                server_running.set()
                
                # サーバーを継続実行
                while not server_stopped.is_set():
                    server.handle_request()
                    if server_stopped.is_set():
                        break
                
                server.server_close()
                logger.debug("コールバックサーバー停止")
            
            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()
            
            # サーバーが起動するまで待機
            if not server_running.wait(timeout=5):
                raise Exception("コールバックサーバーの起動がタイムアウトしました")
            
            return server_running, server_stopped
            
        except Exception as e:
            logger.error(f"コールバックサーバー起動エラー: {e}")
            raise
    
    def authenticate_interactive(self):
        """対話的OAuth認証フロー"""
        logger.info("🔐 OAuth認証開始")
        
        try:
            # 既存のトークンを確認
            if self.load_tokens() and self.is_token_valid():
                logger.info("✅ 有効なトークンが見つかりました")
                return True
            
            # 1. コールバックサーバー開始
            logger.info("🌐 コールバックサーバーを起動中...")
            server_running, server_stopped = self.start_callback_server()
            
            # 2. 認証URL生成
            auth_url, state = self.get_authorization_url()
            
            # 3. ブラウザで認証ページを開く
            logger.info("🌐 ブラウザで認証ページを開きます...")
            logger.info(f"認証URL: {auth_url}")
            webbrowser.open(auth_url)
            
            # 4. 認証完了まで待機
            logger.info("⏳ 認証完了を待機中...")
            logger.info("ブラウザでサクソバンクにログインしてください...")
            
            start_time = time.time()
            timeout = 300  # 5分
            
            while time.time() - start_time < timeout:
                if self.authorization_code:
                    break
                time.sleep(1)
            
            if not self.authorization_code:
                logger.error("❌ 認証タイムアウト（5分）")
                return False
            
            # 5. アクセストークン取得
            if self.exchange_code_for_tokens():
                logger.info("✅ OAuth認証完了")
                self.start_auto_refresh()
                return True
            else:
                logger.error("❌ トークン取得に失敗")
                return False
                
        except Exception as e:
            logger.error(f"OAuth認証エラー: {e}")
            logger.exception("OAuth認証エラーの詳細:")
            return False
    
    def exchange_code_for_tokens(self):
        """認証コードをアクセストークンに交換"""
        try:
            logger.info("🔄 トークン取得中...")
            
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': self.authorization_code,
                'redirect_uri': self.redirect_uri,
                'code_verifier': self.code_verifier
            }
            
            response = requests.post(f"{self.auth_base_url}/token", headers=headers, data=data)
            
            logger.debug(f"トークンレスポンス: {response.status_code}")
            
            # 200と201の両方を成功として処理
            if response.status_code in [200, 201]:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                
                expires_in = token_data.get('expires_in', 3600)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"✅ トークン取得成功")
                logger.info(f"   有効期限: {self.token_expires_at}")
                logger.info(f"   リフレッシュトークン: {'あり' if self.refresh_token else 'なし'}")
                
                self.save_tokens()
                return True
            else:
                logger.error(f"トークン取得失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"トークン取得エラー: {e}")
            logger.exception("トークン取得エラーの詳細:")
            return False
    
    def refresh_access_token(self):
        """アクセストークンを更新"""
        if not self.refresh_token:
            logger.warning("リフレッシュトークンがありません")
            return False
        
        try:
            logger.info("🔄 トークン更新中...")
            
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }
            
            response = requests.post(f"{self.auth_base_url}/token", headers=headers, data=data)
            
            if response.status_code in [200, 201]:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                if 'refresh_token' in token_data:
                    self.refresh_token = token_data['refresh_token']
                
                expires_in = token_data.get('expires_in', 3600)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"✅ トークン更新成功")
                logger.info(f"   新しい有効期限: {self.token_expires_at}")
                
                self.save_tokens()
                return True
            else:
                logger.error(f"トークン更新失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"トークン更新エラー: {e}")
            logger.exception("トークン更新エラーの詳細:")
            return False
    
    def is_token_valid(self):
        """トークンの有効性チェック"""
        if not self.access_token or not self.token_expires_at:
            return False
        return datetime.now() < self.token_expires_at - timedelta(minutes=5)
    
    def get_valid_token(self):
        """有効なアクセストークンを取得（必要に応じて更新）"""
        if self.is_token_valid():
            return self.access_token
        
        logger.info("トークンが期限切れまたは無効です。更新を試行します。")
        
        if self.refresh_access_token():
            return self.access_token
        else:
            logger.error("トークン更新に失敗しました。再認証が必要です。")
            return None
    
    def save_tokens(self):
        """トークンをファイルに保存（親ディレクトリ）"""
        try:
            token_data = {
                'access_token': self.access_token,
                'refresh_token': self.refresh_token,
                'expires_at': self.token_expires_at.isoformat() if self.token_expires_at else None,
                'environment': self.environment
            }
            
            with open(self.token_file, 'w') as f:
                json.dump(token_data, f, indent=2)
            
            logger.info(f"💾 トークン保存完了: {self.token_file}")
            
        except Exception as e:
            logger.error(f"トークン保存エラー: {e}")
    
    def load_tokens(self):
        """ファイルからトークンを読み込み"""
        try:
            if not self.token_file.exists():
                logger.debug("トークンファイルが存在しません")
                return False
            
            with open(self.token_file, 'r') as f:
                token_data = json.load(f)
            
            if token_data.get('environment') != self.environment:
                logger.warning(f"環境が異なります: {token_data.get('environment')} != {self.environment}")
                return False
            
            self.access_token = token_data.get('access_token')
            self.refresh_token = token_data.get('refresh_token')
            
            if token_data.get('expires_at'):
                self.token_expires_at = datetime.fromisoformat(token_data['expires_at'])
            
            logger.debug(f"トークン読み込み完了: {self.token_file}")
            return True
            
        except Exception as e:
            logger.error(f"トークン読み込みエラー: {e}")
            return False
    
    def start_auto_refresh(self):
        """自動トークン更新開始"""
        if self.refresh_thread and self.refresh_thread.is_alive():
            logger.debug("自動更新スレッドは既に実行中です")
            return
        
        self.is_running = True
        self.refresh_thread = threading.Thread(target=self._auto_refresh_worker, daemon=True)
        self.refresh_thread.start()
        
        logger.info("🔄 自動トークン更新開始")
    
    def stop_auto_refresh(self):
        """自動トークン更新停止"""
        self.is_running = False
        if self.refresh_thread:
            self.refresh_thread.join(timeout=5)
        
        logger.info("🛑 自動トークン更新停止")
    
    def _auto_refresh_worker(self):
        """自動更新ワーカー"""
        while self.is_running:
            try:
                if self.token_expires_at:
                    refresh_time = self.token_expires_at - timedelta(minutes=10)
                    now = datetime.now()
                    
                    if now >= refresh_time:
                        logger.info("⏰ 自動トークン更新実行")
                        self.refresh_access_token()
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"自動更新エラー: {e}")
                time.sleep(60)
    
    def get_api_headers(self):
        """API呼び出し用ヘッダーを取得"""
        token = self.get_valid_token()
        if not token:
            return None
        
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    
    def test_connection(self):
        """API接続テスト"""
        try:
            headers = self.get_api_headers()
            if not headers:
                logger.error("有効なトークンが取得できません")
                return False
            
            response = requests.get(f"{self.api_base_url}/port/v1/users/me", headers=headers)
            
            if response.status_code == 200:
                user_info = response.json()
                logger.info("✅ API接続テスト成功")
                logger.info(f"   ユーザー名: {user_info.get('Name', 'N/A')}")
                logger.info(f"   環境: {self.environment}")
                return True
            else:
                logger.error(f"API接続テスト失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"API接続テストエラー: {e}")
            return False