#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
manual_oauth_test.py - 手動認証テスト（ディレクトリ構造対応版）
oauth フォルダに配置、ログは親ディレクトリの log フォルダに保存
"""

import requests
import json
import base64
import urllib.parse
import webbrowser
import logging
from datetime import datetime, timedelta
import hashlib
import secrets
import os
import sys
from pathlib import Path

# 親ディレクトリをパスに追加（config.py をインポートするため）
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import get_oauth_config, get_api_endpoints, validate_config

# ディレクトリ設定
script_dir = Path(__file__).parent  # oauth フォルダ
parent_dir = script_dir.parent      # saxobank フォルダ
log_dir = parent_dir / "log"        # log フォルダ

# log ディレクトリの作成
log_dir.mkdir(exist_ok=True)

# ログ設定（親ディレクトリの log フォルダに保存）
log_filename = log_dir / f'oauth_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ManualOAuthTester:
    def __init__(self):
        """手動OAuth認証テスターの初期化"""
        oauth_config = get_oauth_config()
        api_endpoints = get_api_endpoints()
        
        self.client_id = oauth_config['client_id']
        self.client_secret = oauth_config['client_secret']
        self.environment = oauth_config['environment']
        
        self.auth_base_url = api_endpoints['auth_base_url']
        self.api_base_url = api_endpoints['api_base_url']
        
        # 手動入力用の固定リダイレクトURI
        self.redirect_uri = "https://www.saxobank.com"
        
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
        # PKCE パラメータ
        self.code_verifier = None
        self.code_challenge = None
        
        # トークンファイルパス（親ディレクトリ）
        self.token_file = parent_dir / "saxo_tokens.json"
    
    def _generate_pkce_params(self):
        """PKCE パラメータ生成"""
        self.code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
        challenge_bytes = hashlib.sha256(self.code_verifier.encode('utf-8')).digest()
        self.code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        logger.debug(f"PKCE パラメータ生成完了")
    
    def get_authorization_url(self):
        """認証URL生成"""
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
    
    def authenticate_manual(self):
        """手動OAuth認証フロー"""
        logger.info("🔐 手動OAuth認証開始")
        
        try:
            # 1. 認証URL生成
            auth_url, state = self.get_authorization_url()
            
            # 2. ブラウザで認証ページを開く
            logger.info("🌐 ブラウザで認証ページを開きます...")
            webbrowser.open(auth_url)
            
            # 3. ユーザーに手順を説明
            print("\n" + "="*80)
            print("📋 手動認証の手順:")
            print("="*80)
            print("1. ブラウザでサクソバンクにログインしてください")
            print("2. 認証が完了すると、URLが以下のような形になります:")
            print("   https://www.saxobank.com/?code=XXXXXXXX&state=XXXXXXXX")
            print("3. URLバーから「code=」の後の文字列をコピーしてください")
            print("4. 以下に認証コードを貼り付けてEnterを押してください")
            print("="*80)
            
            # 4. 認証コードを手動入力
            while True:
                auth_code = input("\n🔑 認証コード: ").strip()
                
                if not auth_code:
                    print("❌ 認証コードが空です。再度入力してください。")
                    continue
                
                # URLが丸ごと貼り付けられた場合の処理
                if 'code=' in auth_code:
                    try:
                        parsed_url = urllib.parse.urlparse(auth_code)
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        if 'code' in query_params:
                            auth_code = query_params['code'][0]
                            logger.info("✅ URLから認証コードを抽出しました")
                    except:
                        pass
                
                break
            
            # 5. アクセストークン取得
            logger.info("🔄 認証コードをアクセストークンに交換中...")
            if self.exchange_code_for_tokens(auth_code):
                logger.info("✅ 手動OAuth認証完了")
                return True
            else:
                logger.error("❌ トークン取得に失敗")
                return False
                
        except Exception as e:
            logger.error(f"手動OAuth認証エラー: {e}")
            logger.exception("認証エラーの詳細:")
            return False
    
    def exchange_code_for_tokens(self, auth_code):
        """認証コードをアクセストークンに交換（修正版）"""
        try:
            # Basic認証ヘッダー作成
            auth_string = f"{self.client_id}:{self.client_secret}"
            auth_bytes = auth_string.encode('ascii')
            auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
            
            headers = {
                'Authorization': f'Basic {auth_b64}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            data = {
                'grant_type': 'authorization_code',
                'code': auth_code,
                'redirect_uri': self.redirect_uri,
                'code_verifier': self.code_verifier
            }
            
            logger.debug(f"トークン取得リクエスト送信中...")
            response = requests.post(f"{self.auth_base_url}/token", headers=headers, data=data)
            
            logger.info(f"トークンレスポンス: {response.status_code}")
            
            # 200と201の両方を成功として処理
            if response.status_code in [200, 201]:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                
                expires_in = token_data.get('expires_in', 3600)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info(f"✅ トークン取得成功")
                logger.info(f"   アクセストークン: {self.access_token[:20]}...")
                logger.info(f"   リフレッシュトークン: {'あり' if self.refresh_token else 'なし'}")
                logger.info(f"   有効期限: {self.token_expires_at}")
                logger.info(f"   有効時間: {expires_in}秒 ({expires_in//60}分)")
                
                # トークンをファイルに保存
                self.save_tokens()
                
                return True
            else:
                logger.error(f"❌ トークン取得失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"トークン取得エラー: {e}")
            logger.exception("トークン取得エラーの詳細:")
            return False
    
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
            
            logger.info(f"💾 トークンファイル保存完了: {self.token_file}")
            
        except Exception as e:
            logger.error(f"トークン保存エラー: {e}")
    
    def test_connection(self):
        """API接続テスト"""
        try:
            if not self.access_token:
                logger.error("アクセストークンがありません")
                return False
            
            headers = {
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json'
            }
            
            logger.info("🔍 API接続テスト実行中...")
            
            # ユーザー情報取得テスト
            response = requests.get(f"{self.api_base_url}/port/v1/users/me", headers=headers)
            
            logger.info(f"API接続レスポンス: {response.status_code}")
            
            if response.status_code == 200:
                user_info = response.json()
                logger.info("✅ API接続テスト成功")
                logger.info(f"   ユーザー名: {user_info.get('Name', 'N/A')}")
                logger.info(f"   言語: {user_info.get('Language', 'N/A')}")
                logger.info(f"   環境: {self.environment}")
                return True
            else:
                logger.error(f"❌ API接続テスト失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"API接続テストエラー: {e}")
            logger.exception("API接続テストエラーの詳細:")
            return False

def show_success_summary():
    """成功時のサマリー表示"""
    print("\n" + "🎉" * 30)
    print("🎉 OAuth認証完全成功！ 🎉")
    print("🎉" * 30)
    print()
    print("✅ 完了した項目:")
    print("   🔐 OAuth認証: 成功")
    print("   🔑 アクセストークン: 取得済み")
    print("   🔄 リフレッシュトークン: 取得済み") 
    print("   💾 トークンファイル: 保存済み")
    print("   🌐 API接続: 確認済み")
    print()
    print("📋 次にできること:")
    print("   🤖 python bot_saxo.py - FX自動エントリーシステム実行")
    print("   📊 python fx_rate_collector_oauth.py - レート収集実行")
    print("   🔍 python oauth/oauth_test.py - 通常のOAuth認証テスト")
    print()
    print("📁 生成されたファイル:")
    print(f"   📄 {parent_dir / 'saxo_tokens.json'} - 認証トークン")
    print(f"   📄 {log_filename} - 実行ログ")
    print()
    print("=" * 60)

def pause_before_exit():
    """終了前に一時停止"""
    print("\n" + "="*80)
    print("📋 実行結果:")
    print("="*80)
    
    # トークンファイルの存在確認（親ディレクトリ）
    token_file = parent_dir / "saxo_tokens.json"
    if token_file.exists():
        print(f"✅ saxo_tokens.json: 生成済み ({token_file})")
        try:
            with open(token_file, 'r') as f:
                token_data = json.load(f)
            print(f"✅ 環境: {token_data.get('environment', 'N/A')}")
            print(f"✅ 有効期限: {token_data.get('expires_at', 'N/A')}")
        except:
            print("⚠️ トークンファイルの読み込みでエラー")
    else:
        print(f"❌ saxo_tokens.json: 生成されていません ({token_file})")
    
    # ログファイル情報
    print(f"📝 ログファイル: {log_filename}")
    
    print("="*80)
    input("\n👆 結果を確認してください。Enterキーを押すと終了します...")

def main():
    """メイン関数"""
    try:
        print("=" * 80)
        print("🔐 手動OAuth認証テスト（ディレクトリ構造対応版）")
        print("=" * 80)
        print(f"📁 実行ディレクトリ: {script_dir}")
        print(f"📁 親ディレクトリ: {parent_dir}")
        print(f"📄 トークンファイル: {parent_dir / 'saxo_tokens.json'}")
        print(f"📄 ログファイル: {log_filename}")
        print("=" * 80)
        
        # 設定検証
        config_errors = validate_config()
        if config_errors:
            logger.error("❌ 設定エラーが検出されました:")
            for error in config_errors:
                logger.error(f"  - {error}")
            pause_before_exit()
            return 1
        
        # 手動OAuth認証テスト
        tester = ManualOAuthTester()
        
        auth_success = False
        api_success = False
        
        if tester.authenticate_manual():
            auth_success = True
            logger.info("🎉 認証フェーズ完了")
            
            # API接続テスト
            if tester.test_connection():
                api_success = True
                logger.info("🎉 API接続テスト完了")
                
                # 成功サマリー表示
                show_success_summary()
            else:
                logger.error("❌ API接続テストに失敗しました")
        else:
            logger.error("❌ OAuth認証に失敗しました")
        
        # 最終結果表示
        print("\n" + "="*80)
        if auth_success and api_success:
            print("🎉 OAuth認証システム完全動作確認済み！")
            print("✅ OAuth認証: 成功")
            print("✅ API接続テスト: 成功") 
            print("✅ トークンファイル生成: 親ディレクトリに保存済み")
            print("✅ システム使用準備: 完了")
            result = 0
        elif auth_success:
            print("⚠️ 認証は成功しましたが、API接続テストに失敗")
            print("✅ OAuth認証: 成功")
            print("❌ API接続テスト: 失敗")
            result = 1
        else:
            print("❌ OAuth認証に失敗しました")
            print("❌ OAuth認証: 失敗")
            result = 1
        print("="*80)
        
        pause_before_exit()
        return result
        
    except Exception as e:
        logger.error(f"予期しないエラー: {e}")
        logger.exception("予期しないエラーの詳細:")
        pause_before_exit()
        return 1

if __name__ == "__main__":
    exit(main())