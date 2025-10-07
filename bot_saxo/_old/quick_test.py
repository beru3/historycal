#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_auto_entry_system.py (タイミング修正版) - サクソバンクAPI FX自動エントリーシステム
step3のエントリーポイントに基づいて自動的にFX取引を実行
00秒ちょうどにエントリーチェックを実行
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
from config import TEST_TOKEN_24H, BASE_URL

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fx_auto_entry.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
        
        # データ保存用
        self.account_key = None
        self.currency_uic_mapping = {}
        self.entry_points_df = None
        self.active_positions = []
        self.running = False
        
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
                        # サクソバンクでは'Identifier'がUICに相当
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
        """現在価格取得"""
        try:
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return None
            
            params = {
                'Uics': str(uic),
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            response = requests.get(f"{self.base_url}/trade/v1/infoprices", headers=self.headers, params=params)
            
            if response.status_code == 200:
                prices = response.json()
                if prices.get('Data'):
                    quote = prices['Data'][0].get('Quote', {})
                    return {
                        'bid': quote.get('Bid'),
                        'ask': quote.get('Ask'),
                        'spread': quote.get('Spread')
                    }
            
            logger.error(f"価格取得失敗: {currency_pair}")
            return None
            
        except Exception as e:
            logger.error(f"価格取得エラー: {e}")
            return None
    
    def calculate_position_size(self, currency_pair, entry_price, risk_amount):
        """ポジションサイズ計算"""
        try:
            # リスク管理：口座資金の2%をリスクとする
            # 簡単な例：固定額から開始
            base_amount = self.default_amount
            
            # 実用スコアに基づく調整
            if hasattr(self, '_current_entry_score'):
                score_multiplier = min(self._current_entry_score / 7.0, 2.0)  # 最大2倍
                base_amount = int(base_amount * score_multiplier)
            
            return base_amount
            
        except Exception as e:
            logger.error(f"ポジションサイズ計算エラー: {e}")
            return self.default_amount
    
    def place_order(self, currency_pair, direction, amount, order_type='Market'):
        """注文発注"""
        try:
            uic = self.currency_uic_mapping.get(currency_pair)
            if not uic:
                logger.error(f"UICが見つかりません: {currency_pair}")
                return False
            
            # 注文方向の変換
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
            
            logger.info(f"📋 注文データ: {json.dumps(order_data, indent=2)}")
            
            # 実際の注文はコメントアウト（安全のため）
            # response = requests.post(f"{self.base_url}/trade/v2/orders", headers=self.headers, json=order_data)
            
            # シミュレーション用の成功レスポンス
            logger.info(f"✅ [SIMULATION] 注文発注: {currency_pair} {direction} {amount:,}通貨")
            
            return True  # シミュレーション用
            
        except Exception as e:
            logger.error(f"注文発注エラー: {e}")
            return False
    
    def check_entry_conditions(self):
        """エントリー条件チェック（00秒ちょうどの時刻で）"""
        current_time = datetime.now().strftime('%H:%M:%S')
        
        # 00秒でない場合は秒部分を00に調整した時刻でチェック
        current_minute_time = datetime.now().strftime('%H:%M:00')
        
        logger.info(f"⏰ エントリー条件チェック: 実際時刻={current_time}, チェック対象={current_minute_time}")
        
        try:
            # 00秒時刻と一致するエントリーポイントを検索
            matching_entries = self.entry_points_df[
                self.entry_points_df['Entry'] == current_minute_time
            ]
            
            if not matching_entries.empty:
                logger.info(f"🎯 エントリーポイント発見: {len(matching_entries)}件")
                
                for _, entry in matching_entries.iterrows():
                    self._process_entry_signal(entry)
            
            else:
                # 次のエントリーポイントまでの時間を表示
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
        self._current_entry_score = score
        entry_price = current_price['ask'] if direction.upper() == 'LONG' else current_price['bid']
        position_size = self.calculate_position_size(currency_pair, entry_price, None)
        
        logger.info(f"   ポジションサイズ: {position_size:,}通貨")
        
        # 最大ポジション数チェック
        if len(self.active_positions) >= self.max_positions:
            logger.warning("⚠️  最大ポジション数に達しています")
            return
        
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
                'entry_price': entry_price
            }
            self.active_positions.append(position_info)
            
            logger.info(f"✅ ポジション追加: アクティブ数={len(self.active_positions)}")
    
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
                
                logger.info(f"📅 次のエントリー: {next_entry['Entry']} ({next_entry['通貨ペア']} {next_entry['方向']}) - あと{time_diff}")
            else:
                logger.info("📅 本日のエントリーポイントは終了しました")
                
        except Exception as e:
            logger.error(f"次のエントリー情報取得エラー: {e}")
    
    def check_exit_conditions(self):
        """エグジット条件チェック"""
        current_time = datetime.now().strftime('%H:%M:00')  # 00秒に調整
        
        for i, position in enumerate(self.active_positions[:]):
            if position['exit_time'] == current_time:
                logger.info(f"🔚 エグジット時刻到達: {position['currency_pair']} {position['direction']}")
                
                # 実際の環境では決済注文を発注
                logger.info(f"✅ [SIMULATION] ポジション決済: {position['currency_pair']}")
                
                # ポジションをアクティブリストから削除
                self.active_positions.remove(position)
                logger.info(f"📊 アクティブポジション数: {len(self.active_positions)}")
    
    def monitor_positions(self):
        """ポジション監視"""
        if self.active_positions:
            logger.info(f"📊 アクティブポジション監視: {len(self.active_positions)}件")
            
            for position in self.active_positions:
                logger.info(f"   {position['currency_pair']} {position['direction']} "
                           f"エグジット予定: {position['exit_time']}")
    
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