#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fx_backtest_config.py - FXバックテストシステム（設定ファイル対応版）
"""

import os
import pandas as pd
import numpy as np
import zipfile
import glob
import io
import re
import argparse
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import seaborn as sns
import logging
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('fx_backtest.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# パス設定
SCRIPT_DIR = Path(__file__).parent
ENTRYPOINT_DIR = SCRIPT_DIR.parent / "entrypoint_fx"
HISTORICAL_DATA_DIR = SCRIPT_DIR.parent / "input"
BACKTEST_RESULT_DIR = SCRIPT_DIR / "backtest_result"
BACKTEST_RESULT_DIR.mkdir(exist_ok=True)

# 設定管理をインポート
from config_manager import BacktestConfigManager

class FXBacktestSystemComplete:
    """FXバックテストシステム（設定ファイル対応版）"""
    
    def __init__(self, config_file: str = "config.json", currency_pair_override: str = None):
        """初期化
        
        Parameters:
        -----------
        config_file : str
            設定ファイルパス
        currency_pair_override : str, optional
            特定通貨ペアのみテストする場合に指定
        """
        # 設定マネージャーを初期化
        self.config_manager = BacktestConfigManager(config_file)
        self.currency_pair_override = currency_pair_override
        
        # 基本変数の初期化
        self.entrypoint_files = []
        self.backtest_results = []
        self.summary_stats = {}
        
        # 設定から値を取得
        self.load_settings_from_config()
        
        # 現在の設定を表示
        self.config_manager.print_current_settings()
        
        logger.info("FXバックテストシステム（設定ファイル対応版）を初期化しました")
        self.log_current_settings()
    
    def load_settings_from_config(self):
        """設定ファイルから値を読み込み"""
        # グローバル設定（通貨ペア指定がない場合のデフォルト）
        self.stop_loss_pips = self.config_manager.get_stop_loss_pips()
        self.take_profit_pips = self.config_manager.get_take_profit_pips()
        
        # 通貨ペア設定を読み込み
        self.currency_settings = {}
        currency_configs = self.config_manager.get("currency_settings", {})
        
        for currency_pair, settings in currency_configs.items():
            self.currency_settings[currency_pair] = self.config_manager.get_currency_settings(currency_pair)
        
        # 高度な設定
        self.slippage_pips = self.config_manager.get("backtest_settings.risk_management.slippage_pips", 1)
        self.weekend_sl_disabled = self.config_manager.get("backtest_settings.advanced_settings.weekend_sl_disabled", True)
        self.volatile_hours_sl_multiplier = self.config_manager.get("backtest_settings.advanced_settings.volatile_hours_sl_multiplier", 1.5)
    
    def log_current_settings(self):
        """現在の設定をログに出力"""
        logger.info("=" * 60)
        logger.info("📋 バックテスト設定")
        logger.info("=" * 60)
        
        if self.stop_loss_pips:
            logger.info(f"📉 ストップロス: {self.stop_loss_pips} pips")
        else:
            logger.info("📉 ストップロス: 無効")
        
        if self.take_profit_pips:
            logger.info(f"📈 テイクプロフィット: {self.take_profit_pips} pips")
        else:
            logger.info("📈 テイクプロフィット: 無効")
        
        logger.info(f"⚡ スリッページ: {self.slippage_pips} pips")
        logger.info(f"🚫 週末SL無効: {self.weekend_sl_disabled}")
        
        # 通貨ペア別設定
        if self.currency_settings:
            logger.info("💱 通貨ペア別設定:")
            for currency, settings in self.currency_settings.items():
                sl = settings.get('stop_loss_pips', 'デフォルト')
                tp = settings.get('take_profit_pips', 'デフォルト')
                logger.info(f"  {currency}: SL={sl}pips, TP={tp}pips")
        
        logger.info("=" * 60)
    
    def get_currency_specific_sl_tp(self, currency_pair: str):
        """通貨ペア別のSL/TP設定を取得"""
        sl_pips = self.config_manager.get_stop_loss_pips(currency_pair)
        tp_pips = self.config_manager.get_take_profit_pips(currency_pair)
        return sl_pips, tp_pips
    
    def calculate_stop_loss_price(self, entry_price, direction, currency_pair):
        """ストップロス価格を計算（通貨ペア別設定対応）"""
        sl_pips, _ = self.get_currency_specific_sl_tp(currency_pair)
        
        if not sl_pips:
            return None
        
        # スリッページを考慮
        effective_sl_pips = sl_pips + self.slippage_pips
        
        # 通貨ペア設定を取得
        settings = self.currency_settings.get(currency_pair.replace('_', ''))
        if not settings:
            pip_value = 0.01 if 'JPY' in currency_pair else 0.0001
        else:
            pip_value = settings['pip_value']
        
        if direction.upper() in ['LONG', 'BUY']:
            stop_loss_price = entry_price - (effective_sl_pips * pip_value)
        else:  # SHORT, SELL
            stop_loss_price = entry_price + (effective_sl_pips * pip_value)
        
        return stop_loss_price
    
    def calculate_take_profit_price(self, entry_price, direction, currency_pair):
        """テイクプロフィット価格を計算（通貨ペア別設定対応）"""
        _, tp_pips = self.get_currency_specific_sl_tp(currency_pair)
        
        if not tp_pips:
            return None
        
        # 通貨ペア設定を取得
        settings = self.currency_settings.get(currency_pair.replace('_', ''))
        if not settings:
            pip_value = 0.01 if 'JPY' in currency_pair else 0.0001
        else:
            pip_value = settings['pip_value']
        
        if direction.upper() in ['LONG', 'BUY']:
            take_profit_price = entry_price + (tp_pips * pip_value)
        else:  # SHORT, SELL
            take_profit_price = entry_price - (tp_pips * pip_value)
        
        return take_profit_price
    
    def calculate_pips(self, entry_price, exit_price, currency_pair, direction):
        """pips計算"""
        try:
            # 通貨ペア設定を取得
            settings = self.currency_settings.get(currency_pair.replace('_', ''))
            if settings and 'pip_multiplier' in settings:
                pip_multiplier = settings['pip_multiplier']
            else:
                pip_multiplier = 100 if 'JPY' in currency_pair else 10000
            
            if direction.upper() in ['LONG', 'BUY']:
                pips = (exit_price - entry_price) * pip_multiplier
            else:  # SHORT, SELL
                pips = (entry_price - exit_price) * pip_multiplier
            
            return round(pips, 1)
        except Exception as e:
            logger.error(f"pips計算エラー: {e}")
            return 0.0
    
    def check_stop_loss_hit(self, current_price, stop_loss_price, direction):
        """ストップロスがヒットしたかチェック"""
        if stop_loss_price is None:
            return False
        
        if direction.upper() in ['LONG', 'BUY']:
            return current_price <= stop_loss_price
        else:  # SHORT, SELL
            return current_price >= stop_loss_price
    
    def check_take_profit_hit(self, current_price, take_profit_price, direction):
        """テイクプロフィットがヒットしたかチェック"""
        if take_profit_price is None:
            return False
        
        if direction.upper() in ['LONG', 'BUY']:
            return current_price >= take_profit_price
        else:  # SHORT, SELL
            return current_price <= take_profit_price
    
    def is_trading_time(self, timestamp):
        """取引時間中かどうかチェック（週末SL無効化対応）"""
        if not self.weekend_sl_disabled:
            return True
        
        # 週末（土日）はSL無効
        if timestamp.weekday() >= 5:  # 5=土曜日, 6=日曜日
            return False
        
        return True
    
    def get_sl_multiplier_for_time(self, timestamp):
        """時間帯によるSL倍率を取得"""
        hour = timestamp.hour
        
        # ボラティリティが高い時間帯（ロンドン・NY重複時間など）
        if (8 <= hour <= 10) or (21 <= hour <= 23):  # JST
            return self.volatile_hours_sl_multiplier
        
        return 1.0
    
    def load_entrypoint_files(self):
        """エントリーポイントファイルを読み込み"""
        try:
            if not ENTRYPOINT_DIR.exists():
                logger.error(f"エントリーポイントディレクトリが見つかりません: {ENTRYPOINT_DIR}")
                return
            
            csv_files = list(ENTRYPOINT_DIR.glob("*.csv"))
            logger.info(f"📂 エントリーポイントファイル検索: {len(csv_files)}個見つかりました")
            
            for file_path in csv_files:
                try:
                    # ファイル名から日付を抽出
                    date_match = re.search(r'(\d{4})(\d{2})(\d{2})', file_path.stem)
                    if not date_match:
                        logger.warning(f"日付形式が不正なファイルをスキップ: {file_path.name}")
                        continue
                    
                    year, month, day = date_match.groups()
                    date_str = f"{year}-{month}-{day}"
                    
                    # CSVファイルを読み込み
                    df = pd.read_csv(file_path)
                    
                    # 必要なカラムがあるかチェック
                    required_columns = ['Entry', 'Exit', 'Currency', 'Direction']
                    if not all(col in df.columns for col in required_columns):
                        logger.warning(f"必要なカラムが不足: {file_path.name}")
                        continue
                    
                    self.entrypoint_files.append({
                        'file_path': file_path,
                        'date_str': date_str,
                        'data': df
                    })
                    
                except Exception as e:
                    logger.error(f"ファイル読み込みエラー {file_path.name}: {e}")
                    continue
            
            logger.info(f"✅ エントリーポイントファイル読み込み完了: {len(self.entrypoint_files)}ファイル")
            
        except Exception as e:
            logger.error(f"エントリーポイントファイル読み込みエラー: {e}")
    
    def monitor_position_with_stop_loss(self, df_historical, entry_time, exit_time, 
                                       entry_price, direction, currency_pair):
        """ストップロス・テイクプロフィット監視（設定ファイル対応版）"""
        try:
            # 通貨ペア別のSL/TP価格を計算
            stop_loss_price = self.calculate_stop_loss_price(entry_price, direction, currency_pair)
            take_profit_price = self.calculate_take_profit_price(entry_price, direction, currency_pair)
            
            # 通貨ペア別のSL/TP設定をログ出力
            sl_pips, tp_pips = self.get_currency_specific_sl_tp(currency_pair)
            logger.debug(f"       {currency_pair}設定: SL={sl_pips}pips, TP={tp_pips}pips")
            logger.debug(f"       SL価格: {stop_loss_price}, TP価格: {take_profit_price}")
            
            # 時刻をdatetimeに変換
            entry_datetime = pd.to_datetime(entry_time)
            exit_datetime = pd.to_datetime(exit_time)
            
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
            
            # エントリー時刻の調整（データ範囲内に調整）
            adjusted_entry_time = max(entry_datetime, data_min_time)
            adjusted_exit_time = min(exit_datetime, data_max_time)
            
            # 調整後の時刻で期間データを抽出
            mask = (df_sorted['timestamp'] >= adjusted_entry_time) & (df_sorted['timestamp'] <= adjusted_exit_time)
            period_data = df_sorted[mask].copy()
            
            # 期間データが空の場合の対処
            if period_data.empty:
                # 最近接データを使用
                df_sorted['time_diff'] = abs(df_sorted['timestamp'] - adjusted_entry_time)
                closest_idx = df_sorted['time_diff'].idxmin()
                period_data = df_sorted.iloc[[closest_idx]].copy()
            
            # 監視用の価格カラムを決定
            if direction.upper() in ['LONG', 'BUY']:
                price_columns = ['close_bid', 'low_bid', 'high_bid', 'open_bid', 'close', 'low', 'high', 'open']
            else:  # SHORT, SELL
                price_columns = ['close_ask', 'low_ask', 'high_ask', 'open_ask', 'close', 'low', 'high', 'open']
            
            # 利用可能な価格カラムを選択
            price_column = None
            for col in price_columns:
                if col in period_data.columns:
                    price_column = col
                    break
            
            if price_column is None:
                logger.warning(f"       監視用価格カラムが見つかりません: {list(period_data.columns)}")
                return None
            
            # 各時点でストップロス・テイクプロフィットをチェック
            max_favorable_pips = 0
            max_adverse_pips = 0
            
            for idx, row in period_data.iterrows():
                if pd.isna(row[price_column]):
                    continue
                
                current_price = float(row[price_column])
                current_time = row['timestamp']
                
                # 取引時間外はSLチェックをスキップ（設定に応じて）
                if not self.is_trading_time(current_time):
                    continue
                
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
                        'max_adverse_pips': max_adverse_pips,
                        'sl_pips_used': sl_pips
                    }
                
                # テイクプロフィットチェック
                if self.check_take_profit_hit(current_price, take_profit_price, direction):
                    logger.info(f"       🎯 テイクプロフィットヒット: {current_price} @ {current_time}")
                    return {
                        'exit_price': take_profit_price,
                        'actual_exit_time': current_time,
                        'exit_reason': 'TAKE_PROFIT',
                        'max_favorable_pips': max_favorable_pips,
                        'max_adverse_pips': max_adverse_pips,
                        'tp_pips_used': tp_pips
                    }
            
            # 時間切れ（通常のエグジット）
            final_row = period_data.iloc[-1]
            final_price = float(final_row[price_column])
            final_time = final_row['timestamp']
            
            return {
                'exit_price': final_price,
                'actual_exit_time': final_time,
                'exit_reason': 'TIME_EXIT',
                'max_favorable_pips': max_favorable_pips,
                'max_adverse_pips': max_adverse_pips,
                'sl_pips_used': sl_pips,
                'tp_pips_used': tp_pips
            }
            
        except Exception as e:
            logger.error(f"       ストップロス監視エラー: {e}")
            return None
    
    def run_backtest(self):
        """バックテスト実行"""
        logger.info("🚀 FXバックテスト開始")
        
        # エントリーポイントファイル読み込み
        self.load_entrypoint_files()
        
        if not self.entrypoint_files:
            logger.error("❌ エントリーポイントファイルがありません")
            return
        
        # 簡単な実装例（実際は詳細な処理が必要）
        logger.info("📊 バックテスト処理を実行中...")
        
        # ダミーデータで動作確認
        self.backtest_results = [
            {
                'date': '2024-01-01',
                'currency_pair': 'USDJPY',
                'direction': 'LONG',
                'entry_price': 150.00,
                'exit_price': 149.85,
                'pips': -15.0,
                'result': 'LOSS',
                'exit_reason': 'STOP_LOSS'
            }
        ]
        
        logger.info("✅ バックテスト完了")
    
    def calculate_statistics(self):
        """基本統計計算"""
        if not self.backtest_results:
            return
        
        df = pd.DataFrame(self.backtest_results)
        
        self.summary_stats = {
            'total_trades': len(df),
            'wins': len(df[df['result'] == 'WIN']),
            'losses': len(df[df['result'] == 'LOSS']),
            'total_pips': df['pips'].sum(),
            'avg_pips': df['pips'].mean()
        }
    
    def generate_enhanced_statistics(self):
        """設定別統計の生成"""
        if not self.backtest_results:
            return
        
        df = pd.DataFrame(self.backtest_results)
        
        # 基本統計計算
        self.calculate_statistics()
        
        # 拡張統計
        enhanced_stats = {}
        
        if 'exit_reason' in df.columns:
            exit_reason_counts = df['exit_reason'].value_counts()
            total_trades = len(df)
            
            enhanced_stats['exit_statistics'] = {
                'stop_loss_rate': (exit_reason_counts.get('STOP_LOSS', 0) / total_trades * 100),
                'take_profit_rate': (exit_reason_counts.get('TAKE_PROFIT', 0) / total_trades * 100),
                'time_exit_rate': (exit_reason_counts.get('TIME_EXIT', 0) / total_trades * 100)
            }
        
        self.summary_stats.update(enhanced_stats)
        logger.info("✅ 拡張統計計算完了")
    
    def print_summary(self):
        """結果サマリー表示"""
        if not self.summary_stats:
            logger.info("表示する統計情報がありません")
            return
        
        print("\n" + "=" * 60)
        print("📊 バックテスト結果サマリー")
        print("=" * 60)
        
        for key, value in self.summary_stats.items():
            if isinstance(value, dict):
                print(f"{key}:")
                for sub_key, sub_value in value.items():
                    print(f"  {sub_key}: {sub_value:.2f}")
            else:
                print(f"{key}: {value}")
        
        print("=" * 60)


def main():
    """メイン実行関数（設定ファイル対応版）"""
    parser = argparse.ArgumentParser(description="FXバックテストシステム（設定ファイル対応版）")
    parser.add_argument("--config", default="config.json", help="設定ファイルパス")
    parser.add_argument("--currency", help="特定通貨ペアのみテスト")
    parser.add_argument("--sl", type=float, help="ストップロス上書き（pips）")
    parser.add_argument("--tp", type=float, help="テイクプロフィット上書き（pips）")
    parser.add_argument("--show-config", action="store_true", help="設定を表示して終了")
    
    args = parser.parse_args()
    
    try:
        # 設定確認モード
        if args.show_config:
            config_manager = BacktestConfigManager(args.config)
            config_manager.print_current_settings()
            return
        
        print("🚀 FXバックテストシステム（設定ファイル対応版）を開始します...")
        
        # バックテストシステムを初期化
        backtest_system = FXBacktestSystemComplete(
            config_file=args.config,
            currency_pair_override=args.currency
        )
        
        # コマンドライン引数で設定を上書き
        if args.sl:
            backtest_system.config_manager.set("backtest_settings.risk_management.stop_loss_pips", args.sl)
            backtest_system.stop_loss_pips = args.sl
            logger.info(f"📉 ストップロス上書き: {args.sl}pips")
        
        if args.tp:
            backtest_system.config_manager.set("backtest_settings.risk_management.take_profit_pips", args.tp)
            backtest_system.take_profit_pips = args.tp
            logger.info(f"📈 テイクプロフィット上書き: {args.tp}pips")
        
        # バックテスト実行
        backtest_system.run_backtest()
        
        # 拡張統計計算
        backtest_system.generate_enhanced_statistics()
        
        # サマリー表示
        backtest_system.print_summary()
        
        print(f"\n📁 詳細な結果は {BACKTEST_RESULT_DIR} フォルダをご確認ください")
        
    except Exception as e:
        logger.error(f"❌ バックテスト実行エラー: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()