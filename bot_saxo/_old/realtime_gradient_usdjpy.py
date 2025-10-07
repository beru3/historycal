#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_realtime_gradient_usdjpy.py - リアルタイムUSDJPY勾配パラメータ取得
実行時点でのドル円の勾配パラメータを即座に計算・表示
"""

import requests
import pandas as pd
import numpy as np
import os
import zipfile
import io
from datetime import datetime, timedelta
import logging
from config import TEST_TOKEN_24H, BASE_URL

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RealtimeGradientUSDJPY:
    """リアルタイムUSDJPY勾配パラメータ取得クラス"""
    
    def __init__(self):
        self.base_url = BASE_URL
        self.token = TEST_TOKEN_24H
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        self.currency_pair = 'USDJPY'
        self.uic = None
        self.historical_data = None
        
        # 初期化
        self._initialize()
    
    def _initialize(self):
        """システム初期化"""
        logger.info("🚀 リアルタイムUSDJPY勾配パラメータ取得システム初期化")
        
        # USDJPYのUIC取得
        self._get_usdjpy_uic()
        
        # 過去データ読み込み
        self._load_historical_data()
    
    def _get_usdjpy_uic(self):
        """USDJPYのUIC取得"""
        try:
            params = {
                'Keywords': 'USDJPY',
                'AssetTypes': 'FxSpot',
                'limit': 1
            }
            response = requests.get(f"{self.base_url}/ref/v1/instruments", headers=self.headers, params=params)
            
            if response.status_code == 200:
                instruments = response.json()
                if instruments.get('Data'):
                    self.uic = instruments['Data'][0]['Identifier']
                    logger.info(f"✅ USDJPY UIC取得成功: {self.uic}")
                else:
                    raise Exception("USDJPYが見つかりません")
            else:
                raise Exception(f"UIC取得失敗: {response.status_code}")
                
        except Exception as e:
            logger.error(f"UIC取得エラー: {e}")
            raise
    
    def _load_historical_data(self):
        """過去データ読み込み（過去3日分の1分足）"""
        logger.info("📊 過去データ読み込み中...")
        
        try:
            # inputフォルダから最新のUSDJPYデータを取得
            input_dir = "input"
            today = datetime.now()
            
            # 過去1ヶ月分のZIPファイルを探す
            for days_back in range(32):
                target_date = today - timedelta(days=days_back)
                year_month = target_date.strftime('%Y%m')
                zip_path = os.path.join(input_dir, f"USDJPY_{year_month}.zip")
                
                if os.path.exists(zip_path):
                    logger.info(f"   📁 {os.path.basename(zip_path)} を使用")
                    self.historical_data = self._extract_recent_data(zip_path, days_back=3)
                    break
            
            if self.historical_data is None or self.historical_data.empty:
                logger.warning("⚠️  過去データが見つかりません。ダミーデータを使用します")
                self._create_dummy_data()
            else:
                logger.info(f"✅ 過去データ読み込み完了: {len(self.historical_data)}行")
                
        except Exception as e:
            logger.error(f"過去データ読み込みエラー: {e}")
            self._create_dummy_data()
    
    def _extract_recent_data(self, zip_path, days_back=3):
        """ZIPファイルから最近のデータを抽出"""
        try:
            all_data = []
            cutoff_time = datetime.now() - timedelta(days=days_back)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]
                
                for csv_file in csv_files:
                    with zip_ref.open(csv_file) as file:
                        # エンコーディングを試行
                        for encoding in ['utf-8', 'shift_jis', 'cp932']:
                            try:
                                content = file.read().decode(encoding)
                                df = pd.read_csv(io.StringIO(content))
                                
                                # カラム名正規化
                                column_mapping = {
                                    "日時": "timestamp",
                                    "始値(BID)": "open_bid",
                                    "高値(BID)": "high_bid", 
                                    "安値(BID)": "low_bid",
                                    "終値(BID)": "close_bid",
                                    "始値(ASK)": "open_ask",
                                    "高値(ASK)": "high_ask",
                                    "安値(ASK)": "low_ask", 
                                    "終値(ASK)": "close_ask"
                                }
                                df = df.rename(columns=column_mapping)
                                
                                # タイムスタンプを変換
                                df['timestamp'] = pd.to_datetime(df['timestamp'])
                                
                                # 最近のデータのみフィルタ
                                recent_df = df[df['timestamp'] >= cutoff_time]
                                
                                if not recent_df.empty:
                                    # 中間価格を計算
                                    recent_df['close'] = (recent_df['close_bid'] + recent_df['close_ask']) / 2
                                    recent_df['high'] = (recent_df['high_bid'] + recent_df['high_ask']) / 2
                                    recent_df['low'] = (recent_df['low_bid'] + recent_df['low_ask']) / 2
                                    recent_df['open'] = (recent_df['open_bid'] + recent_df['open_ask']) / 2
                                    
                                    all_data.append(recent_df[['timestamp', 'open', 'high', 'low', 'close']])
                                break
                            except UnicodeDecodeError:
                                continue
            
            if all_data:
                combined_df = pd.concat(all_data, ignore_index=True)
                combined_df = combined_df.sort_values('timestamp').drop_duplicates().reset_index(drop=True)
                return combined_df
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"データ抽出エラー: {e}")
            return pd.DataFrame()
    
    def _create_dummy_data(self):
        """ダミーデータ作成（テスト用）"""
        logger.info("🔧 ダミーデータを作成中...")
        
        # 過去3日分の1分足ダミーデータ
        end_time = datetime.now()
        start_time = end_time - timedelta(days=3)
        
        timestamps = pd.date_range(start=start_time, end=end_time, freq='1T')
        
        # ランダムウォークでUSDJPYっぽい価格を生成
        np.random.seed(42)  # 再現可能性のため
        base_price = 143.50
        price_changes = np.random.normal(0, 0.01, len(timestamps))
        prices = base_price + np.cumsum(price_changes)
        
        self.historical_data = pd.DataFrame({
            'timestamp': timestamps,
            'open': prices,
            'high': prices + np.random.uniform(0, 0.02, len(timestamps)),
            'low': prices - np.random.uniform(0, 0.02, len(timestamps)),
            'close': prices
        })
        
        logger.info(f"✅ ダミーデータ作成完了: {len(self.historical_data)}行")
    
    def get_current_price(self):
        """現在のUSDJPY価格を取得"""
        try:
            params = {
                'Uic': str(self.uic),
                'AssetType': 'FxSpot',
                'FieldGroups': 'Quote'
            }
            response = requests.get(f"{self.base_url}/trade/v1/infoprices", headers=self.headers, params=params)
            
            if response.status_code == 200:
                prices = response.json()
                
                if prices.get('Data'):
                    quote = prices['Data'][0].get('Quote', {})
                elif 'Quote' in prices:
                    quote = prices['Quote']
                else:
                    return None
                
                bid = quote.get('Bid', 0)
                ask = quote.get('Ask', 0)
                current_price = (bid + ask) / 2
                
                logger.info(f"💹 現在価格: BID={bid}, ASK={ask}, 中間価格={current_price:.3f}")
                return current_price
            else:
                logger.error(f"価格取得失敗: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"価格取得エラー: {e}")
            return None
    
    def add_current_price_to_history(self, current_price):
        """現在価格を履歴データに追加"""
        if current_price is None:
            return
        
        try:
            # 現在時刻の1分足データを作成
            current_time = datetime.now().replace(second=0, microsecond=0)
            
            new_row = {
                'timestamp': current_time,
                'open': current_price,
                'high': current_price,
                'low': current_price,
                'close': current_price
            }
            
            # 履歴データに追加
            self.historical_data = pd.concat([
                self.historical_data,
                pd.DataFrame([new_row])
            ], ignore_index=True)
            
            # 重複除去とソート
            self.historical_data = self.historical_data.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            logger.info(f"📊 履歴データ更新: {current_time} = {current_price:.3f}")
            
        except Exception as e:
            logger.error(f"履歴データ更新エラー: {e}")
    
    def resample_to_timeframes(self):
        """各時間軸にリサンプル"""
        try:
            df = self.historical_data.set_index('timestamp')
            
            timeframes = {
                '1min': df.resample('1T').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last'
                }).dropna(),
                
                '5min': df.resample('5T').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last'
                }).dropna(),
                
                '15min': df.resample('15T').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last'
                }).dropna(),
                
                '1hour': df.resample('1H').agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last'
                }).dropna()
            }
            
            return timeframes
            
        except Exception as e:
            logger.error(f"リサンプルエラー: {e}")
            return {}
    
    def calculate_macd_gradient(self, df, fast=12, slow=26):
        """MACD勾配計算"""
        try:
            if len(df) < slow + 5:
                return 0.0
            
            # EMA計算
            ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
            ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
            
            # MACDライン
            macd_line = ema_fast - ema_slow
            
            # 最新の勾配（5期間の変化率）
            if len(macd_line) >= 5:
                current_macd = macd_line.iloc[-1]
                past_macd = macd_line.iloc[-5]
                
                if past_macd != 0:
                    gradient = ((current_macd - past_macd) / abs(past_macd)) * 100
                    return max(-100, min(100, gradient))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"MACD勾配計算エラー: {e}")
            return 0.0
    
    def calculate_ma_gradient(self, df, period=20):
        """移動平均勾配計算"""
        try:
            if len(df) < period + 5:
                return 0.0
            
            # 移動平均
            ma = df['close'].rolling(window=period).mean()
            
            # 最新の勾配（5期間の変化率）
            if len(ma) >= 5:
                current_ma = ma.iloc[-1]
                past_ma = ma.iloc[-5]
                
                if past_ma != 0:
                    gradient = ((current_ma - past_ma) / past_ma) * 100
                    return max(-100, min(100, gradient))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"MA勾配計算エラー: {e}")
            return 0.0
    
    def calculate_atr_gradient(self, df, period=14):
        """ATR勾配計算"""
        try:
            if len(df) < period + 5:
                return 0.0
            
            # True Range計算
            df_copy = df.copy()
            df_copy['prev_close'] = df_copy['close'].shift(1)
            df_copy['tr1'] = df_copy['high'] - df_copy['low']
            df_copy['tr2'] = abs(df_copy['high'] - df_copy['prev_close'])
            df_copy['tr3'] = abs(df_copy['low'] - df_copy['prev_close'])
            
            df_copy['true_range'] = df_copy[['tr1', 'tr2', 'tr3']].max(axis=1)
            
            # ATR計算
            atr = df_copy['true_range'].rolling(window=period).mean()
            
            # 最新の勾配（5期間の変化率）
            if len(atr) >= 5:
                current_atr = atr.iloc[-1]
                past_atr = atr.iloc[-5]
                
                if past_atr != 0:
                    gradient = ((current_atr - past_atr) / past_atr) * 100
                    return max(-100, min(100, gradient))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"ATR勾配計算エラー: {e}")
            return 0.0
    
    def calculate_price_gradient(self, df):
        """価格勾配計算"""
        try:
            if len(df) < 5:
                return 0.0
            
            # 価格の変化率
            current_price = df['close'].iloc[-1]
            past_price = df['close'].iloc[-5]
            
            if past_price != 0:
                gradient = ((current_price - past_price) / past_price) * 100
                return max(-100, min(100, gradient))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"価格勾配計算エラー: {e}")
            return 0.0
    
    def calculate_realtime_gradients(self):
        """リアルタイム勾配パラメータ計算"""
        logger.info("📈 リアルタイム勾配パラメータ計算開始")
        
        # 現在価格取得
        current_price = self.get_current_price()
        
        # 履歴データに現在価格を追加
        self.add_current_price_to_history(current_price)
        
        # 時間軸別リサンプル
        timeframes = self.resample_to_timeframes()
        
        if not timeframes:
            logger.error("❌ 時間軸データ生成失敗")
            return None
        
        # 各時間軸の勾配計算
        gradients = {}
        
        for tf_name, df in timeframes.items():
            if df.empty:
                gradients[tf_name] = 0.0
                continue
            
            # 各指標の勾配を計算
            macd_grad = self.calculate_macd_gradient(df)
            ma_grad = self.calculate_ma_gradient(df)
            atr_grad = self.calculate_atr_gradient(df)
            price_grad = self.calculate_price_gradient(df)
            
            # 複合勾配（各指標の重み付け平均）
            composite_gradient = (macd_grad * 0.3 + ma_grad * 0.3 + atr_grad * 0.2 + price_grad * 0.2)
            gradients[tf_name] = round(composite_gradient, 2)
            
            logger.info(f"   {tf_name}: MACD={macd_grad:.2f}, MA={ma_grad:.2f}, ATR={atr_grad:.2f}, Price={price_grad:.2f} → 複合={composite_gradient:.2f}")
        
        # 4時間軸パターン
        pattern = [
            gradients.get('1min', 0.0),
            gradients.get('5min', 0.0),
            gradients.get('15min', 0.0),
            gradients.get('1hour', 0.0)
        ]
        
        return {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'current_price': current_price,
            'gradient_pattern': pattern,
            'detailed_gradients': gradients
        }
    
    def display_results(self, result):
        """結果を見やすく表示"""
        if not result:
            print("❌ 勾配計算結果がありません")
            return
        
        print("=" * 70)
        print("🔥 リアルタイムUSDJPY勾配パラメータ")
        print("=" * 70)
        print(f"⏰ 取得時刻: {result['timestamp']}")
        print(f"💹 現在価格: {result['current_price']:.3f}")
        print()
        print("📊 勾配パターン [1分足, 5分足, 15分足, 1時間足]:")
        print(f"   {result['gradient_pattern']}")
        print()
        print("📈 詳細勾配:")
        for tf, grad in result['detailed_gradients'].items():
            trend = "🔴" if grad < -10 else "🟡" if grad < 10 else "🟢"
            print(f"   {tf:>6}: {grad:>8.2f}% {trend}")
        print()
        
        # トレンド判定
        avg_gradient = sum(result['gradient_pattern']) / 4
        if avg_gradient > 15:
            trend_status = "🚀 強い上昇トレンド"
        elif avg_gradient > 5:
            trend_status = "📈 上昇トレンド"
        elif avg_gradient > -5:
            trend_status = "➡️  レンジ相場"
        elif avg_gradient > -15:
            trend_status = "📉 下降トレンド"
        else:
            trend_status = "💥 強い下降トレンド"
        
        print(f"🎯 総合判定: {trend_status} (平均勾配: {avg_gradient:.2f}%)")
        print("=" * 70)

def main():
    """メイン実行"""
    try:
        # システム初期化
        gradient_system = RealtimeGradientUSDJPY()
        
        # リアルタイム勾配計算
        result = gradient_system.calculate_realtime_gradients()
        
        # 結果表示
        gradient_system.display_results(result)
        
    except Exception as e:
        logger.error(f"実行エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()