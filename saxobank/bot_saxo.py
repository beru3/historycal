#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
bot_saxo.py (OAuth対応版) - サクソバンクAPI FX自動エントリーシステム
OAuth認証 + 自動トークン更新対応
step3のエントリーポイントに基づいて自動的にFX取引を実行
"""

import requests
import json
import pandas as pd
import os
import glob
import time
import threading
from datetime import datetime, timedelta
import logging
from pathlib import Path

# 自作モジュール
from oauth.oauth_auth import SaxoOAuthManager
from config import (
    get_oauth_config, get_api_endpoints, DEFAULT_TRADING_SETTINGS,
    LOG_SETTINGS, ENTRYPOINT_PATH, API_CALL_INTERVAL, REQUEST_TIMEOUT
)

# ログディレクトリの作成
script_dir = Path(__file__).parent
log_dir = script_dir / "log"
log_dir.mkdir(exist_ok=True)

# ロギング設定の強化
def setup_logging():
    """詳細ログ設定"""
    log_format = '%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_SETTINGS['level']))
    
    # 既存のハンドラーをクリア
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 詳細ログファイル（全レベル）
    detailed_handler = logging.FileHandler(
        log_dir / f'fx_auto_entry_detailed_{datetime.now().strftime("%Y%m%d")}.log',
        encoding='utf-8'
    )
    detailed_handler.setLevel(logging.DEBUG)
    detailed_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # エラーログファイル（エラーレベルのみ）
    error_handler = logging.FileHandler(
        log_dir / f'fx_auto_entry_errors_{datetime.now().strftime("%Y%m%d")}.log',
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(log_format, date_format))
    
    # 取引ログファイル（重要な取引情報のみ）
    trade_handler = logging.FileHandler(
        log_dir / f'fx_trades_{datetime.now().strftime("%Y%m%d")}.log',
        encoding='utf-8'
    )
    trade_handler.setLevel(logging.INFO)
    trade_filter = lambda record: 'TRADE' in record.getMessage()
    trade_handler.addFilter(trade_filter)
    trade_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', date_format))
    
    # コンソール出力（INFO以上）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s', 
        '%H:%M:%S'
    ))
    
    # ハンドラーを追加
    root_logger.addHandler(detailed_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(trade_handler)
    root_logger.addHandler(console_handler)
    
    return logging.getLogger(__name__)

# ログ設定を実行
logger = setup_logging()

class FXAutoEntrySystem:
    def __init__(self):
        """FX自動エントリーシステムの初期化（OAuth対応）"""
        logger.info("=" * 80)
        logger.info("🚀 FX自動エントリーシステム起動 (OAuth対応版)")
        logger.info("=" * 80)
        
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
        
        # トレーディング設定
        self.max_positions = DEFAULT_TRADING_SETTINGS['max_positions']
        self.risk_per_trade = DEFAULT_TRADING_SETTINGS['risk_per_trade']
        self.default_amount = DEFAULT_TRADING_SETTINGS['default_amount']
        self.leverage = DEFAULT_TRADING_SETTINGS['leverage']
        self.order_type = DEFAULT_TRADING_SETTINGS['order_type']
        
        # データ保存用
        self.account_key = None
        self.currency_uic_mapping = {}
        self.entry_points_df = None
        self.active_positions = []
        self.running = False
        
        # 統計情報
        self.stats = {
            'total_entries': 0,
            'total_exits': 0,
            'total_pips': 0.0,
            'session_start_time': datetime.now()
        }
        
        logger.debug("システム設定:")
        logger.debug(f"  - 環境: {oauth_config['environment']}")
        logger.debug(f"  - 最大ポジション数: {self.max_positions}")
        logger.debug(f"  - 1取引リスク: {self.risk_per_trade * 100}%")
        logger.debug(f"  - デフォルト取引量: {self.default_amount:,}通貨")
        logger.debug(f"  - レバレッジ: {self.leverage}倍")
        
        # 初期化
        self._initialize_system()
    
    def _initialize_system(self):
        """システム初期化（OAuth認証付き）"""
        logger.info("📋 システム初期化を開始します...")
        
        try:
            # 1. OAuth認証
            logger.debug("1/4: OAuth認証中...")
            if not self._authenticate():
                raise Exception("OAuth認証に失敗しました")
            
            # 2. アカウント情報取得
            logger.debug("2/4: アカウント情報取得中...")
            self._get_account_info()
            
            # 3. 通貨ペアUICマッピング作成
            logger.debug("3/4: 通貨ペアUICマッピング作成中...")
            self._create_currency_mapping()
            
            # 4. エントリーポイント読み込み
            logger.debug("4/4: エントリーポイント読み込み中...")
            self._load_entry_points()
            
            logger.info("✅ システム初期化完了")
            
            # 初期化完了の詳細情報
            logger.info(f"📊 システム状態:")
            logger.info(f"  - アカウントキー: {self.account_key}")
            logger.info(f"  - 対応通貨ペア数: {len(self.currency_uic_mapping)}")
            logger.info(f"  - エントリーポイント数: {len(self.entry_points_df) if self.entry_points_df is not None else 0}")
            
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
                # 自動更新開始
                self.oauth_manager.start_auto_refresh()
                return True
            
            # 対話的認証フロー
            if self.oauth_manager.authenticate_interactive():
                # 接続テスト
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
    
    def _get_account_info(self):
        """アカウント情報取得（OAuth対応）"""
        try:
            logger.debug("API呼び出し: /port/v1/accounts/me")
            headers = self._get_api_headers()
            if not headers:
                raise Exception("APIヘッダーが取得できません")
            
            response = requests.get(
                f"{self.api_base_url}/port/v1/accounts/me", 
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            
            logger.debug(f"アカウント情報レスポンス: {response.status_code}")
            
            if response.status_code == 200:
                accounts = response.json()
                logger.debug(f"アカウントデータ: {json.dumps(accounts, indent=2)}")
                
                if accounts.get('Data'):
                    self.account_key = accounts['Data'][0]['AccountKey']
                    account_currency = accounts['Data'][0].get('Currency', 'Unknown')
                    logger.info(f"✅ アカウント取得成功")
                    logger.info(f"  - アカウントキー: {self.account_key}")
                    logger.info(f"  - 基準通貨: {account_currency}")
                else:
                    raise Exception("アカウントデータが見つかりません")
            else:
                logger.error(f"アカウント取得失敗: {response.status_code}")
                logger.error(f"レスポンス: {response.text}")
                raise Exception(f"アカウント取得失敗: {response.status_code}")
                
        except Exception as e:
            logger.error(f"アカウント情報取得エラー: {e}")
            raise
    
    def _create_currency_mapping(self):
        """通貨ペアUICマッピング作成（OAuth対応）"""
        logger.info("🔍 通貨ペアUICマッピングを作成中...")
        
        from config import SUPPORTED_CURRENCY_PAIRS
        currency_pairs = SUPPORTED_CURRENCY_PAIRS
        
        successful_mappings = 0
        headers = self._get_api_headers()
        
        if not headers:
            raise Exception("APIヘッダーが取得できません")
        
        for currency_pair in currency_pairs:
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
                    logger.debug(f"{currency_pair}: データ {json.dumps(instruments, indent=2)}")
                    
                    if instruments.get('Data'):
                        # サクソバンクでは'Identifier'がUICに相当
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
                    logger.debug(f"  エラー詳細: {response.text}")
                
                # API制限対策
                time.sleep(API_CALL_INTERVAL)
                    
            except Exception as e:
                logger.error(f"  ❌ {currency_pair}: エラー {e}")
                logger.debug(f"  例外詳細:", exc_info=True)
        
        logger.info(f"✅ UICマッピング作成完了: {successful_mappings}/{len(currency_pairs)}通貨ペア")
        
        if successful_mappings == 0:
            logger.error("⚠️  通貨ペアマッピングが1つも作成されませんでした")
            raise Exception("通貨ペアマッピング作成に失敗しました")
    
    def _load_entry_points(self):
        """エントリーポイントファイル読み込み"""
        try:
            entry_dir = Path(ENTRYPOINT_PATH)
            
            logger.debug(f"エントリーポイントディレクトリ: {entry_dir}")
            
            if not entry_dir.exists():
                logger.error(f"エントリーポイントディレクトリが見つかりません: {entry_dir}")
                raise Exception(f"エントリーポイントディレクトリが見つかりません: {entry_dir}")
            
            files = list(entry_dir.glob("entrypoints_*.csv"))
            logger.debug(f"発見されたファイル: {[f.name for f in files]}")
            
            if not files:
                logger.error("エントリーポイントファイルが見つかりません")
                raise Exception("エントリーポイントファイルが見つかりません")
            
            latest_file = max(files, key=lambda x: x.name.split('_')[1].split('.')[0])
            logger.info(f"📁 使用ファイル: {latest_file.name}")
            
            # ファイル内容を詳細ログ
            logger.debug(f"ファイルパス: {latest_file}")
            logger.debug(f"ファイルサイズ: {latest_file.stat().st_size} bytes")
            
            self.entry_points_df = pd.read_csv(latest_file, encoding='utf-8-sig')
            
            # エントリーポイントの詳細分析
            total_entries = len(self.entry_points_df)
            currency_counts = self.entry_points_df['通貨ペア'].value_counts()
            direction_counts = self.entry_points_df['方向'].value_counts()
            time_range = f"{self.entry_points_df['Entry'].min()} - {self.entry_points_df['Entry'].max()}"
            
            logger.info(f"✅ エントリーポイント読み込み完了: {total_entries}件")
            logger.info(f"📊 通貨ペア別内訳:")
            for currency, count in currency_counts.items():
                logger.info(f"  - {currency}: {count}件")
            
            logger.info(f"📊 方向別内訳:")
            for direction, count in direction_counts.items():
                logger.info(f"  - {direction}: {count}件")
            
            logger.info(f"⏰ 時間範囲: {time_range}")
            
            # 最初の3件をサンプル表示
            logger.debug("エントリーポイントサンプル（最初の3件）:")
            for i, row in self.entry_points_df.head(3).iterrows():
                logger.debug(f"  {i+1}: {row['Entry']} {row['通貨ペア']} {row['方向']} (スコア: {row.get('実用スコア', 'N/A')})")
            
        except Exception as e:
            logger.error(f"エントリーポイント読み込みエラー: {e}")
            logger.exception("読み込みエラーの詳細:")
            raise
    
    def get_current_price(self, currency_pair):
        """現在価格取得（OAuth対応、JPYペアは小数点第3位、それ以外は第5位まで）"""
        try:
            logger.debug(f"価格取得開始: {currency_pair}")
            
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return None
            
            headers = self._get_api_headers()
            if not headers:
                logger.error("APIヘッダーが取得できません")
                return None
            
            params = {
                'Uic': str(uic),
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            
            logger.debug(f"価格取得APIパラメータ: {params}")
            
            response = requests.get(
                f"{self.api_base_url}/trade/v1/infoprices", 
                headers=headers, 
                params=params,
                timeout=REQUEST_TIMEOUT
            )
            
            logger.debug(f"価格取得レスポンス: {response.status_code}")
            
            if response.status_code == 200:
                prices = response.json()
                logger.debug(f"価格データ: {json.dumps(prices, indent=2)}")
                
                decimals = 3 if 'JPY' in currency_pair else 5  # JPYペアは3桁、それ以外は5桁
                
                # Dataキーがある場合（複数通貨ペア取得時）
                if prices.get('Data'):
                    quote = prices['Data'][0].get('Quote', {})
                    result = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread')
                    }
                # Dataキーがなく、直接Quoteがある場合（単一通貨ペア取得時）
                elif 'Quote' in prices:
                    quote = prices['Quote']
                    result = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread')
                    }
                else:
                    logger.error(f"価格データの構造が予期しない形式: {prices}")
                    return None
                
                logger.debug(f"{currency_pair} 価格取得成功: {result}")
                return result
            
            logger.error(f"価格取得失敗: {currency_pair} (ステータス: {response.status_code})")
            logger.error(f"レスポンス: {response.text}")
            return None
            
        except Exception as e:
            logger.error(f"価格取得エラー: {currency_pair} - {str(e)}")
            logger.exception("価格取得エラーの詳細:")
            return None
    
    def get_account_balance(self):
        """口座残高取得（OAuth対応）"""
        try:
            logger.debug("口座残高取得開始")
            
            headers = self._get_api_headers()
            if not headers:
                logger.error("APIヘッダーが取得できません")
                return DEFAULT_TRADING_SETTINGS['fallback_balance']  # ←修正
            
            response = requests.get(
                f"{self.api_base_url}/port/v1/balances/me", 
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            
            if response.status_code == 200:
                balances = response.json()
                
                if 'Data' in balances and balances['Data']:
                    balance = balances['Data'][0].get('NetPositionValue', DEFAULT_TRADING_SETTINGS['fallback_balance'])
                    logger.info(f"✅ 口座残高取得成功: {balance:,.0f}円")
                    return balance
                else:
                    logger.warning(f"残高データが見つからない。デフォルト値使用: {DEFAULT_TRADING_SETTINGS['fallback_balance']:,.0f}円")
                    return DEFAULT_TRADING_SETTINGS['fallback_balance']  # ←修正
            else:
                logger.warning(f"残高取得API失敗: {response.status_code}, デフォルト値使用: {DEFAULT_TRADING_SETTINGS['fallback_balance']:,.0f}円")
                return DEFAULT_TRADING_SETTINGS['fallback_balance']  # ←修正
                
        except Exception as e:
            logger.error(f"口座残高取得エラー: {e}")
            logger.error(f"デフォルト値使用: {DEFAULT_TRADING_SETTINGS['fallback_balance']:,.0f}円")
            return DEFAULT_TRADING_SETTINGS['fallback_balance']  # ←修正
        
    def calculate_position_size(self, currency_pair, entry_price, risk_amount):
        """
        口座残高×レバレッジ÷エントリー価格でロット数（通貨量）を算出
        端数切り捨て
        """
        try:
            logger.debug(f"ポジションサイズ計算開始: {currency_pair}")
            
            account_balance = self.get_account_balance()
            
            # ロット数（通貨量）をそのまま計算
            position_size = (account_balance * self.leverage) / entry_price
            # 通貨量は整数に（API仕様により必要ならintに）
            position_size = int(position_size)
            
            logger.info(f"💰 ポジションサイズ計算:")
            logger.info(f"  - 口座残高: {account_balance:,.2f}")
            logger.info(f"  - レバレッジ: {self.leverage}倍")
            logger.info(f"  - エントリー価格: {entry_price}")
            logger.info(f"  - 計算結果: {position_size:,}通貨")
            
            return position_size
            
        except Exception as e:
            logger.error(f"ポジションサイズ計算エラー: {e}")
            logger.exception("ポジションサイズ計算エラーの詳細:")
            return 100000  # エラー時は仮の値
    
    def place_order(self, currency_pair, direction, amount, order_type='Market'):
        """注文発注（OAuth対応）"""
        try:
            logger.info(f"📋 TRADE: 注文発注開始")
            logger.info(f"📋 TRADE:   通貨ペア: {currency_pair}")
            logger.info(f"📋 TRADE:   方向: {direction}")
            logger.info(f"📋 TRADE:   数量: {amount:,}通貨")
            logger.info(f"📋 TRADE:   注文タイプ: {order_type}")
            
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return False
            
            headers = self._get_api_headers()
            if not headers:
                logger.error("APIヘッダーが取得できません")
                return False
            
            buy_sell = 'Buy' if direction.upper() in ['LONG', 'BUY'] else 'Sell'
            
            order_data = {
                'AccountKey': self.account_key,
                'Uic': uic,
                'AssetType': 'FxSpot',
                'OrderType': order_type,
                'OrderDuration': {
                    'DurationType': 'DayOrder'
                },
                'Amount': amount,
                'BuySell': buy_sell
            }
            
            logger.debug(f"注文データ詳細: {json.dumps(order_data, indent=2)}")
            
            # 実際の注文はコメントアウト（安全のため）
            # response = requests.post(
            #     f"{self.api_base_url}/trade/v2/orders", 
            #     headers=headers, 
            #     json=order_data,
            #     timeout=REQUEST_TIMEOUT
            # )
            
            logger.info(f"✅ TRADE: [SIMULATION] 注文発注完了")
            logger.info(f"✅ TRADE:   {currency_pair} {direction} {amount:,}通貨")
            
            # 統計更新
            self.stats['total_entries'] += 1
            
            return True  # シミュレーション用
            
        except Exception as e:
            logger.error(f"注文発注エラー: {e}")
            logger.exception("注文発注エラーの詳細:")
            return False
    
    def check_entry_conditions(self):
        """エントリー条件チェック（00秒ちょうどの時刻で）"""
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # 00秒でない場合は秒部分を00に調整した時刻でチェック
        current_minute_time = datetime.now().strftime('%H:%M:00')
        
        logger.debug(f"エントリー条件チェック: 実際時刻={current_time}, チェック対象={current_minute_time}")
        
        try:
            # 00秒時刻と一致するエントリーポイントを検索
            matching_entries = self.entry_points_df[
                self.entry_points_df['Entry'] == current_minute_time
            ]
            
            if not matching_entries.empty:
                logger.info(f"🎯 エントリーポイント発見: {len(matching_entries)}件")
                logger.debug(f"発見されたエントリーポイント:")
                for i, entry in matching_entries.iterrows():
                    logger.debug(f"  - {entry['通貨ペア']} {entry['方向']} (スコア: {entry.get('実用スコア', 'N/A')})")
                
                for _, entry in matching_entries.iterrows():
                    self._process_entry_signal(entry)
            
            else:
                # 次のエントリーポイントまでの時間を表示
                self._show_next_entry_info()
                
        except Exception as e:
            logger.error(f"エントリー条件チェックエラー: {e}")
            logger.exception("エントリー条件チェックエラーの詳細:")
    
    def _process_entry_signal(self, entry):
        """エントリーシグナル処理"""
        currency_pair = entry['通貨ペア']
        direction = entry['方向']
        score = entry.get('実用スコア', 0)
        
        logger.info(f"📈 エントリーシグナル処理開始")
        logger.info(f"  通貨ペア: {currency_pair}")
        logger.info(f"  方向: {direction}")
        logger.info(f"  実用スコア: {score}")
        logger.info(f"  エグジット予定: {entry['Exit']}")
        
        # 最大ポジション数チェック
        if len(self.active_positions) >= self.max_positions:
            logger.warning("⚠️  最大ポジション数に達しているため、エントリーをスキップします")
            logger.warning(f"  現在のポジション数: {len(self.active_positions)}/{self.max_positions}")
            return
        
        # 現在価格取得
        logger.debug("現在価格取得開始...")
        current_price = self.get_current_price(currency_pair)
        if not current_price:
            logger.error("価格取得に失敗しました。エントリーをスキップします。")
            return
        
        logger.info(f"💹 現在価格: BID={current_price['bid']}, ASK={current_price['ask']}")
        if current_price.get('spread'):
            logger.info(f"  スプレッド: {current_price['spread']}")
        
        # ポジションサイズ計算
        entry_price = current_price['ask'] if direction.upper() == 'LONG' else current_price['bid']
        position_size = self.calculate_position_size(currency_pair, entry_price, None)
        
        # 注文発注
        if self.place_order(currency_pair, direction, position_size):
            # アクティブポジションに追加
            position_info = {
                'currency_pair': currency_pair,
                'direction': direction,
                'entry_time': datetime.now(),
                'exit_time': entry['Exit'],
                'amount': position_size,
                'score': score,
                'entry_price': entry_price,
                'entry_id': f"{currency_pair}_{direction}_{datetime.now().strftime('%H%M%S')}"
            }
            self.active_positions.append(position_info)
            
            logger.info(f"✅ ポジション追加完了")
            logger.info(f"  エントリーID: {position_info['entry_id']}")
            logger.info(f"  アクティブポジション数: {len(self.active_positions)}/{self.max_positions}")
            
            # TRADE ログ
            logger.info(f"📋 TRADE: ポジション開始 - {position_info['entry_id']}")
    
    def _show_next_entry_info(self):
        """次のエントリーポイント情報表示"""
        try:
            current_time_obj = datetime.strptime(datetime.now().strftime('%H:%M:00'), '%H:%M:%S').time()
            
            # 現在時刻以降のエントリーポイントを取得
            all_times = pd.to_datetime(self.entry_points_df['Entry'], format='%H:%M:%S').dt.time
            future_entries = self.entry_points_df[all_times > current_time_obj]
            
            if not future_entries.empty:
                next_entry = future_entries.iloc[0]
                next_time = datetime.strptime(next_entry['Entry'], '%H:%M:%S')
                current_datetime = datetime.strptime(datetime.now().strftime('%H:%M:00'), '%H:%M:%S')
                time_diff = next_time - current_datetime
                
                logger.debug(f"📅 次のエントリー: {next_entry['Entry']} ({next_entry['通貨ペア']} {next_entry['方向']}) - あと{time_diff}")
            else:
                logger.debug("📅 本日のエントリーポイントは終了しました")
                
        except Exception as e:
            logger.error(f"次のエントリー情報取得エラー: {e}")
            logger.debug("次のエントリー情報エラー詳細:", exc_info=True)
    
    def check_exit_conditions(self):
        """エグジット条件チェック"""
        current_time = datetime.now().strftime('%H:%M:00')  # 00秒に調整
        
        exit_positions = []
        
        for i, position in enumerate(self.active_positions[:]):
            if position['exit_time'] == current_time:
                exit_positions.append(position)
        
        if exit_positions:
            logger.info(f"🔚 エグジット時刻到達: {len(exit_positions)}ポジション")
            
            for position in exit_positions:
                self._process_exit_signal(position)
    
    def _process_exit_signal(self, position):
        """エグジットシグナル処理"""
        logger.info(f"🔚 エグジット処理開始: {position['entry_id']}")
        logger.info(f"  通貨ペア: {position['currency_pair']}")
        logger.info(f"  方向: {position['direction']}")
        logger.info(f"  保有期間: {datetime.now() - position['entry_time']}")
        
        # 現在価格取得
        current_price = self.get_current_price(position['currency_pair'])
        if not current_price:
            logger.error("エグジット時の価格取得に失敗しました")
            return

        # 損益計算（pips）
        entry_price = position['entry_price']
        exit_price = current_price['bid'] if position['direction'].upper() == 'LONG' else current_price['ask']
        
        if 'JPY' in position['currency_pair']:
            pips = (exit_price - entry_price) * 100 if position['direction'].upper() == 'LONG' else (entry_price - exit_price) * 100
        else:
            pips = (exit_price - entry_price) * 10000 if position['direction'].upper() == 'LONG' else (entry_price - exit_price) * 10000

        logger.info(f"💹 損益計算:")
        logger.info(f"  エントリー価格: {entry_price}")
        logger.info(f"  エグジット価格: {exit_price}")
        logger.info(f"  損益: {pips:.1f} pips")
        
        # 実際の環境では決済注文を発注
        logger.info(f"✅ TRADE: [SIMULATION] ポジション決済完了")
        logger.info(f"✅ TRADE:   {position['currency_pair']} {position['direction']}")
        logger.info(f"✅ TRADE:   損益: {pips:.1f} pips")
        
        # ポジションをアクティブリストから削除
        self.active_positions.remove(position)
        
        # 統計更新
        self.stats['total_exits'] += 1
        self.stats['total_pips'] += pips
        
        logger.info(f"📊 ポジション削除完了")
        logger.info(f"  アクティブポジション数: {len(self.active_positions)}")
        logger.info(f"  セッション累計pips: {self.stats['total_pips']:.1f}")
        
        # TRADE ログ
        logger.info(f"📋 TRADE: ポジション終了 - {position['entry_id']} ({pips:.1f} pips)")
    
    def monitor_positions(self):
        """ポジション監視"""
        if self.active_positions:
            logger.debug(f"📊 アクティブポジション監視: {len(self.active_positions)}件")
            
            for position in self.active_positions:
                holding_time = datetime.now() - position['entry_time']
                logger.debug(f"  - {position['entry_id']}: {position['currency_pair']} {position['direction']} "
                           f"(保有時間: {holding_time}, エグジット予定: {position['exit_time']})")
        else:
            logger.debug("📊 アクティブポジション: なし")
    
    def _log_session_stats(self):
        """セッション統計ログ"""
        session_duration = datetime.now() - self.stats['session_start_time']
        
        logger.info("📊 セッション統計:")
        logger.info(f"  - 開始時刻: {self.stats['session_start_time'].strftime('%H:%M:%S')}")
        logger.info(f"  - 稼働時間: {session_duration}")
        logger.info(f"  - 総エントリー数: {self.stats['total_entries']}")
        logger.info(f"  - 総エグジット数: {self.stats['total_exits']}")
        logger.info(f"  - 累計pips: {self.stats['total_pips']:.1f}")
        logger.info(f"  - アクティブポジション: {len(self.active_positions)}")
        
        if self.stats['total_exits'] > 0:
            avg_pips = self.stats['total_pips'] / self.stats['total_exits']
            logger.info(f"  - 平均pips/取引: {avg_pips:.1f}")
    
    def run_single_check(self):
        """1回のチェック実行"""
        try:
            logger.debug("=" * 60)
            logger.debug("🔄 定期チェック実行開始")
            
            # OAuth トークン有効性チェック
            if not self.oauth_manager.is_token_valid():
                logger.warning("⚠️ トークンが期限切れです。自動更新を待機中...")
                return
            
            # エントリー条件チェック
            logger.debug("1/3: エントリー条件チェック...")
            self.check_entry_conditions()
            
            # エグジット条件チェック
            logger.debug("2/3: エグジット条件チェック...")
            self.check_exit_conditions()
            
            # ポジション監視
            logger.debug("3/3: ポジション監視...")
            self.monitor_positions()
            
            # 10分ごとにセッション統計表示
            if datetime.now().minute % 10 == 0:
                self._log_session_stats()
            
            logger.debug("🔄 定期チェック完了")
            
        except Exception as e:
            logger.error(f"定期チェックエラー: {e}")
            logger.exception("定期チェックエラーの詳細:")
    
    def wait_for_next_minute(self):
        """次の分の00秒まで待機"""
        now = datetime.now()
        
        # 次の分の00秒を計算
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        
        # 待機時間を計算
        wait_time = (next_minute - now).total_seconds()
        
        logger.debug(f"⏰ 次のチェックまで待機: {wait_time:.1f}秒 (次回実行: {next_minute.strftime('%H:%M:%S')})")
        
        return wait_time
    
    def start_monitoring(self):
        """監視開始（00秒ちょうどに同期、OAuth対応）"""
        logger.info("🚀 FX自動エントリーシステム監視開始 (OAuth対応)")
        logger.info(f"📁 エントリーポイント数: {len(self.entry_points_df)}")
        logger.info(f"🔧 対応通貨ペア: {list(self.currency_uic_mapping.keys())}")
        logger.info("⏰ 毎分00秒にエントリー・エグジットチェックを実行")
        logger.info(f"📂 ログ保存先: {log_dir}")
        logger.info(f"🔐 OAuth自動更新: 有効")
        
        self.running = True
        
        # システム状態の詳細ログ
        logger.debug("システム状態詳細:")
        logger.debug(f"  - APIベースURL: {self.api_base_url}")
        logger.debug(f"  - アカウントキー: {self.account_key}")
        logger.debug(f"  - 最大ポジション数: {self.max_positions}")
        logger.debug(f"  - リスク/取引: {self.risk_per_trade * 100}%")
        logger.debug(f"  - レバレッジ: {self.leverage}倍")
        
        # 最初の1回を即座に実行
        logger.info("🔄 初回チェック実行...")
        self.run_single_check()
        
        try:
            while self.running:
                # 次の分の00秒まで待機
                wait_time = self.wait_for_next_minute()
                
                # 停止フラグをチェックしながら待機
                start_time = time.time()
                while time.time() - start_time < wait_time and self.running:
                    time.sleep(0.1)  # 100ms間隔でチェック
                
                # 停止された場合は終了
                if not self.running:
                    break
                
                # 00秒ちょうどでチェック実行
                self.run_single_check()
                
        except KeyboardInterrupt:
            logger.info("👋 システム停止（Ctrl+C）")
            self.running = False
        except Exception as e:
            logger.error(f"監視エラー: {e}")
            logger.exception("監視エラーの詳細:")
            self.running = False
        finally:
            # OAuth自動更新停止
            self.oauth_manager.stop_auto_refresh()
            
            # 終了時の統計表示
            logger.info("🏁 システム終了")
            self._log_session_stats()
            
            # アクティブポジションがある場合の警告
            if self.active_positions:
                logger.warning(f"⚠️  システム終了時にアクティブポジションが残っています: {len(self.active_positions)}件")
                for position in self.active_positions:
                    logger.warning(f"  - {position['entry_id']}: {position['currency_pair']} {position['direction']}")

def main():
    """メイン実行関数"""
    try:
        logger.info("🎬 FX自動エントリーシステム開始 (OAuth対応版)")
        logger.info(f"📁 ログディレクトリ: {log_dir}")
        
        # 設定検証
        from config import validate_config
        config_errors = validate_config()
        if config_errors:
            logger.error("❌ 設定エラーが検出されました:")
            for error in config_errors:
                logger.error(f"  - {error}")
            logger.error("config.py を確認してください")
            return 1
        
        # システム初期化
        fx_system = FXAutoEntrySystem()
        
        # 監視開始
        fx_system.start_monitoring()
        
        return 0
        
    except Exception as e:
        logger.error(f"システムエラー: {e}")
        logger.exception("システムエラーの詳細:")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())