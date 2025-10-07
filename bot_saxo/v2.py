#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_auto_entry_with_gradient_monitoring.py - サクソバンクAPI FX自動エントリーシステム (勾配監視版)
step3のエントリーポイントに基づいて自動的にFX取引を実行
エントリー後は5秒間隔で勾配パラメータを監視し、早期エグジット判定を実行
"""

import requests
import json
import pandas as pd
import numpy as np
import os
import glob
import time
import threading
from datetime import datetime, timedelta
import logging
from config import TEST_TOKEN_24H, BASE_URL

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fx_auto_entry_gradient.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class GradientCalculator:
    """勾配パラメータ計算クラス"""
    
    def __init__(self):
        self.price_history = {}  # 通貨ペア別の価格履歴
        
    def add_price_data(self, currency_pair, timestamp, bid, ask):
        """価格データを履歴に追加"""
        if currency_pair not in self.price_history:
            self.price_history[currency_pair] = []
        
        # 中間価格を計算
        mid_price = (bid + ask) / 2
        
        self.price_history[currency_pair].append({
            'timestamp': timestamp,
            'bid': bid,
            'ask': ask,
            'mid': mid_price
        })
        
        # 履歴を最新100件に制限（約8分間の履歴）
        if len(self.price_history[currency_pair]) > 100:
            self.price_history[currency_pair] = self.price_history[currency_pair][-100:]
    
    def calculate_macd_gradient(self, currency_pair, timeframe_minutes=1):
        """MACD勾配計算（簡易版）"""
        try:
            if currency_pair not in self.price_history:
                return 0
            
            history = self.price_history[currency_pair]
            if len(history) < 26:  # MACD計算に最低必要な期間
                return 0
            
            # 価格データをPandasシリーズに変換
            prices = pd.Series([item['mid'] for item in history])
            
            # EMA計算
            ema_12 = prices.ewm(span=12, adjust=False).mean()
            ema_26 = prices.ewm(span=26, adjust=False).mean()
            
            # MACDライン計算
            macd_line = ema_12 - ema_26
            
            # 勾配計算（最新値と5期間前の差分）
            if len(macd_line) >= 6:
                current_macd = macd_line.iloc[-1]
                past_macd = macd_line.iloc[-6]
                
                if past_macd != 0:
                    gradient = ((current_macd - past_macd) / abs(past_macd)) * 100
                    # -100% ~ +100% の範囲にクリップ
                    gradient = max(-100, min(100, gradient))
                    return gradient
            
            return 0
            
        except Exception as e:
            logger.error(f"MACD勾配計算エラー: {e}")
            return 0
    
    def calculate_ma_gradient(self, currency_pair, period=20):
        """移動平均勾配計算"""
        try:
            if currency_pair not in self.price_history:
                return 0
            
            history = self.price_history[currency_pair]
            if len(history) < period + 5:
                return 0
            
            # 価格データをPandasシリーズに変換
            prices = pd.Series([item['mid'] for item in history])
            
            # 移動平均計算
            ma = prices.rolling(window=period).mean()
            
            # 勾配計算
            if len(ma) >= 6:
                current_ma = ma.iloc[-1]
                past_ma = ma.iloc[-6]
                
                if past_ma != 0:
                    gradient = ((current_ma - past_ma) / past_ma) * 100
                    gradient = max(-100, min(100, gradient))
                    return gradient
            
            return 0
            
        except Exception as e:
            logger.error(f"MA勾配計算エラー: {e}")
            return 0
    
    def calculate_atr_gradient(self, currency_pair, period=14):
        """ATR勾配計算"""
        try:
            if currency_pair not in self.price_history:
                return 0
            
            history = self.price_history[currency_pair]
            if len(history) < period + 5:
                return 0
            
            # True Range計算用のデータ準備
            high_prices = [item['ask'] for item in history]  # ASKを高値として使用
            low_prices = [item['bid'] for item in history]   # BIDを安値として使用
            close_prices = [item['mid'] for item in history]
            
            df = pd.DataFrame({
                'high': high_prices,
                'low': low_prices,
                'close': close_prices
            })
            
            # True Range計算
            df['prev_close'] = df['close'].shift(1)
            df['tr1'] = df['high'] - df['low']
            df['tr2'] = abs(df['high'] - df['prev_close'])
            df['tr3'] = abs(df['low'] - df['prev_close'])
            
            df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            
            # ATR計算
            atr = df['true_range'].rolling(window=period).mean()
            
            # 勾配計算
            if len(atr) >= 6:
                current_atr = atr.iloc[-1]
                past_atr = atr.iloc[-6]
                
                if past_atr != 0:
                    gradient = ((current_atr - past_atr) / past_atr) * 100
                    gradient = max(-100, min(100, gradient))
                    return gradient
            
            return 0
            
        except Exception as e:
            logger.error(f"ATR勾配計算エラー: {e}")
            return 0
    
    def get_gradient_pattern(self, currency_pair):
        """4時間軸勾配パターンを取得"""
        # 実際の実装では1分足、5分足、15分足、1時間足の勾配を計算
        # ここでは簡易版として1つの時間軸で4つの指標を計算
        
        macd_gradient = self.calculate_macd_gradient(currency_pair)
        ma_gradient = self.calculate_ma_gradient(currency_pair, 20)
        atr_gradient = self.calculate_atr_gradient(currency_pair)
        
        # 4つ目の指標として短期移動平均の勾配
        ma_short_gradient = self.calculate_ma_gradient(currency_pair, 5)
        
        return [macd_gradient, ma_gradient, atr_gradient, ma_short_gradient]

class FXAutoEntrySystem:
    def __init__(self):
        """FX自動エントリーシステムの初期化"""
        self.base_url = BASE_URL
        self.token = TEST_TOKEN_24H
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        
        # 設定
        self.default_amount = 10000  # デフォルト取引単位（10,000通貨）
        self.max_positions = 5       # 最大同時ポジション数
        self.risk_per_trade = 0.02   # 1回の取引リスク（口座資金の2%）
        
        # 勾配監視設定
        self.gradient_check_interval = 5  # 5秒間隔
        self.early_exit_threshold = -75   # 早期エグジット閾値
        
        # データ保存用
        self.account_key = None
        self.currency_uic_mapping = {}
        self.entry_points_df = None
        self.active_positions = []
        self.running = False
        
        # 勾配計算器
        self.gradient_calculator = GradientCalculator()
        
        # 勾配監視スレッド
        self.gradient_monitoring_thread = None
        self.gradient_monitoring_running = False
        
        # 初期化
        self._initialize_system()
    
    def _initialize_system(self):
        """システム初期化"""
        logger.info("=== FX自動エントリーシステム初期化開始 ===")
        
        try:
            # アカウント情報取得
            self._get_account_info()
            
            # 通貨ペアUICマッピング作成
            self._create_currency_mapping()
            
            # エントリーポイント読み込み
            self._load_entry_points()
            
            logger.info("✅ システム初期化完了")
            
        except Exception as e:
            logger.error(f"❌ システム初期化エラー: {e}")
            raise
    
    def _get_account_info(self):
        """アカウント情報取得"""
        try:
            response = requests.get(f"{self.base_url}/port/v1/accounts/me", headers=self.headers)
            
            if response.status_code == 200:
                accounts = response.json()
                if accounts.get('Data'):
                    self.account_key = accounts['Data'][0]['AccountKey']
                    logger.info(f"✅ アカウント取得成功: {self.account_key}")
                else:
                    raise Exception("アカウントデータが見つかりません")
            else:
                raise Exception(f"アカウント取得失敗: {response.status_code}")
                
        except Exception as e:
            logger.error(f"アカウント情報取得エラー: {e}")
            raise
    
    def _create_currency_mapping(self):
        """通貨ペアUICマッピング作成"""
        logger.info("通貨ペアUICマッピングを作成中...")
        
        currency_pairs = ['USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY', 'CHFJPY', 'EURUSD', 'GBPUSD', 'AUDUSD']
        
        for currency_pair in currency_pairs:
            try:
                params = {
                    'Keywords': currency_pair,
                    'AssetTypes': 'FxSpot',
                    'limit': 1
                }
                response = requests.get(f"{self.base_url}/ref/v1/instruments", headers=self.headers, params=params)
                
                if response.status_code == 200:
                    instruments = response.json()
                    if instruments.get('Data'):
                        uic = instruments['Data'][0]['Identifier']
                        self.currency_uic_mapping[currency_pair] = uic
                        logger.info(f"   {currency_pair}: UIC {uic}")
                    else:
                        logger.warning(f"   {currency_pair}: 見つかりませんでした")
                else:
                    logger.warning(f"   {currency_pair}: API エラー {response.status_code}")
                    
            except Exception as e:
                logger.error(f"   {currency_pair}: エラー {e}")
        
        logger.info(f"✅ UICマッピング作成完了: {len(self.currency_uic_mapping)}通貨ペア")
    
    def _load_entry_points(self):
        """エントリーポイントファイル読み込み"""
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            entry_dir = os.path.join(os.path.dirname(base_dir), "entrypoint_fx")
            
            if not os.path.exists(entry_dir):
                raise Exception(f"エントリーポイントディレクトリが見つかりません: {entry_dir}")
            
            files = glob.glob(os.path.join(entry_dir, "entrypoints_*.csv"))
            
            if not files:
                raise Exception("エントリーポイントファイルが見つかりません")
            
            latest_file = max(files, key=lambda x: os.path.basename(x).split('_')[1].split('.')[0])
            
            self.entry_points_df = pd.read_csv(latest_file, encoding='utf-8-sig')
            logger.info(f"✅ エントリーポイント読み込み: {len(self.entry_points_df)}件")
            
        except Exception as e:
            logger.error(f"エントリーポイント読み込みエラー: {e}")
            raise
    
    def get_current_price(self, currency_pair):
        """現在価格取得（JPYペアは小数点第3位、それ以外は第5位まで）"""
        try:
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return None
            
            params = {
                'Uic': str(uic),
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            response = requests.get(f"{self.base_url}/trade/v1/infoprices", headers=self.headers, params=params)
            
            if response.status_code == 200:
                prices = response.json()
                decimals = 3 if 'JPY' in currency_pair else 5
                
                if prices.get('Data'):
                    quote = prices['Data'][0].get('Quote', {})
                    price_data = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread')
                    }
                elif 'Quote' in prices:
                    quote = prices['Quote']
                    price_data = {
                        'bid': round(quote.get('Bid', 0), decimals),
                        'ask': round(quote.get('Ask', 0), decimals),
                        'spread': quote.get('Spread')
                    }
                else:
                    return None
                
                # 勾配計算用に価格履歴に追加
                self.gradient_calculator.add_price_data(
                    currency_pair, 
                    datetime.now(), 
                    price_data['bid'], 
                    price_data['ask']
                )
                
                return price_data
            
            logger.error(f"価格取得失敗: {currency_pair} (ステータス: {response.status_code})")
            return None
            
        except Exception as e:
            logger.error(f"価格取得エラー: {currency_pair} - {str(e)}")
            return None
    
    def get_account_balance(self):
        """口座残高取得"""
        try:
            response = requests.get(f"{self.base_url}/port/v1/balances/me", headers=self.headers)
            
            if response.status_code == 200:
                balances = response.json()
                if 'Data' in balances and balances['Data']:
                    return balances['Data'][0].get('NetPositionValue', 900000)
            return 900000
        except Exception as e:
            logger.error(f"口座残高取得エラー: {e}")
            return 900000

    def calculate_position_size(self, currency_pair, entry_price, risk_amount):
        """ポジションサイズ計算"""
        try:
            account_balance = self.get_account_balance()
            leverage = 20
            position_size = (account_balance * leverage) / entry_price
            position_size = int(position_size)
            logger.info(f"計算ロット数: {position_size}通貨 (残高={account_balance}, レバ={leverage}, 価格={entry_price})")
            return position_size
        except Exception as e:
            logger.error(f"ポジションサイズ計算エラー: {e}")
            return 100000
            
    def place_order(self, currency_pair, direction, amount, order_type='Market'):
        """注文発注"""
        try:
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return False
            
            buy_sell = 'Buy' if direction.upper() in ['LONG', 'BUY'] else 'Sell'
            
            logger.info(f"✅ [SIMULATION] 注文発注: {currency_pair} {direction} {amount:,}通貨")
            
            return True
            
        except Exception as e:
            logger.error(f"注文発注エラー: {e}")
            return False
    
    def calculate_gradient_match_score(self, current_pattern, optimal_pattern):
        """現在の勾配パターンと最適パターンの一致度計算"""
        try:
            if len(current_pattern) != len(optimal_pattern):
                return 0
            
            # コサイン類似度計算
            dot_product = sum(a * b for a, b in zip(current_pattern, optimal_pattern))
            norm_current = sum(a * a for a in current_pattern) ** 0.5
            norm_optimal = sum(b * b for b in optimal_pattern) ** 0.5
            
            if norm_current == 0 or norm_optimal == 0:
                return 0
            
            cosine_similarity = dot_product / (norm_current * norm_optimal)
            
            # -1~1の範囲を0~100%の範囲に変換
            match_score = (cosine_similarity + 1) * 50
            
            return match_score
            
        except Exception as e:
            logger.error(f"勾配マッチスコア計算エラー: {e}")
            return 0
    
    def should_early_exit(self, position):
        """早期エグジット判定"""
        try:
            currency_pair = position['currency_pair']
            
            # 現在の勾配パターンを取得
            current_pattern = self.gradient_calculator.get_gradient_pattern(currency_pair)
            
            # 最適パターン（実際にはDBから取得。ここではダミーデータ）
            optimal_pattern = position.get('optimal_pattern', [50, 30, 20, 40])
            
            # マッチスコア計算
            match_score = self.calculate_gradient_match_score(current_pattern, optimal_pattern)
            
            # 信頼度ランクに基づく閾値取得
            reliability_rank = position.get('reliability_rank', 'B')
            threshold_map = {
                'S': -90, 'A': -85, 'B': -75, 'C': -65, 'D': -55
            }
            threshold = threshold_map.get(reliability_rank, self.early_exit_threshold)
            
            logger.info(f"📊 勾配監視 {currency_pair}: パターン={current_pattern}, マッチ度={match_score:.1f}%, 閾値={threshold}%")
            
            # 早期エグジット判定
            if match_score <= threshold:
                logger.warning(f"⚠️  早期エグジット条件達成: {currency_pair} (マッチ度={match_score:.1f}% <= 閾値={threshold}%)")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"早期エグジット判定エラー: {e}")
            return False
    
    def gradient_monitoring_loop(self):
        """勾配監視ループ（別スレッドで実行）"""
        logger.info("📈 勾配監視スレッド開始")
        
        while self.gradient_monitoring_running:
            try:
                if self.active_positions:
                    logger.info(f"🔍 勾配監視チェック: {len(self.active_positions)}ポジション")
                    
                    positions_to_close = []
                    
                    for position in self.active_positions:
                        # 価格データ更新
                        current_price = self.get_current_price(position['currency_pair'])
                        
                        if current_price:
                            # 早期エグジット判定
                            if self.should_early_exit(position):
                                positions_to_close.append(position)
                    
                    # 早期エグジット実行
                    for position in positions_to_close:
                        self.execute_early_exit(position)
                
                # 次のチェックまで待機
                time.sleep(self.gradient_check_interval)
                
            except Exception as e:
                logger.error(f"勾配監視ループエラー: {e}")
                time.sleep(self.gradient_check_interval)
        
        logger.info("📈 勾配監視スレッド終了")
    
    def execute_early_exit(self, position):
        """早期エグジット実行"""
        try:
            currency_pair = position['currency_pair']
            direction = position['direction']
            
            logger.info(f"🚨 早期エグジット実行: {currency_pair} {direction}")
            
            # 現在価格で損益計算
            current_price = self.get_current_price(currency_pair)
            if current_price:
                entry_price = position['entry_price']
                exit_price = current_price['bid'] if direction.upper() == 'LONG' else current_price['ask']
                
                if 'JPY' in currency_pair:
                    pips = (exit_price - entry_price) * 100 if direction.upper() == 'LONG' else (entry_price - exit_price) * 100
                else:
                    pips = (exit_price - entry_price) * 10000 if direction.upper() == 'LONG' else (entry_price - exit_price) * 10000
                
                logger.info(f"💹 早期エグジット損益: {pips:.1f} pips")
            
            # 実際の環境では決済注文を発注
            logger.info(f"✅ [SIMULATION] 早期エグジット決済: {currency_pair}")
            
            # ポジションをアクティブリストから削除
            if position in self.active_positions:
                self.active_positions.remove(position)
                logger.info(f"📊 早期エグジット後のアクティブポジション数: {len(self.active_positions)}")
            
        except Exception as e:
            logger.error(f"早期エグジット実行エラー: {e}")
    
    def start_gradient_monitoring(self):
        """勾配監視開始"""
        if not self.gradient_monitoring_running:
            self.gradient_monitoring_running = True
            self.gradient_monitoring_thread = threading.Thread(target=self.gradient_monitoring_loop, daemon=True)
            self.gradient_monitoring_thread.start()
            logger.info("📈 勾配監視スレッド開始")
    
    def stop_gradient_monitoring(self):
        """勾配監視停止"""
        if self.gradient_monitoring_running:
            self.gradient_monitoring_running = False
            if self.gradient_monitoring_thread:
                self.gradient_monitoring_thread.join(timeout=10)
            logger.info("📈 勾配監視スレッド停止")
    
    def check_entry_conditions(self):
        """エントリー条件チェック"""
        current_time = datetime.now().strftime('%H:%M:%S')
        current_minute_time = datetime.now().strftime('%H:%M:00')
        
        logger.info(f"⏰ エントリー条件チェック: 実際時刻={current_time}, チェック対象={current_minute_time}")
        
        try:
            matching_entries = self.entry_points_df[
                self.entry_points_df['Entry'] == current_minute_time
            ]
            
            if not matching_entries.empty:
                logger.info(f"🎯 エントリーポイント発見: {len(matching_entries)}件")
                
                for _, entry in matching_entries.iterrows():
                    self._process_entry_signal(entry)
            else:
                self._show_next_entry_info()
                
        except Exception as e:
            logger.error(f"エントリー条件チェックエラー: {e}")
    
    def _process_entry_signal(self, entry):
        """エントリーシグナル処理"""
        currency_pair = entry['通貨ペア']
        direction = entry['方向']
        score = entry['実用スコア']
        
        logger.info(f"📈 エントリーシグナル処理開始")
        logger.info(f"   通貨ペア: {currency_pair}")
        logger.info(f"   方向: {direction}")
        logger.info(f"   実用スコア: {score}")
        logger.info(f"   エグジット予定: {entry['Exit']}")
        
        # 現在価格取得
        current_price = self.get_current_price(currency_pair)
        if not current_price:
            logger.error("価格取得に失敗しました")
            return
        
        logger.info(f"   現在価格: BID={current_price['bid']}, ASK={current_price['ask']}")
        
        # ポジションサイズ計算
        entry_price = current_price['ask'] if direction.upper() == 'LONG' else current_price['bid']
        position_size = self.calculate_position_size(currency_pair, entry_price, None)
        
        logger.info(f"   ポジションサイズ: {position_size:,}通貨")
        
        # 最大ポジション数チェック
        if len(self.active_positions) >= self.max_positions:
            logger.warning("⚠️  最大ポジション数に達しています")
            return
        
        # 注文発注
        if self.place_order(currency_pair, direction, position_size):
            # アクティブポジションに追加（勾配監視用の情報も含む）
            position_info = {
                'currency_pair': currency_pair,
                'direction': direction,
                'entry_time': datetime.now(),
                'exit_time': entry['Exit'],
                'amount': position_size,
                'score': score,
                'entry_price': entry_price,
                'optimal_pattern': [50, 30, 20, 40],  # 実際にはDBから取得
                'reliability_rank': 'B'  # 実際にはDBから取得
            }
            self.active_positions.append(position_info)
            
            logger.info(f"✅ ポジション追加: アクティブ数={len(self.active_positions)}")
            
            # 勾配監視を開始（まだ開始していない場合）
            self.start_gradient_monitoring()
    
    def _show_next_entry_info(self):
        """次のエントリーポイント情報表示"""
        try:
            current_time_obj = datetime.strptime(datetime.now().strftime('%H:%M:00'), '%H:%M:%S').time()
            
            all_times = pd.to_datetime(self.entry_points_df['Entry'], format='%H:%M:%S').dt.time
            future_entries = self.entry_points_df[all_times > current_time_obj]
            
            if not future_entries.empty:
                next_entry = future_entries.iloc[0]
                next_time = datetime.strptime(next_entry['Entry'], '%H:%M:%S')
                current_datetime = datetime.strptime(datetime.now().strftime('%H:%M:00'), '%H:%M:%S')
                time_diff = next_time - current_datetime
                
                logger.info(f"📅 次のエントリー: {next_entry['Entry']} ({next_entry['通貨ペア']} {next_entry['方向']}) - あと{time_diff}")
            else:
                logger.info("📅 本日のエントリーポイントは終了しました")
                
        except Exception as e:
            logger.error(f"次のエントリー情報取得エラー: {e}")
    
    def check_exit_conditions(self):
        """エグジット条件チェック（定時エグジット）"""
        current_time = datetime.now().strftime('%H:%M:00')
        
        positions_to_close = []
        
        for position in self.active_positions:
            if position['exit_time'] == current_time:
                positions_to_close.append(position)
        
        for position in positions_to_close:
            self.execute_scheduled_exit(position)
    
    def execute_scheduled_exit(self, position):
        """定時エグジット実行"""
        try:
            currency_pair = position['currency_pair']
            direction = position['direction']
            
            logger.info(f"🔚 定時エグジット実行: {currency_pair} {direction}")
            
            # 現在価格取得
            current_price = self.get_current_price(currency_pair)
            if not current_price:
                logger.error("エグジット時の価格取得に失敗しました")
                return

            # 損益計算（pips）
            entry_price = position['entry_price']
            exit_price = current_price['bid'] if direction.upper() == 'LONG' else current_price['ask']
            if 'JPY' in currency_pair:
                pips = (exit_price - entry_price) * 100 if direction.upper() == 'LONG' else (entry_price - exit_price) * 100
            else:
                pips = (exit_price - entry_price) * 10000 if direction.upper() == 'LONG' else (entry_price - exit_price) * 10000

            logger.info(f"💹 定時エグジット損益: {pips:.1f} pips (Entry: {entry_price}, Exit: {exit_price})")
            
            # 実際の環境では決済注文を発注
            logger.info(f"✅ [SIMULATION] 定時エグジット決済: {currency_pair}")
            
            # ポジションをアクティブリストから削除
            if position in self.active_positions:
                self.active_positions.remove(position)
                logger.info(f"📊 定時エグジット後のアクティブポジション数: {len(self.active_positions)}")
            
        except Exception as e:
            logger.error(f"定時エグジット実行エラー: {e}")
    
    def monitor_positions(self):
        """ポジション監視"""
        if self.active_positions:
            logger.info(f"📊 アクティブポジション監視: {len(self.active_positions)}件")
            
            for position in self.active_positions:
                # 現在の勾配パターンを表示
                current_pattern = self.gradient_calculator.get_gradient_pattern(position['currency_pair'])
                logger.info(f"   {position['currency_pair']} {position['direction']} "
                           f"エグジット予定: {position['exit_time']}, "
                           f"現在勾配: {[f'{x:.1f}' for x in current_pattern]}")
    
    def run_single_check(self):
        """1回のチェック実行"""
        try:
            logger.info("=" * 60)
            logger.info("🔄 定期チェック実行")
            
            # エントリー条件チェック
            self.check_entry_conditions()
            
            # エグジット条件チェック
            self.check_exit_conditions()
            
            # ポジション監視
            self.monitor_positions()
            
        except Exception as e:
            logger.error(f"定期チェックエラー: {e}")
    
    def wait_for_next_minute(self):
        """次の分の00秒まで待機"""
        now = datetime.now()
        
        # 次の分の00秒を計算
        next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        
        # 待機時間を計算
        wait_time = (next_minute - now).total_seconds()
        
        logger.info(f"⏰ 次のチェックまで待機: {wait_time:.1f}秒 (次回実行: {next_minute.strftime('%H:%M:%S')})")
        
        return wait_time
    
    def start_monitoring(self):
        """監視開始（00秒ちょうどに同期）"""
        logger.info("🚀 FX自動エントリーシステム監視開始")
        logger.info(f"エントリーポイント数: {len(self.entry_points_df)}")
        logger.info(f"対応通貨ペア: {list(self.currency_uic_mapping.keys())}")
        logger.info("⏰ 毎分00秒にエントリー・エグジットチェックを実行")
        logger.info(f"📈 エントリー後は{self.gradient_check_interval}秒間隔で勾配監視を実行")
        
        self.running = True
        
        # 最初の1回を即座に実行
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
            self.running = False
        finally:
            # 勾配監視スレッドを停止
            self.stop_gradient_monitoring()
    
    def stop_system(self):
        """システム停止"""
        logger.info("🛑 システム停止処理開始")
        self.running = False
        self.stop_gradient_monitoring()
        logger.info("✅ システム停止完了")

def main():
    """メイン実行関数"""
    try:
        # システム初期化
        fx_system = FXAutoEntrySystem()
        
        # 監視開始
        fx_system.start_monitoring()
        
    except Exception as e:
        logger.error(f"システムエラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()