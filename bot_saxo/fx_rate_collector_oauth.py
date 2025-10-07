#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_rate_collector_oauth.py - FXエントリーポイントレート収集・スプレッドシート送信システム (OAuth2対応版)
サクソバンクAPIのOAuth2 Code flowを使用した実装
"""

import requests
import pandas as pd
import glob
import os
from datetime import datetime, timedelta
import time
import json
import logging
from pathlib import Path
import re
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import secrets

# ログ設定
script_dir = Path(__file__).parent
log_dir = script_dir / "logs"
backup_dir = script_dir / "backup"

# ディレクトリ作成
log_dir.mkdir(exist_ok=True)
backup_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f'fx_rate_collector_{datetime.now().strftime("%Y%m%d")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# コンソール出力のレベルをINFOに制限
console_handler = None
for handler in logger.handlers:
    if isinstance(handler, logging.StreamHandler) and handler.stream.name == '<stderr>':
        console_handler = handler
        break

if console_handler:
    console_handler.setLevel(logging.INFO)

class AuthorizationCodeHandler(BaseHTTPRequestHandler):
    """OAuth2認証コードを受け取るためのHTTPハンドラー"""
    
    def do_GET(self):
        """GETリクエストの処理"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        # URLパラメータを解析
        query_components = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        
        if 'code' in query_components:
            # 認証コードを保存
            self.server.auth_code = query_components['code']
            self.server.state = query_components.get('state', '')
            
            # 成功ページを表示
            html = '''
            <html>
            <head><title>認証成功</title></head>
            <body>
                <h1>認証が完了しました</h1>
                <p>ブラウザを閉じて、アプリケーションに戻ってください。</p>
            </body>
            </html>
            '''
            self.wfile.write(html.encode())
            
        elif 'error' in query_components:
            # エラー処理
            self.server.auth_error = query_components.get('error_description', query_components['error'])
            
            html = f'''
            <html>
            <head><title>認証エラー</title></head>
            <body>
                <h1>認証エラー</h1>
                <p>エラー: {self.server.auth_error}</p>
            </body>
            </html>
            '''
            self.wfile.write(html.encode())
        
        # サーバー停止シグナル
        threading.Thread(target=self.server.shutdown).start()
    
    def log_message(self, format, *args):
        """ログメッセージを無効化"""
        pass

