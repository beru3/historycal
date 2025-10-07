#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_gradient_calculator.py - FX勾配パラメータ取得専用スクリプト
過去データから1分足ベースで4時間軸の勾配パラメータを計算
"""

import pandas as pd
import numpy as np
import os
import glob
import zipfile
import io
import json
from datetime import datetime, timedelta
import logging

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('fx_gradient_calculator.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FXGradientCalculator:
    """FX勾配パラメータ計算クラス"""
    
    def __init__(self, input_dir="input"):
        self.input_dir = input_dir
        self.cached_data = {}
        
        # カラム名の正規化マッピング
        self.column_mapping = {
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
    
    def get_available_currency_pairs(self):
        """利用可能な通貨ペアを取得"""
        zip_files = glob.glob(os.path.join(self.input_dir, "*.zip"))
        currency_pairs = set()
        
        for zip_file in zip_files:
            filename = os.path.basename(zip_file)
            # USDJPY_202505.zip -> USDJPY
            currency_pair = filename.split('_')[0]
            currency_pairs.add(currency_pair)
        
        return sorted(list(currency_pairs))
    
    def load_recent_data(self, currency_pair, days_back=30):
        """最近のデータを読み込み（過去30日分）"""
        logger.info(f"📊 {currency_pair} の過去{days_back}日分のデータを読み込み中...")
        
        # 対象期間のZIPファイルを特定
        today = datetime.now()
        target_months = []
        
        # 過去2ヶ月分のZIPファイルを対象
        for month_offset in range(3):  # 余裕を持って3ヶ月
            target_month = today - timedelta(days=30 * month_offset)
            target_months.append(target_month.strftime('%Y%m'))
        
        all_data = []
        
        for year_month in target_months:
            zip_pattern = f"{currency_pair}_{year_month}.zip"
            zip_path = os.path.join(self.input_dir, zip_pattern)
            
            if os.path.exists(zip_path):
                logger.info(f"   📁 {zip_pattern} を処理中...")
                month_data = self._extract_data_from_zip(zip_path)
                all_data.extend(month_data)
        
        if not all_data:
            logger.error(f"❌ {currency_pair} のデータが見つかりません")
            return pd.DataFrame()
        
        # DataFrameに変換
        df = pd.DataFrame(all_data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        # 過去30日分にフィルタリング
        cutoff_date = today - timedelta(days=days_back)
        df = df[df['timestamp'] >= cutoff_date]
        
        logger.info(f"✅ {currency_pair}: {len(df)}行のデータを読み込み完了")
        logger.info(f"   期間: {df['timestamp'].min()} ～ {df['timestamp'].max()}")
        
        return df
    
    def _extract_data_from_zip(self, zip_path):
        """ZIPファイルからデータを抽出"""
        data = []
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                csv_files = [f for f in zip_ref.namelist() if f.endswith('.csv')]
                
                for csv_file in csv_files:
                    try:
                        with zip_ref.open(csv_file) as file:
                            # エンコーディングを試行
                            for encoding in ['utf-8', 'shift_jis', 'cp932', 'euc_jp']:
                                try:
                                    content = file.read().decode(encoding)
                                    df = pd.read_csv(io.StringIO(content))
                                    
                                    # カラム名を正規化
                                    df = df.rename(columns=self.column_mapping)
                                    
                                    # 必要なカラムが存在するかチェック
                                    required_cols = ['timestamp', 'open_bid', 'high_bid', 'low_bid', 'close_bid', 
                                                   'open_ask', 'high_ask', 'low_ask', 'close_ask']
                                    
                                    if all(col in df.columns for col in required_cols):
                                        # 中間価格を計算
                                        for _, row in df.iterrows():
                                            data.append({
                                                'timestamp': row['timestamp'],
                                                'open': (row['open_bid'] + row['open_ask']) / 2,
                                                'high': (row['high_bid'] + row['high_ask']) / 2,
                                                'low': (row['low_bid'] + row['low_ask']) / 2,
                                                'close': (row['close_bid'] + row['close_ask']) / 2,
                                                'volume': 1  # ダミー値
                                            })
                                        break
                                except UnicodeDecodeError:
                                    continue
                    except Exception as e:
                        logger.warning(f"CSVファイル処理エラー: {csv_file} - {e}")
                        continue
        
        except Exception as e:
            logger.error(f"ZIP処理エラー: {zip_path} - {e}")
        
        return data
    
    def resample_to_timeframes(self, df):
        """1分足データを各時間軸にリサンプル"""
        if df.empty:
            return {}
        
        df = df.set_index('timestamp')
        
        timeframes = {
            '1min': df.resample('1T'),
            '5min': df.resample('5T'),
            '15min': df.resample('15T'),
            '1hour': df.resample('1H')
        }
        
        resampled = {}
        for tf_name, resampler in timeframes.items():
            resampled[tf_name] = resampler.agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            logger.info(f"   {tf_name}: {len(resampled[tf_name])}本のローソク足")
        
        return resampled
    
    def calculate_macd_gradient(self, df, fast=12, slow=26, signal=9):
        """MACD勾配計算"""
        if len(df) < slow + 10:  # 十分なデータがない場合
            return pd.Series([0] * len(df), index=df.index)
        
        # EMA計算
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        
        # MACDライン
        macd_line = ema_fast - ema_slow
        
        # 勾配計算（5期間の変化率）
        macd_gradient = macd_line.pct_change(periods=5) * 100
        
        # -100% ~ +100% の範囲にクリップ
        macd_gradient = macd_gradient.clip(-100, 100).fillna(0)
        
        return macd_gradient
    
    def calculate_ma_gradient(self, df, period=20):
        """移動平均勾配計算"""
        if len(df) < period + 10:
            return pd.Series([0] * len(df), index=df.index)
        
        # 移動平均
        ma = df['close'].rolling(window=period).mean()
        
        # 勾配計算（5期間の変化率）
        ma_gradient = ma.pct_change(periods=5) * 100
        
        # -100% ~ +100% の範囲にクリップ
        ma_gradient = ma_gradient.clip(-100, 100).fillna(0)
        
        return ma_gradient
    
    def calculate_atr_gradient(self, df, period=14):
        """ATR勾配計算"""
        if len(df) < period + 10:
            return pd.Series([0] * len(df), index=df.index)
        
        # True Range計算
        df_copy = df.copy()
        df_copy['prev_close'] = df_copy['close'].shift(1)
        df_copy['tr1'] = df_copy['high'] - df_copy['low']
        df_copy['tr2'] = abs(df_copy['high'] - df_copy['prev_close'])
        df_copy['tr3'] = abs(df_copy['low'] - df_copy['prev_close'])
        
        df_copy['true_range'] = df_copy[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # ATR計算
        atr = df_copy['true_range'].rolling(window=period).mean()
        
        # 勾配計算（5期間の変化率）
        atr_gradient = atr.pct_change(periods=5) * 100
        
        # -100% ~ +100% の範囲にクリップ
        atr_gradient = atr_gradient.clip(-100, 100).fillna(0)
        
        return atr_gradient
    
    def calculate_price_gradient(self, df):
        """価格勾配計算（終値の変化率）"""
        price_gradient = df['close'].pct_change(periods=5) * 100
        price_gradient = price_gradient.clip(-100, 100).fillna(0)
        return price_gradient
    
    def calculate_all_gradients(self, timeframe_data):
        """全時間軸の勾配を計算"""
        gradients = {}
        
        for tf_name, df in timeframe_data.items():
            if df.empty:
                gradients[tf_name] = {
                    'macd_gradient': pd.Series([0], index=[datetime.now()]),
                    'ma_gradient': pd.Series([0], index=[datetime.now()]),
                    'atr_gradient': pd.Series([0], index=[datetime.now()]),
                    'price_gradient': pd.Series([0], index=[datetime.now()])
                }
                continue
            
            logger.info(f"   📈 {tf_name} の勾配計算中...")
            
            gradients[tf_name] = {
                'macd_gradient': self.calculate_macd_gradient(df),
                'ma_gradient': self.calculate_ma_gradient(df),
                'atr_gradient': self.calculate_atr_gradient(df),
                'price_gradient': self.calculate_price_gradient(df)
            }
        
        return gradients
    
    def get_gradient_at_time(self, gradients, target_time):
        """指定時刻の勾配パターンを取得"""
        pattern = []
        
        timeframe_order = ['1min', '5min', '15min', '1hour']
        
        for tf in timeframe_order:
            if tf not in gradients:
                pattern.append(0.0)
                continue
            
            tf_gradients = gradients[tf]
            
            # 指定時刻に最も近いデータを取得
            macd_val = self._get_closest_value(tf_gradients['macd_gradient'], target_time)
            ma_val = self._get_closest_value(tf_gradients['ma_gradient'], target_time)
            atr_val = self._get_closest_value(tf_gradients['atr_gradient'], target_time)
            price_val = self._get_closest_value(tf_gradients['price_gradient'], target_time)
            
            # 複合勾配スコア（各指標の重み付け平均）
            composite_gradient = (macd_val * 0.3 + ma_val * 0.3 + atr_val * 0.2 + price_val * 0.2)
            pattern.append(round(composite_gradient, 2))
        
        return pattern
    
    def _get_closest_value(self, series, target_time):
        """指定時刻に最も近い値を取得"""
        if series.empty:
            return 0.0
        
        try:
            # target_timeがdatetimeでない場合は変換
            if isinstance(target_time, str):
                target_time = pd.to_datetime(target_time)
            
            # 最も近いインデックスを見つける
            idx = series.index.get_indexer([target_time], method='nearest')[0]
            if idx >= 0 and idx < len(series):
                value = series.iloc[idx]
                return float(value) if not pd.isna(value) else 0.0
            else:
                return 0.0
                
        except Exception as e:
            logger.warning(f"値の取得エラー: {e}")
            return 0.0
    
    def analyze_currency_pair(self, currency_pair):
        """特定通貨ペアの勾配分析"""
        logger.info(f"🔍 {currency_pair} の勾配分析開始")
        
        # データ読み込み
        df = self.load_recent_data(currency_pair)
        if df.empty:
            return None
        
        # 時間軸別にリサンプル
        logger.info(f"⏰ 時間軸別リサンプル実行...")
        timeframe_data = self.resample_to_timeframes(df)
        
        # 勾配計算
        logger.info(f"📊 勾配パラメータ計算...")
        gradients = self.calculate_all_gradients(timeframe_data)
        
        # サンプル時刻での勾配パターンを表示
        sample_times = [
            datetime.now() - timedelta(hours=1),
            datetime.now() - timedelta(hours=2),
            datetime.now() - timedelta(hours=6),
            datetime.now() - timedelta(hours=12)
        ]
        
        results = []
        for sample_time in sample_times:
            pattern = self.get_gradient_at_time(gradients, sample_time)
            results.append({
                'time': sample_time.strftime('%Y-%m-%d %H:%M'),
                'pattern': pattern
            })
            logger.info(f"   {sample_time.strftime('%H:%M')}: {pattern}")
        
        return {
            'currency_pair': currency_pair,
            'gradients': gradients,
            'sample_results': results
        }
    
    def test_gradient_calculation(self, target_currency='USDJPY'):
        """勾配計算のテスト実行"""
        logger.info("🚀 FX勾配パラメータ計算テスト開始")
        
        # 利用可能通貨ペア表示
        available_pairs = self.get_available_currency_pairs()
        logger.info(f"📋 利用可能通貨ペア: {available_pairs}")
        
        if target_currency not in available_pairs:
            logger.error(f"❌ {target_currency} のデータが見つかりません")
            return False
        
        # 勾配分析実行
        result = self.analyze_currency_pair(target_currency)
        
        if result:
            logger.info("✅ 勾配計算テスト完了")
            
            # 結果の保存
            output_file = f"gradient_test_result_{target_currency}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            # JSON形式で保存（datetimeとSeriesは除外）
            save_data = {
                'currency_pair': result['currency_pair'],
                'sample_results': result['sample_results'],
                'analysis_time': datetime.now().isoformat()
            }
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"📄 結果を保存しました: {output_file}")
            return True
        else:
            logger.error("❌ 勾配計算テスト失敗")
            return False

def main():
    """メイン実行関数"""
    try:
        # 勾配計算器を初期化
        calculator = FXGradientCalculator()
        
        # テスト実行（デフォルトはUSDJPY）
        success = calculator.test_gradient_calculation('USDJPY')
        
        if success:
            print("\n" + "="*60)
            print("🎉 勾配パラメータ取得テスト成功！")
            print("次のステップ:")
            print("1. fx_analysis_step1.py に勾配計算機能を統合")
            print("2. エントリーポイントCSVに勾配データを追加")
            print("3. リアルタイム監視システムに組み込み")
            print("="*60)
        else:
            print("\n❌ テスト失敗。ログを確認してください。")
        
    except Exception as e:
        logger.error(f"メイン実行エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()