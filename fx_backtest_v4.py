#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_backtest_fixed_complete.py - FXエントリーポイント バックテストシステム（完全修正版 + 3層戦略）
CSV読み込みエラーを完全解決し、デバッグ機能を強化
BASE/EXPAND/ATR 3層戦略を実装
"""

import os
import pandas as pd
import numpy as np
import zipfile
import glob
import io
import re
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
import logging
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# chardetのインポートを安全に行う
try:
    import chardet
    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False
    print("⚠️  chardet ライブラリがインストールされていません。")
    print("   より正確な文字コード検出のため、以下のコマンドでインストールすることをお勧めします:")
    print("   pip install chardet")

# 基本設定
BASE_DIR = Path(__file__).resolve().parent
ENTRYPOINT_DIR = BASE_DIR / "entrypoint_fx"
# ENTRYPOINT_DIR = BASE_DIR / "entrypoint_fx_よくばり"
HISTORICAL_DATA_DIR = BASE_DIR / "input"
BACKTEST_RESULT_DIR = BASE_DIR / "backtest_results"
BACKTEST_RESULT_DIR.mkdir(exist_ok=True)

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(BACKTEST_RESULT_DIR / "backtest_fixed_complete.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class FXBacktestSystemComplete:
    """FXバックテストシステム（完全修正版 + ストップロス機能 + 3層戦略）"""
    
    def __init__(self, stop_loss_pips=None, take_profit_pips=None):
        """初期化
        
        Parameters:
        -----------
        stop_loss_pips : float, optional
            ストップロス設定（pips）。Noneの場合は無効
        take_profit_pips : float, optional
            テイクプロフィット設定（pips）。Noneの場合は無効
        """
        self.entrypoint_files = []
        self.backtest_results = []
        self.summary_stats = {}
        
        # ストップロス・テイクプロフィット設定
        self.stop_loss_pips = stop_loss_pips
        self.take_profit_pips = take_profit_pips
        
        # 通貨ペア設定
        self.currency_settings = {
            "USDJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "EURJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "GBPJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "AUDJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "CHFJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "CADJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "NZDJPY": {"pip_value": 0.01, "pip_multiplier": 100},
            "EURUSD": {"pip_value": 0.0001, "pip_multiplier": 10000},
            "GBPUSD": {"pip_value": 0.0001, "pip_multiplier": 10000},
            "AUDUSD": {"pip_value": 0.0001, "pip_multiplier": 10000},
            "NZDUSD": {"pip_value": 0.0001, "pip_multiplier": 10000},
            "USDCHF": {"pip_value": 0.0001, "pip_multiplier": 10000}
        }
        
        logger.info("FXバックテストシステム（完全修正版 + ストップロス機能 + 3層戦略）を初期化しました")
        if self.stop_loss_pips:
            logger.info(f"📉 ストップロス設定: {self.stop_loss_pips} pips")
        if self.take_profit_pips:
            logger.info(f"📈 テイクプロフィット設定: {self.take_profit_pips} pips")
        logger.info("🎯 3層戦略: BASE/EXPAND/ATR を有効化")
    
    def decide_layer(
            self,
            spread      : float,
            true_range  : float,
            dir_5m      : bool,
            dir_15m     : bool,
            dir_1h      : bool,
            sp30        : float,
            sp40        : float,
            tr40        : float,
            atr14       : float,
            atr14_med   : float
    ) -> str:
        """
        BASE : 低スプレッド & 低ボラ & 5 分と15 分が同一方向
        EXPAND : 中庸スプレッド以下 & MFT 完全一致 & 勢い(ATR 高)
        ATR : 上記以外
        """

        # ── BASE ──
        if (spread <= sp30) and (true_range <= tr40) and (dir_5m == dir_15m):
            return "BASE"

        # ── EXPAND ──
        if (spread <= sp40) and dir_5m and dir_15m and dir_1h and (atr14 > atr14_med):
            return "EXPAND"

        # ── ATR ──
        return "ATR"

    def get_layer_sl_tp(self, layer: str, atr14: float) -> tuple[int, int]:
        """
        BASE : SL 8 / TP 14
        EXPAND : SL 12 / TP 30
        ATR : SL = int(ATR14×1.3) / TP = SL×2
        """
        if layer == "BASE":
            return 8, 14

        if layer == "EXPAND":
            return 12, 30

        # layer == "ATR"
        sl = int(atr14 * 1.3)
        return sl, sl * 2

    @staticmethod
    def _calc_day_thresholds(df_day: pd.DataFrame) -> dict:
        """
        BASE／EXPAND 判定に用いる分位点を日次で計算して返す
        """
        return {
            "sp30"         : df_day["spread"].quantile(0.30),
            "sp35"         : df_day["spread"].quantile(0.35),
            "sp40"         : df_day["spread"].quantile(0.40),
            "tr40"         : df_day["true_range"].quantile(0.40),
            "tr50"         : df_day["true_range"].quantile(0.50),
            "atr14_median" : df_day["atr14"].median(),
        }

    def calculate_stop_loss_price(self, entry_price, direction, currency_pair):
        """ストップロス価格を計算"""
        if not self.stop_loss_pips:
            return None
        
        settings = self.currency_settings.get(currency_pair.replace('_', ''))
        if not settings:
            pip_value = 0.01 if 'JPY' in currency_pair else 0.0001
        else:
            pip_value = settings['pip_value']
        
        if direction.upper() in ['LONG', 'BUY']:
            # Longポジションの場合、エントリー価格より下にストップロス
            stop_loss_price = entry_price - (self.stop_loss_pips * pip_value)
        else:  # SHORT, SELL
            # Shortポジションの場合、エントリー価格より上にストップロス
            stop_loss_price = entry_price + (self.stop_loss_pips * pip_value)
        
        return stop_loss_price
    
    def calculate_take_profit_price(self, entry_price, direction, currency_pair):
        """テイクプロフィット価格を計算"""
        if not self.take_profit_pips:
            return None
        
        settings = self.currency_settings.get(currency_pair.replace('_', ''))
        if not settings:
            pip_value = 0.01 if 'JPY' in currency_pair else 0.0001
        else:
            pip_value = settings['pip_value']
        
        if direction.upper() in ['LONG', 'BUY']:
            # Longポジションの場合、エントリー価格より上にテイクプロフィット
            take_profit_price = entry_price + (self.take_profit_pips * pip_value)
        else:  # SHORT, SELL
            # Shortポジションの場合、エントリー価格より下にテイクプロフィット
            take_profit_price = entry_price - (self.take_profit_pips * pip_value)
        
        return take_profit_price
    
    def check_stop_loss_hit(self, current_price, stop_loss_price, direction):
        """ストップロスがヒットしたかチェック"""
        if stop_loss_price is None:
            return False
        
        if direction.upper() in ['LONG', 'BUY']:
            # Longポジション：現在価格がストップロス価格以下
            return current_price <= stop_loss_price
        else:  # SHORT, SELL
            # Shortポジション：現在価格がストップロス価格以上
            return current_price >= stop_loss_price
    
    def check_take_profit_hit(self, current_price, take_profit_price, direction):
        """テイクプロフィットがヒットしたかチェック"""
        if take_profit_price is None:
            return False
        
        if direction.upper() in ['LONG', 'BUY']:
            # Longポジション：現在価格がテイクプロフィット価格以上
            return current_price >= take_profit_price
        else:  # SHORT, SELL
            # Shortポジション：現在価格がテイクプロフィット価格以下
            return current_price <= take_profit_price
    
    def monitor_position_with_stop_loss(self, df_historical, entry_time, exit_time, entry_price, direction, currency_pair):
        """ストップロス・テイクプロフィット監視付きポジション管理（完全修正版）
        
        Returns:
        --------
        dict: {
            'exit_price': float,
            'actual_exit_time': datetime,
            'exit_reason': str,
            'max_favorable_pips': float,
            'max_adverse_pips': float
        }
        """
        try:
            # ストップロス・テイクプロフィット価格を計算
            stop_loss_price = self.calculate_stop_loss_price(entry_price, direction, currency_pair)
            take_profit_price = self.calculate_take_profit_price(entry_price, direction, currency_pair)
            
            logger.debug(f"       SL: {stop_loss_price}, TP: {take_profit_price}")
            
            # 時刻をdatetimeに変換
            entry_datetime = pd.to_datetime(entry_time)
            exit_datetime = pd.to_datetime(exit_time)
            
            logger.debug(f"       監視期間: {entry_datetime} ～ {exit_datetime}")
            
            # データの有効性チェック
            if df_historical.empty:
                logger.warning("       履歴データが空です")
                return None
            
            if 'timestamp' not in df_historical.columns:
                logger.warning(f"       timestampカラムがありません: {list(df_historical.columns)}")
                return None
            
            # データの時間範囲を確認
            df_sorted = df_historical.sort_values('timestamp').copy()
            data_min_time = df_sorted['timestamp'].min()
            data_max_time = df_sorted['timestamp'].max()
            
            logger.debug(f"       データ範囲: {data_min_time} ～ {data_max_time}")
            
            # エントリー時刻の調整（データ範囲内に調整）
            adjusted_entry_time = entry_datetime
            if entry_datetime < data_min_time:
                adjusted_entry_time = data_min_time
                logger.warning(f"       エントリー時刻を調整: {entry_datetime} -> {adjusted_entry_time}")
            elif entry_datetime > data_max_time:
                adjusted_entry_time = data_max_time
                logger.warning(f"       エントリー時刻を調整: {entry_datetime} -> {adjusted_entry_time}")
            
            # エグジット時刻の調整（データ範囲内に調整）
            adjusted_exit_time = exit_datetime
            if exit_datetime < data_min_time:
                adjusted_exit_time = data_min_time
                logger.warning(f"       エグジット時刻を調整: {exit_datetime} -> {adjusted_exit_time}")
            elif exit_datetime > data_max_time:
                adjusted_exit_time = data_max_time
                logger.warning(f"       エグジット時刻を調整: {exit_datetime} -> {adjusted_exit_time}")
            
            # 調整後の時刻で期間データを抽出
            mask = (df_sorted['timestamp'] >= adjusted_entry_time) & (df_sorted['timestamp'] <= adjusted_exit_time)
            period_data = df_sorted[mask].copy()
            
            # 期間データが空の場合の対処
            if period_data.empty:
                logger.warning(f"       期間データが空です。最近接データを使用します")
                # エントリー時刻に最も近いデータを取得
                df_sorted['time_diff'] = abs(df_sorted['timestamp'] - adjusted_entry_time)
                closest_entry_idx = df_sorted['time_diff'].idxmin()
                
                # エグジット時刻に最も近いデータを取得
                df_sorted['time_diff'] = abs(df_sorted['timestamp'] - adjusted_exit_time)
                closest_exit_idx = df_sorted['time_diff'].idxmin()
                
                # エントリーからエグジットまでの範囲を取得
                start_idx = min(closest_entry_idx, closest_exit_idx)
                end_idx = max(closest_entry_idx, closest_exit_idx)
                
                period_data = df_sorted.iloc[start_idx:end_idx+1].copy()
                
                if period_data.empty:
                    # それでも空の場合は、最近接の1つのデータポイントを使用
                    period_data = df_sorted.iloc[[closest_entry_idx]].copy()
                    logger.warning(f"       単一データポイントを使用: {period_data.iloc[0]['timestamp']}")
            
            logger.debug(f"       監視データ数: {len(period_data)}")
            
            # 監視用の価格カラムを決定
            if direction.upper() in ['LONG', 'BUY']:
                price_columns = ['close_bid', 'low_bid', 'high_bid', 'open_bid']
            else:  # SHORT, SELL
                price_columns = ['close_ask', 'low_ask', 'high_ask', 'open_ask']
            
            # 利用可能な価格カラムを選択
            price_column = None
            for col in price_columns:
                if col in period_data.columns:
                    price_column = col
                    break
            
            if price_column is None:
                logger.warning(f"       監視用価格カラムが見つかりません: {list(period_data.columns)}")
                # フォールバック: 数値カラムを探す
                numeric_columns = period_data.select_dtypes(include=[np.number]).columns
                if len(numeric_columns) > 0:
                    price_column = numeric_columns[0]
                    logger.warning(f"       フォールバック価格カラム使用: {price_column}")
                else:
                    logger.error(f"       使用可能な価格カラムがありません")
                    return None
            
            logger.debug(f"       使用価格カラム: {price_column}")
            
            # 含み損益の追跡
            max_favorable_pips = 0
            max_adverse_pips = 0
            
            # 各時点でストップロス・テイクプロフィットをチェック
            for idx, row in period_data.iterrows():
                if pd.isna(row[price_column]):
                    continue
                    
                current_price = float(row[price_column])
                current_time = row['timestamp']
                
                # 現在のpipsを計算
                current_pips = self.calculate_pips(entry_price, current_price, currency_pair, direction)
                
                # 最大含み益・含み損を更新
                if current_pips > max_favorable_pips:
                    max_favorable_pips = current_pips
                if current_pips < max_adverse_pips:
                    max_adverse_pips = current_pips
                
                # ストップロスチェック
                if self.check_stop_loss_hit(current_price, stop_loss_price, direction):
                    logger.info(f"       🛑 ストップロスヒット: {current_price} @ {current_time}")
                    return {
                        'exit_price': stop_loss_price,
                        'actual_exit_time': current_time,
                        'exit_reason': 'STOP_LOSS',
                        'max_favorable_pips': max_favorable_pips,
                        'max_adverse_pips': max_adverse_pips
                    }
                
                # テイクプロフィットチェック
                if self.check_take_profit_hit(current_price, take_profit_price, direction):
                    logger.info(f"       🎯 テイクプロフィットヒット: {current_price} @ {current_time}")
                    return {
                        'exit_price': take_profit_price,
                        'actual_exit_time': current_time,
                        'exit_reason': 'TAKE_PROFIT',
                        'max_favorable_pips': max_favorable_pips,
                        'max_adverse_pips': max_adverse_pips
                    }
            
            # 時間切れ（通常のエグジット）
            final_row = period_data.iloc[-1]
            final_price = float(final_row[price_column])
            final_time = final_row['timestamp']
            
            logger.debug(f"       ⏰ 時間切れエグジット: {final_price} @ {final_time}")
            return {
                'exit_price': final_price,
                'actual_exit_time': final_time,
                'exit_reason': 'TIME_EXIT',
                'max_favorable_pips': max_favorable_pips,
                'max_adverse_pips': max_adverse_pips
            }
            
        except Exception as e:
            logger.error(f"       ストップロス監視エラー: {e}")
            import traceback
            traceback.print_exc()
            
            # エラー時のフォールバック処理
            try:
                if df_historical.empty:
                    return None
                
                # 最後のデータポイントを使用
                last_row = df_historical.iloc[-1]
                
                # 価格カラムを探す
                numeric_cols = df_historical.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) > 0:
                    price_col = numeric_cols[0]
                    fallback_price = float(last_row[price_col])
                    fallback_time = last_row.get('timestamp', pd.Timestamp.now())
                    
                    logger.warning(f"       フォールバック処理: {fallback_price} @ {fallback_time}")
                    
                    return {
                        'exit_price': fallback_price,
                        'actual_exit_time': fallback_time,
                        'exit_reason': 'ERROR_FALLBACK',
                        'max_favorable_pips': 0,
                        'max_adverse_pips': 0
                    }
            except Exception as fallback_error:
                logger.error(f"       フォールバック処理もエラー: {fallback_error}")
            
            return None
            
    def inspect_zip_file_structure(self, zip_path):
        """ZIPファイルの構造を詳細調査"""
        logger.info(f"🔍 ZIPファイル構造調査: {zip_path.name}")
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                logger.info(f"   総ファイル数: {len(file_list)}")
                
                # ファイルリストを表示（最初の10件）
                for i, file_name in enumerate(file_list[:10]):
                    logger.info(f"   {i+1:2d}. {file_name}")
                
                if len(file_list) > 10:
                    logger.info(f"   ... 他 {len(file_list) - 10} ファイル")
                
                # CSVファイルのみを抽出
                csv_files = [f for f in file_list if f.lower().endswith('.csv')]
                logger.info(f"   CSVファイル数: {len(csv_files)}")
                
                if csv_files:
                    # 最初のCSVファイルの詳細を調査
                    test_csv = csv_files[0]
                    logger.info(f"   テストCSV: {test_csv}")
                    
                    with zip_ref.open(test_csv) as csv_file:
                        # ファイルサイズチェック
                        raw_data = csv_file.read()
                        file_size = len(raw_data)
                        logger.info(f"   ファイルサイズ: {file_size:,} bytes")
                        
                        if file_size == 0:
                            logger.error("   ❌ ファイルサイズが0です")
                            return None
                        
                        # 先頭データをダンプ（最初の500文字）
                        preview_data = raw_data[:500]
                        logger.info(f"   ファイル先頭データ（500文字）:")
                        
                        # 複数エンコーディングで試行
                        for encoding in ['utf-8', 'shift_jis', 'cp932', 'iso-8859-1']:
                            try:
                                decoded = preview_data.decode(encoding)
                                logger.info(f"   エンコーディング {encoding}:")
                                lines = decoded.split('\n')[:5]
                                for j, line in enumerate(lines, 1):
                                    logger.info(f"     {j}: {repr(line)}")
                                break
                            except UnicodeDecodeError:
                                continue
                        
                        return test_csv
                else:
                    logger.error("   ❌ CSVファイルが見つかりません")
                    return None
                    
        except Exception as e:
            logger.error(f"   ❌ ZIPファイル調査エラー: {e}")
            return None
    
    def load_entrypoint_files(self):
        """エントリーポイントファイルの読み込み"""
        logger.info("📁 エントリーポイントファイルを読み込んでいます...")
        
        files = list(ENTRYPOINT_DIR.glob("entrypoints_*.csv"))
        # files = list(ENTRYPOINT_DIR.glob("よくばりエントリー_*.csv"))
        files.sort(key=lambda x: x.name)
        
        self.entrypoint_files = []
        
        for file_path in files:
            try:
                # ファイル名から日付を抽出
                date_match = re.search(r'entrypoints_(\d{8})\.csv', file_path.name)
                # date_match = re.search(r'よくばりエントリー_(\d{8})\.csv', file_path.name)
                if date_match:
                    date_str = date_match.group(1)
                    date_obj = datetime.strptime(date_str, '%Y%m%d')
                    
                    # CSV読み込み（複数エンコーディング対応）
                    df = self.read_csv_with_encoding(file_path)
                    if df is not None and not df.empty:
                        self.entrypoint_files.append({
                            'date': date_obj,
                            'date_str': date_str,
                            'file_path': file_path,
                            'data': df
                        })
                        
                        logger.info(f"  ✅ {file_path.name}: {len(df)}エントリーポイント")
                    else:
                        logger.warning(f"  ❌ {file_path.name}: 読み込み失敗またはデータなし")
                    
            except Exception as e:
                logger.error(f"  ❌ {file_path.name}: 読み込みエラー - {e}")
        
        logger.info(f"📊 総計 {len(self.entrypoint_files)} ファイル読み込み完了")
        
        # 最初のエントリーファイルの構造を表示
        if self.entrypoint_files:
            sample_df = self.entrypoint_files[0]['data']
            logger.info(f"📝 エントリーファイル構造サンプル:")
            logger.info(f"   カラム: {list(sample_df.columns)}")
            logger.info(f"   最初の行:")
            for col in sample_df.columns:
                logger.info(f"     {col}: {sample_df.iloc[0][col]}")
    
    def read_csv_with_encoding(self, file_path):
        """複数エンコーディングでCSV読み込み"""
        encodings = ['utf-8', 'utf-8-sig', 'shift_jis', 'cp932', 'euc_jp', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                if not df.empty and len(df.columns) > 1:
                    logger.debug(f"    エンコーディング成功: {encoding}")
                    return df
            except Exception:
                continue
        
        # chardetを使用した文字コード自動判定（利用可能な場合）
        if CHARDET_AVAILABLE:
            try:
                with open(file_path, 'rb') as f:
                    raw_data = f.read()
                    detected = chardet.detect(raw_data)
                    encoding = detected['encoding']
                    if encoding:
                        df = pd.read_csv(file_path, encoding=encoding)
                        if not df.empty and len(df.columns) > 1:
                            logger.debug(f"    文字コード自動判定成功: {encoding}")
                            return df
            except Exception:
                pass
        
        logger.error(f"    全エンコーディング失敗: {file_path}")
        return None
    
    def find_historical_data_file(self, currency_pair, date_obj):
        """指定日付の過去データファイルを検索（完全修正版）"""
        try:
            # 通貨ペア名を統一（アンダースコアなし）
            clean_currency = currency_pair.replace('_', '')
            
            # 年月を取得
            year_month = date_obj.strftime('%Y%m')
            
            logger.debug(f"🔍 過去データ検索: {clean_currency} {year_month}")
            
            # ZIPファイルパターンを作成（より広範囲に検索）
            zip_patterns = [
                f"{clean_currency}_{year_month}.zip",
                f"{clean_currency.upper()}_{year_month}.zip",
                f"{clean_currency.lower()}_{year_month}.zip"
            ]
            
            # ファイルを検索
            for pattern in zip_patterns:
                zip_path = HISTORICAL_DATA_DIR / pattern
                if zip_path.exists():
                    logger.info(f"  ✅ 過去データファイル発見: {pattern}")
                    return zip_path
            
            # 見つからない場合は前後の月も検索
            for month_offset in [-1, 1, -2, 2]:
                try:
                    target_date = date_obj + timedelta(days=month_offset * 30)
                    alt_year_month = target_date.strftime('%Y%m')
                    
                    for pattern_base in [clean_currency, clean_currency.upper(), clean_currency.lower()]:
                        alt_pattern = f"{pattern_base}_{alt_year_month}.zip"
                        alt_zip_path = HISTORICAL_DATA_DIR / alt_pattern
                        if alt_zip_path.exists():
                            logger.warning(f"  ⚠️  代替データファイル使用: {alt_pattern}")
                            return alt_zip_path
                except Exception:
                    continue
            
            # 全ZIPファイルをリストして確認
            all_zips = list(HISTORICAL_DATA_DIR.glob("*.zip"))
            logger.warning(f"  ❌ 過去データファイルが見つかりません: {currency_pair} {year_month}")
            logger.info(f"  📂 利用可能なZIPファイル:")
            for zip_file in all_zips[:10]:  # 最初の10件のみ表示
                logger.info(f"     {zip_file.name}")
            if len(all_zips) > 10:
                logger.info(f"     ... 他 {len(all_zips) - 10} ファイル")
            
            return None
            
        except Exception as e:
            logger.error(f"    過去データファイル検索エラー: {e}")
            return None

    def safe_csv_read_from_zip(self, zip_path, target_date):
        """ZIPファイルからCSVを安全に読み込み（デバッグ強化版 + 3層戦略データ追加）"""
        logger.info(f"📄 CSV読み込み開始: {zip_path.name}")
        
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                
                # CSVファイルを検索
                csv_files = [f for f in file_list if f.lower().endswith('.csv') and not f.startswith('__MACOSX')]
                
                if not csv_files:
                    logger.error(f"   ❌ CSVファイルが見つかりません")
                    return None
                
                logger.info(f"   📁 CSVファイル候補: {len(csv_files)}件")
                
                # 対象日付に最も近いファイルを選択
                target_date_str = target_date.strftime('%Y%m%d')
                best_file = None
                best_score = float('inf')
                
                for csv_file in csv_files:
                    # 日付を含むファイルを優先
                    if target_date_str in csv_file:
                        best_file = csv_file
                        best_score = 0
                        break
                    
                    # ファイル名から日付を抽出
                    date_matches = re.findall(r'(\d{8})', csv_file)
                    if date_matches:
                        for date_str in date_matches:
                            try:
                                file_date = datetime.strptime(date_str, '%Y%m%d')
                                diff_days = abs((file_date - target_date).days)
                                if diff_days < best_score:
                                    best_score = diff_days
                                    best_file = csv_file
                            except ValueError:
                                continue
                
                # 日付一致がない場合は最初のCSVを使用
                if best_file is None:
                    best_file = csv_files[0]
                    logger.warning(f"   ⚠️  日付一致なし、{best_file}を使用")
                else:
                    logger.info(f"   ✅ 選択されたCSV: {best_file}")
                
                # CSVファイルを読み込み
                with zip_ref.open(best_file) as csv_file_obj:
                    # ファイル内容を読み込み
                    raw_data = csv_file_obj.read()
                    
                    if len(raw_data) == 0:
                        logger.error(f"   ❌ ファイルが空です: {best_file}")
                        return None
                    
                    logger.info(f"   📊 ファイルサイズ: {len(raw_data):,} bytes")
                    
                    # エンコーディングを検出して読み込み
                    df = self.decode_and_parse_csv(raw_data, best_file)
                    
                    if df is not None and not df.empty:
                        logger.info(f"   ✅ CSV読み込み成功: {len(df)}行, {len(df.columns)}列")
                        
                        # データ構造をログ出力
                        logger.info(f"   📋 カラム: {list(df.columns)}")
                        if len(df) > 0:
                            logger.info(f"   📝 サンプルデータ（最初の行）:")
                            for col in df.columns[:5]:  # 最初の5列のみ
                                logger.info(f"     {col}: {df.iloc[0][col]}")
                        
                        # 3層戦略用のデータを追加
                        df = self.add_layer_strategy_data(df)
                        
                        return df
                    else:
                        logger.error(f"   ❌ CSV解析失敗: {best_file}")
                        return None
        
        except Exception as e:
            logger.error(f"   ❌ ZIPファイル処理エラー: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def add_layer_strategy_data(self, df):
        """3層戦略用のデータ列を追加"""
        try:
            logger.info("   🎯 3層戦略データを追加中...")
            
            # 1. spread, true_range, mid_close を計算
            if 'close_ask' in df.columns and 'close_bid' in df.columns:
                df['spread'] = df['close_ask'] - df['close_bid']
                df['mid_close'] = (df['close_ask'] + df['close_bid']) / 2
            else:
                logger.warning("   ⚠️  close_ask/close_bid カラムがありません")
                # フォールバック: 利用可能な価格カラムを使用
                price_cols = [col for col in df.columns if any(price in col.lower() for price in ['close', 'price'])]
                if price_cols:
                    df['spread'] = 0.001  # デフォルトスプレッド
                    df['mid_close'] = df[price_cols[0]]
                else:
                    df['spread'] = 0.001
                    df['mid_close'] = 100.0  # デフォルト価格
            
            if 'high_ask' in df.columns and 'low_bid' in df.columns:
                df['true_range'] = df['high_ask'] - df['low_bid']
            else:
                logger.warning("   ⚠️  high_ask/low_bid カラムがありません")
                df['true_range'] = df['spread'] * 2  # フォールバック
            
            # 2. ATR14を計算
            df['atr14'] = df['true_range'].rolling(14, min_periods=1).mean()
            
            # 3. MFT方向フラグを計算（rolling max との比較）
            # Longトレンド判定: mid_close > rolling(n).max().shift(1)
            df['dir_5m'] = df['mid_close'] > df['mid_close'].rolling(5, min_periods=1).max().shift(1)
            df['dir_15m'] = df['mid_close'] > df['mid_close'].rolling(15, min_periods=1).max().shift(1)
            df['dir_1h'] = df['mid_close'] > df['mid_close'].rolling(60, min_periods=1).max().shift(1)
            
            # NaN値を前方補完
            df['dir_5m'] = df['dir_5m'].fillna(method='ffill').fillna(False)
            df['dir_15m'] = df['dir_15m'].fillna(method='ffill').fillna(False)
            df['dir_1h'] = df['dir_1h'].fillna(method='ffill').fillna(False)
            
            # 4. 統計値を計算（後でエントリー時に使用）
            df['spread_q25'] = df['spread'].quantile(0.25)
            df['spread_q50'] = df['spread'].quantile(0.50)
            df['true_range_q75'] = df['true_range'].quantile(0.75)
            
            logger.info(f"   ✅ 3層戦略データ追加完了")
            logger.info(f"     spread範囲: {df['spread'].min():.5f} - {df['spread'].max():.5f}")
            logger.info(f"     true_range範囲: {df['true_range'].min():.5f} - {df['true_range'].max():.5f}")
            logger.info(f"     ATR14平均: {df['atr14'].mean():.5f}")
            
            return df
            
        except Exception as e:
            logger.error(f"   ❌ 3層戦略データ追加エラー: {e}")
            import traceback
            traceback.print_exc()
            return df
    
    def get_entry_market_conditions(self, df_historical, entry_datetime):
        """エントリー直前の市場条件を取得"""
        try:
            # エントリー時刻に最も近いデータを取得
            df_sorted = df_historical.sort_values('timestamp').copy()
            df_sorted['time_diff'] = abs(df_sorted['timestamp'] - pd.to_datetime(entry_datetime))
            closest_idx = df_sorted['time_diff'].idxmin()
            entry_row = df_sorted.loc[closest_idx]
            
            # 必要な値を抽出
            conditions = {
                'spread': entry_row.get('spread', 0.001),
                'true_range': entry_row.get('true_range', 0.002),
                'atr14': entry_row.get('atr14', 0.001),
                'dir_5m': entry_row.get('dir_5m', False),
                'dir_15m': entry_row.get('dir_15m', False),
                'dir_1h': entry_row.get('dir_1h', False),
                'spread_q25': entry_row.get('spread_q25', 0.0005),
                'spread_q50': entry_row.get('spread_q50', 0.001),
                'true_range_q75': entry_row.get('true_range_q75', 0.003)
            }
            
            logger.debug(f"     市場条件: spread={conditions['spread']:.5f}, tr={conditions['true_range']:.5f}, atr14={conditions['atr14']:.5f}")
            logger.debug(f"     方向フラグ: 5m={conditions['dir_5m']}, 15m={conditions['dir_15m']}, 1h={conditions['dir_1h']}")
            
            return conditions
            
        except Exception as e:
            logger.error(f"     市場条件取得エラー: {e}")
            # デフォルト値を返す
            return {
                'spread': 0.001, 'true_range': 0.002, 'atr14': 0.001,
                'dir_5m': False, 'dir_15m': False, 'dir_1h': False,
                'spread_q25': 0.0005, 'spread_q50': 0.001, 'true_range_q75': 0.003
            }
    
    def decode_and_parse_csv(self, raw_data, file_name):
        """バイナリデータをCSVとして解析"""
        logger.debug(f"   🔤 エンコーディング検出開始: {file_name}")
        
        # chardetでエンコーディング検出（利用可能な場合）
        if CHARDET_AVAILABLE:
            try:
                detected = chardet.detect(raw_data)
                detected_encoding = detected.get('encoding')
                confidence = detected.get('confidence', 0)
                logger.info(f"   🎯 検出エンコーディング: {detected_encoding} (信頼度: {confidence:.2f})")
                
                if detected_encoding and confidence > 0.7:
                    encodings = [detected_encoding] + ['utf-8', 'shift_jis', 'cp932', 'iso-8859-1']
                else:
                    encodings = ['utf-8', 'shift_jis', 'cp932', 'iso-8859-1', detected_encoding]
            except Exception:
                encodings = ['utf-8', 'shift_jis', 'cp932', 'iso-8859-1']
        else:
            encodings = ['utf-8', 'shift_jis', 'cp932', 'euc_jp', 'iso-8859-1']
        
        # 各エンコーディングで試行
        for encoding in encodings:
            if encoding is None:
                continue
                
            try:
                # デコード
                csv_content = raw_data.decode(encoding)
                
                # 内容を確認（空でないか）
                if not csv_content.strip():
                    logger.warning(f"     空のコンテンツ: {encoding}")
                    continue
                
                # 区切り文字を検出
                lines = csv_content.split('\n')
                first_line = lines[0] if lines else ""
                
                # 区切り文字の候補
                separators = [',', '\t', ';', '|']
                best_sep = ','
                max_columns = 0
                
                for sep in separators:
                    col_count = len(first_line.split(sep))
                    if col_count > max_columns:
                        max_columns = col_count
                        best_sep = sep
                
                logger.debug(f"     エンコーディング: {encoding}, 区切り文字: '{best_sep}', カラム数: {max_columns}")
                
                # 最低限のカラム数チェック
                if max_columns < 4:
                    logger.warning(f"     カラム数不足: {max_columns}")
                    continue
                
                # DataFrameに変換
                df = pd.read_csv(io.StringIO(csv_content), sep=best_sep)
                
                # データが正常に読み込まれたかチェック
                if df.empty:
                    logger.warning(f"     空のDataFrame: {encoding}")
                    continue
                
                if len(df.columns) < 4:
                    logger.warning(f"     カラム数不足: {len(df.columns)}")
                    continue
                
                # カラム名を標準化
                df = self.normalize_columns_improved(df)
                
                # タイムスタンプを処理
                df = self.process_timestamp_improved(df)
                
                logger.info(f"   ✅ エンコーディング成功: {encoding}")
                return df
                
            except UnicodeDecodeError:
                logger.debug(f"     デコードエラー: {encoding}")
                continue
            except Exception as e:
                logger.debug(f"     解析エラー {encoding}: {e}")
                continue
        
        logger.error(f"   ❌ 全エンコーディング失敗: {file_name}")
        return None
    
    def normalize_columns_improved(self, df):
        """カラム名を標準化（改良版）"""
        renamed_columns = {}
        
        # より柔軟なカラム名マッピング
        column_patterns = {
            'timestamp': [
                '日時', 'timestamp', 'time', '時刻', 'datetime', 'date',
                'Date', 'Time', 'DateTime', '时间', 'Date/Time'
            ],
            'open_bid': [
                '始値(BID)', 'open_bid', 'bid_open', 'open bid', 'Open BID',
                'BID Open', '始値BID', 'BID始値', 'open(bid)', 'Open(BID)'
            ],
            'high_bid': [
                '高値(BID)', 'high_bid', 'bid_high', 'high bid', 'High BID',
                'BID High', '高値BID', 'BID高値', 'high(bid)', 'High(BID)'
            ],
            'low_bid': [
                '安値(BID)', 'low_bid', 'bid_low', 'low bid', 'Low BID',
                'BID Low', '安値BID', 'BID安値', 'low(bid)', 'Low(BID)'
            ],
            'close_bid': [
                '終値(BID)', 'close_bid', 'bid_close', 'close bid', 'Close BID',
                'BID Close', '終値BID', 'BID終値', 'close(bid)', 'Close(BID)'
            ],
            'open_ask': [
                '始値(ASK)', 'open_ask', 'ask_open', 'open ask', 'Open ASK',
                'ASK Open', '始値ASK', 'ASK始値', 'open(ask)', 'Open(ASK)'
            ],
            'high_ask': [
                '高値(ASK)', 'high_ask', 'ask_high', 'high ask', 'High ASK',
                'ASK High', '高値ASK', 'ASK高値', 'high(ask)', 'High(ASK)'
            ],
            'low_ask': [
                '安値(ASK)', 'low_ask', 'ask_low', 'low ask', 'Low ASK',
                'ASK Low', '安値ASK', 'ASK安値', 'low(ask)', 'Low(ASK)'
            ],
            'close_ask': [
                '終値(ASK)', 'close_ask', 'ask_close', 'close ask', 'Close ASK',
                'ASK Close', '終値ASK', 'ASK終値', 'close(ask)', 'Close(ASK)'
            ]
        }
        
        # 完全一致を優先
        for col in df.columns:
            col_str = str(col).strip()
            found = False
            
            for standard_name, patterns in column_patterns.items():
                if col_str in patterns:
                    renamed_columns[col] = standard_name
                    found = True
                    break
            
            # 部分一致・キーワードベース
            if not found:
                col_lower = col_str.lower()
                
                # タイムスタンプ関連
                if any(keyword in col_lower for keyword in ['時', 'time', 'date']):
                    renamed_columns[col] = 'timestamp'
                # BID関連
                elif 'bid' in col_lower:
                    if any(keyword in col_lower for keyword in ['始', 'open']):
                        renamed_columns[col] = 'open_bid'
                    elif any(keyword in col_lower for keyword in ['高', 'high']):
                        renamed_columns[col] = 'high_bid'
                    elif any(keyword in col_lower for keyword in ['安', 'low']):
                        renamed_columns[col] = 'low_bid'
                    elif any(keyword in col_lower for keyword in ['終', 'close']):
                        renamed_columns[col] = 'close_bid'
                # ASK関連
                elif 'ask' in col_lower:
                    if any(keyword in col_lower for keyword in ['始', 'open']):
                        renamed_columns[col] = 'open_ask'
                    elif any(keyword in col_lower for keyword in ['高', 'high']):
                        renamed_columns[col] = 'high_ask'
                    elif any(keyword in col_lower for keyword in ['安', 'low']):
                        renamed_columns[col] = 'low_ask'
                    elif any(keyword in col_lower for keyword in ['終', 'close']):
                        renamed_columns[col] = 'close_ask'
        
        if renamed_columns:
            df = df.rename(columns=renamed_columns)
            logger.debug(f"     カラム名標準化: {len(renamed_columns)}個")
            logger.debug(f"     マッピング: {renamed_columns}")
        
        return df
    
    def process_timestamp_improved(self, df):
        """タイムスタンプ処理（改良版）"""
        try:
            if 'timestamp' in df.columns:
                # 既にdatetime型の場合
                if pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                    logger.debug("     タイムスタンプ既にdatetime型")
                    return df
                
                # 文字列からdatetimeに変換
                timestamp_formats = [
                    '%Y/%m/%d %H:%M:%S',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y/%m/%d %H:%M',
                    '%Y-%m-%d %H:%M',
                    '%m/%d/%Y %H:%M:%S',
                    '%d/%m/%Y %H:%M:%S',
                    '%Y%m%d %H:%M:%S',
                    '%Y%m%d %H%M%S',
                    '%Y.%m.%d %H:%M:%S',
                    '%d.%m.%Y %H:%M:%S'
                ]
                
                for fmt in timestamp_formats:
                    try:
                        df['timestamp'] = pd.to_datetime(df['timestamp'], format=fmt, errors='coerce')
                        # NaTでないものがあるかチェック
                        if not df['timestamp'].isna().all():
                            logger.debug(f"     タイムスタンプ変換成功: {fmt}")
                            return df
                    except Exception:
                        continue
                
                # フォーマット自動検出
                try:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], infer_datetime_format=True, errors='coerce')
                    if not df['timestamp'].isna().all():
                        logger.debug("     タイムスタンプ自動変換成功")
                        return df
                except Exception as e:
                    logger.debug(f"     タイムスタンプ自動変換失敗: {e}")
        
        except Exception as e:
            logger.warning(f"     タイムスタンプ処理エラー: {e}")
        
        return df
    
    def get_price_at_time_improved(self, df, target_time, direction):
        """指定時刻の価格を取得（完全修正版）"""
        try:
            if df.empty:
                logger.warning("     データが空です")
                return None, None
            
            if 'timestamp' not in df.columns:
                logger.warning(f"     タイムスタンプカラムなし。利用可能カラム: {list(df.columns)}")
                return None, None
            
            # 指定時刻のデータを検索
            target_datetime = pd.to_datetime(target_time)
            logger.debug(f"     目標時刻: {target_datetime}")
            
            # データを時系列順にソート
            df_sorted = df.sort_values('timestamp').copy()
            
            # データの時間範囲をログ出力
            min_time = df_sorted['timestamp'].min()
            max_time = df_sorted['timestamp'].max()
            logger.debug(f"     データ時間範囲: {min_time} ～ {max_time}")
            
            # 目標時刻に最も近いデータを検索
            df_sorted['time_diff'] = abs(df_sorted['timestamp'] - target_datetime)
            closest_idx = df_sorted['time_diff'].idxmin()
            row = df_sorted.loc[closest_idx]
            
            time_diff_seconds = df_sorted.loc[closest_idx, 'time_diff'].total_seconds()
            time_diff_minutes = time_diff_seconds / 60
            
            # 時刻差異をログ出力
            if time_diff_minutes > 60:  # 60分以上離れている場合は警告
                logger.warning(f"     時刻差異大: {time_diff_minutes:.1f}分")
            
            logger.debug(f"     最も近い時刻: {row['timestamp']} (差異: {time_diff_minutes:.1f}分)")
            
            # エントリー価格（方向に応じてBID/ASK）
            if direction.upper() in ['LONG', 'BUY']:
                price_columns = ['open_ask', 'close_ask', 'high_ask', 'low_ask']
            else:  # SHORT, SELL
                price_columns = ['open_bid', 'close_bid', 'high_bid', 'low_bid']
            
            # 利用可能な価格カラムを検索
            entry_price = None
            used_column = None
            
            for col in price_columns:
                if col in row.index and pd.notna(row[col]):
                    try:
                        entry_price = float(row[col])
                        used_column = col
                        logger.debug(f"     価格取得成功: {col} = {entry_price}")
                        break
                    except (ValueError, TypeError):
                        continue
            
            # 価格が見つからない場合のフォールバック処理
            if entry_price is None:
                logger.warning(f"     指定価格カラムが見つかりません")
                
                # 数値カラムを探す
                numeric_columns = []
                for col in row.index:
                    if pd.notna(row[col]):
                        try:
                            value = float(row[col])
                            if 50 <= value <= 300:  # 為替レートの一般的な範囲
                                numeric_columns.append((col, value))
                        except (ValueError, TypeError):
                            continue
                
                if numeric_columns:
                    # 価格らしい値を優先
                    col, value = numeric_columns[0]
                    entry_price = value
                    used_column = col
                    logger.warning(f"     フォールバック価格使用: {col} = {entry_price}")
                else:
                    # 最後の手段：任意の数値カラム
                    for col in row.index:
                        if pd.notna(row[col]):
                            try:
                                entry_price = float(row[col])
                                used_column = col
                                logger.warning(f"     緊急フォールバック: {col} = {entry_price}")
                                break
                            except (ValueError, TypeError):
                                continue
            
            if entry_price is None:
                logger.error(f"     利用可能な価格データなし")
                return None, None
            
            return entry_price, row['timestamp']
            
        except Exception as e:
            logger.error(f"     価格取得エラー: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def find_historical_data_file_improved(self, currency_pair, date_obj):
        """指定日付の過去データファイルを検索（改良版）"""
        try:
            # 通貨ペア名を統一（アンダースコアなし）
            clean_currency = currency_pair.replace('_', '')
            
            # 対象日付の年月を取得
            target_year_month = date_obj.strftime('%Y%m')
            target_date_str = date_obj.strftime('%Y%m%d')
            
            logger.debug(f"🔍 過去データ検索: {clean_currency} {target_date_str}")
            
            # 利用可能なZIPファイルをすべて取得
            all_zips = list(HISTORICAL_DATA_DIR.glob("*.zip"))
            matching_zips = []
            
            # 通貨ペアが一致するファイルを抽出
            for zip_file in all_zips:
                zip_name = zip_file.name.upper()
                if clean_currency.upper() in zip_name:
                    # 年月が一致するか確認
                    if target_year_month in zip_name:
                        matching_zips.append((zip_file, 0))  # 完全一致（優先度0）
                        logger.info(f"  ✅ 完全一致: {zip_file.name}")
                    else:
                        # 年月が近いファイルを探す
                        year_months_in_name = re.findall(r'(\d{6})', zip_name)
                        for ym in year_months_in_name:
                            try:
                                file_date = datetime.strptime(ym, '%Y%m')
                                target_date_ym = datetime.strptime(target_year_month, '%Y%m')
                                month_diff = abs((file_date.year - target_date_ym.year) * 12 + (file_date.month - target_date_ym.month))
                                if month_diff <= 2:  # 2ヶ月以内なら候補
                                    matching_zips.append((zip_file, month_diff + 1))
                                    logger.info(f"  ⚠️  近似一致: {zip_file.name} (差異: {month_diff}ヶ月)")
                            except ValueError:
                                continue
            
            if not matching_zips:
                logger.warning(f"  ❌ 過去データファイルが見つかりません: {currency_pair} {target_year_month}")
                return None
            
            # 優先度順にソート（優先度が低い順）
            matching_zips.sort(key=lambda x: x[1])
            selected_zip = matching_zips[0][0]
            
            logger.info(f"  📄 選択されたZIPファイル: {selected_zip.name}")
            return selected_zip
            
        except Exception as e:
            logger.error(f"    過去データファイル検索エラー: {e}")
            return None
    
    def calculate_pips(self, entry_price, exit_price, currency_pair, direction):
        """Pips計算（改良版）"""
        try:
            # 通貨ペア設定を取得
            settings = self.currency_settings.get(currency_pair.replace('_', ''))
            if not settings:
                # デフォルト設定
                if 'JPY' in currency_pair:
                    pip_multiplier = 100
                else:
                    pip_multiplier = 10000
                logger.debug(f"     デフォルト設定使用: {pip_multiplier}")
            else:
                pip_multiplier = settings['pip_multiplier']
            
            # 方向に応じたPips計算
            if direction.upper() in ['LONG', 'BUY']:
                pips = (exit_price - entry_price) * pip_multiplier
            else:  # SHORT, SELL
                pips = (entry_price - exit_price) * pip_multiplier
            
            logger.debug(f"     Pips計算: {entry_price} -> {exit_price} = {pips:.1f}pips ({direction})")
            return round(pips, 1)
            
        except Exception as e:
            logger.error(f"     Pips計算エラー: {e}")
            return 0.0

    def backtest_single_day(self, entry_data: dict) -> list[dict]:
        """
        1 日分のバックテストを実行し、取引結果をリストで返す。
        ▸ 改訂版：3 層戦略の“日次しきい値”を計算して decide_layer に渡す。

        Parameters
        ----------
        entry_data : dict
            {
                'date'     : datetime.date,
                'date_str' : 'YYYYMMDD',
                'data'     : DataFrame  # Step-3 で抽出した当日のエントリーポイント
            }

        Returns
        -------
        list[dict]
            1 トレード = 1 レコードの結果辞書（CSV 保存・集計用）
        """
        date_obj  = entry_data["date"]
        date_str  = entry_data["date_str"]
        df_entries = entry_data["data"]

        logger.info(f"📅 バックテスト実行: {date_str}（{len(df_entries)} エントリー）")

        daily_results          : list[dict] = []
        processed_currencies   : dict[str, dict] = {}   # {pair_date: {"df": DataFrame, "th": dict}}

        # ───────────────────────────────────────────────────────────────────
        # メインループ : 当日の各エントリーポイントを順に処理
        # ───────────────────────────────────────────────────────────────────
        for _, entry in df_entries.iterrows():
            try:
                currency_pair  = entry["通貨ペア"]
                direction      = entry["方向"].upper()
                entry_time_str = entry["Entry"]
                exit_time_str  = entry["Exit"]

                logger.info(f"  💱 {currency_pair} {direction} {entry_time_str}-{exit_time_str}")

                # ❶ 過去データ ZIP を取得
                zip_path = self.find_historical_data_file_improved(currency_pair, date_obj)
                if not zip_path:
                    logger.warning("    ❌ 過去データなし")
                    continue

                # ❷ キャッシュ確認
                cache_key = f"{currency_pair}_{date_str}"
                if cache_key not in processed_currencies:
                    # 初アクセス時：ZIP 構造チェック（最初の 1 回のみ）
                    if len(processed_currencies) == 0:
                        self.inspect_zip_file_structure(zip_path)

                    # 過去データ読み込み（spread / true_range / atr14 列が含まれている）
                    df_hist = self.safe_csv_read_from_zip(zip_path, date_obj)
                    if df_hist is None or df_hist.empty:
                        logger.warning("    ❌ データ読み込み失敗")
                        processed_currencies[cache_key] = None
                        continue

                    # しきい値を日次計算
                    th = self._calc_day_thresholds(df_hist)      # {"sp35", "sp40", "tr50", "atr14_median"}
                    processed_currencies[cache_key] = {"df": df_hist, "th": th}
                    logger.info(f"    📦 キャッシュ保存: {cache_key}")
                else:
                    cached = processed_currencies[cache_key]
                    if cached is None:
                        logger.warning("    ❌ キャッシュ空")
                        continue
                    df_hist, th = cached["df"], cached["th"]

                # ❸ エントリー直前 1 分の市場条件を取得
                entry_dt   = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {entry_time_str}"
                mkt_cond   = self.get_entry_market_conditions(df_hist, entry_dt)  # spread / true_range / dir_5m …

                # ショートの場合は方向フラグを反転
                dir_5m  = mkt_cond["dir_5m"]
                dir_15m = mkt_cond["dir_15m"]
                dir_1h  = mkt_cond["dir_1h"]
                if direction in ("SHORT", "SELL"):
                    dir_5m, dir_15m, dir_1h = (not dir_5m, not dir_15m, not dir_1h)

                # ❹ 3 層判定
                # layer = self.decide_layer(
                #     mkt_cond["spread"], mkt_cond["true_range"],
                #     dir_5m, dir_15m, dir_1h,
                #     th["sp35"], th["sp40"], th["tr50"],
                #     mkt_cond["atr14"], th["atr14_median"]
                # )
                layer = self.decide_layer(
                    # mc["spread"], mc["true_range"],
                    mkt_cond["spread"], mkt_cond["true_range"],
                    dir_5m, dir_15m, dir_1h,
                    th["sp30"], th["sp40"], th["tr40"],
                    # mc["atr14"], th["atr14_median"]
                    mkt_cond["atr14"], th["atr14_median"]
                )
                # ❺ 層別 SL / TP 設定
                sl_pips, tp_pips = self.get_layer_sl_tp(layer, mkt_cond["atr14"])
                original_sl, original_tp = self.stop_loss_pips, self.take_profit_pips
                self.stop_loss_pips, self.take_profit_pips = sl_pips, tp_pips
                logger.info(f"    🎯 層={layer}  SL={sl_pips}  TP={tp_pips}")

                # ❻ エントリー価格取得
                entry_price, actual_entry_time = self.get_price_at_time_improved(
                    df_hist, entry_dt, direction
                )
                if entry_price is None:
                    logger.warning("    ❌ エントリー価格取得失敗")
                    self.stop_loss_pips, self.take_profit_pips = original_sl, original_tp
                    continue

                # ❼ エグジット監視
                exit_dt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {exit_time_str}"
                exit_res = self.monitor_position_with_stop_loss(
                    df_hist, entry_dt, exit_dt, entry_price, direction, currency_pair
                )

                self.stop_loss_pips, self.take_profit_pips = original_sl, original_tp
                if exit_res is None:
                    logger.warning("    ❌ エグジット監視失敗")
                    continue

                # ❽ 結果集計
                exit_price        = exit_res["exit_price"]
                pips              = self.calculate_pips(entry_price, exit_price, currency_pair, direction)
                result_flag       = "WIN" if pips > 0 else "LOSS" if pips < 0 else "EVEN"

                trade_result = {
                    "date"              : date_str,
                    "currency_pair"     : currency_pair,
                    "direction"         : direction,
                    "entry_time"        : entry_time_str,
                    "exit_time"         : exit_time_str,
                    "actual_entry_time" : actual_entry_time,
                    "actual_exit_time"  : exit_res["actual_exit_time"],
                    "entry_price"       : entry_price,
                    "exit_price"        : exit_price,
                    "pips"              : pips,
                    "result"            : result_flag,
                    "exit_reason"       : exit_res["exit_reason"],
                    "max_favorable_pips": exit_res["max_favorable_pips"],
                    "max_adverse_pips"  : exit_res["max_adverse_pips"],
                    "layer"             : layer,
                    "sl_pips"           : sl_pips,
                    "tp_pips"           : tp_pips,
                    "score"             : entry.get("実用スコア", 0.0),
                    "short_win_rate"    : entry.get("短期勝率", 0.0),
                    "mid_win_rate"      : entry.get("中期勝率", 0.0),
                    "long_win_rate"     : entry.get("長期勝率", 0.0),
                }
                daily_results.append(trade_result)

                status = "🎯" if exit_res["exit_reason"] == "TAKE_PROFIT" else \
                         "🛑" if exit_res["exit_reason"] == "STOP_LOSS"   else "⏰"
                logger.info(f"    ✅ {status} {currency_pair} {direction} [{layer}] {pips:.1f}pips ({result_flag})")

            except Exception as e:   # noqa: BLE001
                logger.error(f"    ❌ 取引分析エラー: {e}", exc_info=True)
                continue

        logger.info(f"  ✅ 日次完了: {len(daily_results)}件")
        return daily_results

    
    def run_backtest(self):
        """バックテスト実行（エラー耐性強化版 + 3層戦略集計）"""
        logger.info("=" * 80)
        logger.info("🚀 FXバックテスト開始（エラー耐性強化版 + 3層戦略）")
        
        try:
            # エントリーポイントファイル読み込み
            self.load_entrypoint_files()
            
            if not self.entrypoint_files:
                logger.error("❌ エントリーポイントファイルがありません")
                return
            
            # 利用可能な過去データファイルを確認
            logger.info("📂 利用可能な過去データファイルを確認中...")
            all_zips = list(HISTORICAL_DATA_DIR.glob("*.zip"))
            logger.info(f"   総ZIPファイル数: {len(all_zips)}")
            
            if not all_zips:
                logger.error(f"❌ 過去データファイルが見つかりません: {HISTORICAL_DATA_DIR}")
                logger.info("💡 ヒント:")
                logger.info("   1. inputフォルダに通貨ペアのZIPファイルを配置してください")
                logger.info("   2. ファイル名は 'USDJPY_YYYYMM.zip' 形式にしてください")
                return
            
            # 各日のバックテストを実行
            logger.info("=" * 60)
            logger.info("🔄 バックテスト実行開始")
            
            all_results = []
            successful_days = 0
            total_trades = 0
            error_count = 0
            
            for i, entry_data in enumerate(self.entrypoint_files, 1):
                try:
                    logger.info(f"📊 進捗: {i}/{len(self.entrypoint_files)} ({i/len(self.entrypoint_files)*100:.1f}%)")
                    
                    daily_results = self.backtest_single_day(entry_data)
                    
                    if daily_results:
                        all_results.extend(daily_results)
                        successful_days += 1
                        total_trades += len(daily_results)
                        logger.info(f"   📈 累計取引数: {total_trades}")
                    else:
                        logger.warning(f"   ⚠️  {entry_data['date_str']}: 分析可能な取引なし")
                        
                except Exception as day_error:
                    error_count += 1
                    logger.error(f"   ❌ {entry_data['date_str']}: バックテストエラー - {day_error}")
                    if error_count > len(self.entrypoint_files) * 0.5:  # エラー率が50%を超えた場合
                        logger.error("❌ エラー率が高すぎます。処理を中断します")
                        break
                    continue
            
            self.backtest_results = all_results
            
            # 結果サマリー
            logger.info("=" * 80)
            logger.info("📈 バックテスト結果サマリー")
            logger.info(f"  処理日数: {len(self.entrypoint_files)}日")
            logger.info(f"  成功日数: {successful_days}日")
            logger.info(f"  エラー日数: {error_count}日")
            logger.info(f"  総取引数: {total_trades}件")
            
            if total_trades > 0:
                wins = len([r for r in all_results if r['result'] == 'WIN'])
                losses = len([r for r in all_results if r['result'] == 'LOSS'])
                evens = len([r for r in all_results if r['result'] == 'EVEN'])
                win_rate = wins / total_trades * 100
                total_pips = sum(r['pips'] for r in all_results)
                avg_pips = total_pips / total_trades
                
                logger.info(f"  勝率: {win_rate:.1f}% ({wins}勝 {losses}敗 {evens}分)")
                logger.info(f"  総Pips: {total_pips:.1f}")
                logger.info(f"  平均Pips/取引: {avg_pips:.1f}")
                
                # ストップロス統計
                if self.stop_loss_pips:
                    stop_loss_hits = len([r for r in all_results if r.get('exit_reason') == 'STOP_LOSS'])
                    take_profit_hits = len([r for r in all_results if r.get('exit_reason') == 'TAKE_PROFIT'])
                    time_exits = len([r for r in all_results if r.get('exit_reason') == 'TIME_EXIT'])
                    
                    logger.info(f"  ストップロス発動: {stop_loss_hits}回 ({stop_loss_hits/total_trades*100:.1f}%)")
                    logger.info(f"  テイクプロフィット発動: {take_profit_hits}回 ({take_profit_hits/total_trades*100:.1f}%)")
                    logger.info(f"  時間切れ: {time_exits}回 ({time_exits/total_trades*100:.1f}%)")
                
                # 3層戦略別集計を表示
                self.display_layer_summary(all_results)
                
                # 結果を保存
                self.save_results()
                self.calculate_statistics()
                self.generate_report()
            else:
                logger.warning("⚠️  分析可能な取引がありませんでした")
                logger.info("💡 トラブルシューティング:")
                logger.info("   1. エントリーポイントファイルの形式を確認してください")
                logger.info("   2. 過去データファイルのパスと形式を確認してください")
                logger.info("   3. 通貨ペア名の表記を確認してください")
            
            logger.info("🎉 バックテスト完了")
            
        except Exception as e:
            logger.error(f"❌ バックテスト実行中に致命的エラー: {e}")
            import traceback
            traceback.print_exc()
            
            logger.info("💡 エラー対処法:")
            logger.info("   1. ログファイルで詳細なエラー内容を確認")
            logger.info("   2. データファイルの破損チェック")
            logger.info("   3. ディスク容量とメモリ使用量の確認")
    
    def display_layer_summary(self, all_results):
        """3層戦略別の成績集計を表示"""
        try:
            logger.info("=" * 60)
            logger.info("🎯 3層戦略別成績サマリー")
            
            df_results = pd.DataFrame(all_results)
            
            if 'layer' not in df_results.columns:
                logger.warning("⚠️  層情報が見つかりません")
                return
            
            # 層別集計
            layer_summary = df_results.groupby('layer').agg({
                'pips': ['count', 'sum', 'mean'],
                'result': lambda x: (x == 'WIN').sum()  # 勝利数
            }).round(2)
            
            # プロフィットファクター計算
            layer_pf = {}
            for layer in df_results['layer'].unique():
                layer_data = df_results[df_results['layer'] == layer]
                wins_pips = layer_data[layer_data['pips'] > 0]['pips'].sum()
                loss_pips = abs(layer_data[layer_data['pips'] < 0]['pips'].sum())
                
                if loss_pips > 0:
                    profit_factor = wins_pips / loss_pips
                else:
                    profit_factor = wins_pips if wins_pips > 0 else 0
                
                layer_pf[layer] = profit_factor
            
            # ターミナル出力
            print("\n" + "=" * 60)
            print("====== SUMMARY by LAYER ======")
            print(f"{'layer':<8} {'trades':<8} {'net_pips':<10} {'avg_pips':<10} {'profit_factor':<15}")
            print("-" * 60)
            
            for layer in ['BASE', 'EXPAND', 'ATR']:
                if layer in layer_summary.index:
                    trades = int(layer_summary.loc[layer, ('pips', 'count')])
                    net_pips = int(layer_summary.loc[layer, ('pips', 'sum')])
                    avg_pips = layer_summary.loc[layer, ('pips', 'mean')]
                    profit_factor = layer_pf.get(layer, 0)
                    
                    print(f"{layer:<8} {trades:<8} {net_pips:<10} {avg_pips:<10.2f} {profit_factor:<15.2f}")
                else:
                    print(f"{layer:<8} {'0':<8} {'0':<10} {'0.00':<10} {'0.00':<15}")
            
            print("=" * 60)
            
            # ログにも出力
            logger.info("🎯 層別詳細統計:")
            for layer in ['BASE', 'EXPAND', 'ATR']:
                if layer in layer_summary.index:
                    trades = int(layer_summary.loc[layer, ('pips', 'count')])
                    net_pips = int(layer_summary.loc[layer, ('pips', 'sum')])
                    avg_pips = layer_summary.loc[layer, ('pips', 'mean')]
                    wins = int(layer_summary.loc[layer, ('result', '<lambda>')])
                    win_rate = (wins / trades * 100) if trades > 0 else 0
                    profit_factor = layer_pf.get(layer, 0)
                    
                    logger.info(f"  {layer}: {trades}取引, {net_pips:.0f}pips, 勝率{win_rate:.1f}%, PF{profit_factor:.2f}")
                else:
                    logger.info(f"  {layer}: 0取引")
                    
        except Exception as e:
            logger.error(f"❌ 層別集計エラー: {e}")
            import traceback
            traceback.print_exc()
                
    def save_results(self):
        """結果をCSVに保存"""
        if not self.backtest_results:
            logger.warning("保存する結果がありません")
            return
        
        try:
            df_results = pd.DataFrame(self.backtest_results)
            
            # タイムスタンプを追加
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = BACKTEST_RESULT_DIR / f"backtest_results_complete_{timestamp}.csv"
            
            df_results.to_csv(output_file, index=False, encoding='utf-8-sig')
            logger.info(f"✅ 結果を保存しました: {output_file}")
            
        except Exception as e:
            logger.error(f"❌ 結果保存エラー: {e}")
    
    def calculate_statistics(self):
        """統計計算（改良版）"""
        if not self.backtest_results:
            return
        
        df = pd.DataFrame(self.backtest_results)
        
        # 基本統計
        total_trades = len(df)
        wins = len(df[df['result'] == 'WIN'])
        losses = len(df[df['result'] == 'LOSS'])
        evens = len(df[df['result'] == 'EVEN'])
        
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        total_pips = df['pips'].sum()
        avg_pips_per_trade = df['pips'].mean()
        
        max_win = df[df['result'] == 'WIN']['pips'].max() if wins > 0 else 0
        max_loss = df[df['result'] == 'LOSS']['pips'].min() if losses > 0 else 0
        
        # 連続勝敗の計算
        consecutive_wins = self.calculate_consecutive_streak(df, 'WIN')
        consecutive_losses = self.calculate_consecutive_streak(df, 'LOSS')
        
        # 通貨ペア別統計
        currency_stats = df.groupby('currency_pair').agg({
            'pips': ['count', 'sum', 'mean'],
            'result': lambda x: (x == 'WIN').sum() / len(x) * 100
        }).round(2)
        
        # 方向別統計
        direction_stats = df.groupby('direction').agg({
            'pips': ['count', 'sum', 'mean'],
            'result': lambda x: (x == 'WIN').sum() / len(x) * 100
        }).round(2)
        
        # 層別統計
        layer_stats = df.groupby('layer').agg({
            'pips': ['count', 'sum', 'mean'],
            'result': lambda x: (x == 'WIN').sum() / len(x) * 100
        }).round(2) if 'layer' in df.columns else pd.DataFrame()
        
        # リスク指標
        daily_pips = df.groupby('date')['pips'].sum()
        max_daily_gain = daily_pips.max() if not daily_pips.empty else 0
        max_daily_loss = daily_pips.min() if not daily_pips.empty else 0
        volatility = daily_pips.std() if len(daily_pips) > 1 else 0
        
        # シャープレシオ（簡易版）
        sharpe_ratio = (avg_pips_per_trade / volatility) if volatility > 0 else 0
        
        self.summary_stats = {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'evens': evens,
            'win_rate': win_rate,
            'total_pips': total_pips,
            'avg_pips_per_trade': avg_pips_per_trade,
            'max_win': max_win,
            'max_loss': max_loss,
            'consecutive_wins': consecutive_wins,
            'consecutive_losses': consecutive_losses,
            'max_daily_gain': max_daily_gain,
            'max_daily_loss': max_daily_loss,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'currency_stats': currency_stats,
            'direction_stats': direction_stats,
            'layer_stats': layer_stats,
            'test_period': f"{self.entrypoint_files[0]['date_str']} - {self.entrypoint_files[-1]['date_str']}"
        }
        
        logger.info("✅ 統計計算完了")
    
    def calculate_consecutive_streak(self, df, result_type):
        """連続勝敗の計算"""
        results = df.sort_values(['date', 'entry_time'])['result'].values
        max_streak = 0
        current_streak = 0
        
        for result in results:
            if result == result_type:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def generate_report(self):
        """レポート生成（改良版）"""
        if not self.backtest_results or not self.summary_stats:
            logger.warning("レポート生成用のデータがありません")
            return
        
        try:
            # HTMLレポート生成
            self.generate_html_report()
            
            # グラフ生成
            self.generate_charts()
            
            logger.info("✅ レポート生成完了")
            
        except Exception as e:
            logger.error(f"❌ レポート生成エラー: {e}")
    
    def generate_html_report(self):
        """HTMLレポート生成（完全版 + 3層戦略）"""
        stats = self.summary_stats
        
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FXバックテスト結果レポート（完全修正版 + 3層戦略）</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
                .container {{ max-width: 1400px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 15px; box-shadow: 0 0 30px rgba(0,0,0,0.2); }}
                h1 {{ color: #2c3e50; text-align: center; font-size: 2.5em; margin-bottom: 30px; border-bottom: 3px solid #3498db; padding-bottom: 15px; }}
                h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 10px; margin-top: 40px; }}
                .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; margin-bottom: 40px; }}
                .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 25px; border-radius: 15px; text-align: center; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }}
                .stat-value {{ font-size: 2.2em; font-weight: bold; margin-bottom: 5px; }}
                .stat-label {{ font-size: 1em; opacity: 0.9; }}
                .highlight {{ background: linear-gradient(135deg, #ff7b7b 0%, #ff416c 100%); }}
                .success {{ background: linear-gradient(135deg, #6a11cb 0%, #2575fc 100%); }}
                .layer-success {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
                table {{ border-collapse: collapse; width: 100%; margin-bottom: 30px; border-radius: 10px; overflow: hidden; box-shadow: 0 0 20px rgba(0,0,0,0.1); }}
                th, td {{ text-align: left; padding: 15px; border: none; }}
                th {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; font-weight: bold; }}
                tr:nth-child(even) {{ background-color: #f8f9fa; }}
                tr:hover {{ background-color: #e3f2fd; }}
                .positive {{ color: #27ae60; font-weight: bold; }}
                .negative {{ color: #e74c3c; font-weight: bold; }}
                .neutral {{ color: #7f8c8d; }}
                .chart-container {{ text-align: center; margin: 30px 0; }}
                .risk-metrics {{ background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%); padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .layer-metrics {{ background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%); padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .footer {{ text-align: center; margin-top: 50px; color: #7f8c8d; font-style: italic; }}
            </style>
        </head>
        <body>

            <div class="container">
                <h1>📊 FXバックテスト結果レポート（完全修正版 + 3層戦略）</h1>
                
                <div class="summary">
                    <div class="stat-card success">
                        <div class="stat-value">{stats['total_trades']}</div>
                        <div class="stat-label">総取引数</div>
                    </div>
                    <div class="stat-card {'success' if stats['win_rate'] >= 60 else 'highlight' if stats['win_rate'] >= 50 else ''}">
                        <div class="stat-value">{stats['win_rate']:.1f}%</div>
                        <div class="stat-label">勝率</div>
                    </div>
                    <div class="stat-card {'success' if stats['total_pips'] > 0 else 'highlight'}">
                        <div class="stat-value">{stats['total_pips']:.1f}</div>
                        <div class="stat-label">総Pips</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{stats['avg_pips_per_trade']:.1f}</div>
                        <div class="stat-label">平均Pips/取引</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">{stats['sharpe_ratio']:.2f}</div>
                        <div class="stat-label">シャープレシオ</div>
                    </div>
                </div>
                
                <div class="layer-metrics">
                    <h2>🎯 3層戦略別成績</h2>
                    <table>
                        <tr><th>戦略層</th><th>取引数</th><th>総Pips</th><th>平均Pips</th><th>勝率(%)</th></tr>
        """
        
        # 3層戦略別統計を追加
        if not stats['layer_stats'].empty:
            for layer, stats_row in stats['layer_stats'].iterrows():
                total_pips = stats_row[('pips', 'sum')]
                avg_pips = stats_row[('pips', 'mean')]
                win_rate = stats_row[('result', '<lambda>')]
                count = stats_row[('pips', 'count')]
                
                pips_class = 'positive' if total_pips > 0 else 'negative' if total_pips < 0 else 'neutral'
                
                html_content += f"""
                        <tr>
                            <td><strong>{layer}</strong></td>
                            <td>{count}</td>
                            <td class="{pips_class}">{total_pips:.1f}</td>
                            <td class="{pips_class}">{avg_pips:.1f}</td>
                            <td>{win_rate:.1f}%</td>
                        </tr>
                """
        
        html_content += f"""
                    </table>
                </div>
                
                <div class="risk-metrics">
                    <h2>🛡️ リスク指標</h2>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                        <div>最大勝ち: <span class="positive">{stats['max_win']:.1f} pips</span></div>
                        <div>最大負け: <span class="negative">{stats['max_loss']:.1f} pips</span></div>
                        <div>最大日次利益: <span class="positive">{stats['max_daily_gain']:.1f} pips</span></div>
                        <div>最大日次損失: <span class="negative">{stats['max_daily_loss']:.1f} pips</span></div>
                        <div>最大連勝: <span class="positive">{stats['consecutive_wins']}回</span></div>
                        <div>最大連敗: <span class="negative">{stats['consecutive_losses']}回</span></div>
                    </div>
                </div>
                
                <h2>📈 詳細統計</h2>
                <table>
                    <tr><th>項目</th><th>値</th></tr>
                    <tr><td>テスト期間</td><td>{stats['test_period']}</td></tr>
                    <tr><td>勝ち</td><td class="positive">{stats['wins']}回</td></tr>
                    <tr><td>負け</td><td class="negative">{stats['losses']}回</td></tr>
                    <tr><td>引き分け</td><td class="neutral">{stats['evens']}回</td></tr>
                    <tr><td>日次ボラティリティ</td><td>{stats['volatility']:.1f} pips</td></tr>
                </table>
                
                <h2>💱 通貨ペア別成績</h2>
                <table>
                    <tr><th>通貨ペア</th><th>取引数</th><th>総Pips</th><th>平均Pips</th><th>勝率(%)</th></tr>
        """
        
        # 通貨ペア別統計を追加
        if not stats['currency_stats'].empty:
            for currency, stats_row in stats['currency_stats'].iterrows():
                total_pips = stats_row[('pips', 'sum')]
                avg_pips = stats_row[('pips', 'mean')]
                win_rate = stats_row[('result', '<lambda>')]
                count = stats_row[('pips', 'count')]
                
                pips_class = 'positive' if total_pips > 0 else 'negative' if total_pips < 0 else 'neutral'
                
                html_content += f"""
                        <tr>
                            <td><strong>{currency}</strong></td>
                            <td>{count}</td>
                            <td class="{pips_class}">{total_pips:.1f}</td>
                            <td class="{pips_class}">{avg_pips:.1f}</td>
                            <td>{win_rate:.1f}%</td>
                        </tr>
                """
        
        html_content += """
                </table>
                
                <h2>🎯 方向別成績</h2>
                <table>
                    <tr><th>方向</th><th>取引数</th><th>総Pips</th><th>平均Pips</th><th>勝率(%)</th></tr>
        """
        
        # 方向別統計を追加
        if not stats['direction_stats'].empty:
            for direction, stats_row in stats['direction_stats'].iterrows():
                total_pips = stats_row[('pips', 'sum')]
                avg_pips = stats_row[('pips', 'mean')]
                win_rate = stats_row[('result', '<lambda>')]
                count = stats_row[('pips', 'count')]
                
                pips_class = 'positive' if total_pips > 0 else 'negative' if total_pips < 0 else 'neutral'
                
                html_content += f"""
                        <tr>
                            <td><strong>{direction}</strong></td>
                            <td>{count}</td>
                            <td class="{pips_class}">{total_pips:.1f}</td>
                            <td class="{pips_class}">{avg_pips:.1f}</td>
                            <td>{win_rate:.1f}%</td>
                        </tr>
                """
        
        html_content += f"""
                </table>
                
                <div class="chart-container">
                    <h2>📊 パフォーマンスチャート</h2>
                    <p>詳細なチャートは backtest_charts_complete_*.png をご確認ください</p>
                </div>
                
                <div class="footer">
                    <p>📅 レポート生成日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
                    <p>🔧 システム: FXバックテストシステム完全修正版 + 3層戦略</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # HTMLファイルを保存
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_file = BACKTEST_RESULT_DIR / f"backtest_report_complete_{timestamp}.html"
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"✅ HTMLレポートを保存しました: {html_file}")
    
    def generate_charts(self):
        """チャート生成（改良版 + 3層戦略）"""
        if not self.backtest_results:
            return
        
        try:
            # 日本語フォント設定
            plt.rcParams['font.family'] = 'DejaVu Sans'
            
            df = pd.DataFrame(self.backtest_results)
            
            # 図のサイズを設定（3層戦略用に拡張）
            fig, axes = plt.subplots(3, 3, figsize=(20, 15))
            fig.suptitle('FX Backtest Performance Analysis (Complete Fixed + 3-Layer Strategy)', fontsize=16, fontweight='bold')
            
            # 1. 累積Pips推移
            df_sorted = df.sort_values(['date', 'entry_time']).reset_index(drop=True)
            df_sorted['cumulative_pips'] = df_sorted['pips'].cumsum()
            df_sorted['trade_number'] = range(1, len(df_sorted) + 1)
            
            axes[0, 0].plot(df_sorted['trade_number'], df_sorted['cumulative_pips'], 
                            linewidth=2.5, color='#2E86AB', alpha=0.8)
            axes[0, 0].fill_between(df_sorted['trade_number'], df_sorted['cumulative_pips'], 
                                    alpha=0.3, color='#2E86AB')
            axes[0, 0].set_title('Cumulative Pips Progress', fontweight='bold', fontsize=12)
            axes[0, 0].set_xlabel('Trade Number')
            axes[0, 0].set_ylabel('Cumulative Pips')
            axes[0, 0].grid(True, alpha=0.3)
            axes[0, 0].axhline(y=0, color='red', linestyle='--', alpha=0.7)
            
            # 2. 勝敗分布（円グラフ）
            result_counts = df['result'].value_counts()
            colors = ['#27AE60', '#E74C3C', '#95A5A6']
            axes[0, 1].pie(result_counts.values, labels=result_counts.index, colors=colors, 
                            autopct='%1.1f%%', startangle=90, shadow=True)
            axes[0, 1].set_title('Win/Loss Distribution', fontweight='bold', fontsize=12)
            
            # 3. Pips分布（ヒストグラム）
            axes[0, 2].hist(df['pips'], bins=30, alpha=0.7, color='#F39C12', 
                            edgecolor='black', density=True)
            axes[0, 2].set_title('Pips Distribution', fontweight='bold', fontsize=12)
            axes[0, 2].set_xlabel('Pips')
            axes[0, 2].set_ylabel('Density')
            axes[0, 2].axvline(x=0, color='red', linestyle='--', alpha=0.7)
            axes[0, 2].axvline(x=df['pips'].mean(), color='green', linestyle='-', alpha=0.7, 
                                label=f'Mean: {df["pips"].mean():.1f}')
            axes[0, 2].legend()
            axes[0, 2].grid(True, alpha=0.3)
            
            # 4. 通貨ペア別成績
            currency_pips = df.groupby('currency_pair')['pips'].sum().sort_values(ascending=True)
            colors_curr = ['#E74C3C' if x < 0 else '#27AE60' for x in currency_pips.values]
            
            bars = axes[1, 0].barh(range(len(currency_pips)), currency_pips.values, color=colors_curr)
            axes[1, 0].set_yticks(range(len(currency_pips)))
            axes[1, 0].set_yticklabels(currency_pips.index)
            axes[1, 0].set_title('Total Pips by Currency Pair', fontweight='bold', fontsize=12)
            axes[1, 0].set_xlabel('Total Pips')
            axes[1, 0].axvline(x=0, color='black', linestyle='-', alpha=0.8)
            axes[1, 0].grid(True, alpha=0.3)
            
            # 5. 方向別成績
            direction_pips = df.groupby('direction')['pips'].sum()
            colors_dir = ['#3498DB', '#9B59B6']
            
            bars2 = axes[1, 1].bar(direction_pips.index, direction_pips.values, color=colors_dir, alpha=0.8)
            axes[1, 1].set_title('Total Pips by Direction', fontweight='bold', fontsize=12)
            axes[1, 1].set_ylabel('Total Pips')
            axes[1, 1].grid(True, alpha=0.3)
            
            # 6. 日別成績
            df['date_parsed'] = pd.to_datetime(df['date'], format='%Y%m%d')
            daily_pips = df.groupby('date_parsed')['pips'].sum()
            
            axes[1, 2].plot(daily_pips.index, daily_pips.values, marker='o', linewidth=2, 
                            markersize=6, color='#8E44AD', alpha=0.8)
            axes[1, 2].fill_between(daily_pips.index, daily_pips.values, alpha=0.3, color='#8E44AD')
            axes[1, 2].set_title('Daily Performance', fontweight='bold', fontsize=12)
            axes[1, 2].set_xlabel('Date')
            axes[1, 2].set_ylabel('Daily Pips')
            axes[1, 2].tick_params(axis='x', rotation=45)
            axes[1, 2].grid(True, alpha=0.3)
            axes[1, 2].axhline(y=0, color='red', linestyle='--', alpha=0.7)
            
            # 7. 3層戦略別成績（棒グラフ）
            if 'layer' in df.columns:
                layer_pips = df.groupby('layer')['pips'].sum()
                layer_colors = {'BASE': '#3498DB', 'EXPAND': '#27AE60', 'ATR': '#E67E22'}
                colors_layer = [layer_colors.get(layer, '#95A5A6') for layer in layer_pips.index]
                
                bars3 = axes[2, 0].bar(layer_pips.index, layer_pips.values, color=colors_layer, alpha=0.8)
                axes[2, 0].set_title('Total Pips by Strategy Layer', fontweight='bold', fontsize=12)
                axes[2, 0].set_ylabel('Total Pips')
                axes[2, 0].grid(True, alpha=0.3)
                axes[2, 0].axhline(y=0, color='black', linestyle='-', alpha=0.8)
                
                # 8. 3層戦略別取引数（円グラフ）
                layer_counts = df['layer'].value_counts()
                layer_pie_colors = [layer_colors.get(layer, '#95A5A6') for layer in layer_counts.index]
                
                axes[2, 1].pie(layer_counts.values, labels=layer_counts.index, colors=layer_pie_colors,
                                autopct='%1.1f%%', startangle=90, shadow=True)
                axes[2, 1].set_title('Trade Distribution by Layer', fontweight='bold', fontsize=12)
                
                # 9. 3層戦略別勝率
                layer_winrates = df.groupby('layer').apply(lambda x: (x['result'] == 'WIN').sum() / len(x) * 100)
                
                bars4 = axes[2, 2].bar(layer_winrates.index, layer_winrates.values, 
                                        color=[layer_colors.get(layer, '#95A5A6') for layer in layer_winrates.index], 
                                        alpha=0.8)
                axes[2, 2].set_title('Win Rate by Strategy Layer', fontweight='bold', fontsize=12)
                axes[2, 2].set_ylabel('Win Rate (%)')
                axes[2, 2].set_ylim(0, 100)
                axes[2, 2].grid(True, alpha=0.3)
                axes[2, 2].axhline(y=50, color='red', linestyle='--', alpha=0.7, label='Break-even')
                axes[2, 2].legend()
            else:
                # 3層戦略データがない場合は空のプロット
                for i in range(3):
                    axes[2, i].text(0.5, 0.5, 'No Layer Data', ha='center', va='center', transform=axes[2, i].transAxes)
                    axes[2, i].set_title(f'Layer Analysis {i+1}', fontweight='bold', fontsize=12)
            
            # レイアウト調整
            plt.tight_layout()
            
            # チャートを保存
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            chart_file = BACKTEST_RESULT_DIR / f"backtest_charts_complete_{timestamp}.png"
            plt.savefig(chart_file, dpi=300, bbox_inches='tight', facecolor='white')
            plt.close()
            
            logger.info(f"✅ チャートを保存しました: {chart_file}")
            
        except Exception as e:
            logger.error(f"❌ チャート生成エラー: {e}")
            import traceback
            traceback.print_exc()
    
    def print_summary(self):
        """サマリーをコンソールに出力（改良版 + 3層戦略）"""
        if not self.summary_stats:
            logger.warning("サマリー統計がありません")
            return
        
        stats = self.summary_stats
        
        print("\n" + "=" * 80)
        print("📊 FXバックテスト結果サマリー（完全修正版 + 3層戦略）")
        print("=" * 80)
        print(f"📅 テスト期間: {stats['test_period']}")
        print(f"📈 総取引数: {stats['total_trades']}")
        
        if stats['total_trades'] > 0:
            print(f"🎯 勝率: {stats['win_rate']:.1f}% ({stats['wins']}勝 {stats['losses']}敗 {stats['evens']}分)")
            print(f"💰 総Pips: {stats['total_pips']:.1f}")
            print(f"📊 平均Pips/取引: {stats['avg_pips_per_trade']:.1f}")
            print(f"🚀 最大勝ち: {stats['max_win']:.1f} pips")
            print(f"📉 最大負け: {stats['max_loss']:.1f} pips")
            print(f"🔥 最大連勝: {stats['consecutive_wins']}回")
            print(f"❄️  最大連敗: {stats['consecutive_losses']}回")
            print(f"📈 最大日次利益: {stats['max_daily_gain']:.1f} pips")
            print(f"📉 最大日次損失: {stats['max_daily_loss']:.1f} pips")
            print(f"📊 シャープレシオ: {stats['sharpe_ratio']:.2f}")
            
            print("=" * 80)
            
            # 3層戦略別成績
            if not stats['layer_stats'].empty:
                print("🎯 3層戦略別成績:")
                for layer, row in stats['layer_stats'].iterrows():
                    total_pips = row[('pips', 'sum')]
                    win_rate = row[('result', '<lambda>')]
                    count = row[('pips', 'count')]
                    print(f"  {layer}: {total_pips:.1f}pips (勝率{win_rate:.1f}%, {count}回)")
            
            # 通貨ペア別トップ3
            currency_stats = stats['currency_stats']
            if not currency_stats.empty:
                top_currencies = currency_stats.sort_values(('pips', 'sum'), ascending=False).head(3)
                
                print("\n🏆 通貨ペア別成績 TOP3:")
                for i, (currency, row) in enumerate(top_currencies.iterrows(), 1):
                    total_pips = row[('pips', 'sum')]
                    win_rate = row[('result', '<lambda>')]
                    count = row[('pips', 'count')]
                    print(f"  {i}. {currency}: {total_pips:.1f}pips (勝率{win_rate:.1f}%, {count}回)")
            
            # 方向別成績
            direction_stats = stats['direction_stats']
            if not direction_stats.empty:
                print("\n🎯 方向別成績:")
                for direction, row in direction_stats.iterrows():
                    total_pips = row[('pips', 'sum')]
                    win_rate = row[('result', '<lambda>')]
                    count = row[('pips', 'count')]
                    print(f"  {direction}: {total_pips:.1f}pips (勝率{win_rate:.1f}%, {count}回)")
            
            # パフォーマンス評価
            print("\n🎖️  パフォーマンス評価:")
            if stats['win_rate'] >= 70:
                print("  勝率: ⭐⭐⭐ 優秀")
            elif stats['win_rate'] >= 60:
                print("  勝率: ⭐⭐ 良好")
            elif stats['win_rate'] >= 50:
                print("  勝率: ⭐ 普通")
            else:
                print("  勝率: ❌ 要改善")
            
            if stats['total_pips'] > 0:
                print("  総収益: ✅ プラス")
            else:
                print("  総収益: ❌ マイナス")
            
            if stats['sharpe_ratio'] > 1.0:
                print("  リスク調整収益: ⭐⭐⭐ 優秀")
            elif stats['sharpe_ratio'] > 0.5:
                print("  リスク調整収益: ⭐⭐ 良好")
            elif stats['sharpe_ratio'] > 0:
                print("  リスク調整収益: ⭐ 普通")
            else:
                print("  リスク調整収益: ❌ 要改善")
                
        else:
            print("❌ 分析可能な取引がありませんでした")
        
        print("=" * 80)


def main():
    """メイン実行関数"""
    try:
        print("🚀 FXバックテストシステム（完全修正版 + 3層戦略）を開始します...")
        
        # バックテストシステムを初期化
        backtest_system = FXBacktestSystemComplete()
        
        # バックテスト実行
        backtest_system.run_backtest()
        
        # サマリー表示
        backtest_system.print_summary()
        
        print(f"\n📁 詳細な結果は {BACKTEST_RESULT_DIR} フォルダをご確認ください")
        print("📋 以下のファイルが生成されます:")
        print("  - backtest_results_complete_*.csv : 全取引詳細データ（層情報付き）")
        print("  - backtest_report_complete_*.html : 美しいHTMLレポート（3層戦略対応）")
        print("  - backtest_charts_complete_*.png : パフォーマンスチャート（層別分析付き）")
        print("  - backtest_fixed_complete.log : 実行ログ")
        
    except Exception as e:
        logger.error(f"❌ バックテスト実行エラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
   main()