class FXRateCollector:
    def __init__(self):
        """FXレート収集システムの初期化"""
        logger.info("🚀 FXレート収集システム開始 (OAuth2対応版)")
        
        # パス設定
        self.entrypoint_path = r"C:\Users\beru\Dropbox\006_TRADE\historycal\entrypoint_fx"
        self.verification_path = r"C:\Users\beru\Downloads"
        
        # スプレッドシートWebhook URL
        self.webhook_url = "https://script.google.com/macros/s/AKfycbxwox807RBi4yJG2rHSklR5wiW5uA2Z38rxaJVs-WPJ/exec"
        
        # サクソバンクAPI設定（SIM環境）
        self.client_id = "5f19317941744e688ca30be6b2f53659"
        self.client_secret = "7e7f99b6a65343ebae16c915daddff80"  
        
        # SIM環境のエンドポイント
        self.base_url = "https://gateway.saxobank.com/sim/openapi"
        self.auth_base_url = "https://sim.logonvalidation.net"
        self.token_endpoint = f"{self.auth_base_url}/token"
        self.authorization_endpoint = f"{self.auth_base_url}/authorize"
        
        # リダイレクト設定
        self.redirect_uri = "http://localhost:8080/callback"
        self.redirect_port = 8080
        
        # 認証関連
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None
        
        self.headers = {
            'Content-Type': 'application/json'
        }
        
        # 通貨ペアマッピング
        self.currency_uic_mapping = {
            'USDJPY': 31,
            'EURJPY': 16,
            'GBPJPY': 154,
            'AUDJPY': 4,
            'CHFJPY': 14,
            'EURUSD': 21,
            'GBPUSD': 22,
            'AUDUSD': 2
        }
        
        # データ保存用
        self.entrypoints_df = None
        self.verification_data = {}
        self.collected_rates = []
        
        # テスト用設定
        self.test_mode = True  # テストモード（実際のAPI呼び出しをしない）
        
        # 初期化
        self._initialize_system()
    
    def _initialize_system(self):
        """システム初期化"""
        logger.info("📋 システム初期化を開始します...")
        
        try:
            if not self.test_mode:
                # 1. OAuth2認証
                logger.debug("1/3: OAuth2認証中...")
                if not self.authenticate_oauth2():
                    raise Exception("OAuth2認証に失敗しました")
            else:
                logger.info("🧪 テストモードで実行します（実際のAPI呼び出しは行いません）")
            
            # 2. 通貨ペアUICマッピング確認
            logger.debug("2/3: 通貨ペアUICマッピング確認中...")
            self._validate_currency_mapping()
            
            # 3. ファイル存在確認
            logger.debug("3/3: ファイル存在確認中...")
            self._validate_file_paths()
            
            logger.info("✅ システム初期化完了")
            
        except Exception as e:
            logger.error(f"❌ システム初期化エラー: {e}")
            logger.exception("初期化エラーの詳細:")
            raise
    
    def authenticate_oauth2(self):
        """OAuth2 Code flow認証"""
        try:
            logger.info("🔐 OAuth2認証開始")
            
            # 1. 認証サーバー起動
            logger.info("認証用ローカルサーバーを起動中...")
            auth_server = self._start_auth_server()
            
            # 2. 認証URLを生成してブラウザで開く
            auth_url = self._build_authorization_url()
            logger.info(f"認証URL: {auth_url}")
            logger.info("ブラウザで認証画面を開いています...")
            
            webbrowser.open(auth_url)
            
            # 3. 認証コードを待機
            logger.info("認証コードの取得を待機中...")
            auth_code = self._wait_for_auth_code(auth_server)
            
            if not auth_code:
                logger.error("認証コードの取得に失敗しました")
                return False
            
            # 4. 認証コードをアクセストークンに交換
            logger.info("認証コードをアクセストークンに交換中...")
            if self._exchange_code_for_token(auth_code):
                logger.info("✅ OAuth2認証完了")
                return True
            else:
                logger.error("アクセストークンの取得に失敗しました")
                return False
                
        except Exception as e:
            logger.error(f"OAuth2認証エラー: {e}")
            logger.exception("OAuth2認証エラーの詳細:")
            return False
    
    def _start_auth_server(self):
        """認証用HTTPサーバーを起動"""
        server = HTTPServer(('localhost', self.redirect_port), AuthorizationCodeHandler)
        server.auth_code = None
        server.auth_error = None
        server.state = None
        
        # バックグラウンドでサーバー起動
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        logger.debug(f"認証サーバーがポート {self.redirect_port} で起動しました")
        return server
    
    def _build_authorization_url(self):
        """認証URL生成"""
        state = secrets.token_urlsafe(32)
        
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'state': state,
            'scope': 'openapi'  # 必要なスコープを指定
        }
        
        return f"{self.authorization_endpoint}?" + urllib.parse.urlencode(params)
    
    def _wait_for_auth_code(self, server, timeout=300):
        """認証コードの取得を待機"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if server.auth_code:
                logger.debug(f"認証コード取得成功: {server.auth_code[:10]}...")
                return server.auth_code
            elif server.auth_error:
                logger.error(f"認証エラー: {server.auth_error}")
                return None
            
            time.sleep(0.5)
        
        logger.error("認証コード取得がタイムアウトしました")
        return None
    
    def _exchange_code_for_token(self, auth_code):
        """認証コードをアクセストークンに交換"""
        try:
            data = {
                'grant_type': 'authorization_code',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'code': auth_code,
                'redirect_uri': self.redirect_uri
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            response = requests.post(self.token_endpoint, data=data, headers=headers)
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                expires_in = token_data.get('expires_in', 3600)
                
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                # ヘッダーにアクセストークンを設定
                self.headers['Authorization'] = f'Bearer {self.access_token}'
                
                logger.info("✅ アクセストークン取得成功")
                logger.info(f"トークン有効期限: {self.token_expires_at}")
                
                return True
            else:
                logger.error(f"トークン取得失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"トークン交換エラー: {e}")
            return False
    
    def refresh_access_token(self):
        """リフレッシュトークンを使用してアクセストークンを更新"""
        if not self.refresh_token:
            logger.warning("リフレッシュトークンがありません。再認証が必要です。")
            return False
        
        try:
            data = {
                'grant_type': 'refresh_token',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            response = requests.post(self.token_endpoint, data=data, headers=headers)
            
            if response.status_code == 200:
                token_data = response.json()
                
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token', self.refresh_token)
                expires_in = token_data.get('expires_in', 3600)
                
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
                
                # ヘッダーを更新
                self.headers['Authorization'] = f'Bearer {self.access_token}'
                
                logger.info("✅ アクセストークン更新成功")
                logger.info(f"新しい有効期限: {self.token_expires_at}")
                
                return True
            else:
                logger.error(f"トークン更新失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"トークン更新エラー: {e}")
            return False
    
    def is_token_valid(self):
        """アクセストークンの有効性チェック"""
        if not self.access_token or not self.token_expires_at:
            return False
        return datetime.now() < self.token_expires_at - timedelta(minutes=5)  # 5分前に更新
    
    def ensure_valid_token(self):
        """有効なトークンを確保"""
        if not self.is_token_valid():
            logger.info("トークンが無効または期限切れ。更新を試行します。")
            if not self.refresh_access_token():
                logger.error("トークン更新に失敗しました。再認証が必要です。")
                return False
        return True
    
    def _validate_currency_mapping(self):
        """通貨ペアマッピングの検証"""
        logger.info(f"📊 対応通貨ペア数: {len(self.currency_uic_mapping)}")
        for pair, uic in self.currency_uic_mapping.items():
            logger.debug(f"  - {pair}: UIC {uic}")
    
    def _validate_file_paths(self):
        """ファイルパスの検証"""
        if not os.path.exists(self.entrypoint_path):
            raise Exception(f"エントリーポイントディレクトリが見つかりません: {self.entrypoint_path}")
        
        if not os.path.exists(self.verification_path):
            raise Exception(f"検証ファイルディレクトリが見つかりません: {self.verification_path}")
    
    def find_latest_entrypoint_file(self):
        """最新のエントリーポイントファイルを取得"""
        try:
            pattern = os.path.join(self.entrypoint_path, "entrypoints_*.csv")
            files = glob.glob(pattern)
            
            if not files:
                raise Exception(f"エントリーポイントファイルが見つかりません: {self.entrypoint_path}")
            
            # ファイル名から日付を抽出してソート
            def extract_date(filename):
                match = re.search(r'entrypoints_(\d{8})\.csv', filename)
                if match:
                    return datetime.strptime(match.group(1), '%Y%m%d')
                return datetime.min
            
            latest_file = max(files, key=extract_date)
            logger.info(f"📁 最新エントリーポイントファイル: {os.path.basename(latest_file)}")
            return latest_file
            
        except Exception as e:
            logger.error(f"エントリーポイントファイル取得エラー: {e}")
            raise
    
    def find_latest_verification_file(self):
        """最新の検証ファイルを取得"""
        try:
            pattern = os.path.join(self.verification_path, "アノマリーFX 検証ポイント*エントリーポイント.csv")
            files = glob.glob(pattern)
            
            if not files:
                raise Exception(f"検証ファイルが見つかりません: {self.verification_path}")
            
            # ファイル名から日付を抽出してソート
            def extract_date(filename):
                match = re.search(r'(\d{4})年(\d{2})月(\d{2})日', filename)
                if match:
                    year, month, day = match.groups()
                    return datetime(int(year), int(month), int(day))
                return datetime.min
            
            latest_file = max(files, key=extract_date)
            logger.info(f"📁 最新検証ファイル: {os.path.basename(latest_file)}")
            return latest_file
            
        except Exception as e:
            logger.error(f"検証ファイル取得エラー: {e}")
            raise
    
    def load_entrypoint_file(self):
        """エントリーポイントファイル読み込み"""
        try:
            file_path = self.find_latest_entrypoint_file()
            self.entrypoints_df = pd.read_csv(file_path, encoding='utf-8-sig')
            
            logger.info(f"✅ エントリーポイント読み込み完了: {len(self.entrypoints_df)}件")
            logger.info(f"📊 通貨ペア別内訳:")
            for currency, count in self.entrypoints_df['通貨ペア'].value_counts().items():
                logger.info(f"  - {currency}: {count}件")
                
        except Exception as e:
            logger.error(f"エントリーポイントファイル読み込みエラー: {e}")
            raise
    
    def load_verification_file(self):
        """検証ファイル読み込み（改良版）"""
        try:
            file_path = self.find_latest_verification_file()
            
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            
            logger.debug(f"検証ファイル総行数: {len(lines)}")
            
            # 各セクションを識別して読み込み
            sections = {
                '利益効率（Hatch検証）日中版': [],
                '利益効率（Hatch検証）': [],
                '勝率重視（ぶりんださん検証） 日中版': [],
                '勝率重視（ぶりんださん検証）': [],
                '時間効率重視 日中版': [],
                '時間効率重視 終日版': [],
                '最大利益 日中版': [],
                '最大利益 終日版': []
            }
            
            current_section = None
            reading_time_order = False
            
            for line_num, line in enumerate(lines, 1):
                original_line = line
                line = line.strip()
                
                if not line:
                    continue
                
                # セクション識別
                section_found = False
                for section_key in sections.keys():
                    if (f"#{section_key}" in line or 
                        section_key in line or
                        (section_key.replace('（', '(').replace('）', ')') in line)):
                        current_section = section_key
                        reading_time_order = False
                        section_found = True
                        logger.debug(f"行{line_num}: セクション発見 '{current_section}'")
                        break
                
                if section_found:
                    continue
                
                # 時刻順セクション識別
                if current_section and ("時刻順" in line or "採用された時間枠 (時刻順" in line):
                    reading_time_order = True
                    logger.debug(f"行{line_num}: 時刻順セクション開始 '{current_section}'")
                    continue
                
                # データ行の処理
                if current_section and reading_time_order:
                    parts = line.split(',')
                    
                    if (len(parts) >= 5 and 
                        parts[0].strip().isdigit() and 
                        parts[1].strip() and 
                        parts[2].strip() and 
                        parts[3].strip() and 
                        parts[4].strip()):
                        
                        entry_data = {
                            'currency_pair': parts[1].strip(),
                            'entry_time': parts[2].strip(),
                            'exit_time': parts[3].strip(),
                            'direction': parts[4].strip()
                        }
                        sections[current_section].append(entry_data)
                        logger.debug(f"行{line_num}: データ追加 {entry_data}")
                
                # 空行や区切り行でセクション状態をリセット
                if line.startswith(',,,') or not line.strip():
                    if reading_time_order:
                        logger.debug(f"行{line_num}: セクション終了")
                    reading_time_order = False
            
            self.verification_data = sections
            
            # 読み込み結果ログ
            logger.info("✅ 検証ファイル読み込み完了:")
            total_entries = 0
            for section, data in sections.items():
                logger.info(f"  - {section}: {len(data)}件")
                total_entries += len(data)
            
            logger.info(f"📊 検証ファイル総エントリー数: {total_entries}件")
                
        except Exception as e:
            logger.error(f"検証ファイル読み込みエラー: {e}")
            logger.exception("検証ファイル読み込みエラーの詳細:")
            raise
    
    def get_current_price(self, currency_pair):
        """現在価格取得（OAuth2対応版）"""
        try:
            # テストモードの場合はダミーデータを返す
            if self.test_mode:
                return self._get_test_price(currency_pair)
            
            # トークンの有効性チェック
            if not self.ensure_valid_token():
                logger.error("有効なトークンが取得できません")
                return None
            
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.warning(f"UICが見つかりません: {currency_pair}")
                return None
            
            params = {
                'Uic': str(uic),
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            
            response = requests.get(
                f"{self.base_url}/trade/v1/infoprices", 
                headers=self.headers, 
                params=params,
                timeout=10
            )
            
            if response.status_code == 200:
                prices = response.json()
                
                # 小数点桁数設定
                decimals = 3 if 'JPY' in currency_pair else 5
                
                if 'Quote' in prices:
                    quote = prices['Quote']
                    result = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread', 0),
                        'timestamp': datetime.now().isoformat()
                    }
                elif prices.get('Data') and len(prices['Data']) > 0:
                    quote = prices['Data'][0].get('Quote', {})
                    result = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread', 0),
                        'timestamp': datetime.now().isoformat()
                    }
                else:
                    logger.error(f"価格データの構造が予期しない形式: {prices}")
                    return None
                
                logger.debug(f"{currency_pair} 価格取得成功: {result}")
                return result
            
            elif response.status_code == 401:
                logger.warning("認証エラー。トークンを更新します。")
                if self.refresh_access_token():
                    # 再帰的に再試行（1回のみ）
                    return self.get_current_price(currency_pair)
            
            logger.warning(f"価格取得失敗: {currency_pair} (ステータス: {response.status_code})")
            logger.debug(f"レスポンス: {response.text}")
            return None
            
        except Exception as e:
            logger.error(f"価格取得エラー: {currency_pair} - {str(e)}")
            return None
    
    def _get_test_price(self, currency_pair):
        """テスト用価格データ生成"""
        import random
        
        # 通貨ペア別の大まかな価格レンジ
        price_ranges = {
            'USDJPY': (148.0, 152.0),
            'EURJPY': (160.0, 170.0),
            'GBPJPY': (180.0, 190.0),
            'AUDJPY': (95.0, 105.0),
            'CHFJPY': (165.0, 175.0),
            'EURUSD': (1.05, 1.10),
            'GBPUSD': (1.20, 1.30),
            'AUDUSD': (0.65, 0.70)
        }
        
        min_price, max_price = price_ranges.get(currency_pair, (1.0, 2.0))
        base_price = random.uniform(min_price, max_price)
        
        # 小数点桁数設定
        decimals = 3 if 'JPY' in currency_pair else 5
        
        # スプレッドを設定
        spread_pips = random.uniform(0.5, 3.0)
        if 'JPY' in currency_pair:
            spread = spread_pips * 0.01  # JPYペアは0.01単位
        else:
            spread = spread_pips * 0.0001  # その他は0.0001単位
        
        bid = round(base_price - spread/2, decimals)
        ask = round(base_price + spread/2, decimals)
        
        logger.debug(f"🧪 テストデータ生成: {currency_pair} BID={bid}, ASK={ask}")
        
        return {
            'bid': bid,
            'ask': ask,
            'spread': round(spread, decimals),
            'timestamp': datetime.now().isoformat()
        }
    
    def collect_rates_for_entrypoints(self):
        """エントリーポイントのレート収集"""
        logger.info("📈 エントリーポイントレート収集開始")
        
        for index, row in self.entrypoints_df.iterrows():
            currency_pair = row['通貨ペア']
            entry_time = row['Entry']
            exit_time = row['Exit']
            direction = row['方向']
            
            logger.info(f"レート取得: {currency_pair} {entry_time}-{exit_time} {direction}")
            
            # エントリー価格取得
            entry_price_data = self.get_current_price(currency_pair)
            time.sleep(0.2)  # 短い待機
            
            # エグジット価格取得
            exit_price_data = self.get_current_price(currency_pair)
            
            if entry_price_data and exit_price_data:
                # エントリー価格とエグジット価格を決定
                if direction.upper() in ['LONG', 'BUY']:
                    entry_price = entry_price_data['ask']  # ロングはASKで買い
                    exit_price = exit_price_data['bid']    # ロングはBIDで売り
                else:  # SHORT, SELL
                    entry_price = entry_price_data['bid']  # ショートはBIDで売り
                    exit_price = exit_price_data['ask']    # ショートはASKで買い戻し
                
                # pips差を計算
                pips_diff = self.calculate_pips_difference(
                    currency_pair, entry_price, exit_price, direction
                )
                
                rate_info = {
                    'source': 'entrypoints',
                    'currency_pair': currency_pair,
                    'entry_time': entry_time,
                    'exit_time': exit_time,
                    'direction': direction,
                    'score': row.get('実用スコア', 0),
                    'entry_bid': entry_price_data['bid'],
                    'entry_ask': entry_price_data['ask'],
                    'exit_bid': exit_price_data['bid'],
                    'exit_ask': exit_price_data['ask'],
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'pips_diff': pips_diff,
                    'spread_entry': entry_price_data['spread'],
                    'spread_exit': exit_price_data['spread'],
                    'timestamp': datetime.now().isoformat()
                }
                self.collected_rates.append(rate_info)
                
                logger.info(f"  ✅ {currency_pair}: エントリー={entry_price}, エグジット={exit_price}, Pips差={pips_diff:.1f}")
            else:
                logger.warning(f"  ❌ {currency_pair}: レート取得失敗")
            
            # API制限対策で少し待機
            time.sleep(0.5)
    
    def collect_rates_for_verification(self):
        """検証データのレート収集"""
        logger.info("📊 検証データレート収集開始")
        
        for section_name, entries in self.verification_data.items():
            logger.info(f"セクション処理: {section_name} ({len(entries)}件)")
            
            for entry in entries:
                currency_pair = entry['currency_pair']
                entry_time = entry['entry_time']
                exit_time = entry['exit_time']
                direction = entry['direction']
                
                logger.info(f"レート取得: {currency_pair} {entry_time}-{exit_time} {direction}")
                
                # エントリー価格取得
                entry_price_data = self.get_current_price(currency_pair)
                time.sleep(0.2)  # 短い待機
                
                # エグジット価格取得
                exit_price_data = self.get_current_price(currency_pair)
                
                if entry_price_data and exit_price_data:
                    # エントリー価格とエグジット価格を決定
                    if direction.upper() in ['LONG', 'BUY']:
                        entry_price = entry_price_data['ask']
                        exit_price = exit_price_data['bid']
                    else:  # SHORT, SELL
                        entry_price = entry_price_data['bid']
                        exit_price = exit_price_data['ask']
                    
                    # pips差を計算
                    pips_diff = self.calculate_pips_difference(
                        currency_pair, entry_price, exit_price, direction
                    )
                    
                    rate_info = {
                        'source': section_name,
                        'currency_pair': currency_pair,
                        'entry_time': entry_time,
                        'exit_time': exit_time,
                        'direction': direction,
                        'entry_bid': entry_price_data['bid'],
                        'entry_ask': entry_price_data['ask'],
                        'exit_bid': exit_price_data['bid'],
                        'exit_ask': exit_price_data['ask'],
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pips_diff': pips_diff,
                        'spread_entry': entry_price_data['spread'],
                        'spread_exit': exit_price_data['spread'],
                        'timestamp': datetime.now().isoformat()
                    }
                    self.collected_rates.append(rate_info)
                    
                    logger.info(f"  ✅ {currency_pair}: エントリー={entry_price}, エグジット={exit_price}, Pips差={pips_diff:.1f}")
                else:
                    logger.warning(f"  ❌ {currency_pair}: レート取得失敗")
                
                # API制限対策で少し待機
                time.sleep(0.5)
    
    def calculate_pips_difference(self, currency_pair, entry_price, exit_price, direction):
        """pips差を計算"""
        try:
            # JPYペアの場合は100倍、その他は10000倍でpips計算
            if 'JPY' in currency_pair:
                pip_factor = 100
            else:
                pip_factor = 10000
            
            # 方向に応じてpips差を計算
            if direction.upper() in ['LONG', 'BUY']:
                # ロング: エグジット価格 - エントリー価格
                pips_diff = (exit_price - entry_price) * pip_factor
            else:  # SHORT, SELL
                # ショート: エントリー価格 - エグジット価格
                pips_diff = (entry_price - exit_price) * pip_factor
            
            return round(pips_diff, 1)
            
        except Exception as e:
            logger.error(f"pips差計算エラー: {e}")
            return 0.0
    
    def prepare_spreadsheet_data(self):
        """スプレッドシート送信データ準備（ソース番号付き、時刻順ソート）"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # データをセクション別に整理してソース名に番号を付ける
        source_counters = {}  # 各ソースの番号カウンター
        
        # 各レートデータにソース番号を追加
        for rate in self.collected_rates:
            source = rate['source']
            if source not in source_counters:
                source_counters[source] = 0
            source_counters[source] += 1
            
            # 丸囲み数字を追加
            circled_number = self._get_circled_number(source_counters[source])
            rate['numbered_source'] = f"{source}{circled_number}"
        
        # エントリー時刻で昇順ソート
        self.collected_rates.sort(key=lambda x: x['entry_time'])
        
        # データをスプレッドシート用に整理
        spreadsheet_data = {
            'sheet_name': f'FX_Rates_{today}',
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_points': len(self.collected_rates),
                'currency_pairs': list(set([r['currency_pair'] for r in self.collected_rates])),
                'collection_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            },
            'data': []
        }
        
        # ヘッダー行
        headers = [
            'No.', 'ソース', '通貨ペア', 'エントリー時刻', 'エグジット時刻', '方向',
            'エントリー価格', 'エグジット価格', 'Pips差', 
            'エントリーBID', 'エントリーASK', 'エグジットBID', 'エグジットASK',
            'エントリースプレッド', 'エグジットスプレッド', '取得時刻', 'スコア'
        ]
        
        # ヘッダー行を追加
        spreadsheet_data['data'].append(headers)
        
        # データ行を追加（時刻順、番号付きソース名）
        for index, rate in enumerate(self.collected_rates, 1):
            row = [
                index,  # 行番号
                rate['numbered_source'],  # 番号付きソース名
                rate['currency_pair'],
                rate['entry_time'],
                rate['exit_time'],
                rate['direction'],
                rate.get('entry_price', ''),
                rate.get('exit_price', ''),
                rate.get('pips_diff', ''),
                rate.get('entry_bid', rate.get('bid', '')),
                rate.get('entry_ask', rate.get('ask', '')),
                rate.get('exit_bid', ''),
                rate.get('exit_ask', ''),
                rate.get('spread_entry', rate.get('spread', '')),
                rate.get('spread_exit', ''),
                rate['timestamp'],
                rate.get('score', '')
            ]
            spreadsheet_data['data'].append(row)
        
        logger.info(f"📋 スプレッドシートデータ準備完了: {len(spreadsheet_data['data'])-1}行（時刻順ソート済み）")
        return spreadsheet_data
    
    def _get_circled_number(self, number):
        """数字を丸囲み文字に変換"""
        # Unicode丸囲み数字（①②③...）
        circled_numbers = [
            '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
            '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳'
        ]
        
        if 1 <= number <= len(circled_numbers):
            return circled_numbers[number - 1]
        else:
            # 20を超える場合は普通の括弧数字
            return f'({number})'
    
    def send_to_spreadsheet(self, data):
        """スプレッドシートにデータ送信"""
        try:
            logger.info("📤 スプレッドシートにデータ送信中...")
            
            # Webhookの設定チェック
            if self.webhook_url == "YOUR_GOOGLE_SHEETS_WEBHOOK_URL_HERE":
                logger.warning("⚠️ Webhook URLが設定されていません。データをローカルに保存します。")
                self.save_data_locally(data)
                return
            
            # Google Sheets Webhookに送信
            response = requests.post(
                self.webhook_url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info("✅ スプレッドシート送信成功")
                logger.info(f"レスポンス: {response.text}")
            else:
                logger.error(f"❌ スプレッドシート送信失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                # バックアップとしてローカル保存
                self.save_data_locally(data)
                
        except Exception as e:
            logger.error(f"スプレッドシート送信エラー: {e}")
            # バックアップとしてローカル保存
            self.save_data_locally(data)
    
    def save_data_locally(self, data):
        """データをローカルファイルに保存（バックアップ）"""
        try:
            today = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # JSON形式で保存
            json_filename = backup_dir / f'fx_rates_backup_{today}.json'
            with open(json_filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # CSV形式でも保存
            csv_filename = backup_dir / f'fx_rates_backup_{today}.csv'
            df = pd.DataFrame(data['data'][1:], columns=data['data'][0])  # ヘッダーを除いてDataFrame作成
            df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
            
            logger.info(f"📁 バックアップファイル保存完了:")
            logger.info(f"  - JSON: {json_filename}")
            logger.info(f"  - CSV: {csv_filename}")
            
        except Exception as e:
            logger.error(f"ローカル保存エラー: {e}")
    
    def run(self):
        """メイン実行"""
        try:
            logger.info("=" * 80)
            logger.info("🎬 FXレート収集開始（OAuth2対応版）")
            logger.info("=" * 80)
            
            # 1. ファイル読み込み
            logger.info("📂 Step 1: ファイル読み込み")
            self.load_entrypoint_file()
            self.load_verification_file()
            
            # 2. レート収集
            logger.info("📈 Step 2: レート収集")
            self.collect_rates_for_entrypoints()
            self.collect_rates_for_verification()
            
            # 3. データ準備
            logger.info("📋 Step 3: スプレッドシートデータ準備")
            spreadsheet_data = self.prepare_spreadsheet_data()
            
            # 4. スプレッドシート送信
            logger.info("📤 Step 4: スプレッドシート送信")
            self.send_to_spreadsheet(spreadsheet_data)
            
            # 5. 完了レポート
            logger.info("=" * 80)
            logger.info("🎉 FXレート収集完了")
            logger.info(f"📊 収集データ統計:")
            logger.info(f"  - 総エントリーポイント数: {len(self.collected_rates)}")
            logger.info(f"  - 対象通貨ペア: {len(set([r['currency_pair'] for r in self.collected_rates]))}")
            logger.info(f"  - データソース数: {len(set([r['source'] for r in self.collected_rates]))}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ システムエラー: {e}")
            logger.exception("システムエラーの詳細:")
            raise

def main():
    """メイン関数"""
    try:
        collector = FXRateCollector()
        collector.run()
    except Exception as e:
        logger.error(f"実行エラー: {e}")
        return 1
    return 0

if __name__ == "__main__":
    exit(main())