#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_rate_collector_new.py - FXエントリーポイントレート収集・スプレッドシート送信システム
要件に基づく新規作成版
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

# OAuth認証モジュールを使用
from oauth.oauth_auth import SaxoOAuthManager
from config import (
    get_oauth_config, get_api_endpoints, 
    SPREADSHEET_WEBHOOK_URL,
    SUPPORTED_CURRENCY_PAIRS, API_CALL_INTERVAL, REQUEST_TIMEOUT
)

# ログ設定
script_dir = Path(__file__).parent
log_dir = script_dir / "log"
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

class FXRateCollector:
    def __init__(self):
        """FXレート収集システムの初期化"""
        logger.info("🚀 FXレート収集システム開始")
        
        # OAuth設定取得
        oauth_config = get_oauth_config()
        api_endpoints = get_api_endpoints()
        
        # OAuth認証管理インスタンス作成
        self.oauth_manager = SaxoOAuthManager(
            client_id=oauth_config['client_id'],
            client_secret=oauth_config['client_secret'],
            redirect_uri=oauth_config['redirect_uri'],
            environment=oauth_config['environment']
        )
        
        self.api_base_url = api_endpoints['api_base_url']
        
        # パス設定（要件に基づく）
        self.entrypoint_path = r"C:\Users\beru\Dropbox\006_TRADE\historycal\entrypoint_fx"
        self.verification_path = r"C:\Users\beru\Downloads"
        self.webhook_url = SPREADSHEET_WEBHOOK_URL
        
        # 通貨ペアマッピング（動的に取得）
        self.currency_uic_mapping = {}
        
        # データ保存用
        self.entrypoints_df = None
        self.verification_data = {}
        self.collected_rates = []
        
        # テスト用設定
        self.test_mode = False  # 実際のAPI呼び出しを行う
        
        # 初期化
        self._initialize_system()
    
    def _initialize_system(self):
        """システム初期化"""
        logger.info("📋 システム初期化を開始します...")
        
        try:
            if not self.test_mode:
                # 1. OAuth認証
                logger.debug("1/4: OAuth認証中...")
                if not self._authenticate():
                    raise Exception("OAuth認証に失敗しました")
                
                # 2. 通貨ペアUICマッピング作成
                logger.debug("2/4: 通貨ペアUICマッピング作成中...")
                self._create_currency_mapping()
            else:
                logger.info("🧪 テストモードで実行します")
                self._setup_test_currency_mapping()
            
            # 3. ファイル存在確認
            logger.debug("3/4: ファイル存在確認中...")
            self._validate_file_paths()
            
            logger.info("✅ システム初期化完了")
            
        except Exception as e:
            logger.error(f"❌ システム初期化エラー: {e}")
            logger.exception("初期化エラーの詳細:")
            raise
    
    def _authenticate(self):
        """OAuth認証実行"""
        try:
            logger.info("🔐 OAuth認証開始")
            
            # 既存トークンの確認
            if self.oauth_manager.load_tokens() and self.oauth_manager.is_token_valid():
                logger.info("✅ 有効な既存トークンを使用")
                self.oauth_manager.start_auto_refresh()
                return True
            
            # 対話的認証フロー
            if self.oauth_manager.authenticate_interactive():
                if self.oauth_manager.test_connection():
                    logger.info("✅ OAuth認証・接続テスト完了")
                    return True
                else:
                    logger.error("❌ API接続テストに失敗")
                    return False
            else:
                logger.error("❌ OAuth認証に失敗")
                return False
                
        except Exception as e:
            logger.error(f"OAuth認証エラー: {e}")
            logger.exception("OAuth認証エラーの詳細:")
            return False
    
    def _get_api_headers(self):
        """API呼び出し用ヘッダーを取得"""
        headers = self.oauth_manager.get_api_headers()
        if not headers:
            logger.error("有効なAPIヘッダーが取得できません")
            return None
        return headers
    
    def _create_currency_mapping(self):
        """通貨ペアUICマッピング作成"""
        logger.info("🔍 通貨ペアUICマッピングを作成中...")
        
        successful_mappings = 0
        headers = self._get_api_headers()
        
        if not headers:
            raise Exception("APIヘッダーが取得できません")
        
        for currency_pair in SUPPORTED_CURRENCY_PAIRS:
            try:
                logger.debug(f"通貨ペア検索開始: {currency_pair}")
                
                params = {
                    'Keywords': currency_pair,
                    'AssetTypes': 'FxSpot',
                    'limit': 1
                }
                
                response = requests.get(
                    f"{self.api_base_url}/ref/v1/instruments", 
                    headers=headers, 
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )
                
                logger.debug(f"{currency_pair}: API応答 {response.status_code}")
                
                if response.status_code == 200:
                    instruments = response.json()
                    
                    if instruments.get('Data'):
                        uic = instruments['Data'][0]['Identifier']
                        symbol = instruments['Data'][0].get('Symbol', currency_pair)
                        description = instruments['Data'][0].get('Description', '')
                        
                        self.currency_uic_mapping[currency_pair] = uic
                        successful_mappings += 1
                        
                        logger.info(f"  ✅ {currency_pair}: UIC {uic} ({description})")
                    else:
                        logger.warning(f"  ❌ {currency_pair}: 検索結果が見つかりませんでした")
                else:
                    logger.warning(f"  ❌ {currency_pair}: API エラー {response.status_code}")
                
                # API制限対策
                time.sleep(API_CALL_INTERVAL)
                    
            except Exception as e:
                logger.error(f"  ❌ {currency_pair}: エラー {e}")
        
        logger.info(f"✅ UICマッピング作成完了: {successful_mappings}/{len(SUPPORTED_CURRENCY_PAIRS)}通貨ペア")
        
        if successful_mappings == 0:
            logger.error("⚠️  通貨ペアマッピングが1つも作成されませんでした")
            raise Exception("通貨ペアマッピング作成に失敗しました")
    
    def _setup_test_currency_mapping(self):
        """テスト用通貨ペアマッピング設定"""
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
        logger.info(f"🧪 テスト用UICマッピング設定完了: {len(self.currency_uic_mapping)}通貨ペア")
    
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
        """検証ファイル読み込み - 要件に基づく8つのセクション"""
        try:
            file_path = self.find_latest_verification_file()
            
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
            
            logger.debug(f"検証ファイル総行数: {len(lines)}")
            
            # 要件に基づく8つのセクション
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
        """現在価格取得"""
        try:
            # テストモードの場合はダミーデータを返す
            if self.test_mode:
                return self._get_test_price(currency_pair)
            
            headers = self._get_api_headers()
            if not headers:
                logger.error("APIヘッダーが取得できません")
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
                f"{self.api_base_url}/trade/v1/infoprices", 
                headers=headers, 
                params=params,
                timeout=REQUEST_TIMEOUT
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
                time.sleep(1)
                headers = self._get_api_headers()
                if headers:
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
        
        decimals = 3 if 'JPY' in currency_pair else 5
        
        spread_pips = random.uniform(0.5, 3.0)
        if 'JPY' in currency_pair:
            spread = spread_pips * 0.01
        else:
            spread = spread_pips * 0.0001
        
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
            time.sleep(0.2)
            
            # エグジット価格取得
            exit_price_data = self.get_current_price(currency_pair)
            
            if entry_price_data and exit_price_data:
                # エントリー価格とエグジット価格を決定
                if direction.upper() in ['LONG', 'BUY']:
                    entry_price = entry_price_data['ask']
                    exit_price = exit_price_data['bid']
                else:
                    entry_price = entry_price_data['bid']
                    exit_price = exit_price_data['ask']
                
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
            
            time.sleep(0.5)
    
    def collect_rates_for_verification(self):
        """検証データのレート収集 - 要件に基づく8つのセクション"""
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
                time.sleep(0.2)
                
                # エグジット価格取得
                exit_price_data = self.get_current_price(currency_pair)
                
                if entry_price_data and exit_price_data:
                    if direction.upper() in ['LONG', 'BUY']:
                        entry_price = entry_price_data['ask']
                        exit_price = exit_price_data['bid']
                    else:
                        entry_price = entry_price_data['bid']
                        exit_price = exit_price_data['ask']
                    
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
                
                time.sleep(0.5)
    
    def calculate_pips_difference(self, currency_pair, entry_price, exit_price, direction):
        """pips差を計算"""
        try:
            if 'JPY' in currency_pair:
                pip_factor = 100
            else:
                pip_factor = 10000
            
            if direction.upper() in ['LONG', 'BUY']:
                pips_diff = (exit_price - entry_price) * pip_factor
            else:
                pips_diff = (entry_price - exit_price) * pip_factor
            
            return round(pips_diff, 1)
            
        except Exception as e:
            logger.error(f"pips差計算エラー: {e}")
            return 0.0
    
    def prepare_spreadsheet_data(self):
        """スプレッドシート送信データ準備 - 1日1シート形式"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # データをセクション別に整理してソース名に番号を付ける
        source_counters = {}
        
        for rate in self.collected_rates:
            source = rate['source']
            if source not in source_counters:
                source_counters[source] = 0
            source_counters[source] += 1
            
            circled_number = self._get_circled_number(source_counters[source])
            rate['numbered_source'] = f"{source}{circled_number}"
        
        # エントリー時刻で昇順ソート
        self.collected_rates.sort(key=lambda x: x['entry_time'])
        
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
        
        # データ行を追加
        for index, rate in enumerate(self.collected_rates, 1):
            row = [
                index,
                rate['numbered_source'],
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
        circled_numbers = [
            '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
            '⑪', '⑫', '⑬', '⑭', '⑮', '⑯', '⑰', '⑱', '⑲', '⑳'
        ]
        
        if 1 <= number <= len(circled_numbers):
            return circled_numbers[number - 1]
        else:
            return f'({number})'
    
    def send_to_spreadsheet(self, data):
        """スプレッドシートにデータ送信"""
        try:
            logger.info("📤 スプレッドシートにデータ送信中...")
            
            # Webhookの設定チェック
            if not self.webhook_url or self.webhook_url == "YOUR_GOOGLE_SHEETS_WEBHOOK_URL_HERE":
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
            if len(data['data']) > 1:  # ヘッダー + データ行があるかチェック
                df = pd.DataFrame(data['data'][1:], columns=data['data'][0])
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
            logger.info("🎬 FXレート収集開始（要件対応版）")
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
            
            # セクション別統計
            logger.info("📊 セクション別統計:")
            section_stats = {}
            for rate in self.collected_rates:
                source = rate['source']
                if source not in section_stats:
                    section_stats[source] = 0
                section_stats[source] += 1
            
            for section, count in section_stats.items():
                logger.info(f"  - {section}: {count}件")
            
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ システムエラー: {e}")
            logger.exception("システムエラーの詳細:")
            raise
        finally:
            # OAuth自動更新停止
            if hasattr(self, 'oauth_manager') and self.oauth_manager:
                self.oauth_manager.stop_auto_refresh()

def main():
    """メイン関数"""
    try:
        # 設定検証
        from config import validate_config
        config_errors = validate_config()
        if config_errors:
            logger.error("❌ 設定エラーが検出されました:")
            for error in config_errors:
                logger.error(f"  - {error}")
            logger.error("config.py を確認してください")
            return 1
        
        collector = FXRateCollector()
        collector.run()
        return 0
    except Exception as e:
        logger.error(f"実行エラー: {e}")
        logger.exception("実行エラーの詳細:")
        return 1

if __name__ == "__main__":
    exit(main())