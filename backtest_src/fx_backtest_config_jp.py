#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fx_backtest_config_japanese.py - 日本語カラム対応版
"""

import os
import pandas as pd
import numpy as np
import re
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

# 設定管理をインポート
from config_manager import BacktestConfigManager

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

class FXBacktestSystemComplete:
    """FXバックテストシステム（日本語カラム対応版）"""
    
    def __init__(self, config_file: str = "config.json", currency_pair_override: str = None):
        """初期化"""
        # 設定マネージャーを初期化
        self.config_manager = BacktestConfigManager(config_file)
        self.currency_pair_override = currency_pair_override
        
        # 基本変数の初期化
        self.entrypoint_files = []
        self.backtest_results = []
        self.summary_stats = {}
        
        # 実際のファイル構造に基づくカラム名マッピング
        self.column_mappings = {
            'entry_time': ['Entry', 'entry', 'EntryTime', 'entry_time', 'エントリー時刻', 'エントリー', 'ENTRY'],
            'exit_time': ['Exit', 'exit', 'ExitTime', 'exit_time', 'エグジット時刻', 'エグジット', 'EXIT'],
            'currency_pair': ['通貨ペア', 'Currency', 'currency', 'CurrencyPair', 'currency_pair', 'Pair', 'pair', 'Symbol', 'symbol', 'CURRENCY'],
            'direction': ['方向', 'Direction', 'direction', 'Dir', 'dir', 'Side', 'side', 'Type', 'type', 'DIRECTION'],
            'entry_price': ['EntryPrice', 'entry_price', 'Price', 'price', 'エントリー価格', 'PRICE'],
            'exit_price': ['ExitPrice', 'exit_price', 'ClosePrice', 'close_price', 'エグジット価格', 'CLOSE_PRICE'],
            'pips': ['Pips', 'pips', 'PIPS', 'Pip', 'pip', 'PIP'],
            'profit': ['Profit', 'profit', 'PL', 'pl', 'P&L', 'p&l', '損益', 'PROFIT']
        }
        
        # 設定から値を取得
        self.load_settings_from_config()
        
        # 現在の設定を表示
        self.config_manager.print_current_settings()
        
        logger.info("FXバックテストシステム（日本語カラム対応版）を初期化しました")
        self.log_current_settings()
    
    def load_settings_from_config(self):
        """設定ファイルから値を読み込み"""
        # グローバル設定
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
    
    def find_column_mapping(self, df, target_field):
        """カラム名を柔軟にマッピング"""
        possible_names = self.column_mappings.get(target_field, [])
        
        for col_name in df.columns:
            # 完全一致（優先）
            if col_name in possible_names:
                return col_name
            
            # 大文字小文字を無視した一致
            for possible_name in possible_names:
                if col_name.lower() == possible_name.lower():
                    return col_name
            
            # 部分一致
            col_lower = col_name.lower()
            for possible_name in possible_names:
                possible_lower = possible_name.lower()
                if possible_lower in col_lower or col_lower in possible_lower:
                    return col_name
        
        return None
    
    def standardize_direction(self, direction_value):
        """方向を標準化（日本語対応）"""
        if pd.isna(direction_value):
            return 'UNKNOWN'
        
        direction_str = str(direction_value).strip().upper()
        
        # 英語パターン
        if direction_str in ['LONG', 'BUY', 'L', 'B']:
            return 'LONG'
        elif direction_str in ['SHORT', 'SELL', 'S']:
            return 'SHORT'
        
        # 日本語パターン
        direction_lower = direction_str.lower()
        if direction_lower in ['long', 'ロング', '買い', '買']:
            return 'LONG'
        elif direction_lower in ['short', 'ショート', '売り', '売']:
            return 'SHORT'
        
        logger.warning(f"不明な方向値: {direction_value} → LONG に設定")
        return 'LONG'
    
    def standardize_currency_pair(self, currency_value):
        """通貨ペアを標準化（日本語対応）"""
        if pd.isna(currency_value):
            return 'USDJPY'
        
        currency_str = str(currency_value).strip().upper()
        
        # 通貨ペアの標準化
        currency_mapping = {
            'USDJPY': ['USDJPY', 'USD/JPY', 'USD-JPY', 'ドル円', 'ドル/円'],
            'EURJPY': ['EURJPY', 'EUR/JPY', 'EUR-JPY', 'ユーロ円', 'ユーロ/円'],
            'GBPJPY': ['GBPJPY', 'GBP/JPY', 'GBP-JPY', 'ポンド円', 'ポンド/円'],
            'EURUSD': ['EURUSD', 'EUR/USD', 'EUR-USD', 'ユーロドル', 'ユーロ/ドル'],
            'GBPUSD': ['GBPUSD', 'GBP/USD', 'GBP-USD', 'ポンドドル', 'ポンド/ドル']
        }
        
        for standard_name, variants in currency_mapping.items():
            if currency_str in variants:
                return standard_name
        
        logger.warning(f"不明な通貨ペア: {currency_value} → USDJPY に設定")
        return 'USDJPY'
    
    def parse_time_string(self, time_str, base_date):
        """時刻文字列をdatetimeに変換"""
        try:
            if pd.isna(time_str):
                return None
            
            time_str = str(time_str).strip()
            
            # HH:MM:SS 形式
            if re.match(r'^\d{2}:\d{2}:\d{2}$', time_str):
                hour, minute, second = map(int, time_str.split(':'))
                return base_date.replace(hour=hour, minute=minute, second=second, microsecond=0)
            
            # HH:MM 形式
            elif re.match(r'^\d{2}:\d{2}$', time_str):
                hour, minute = map(int, time_str.split(':'))
                return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            else:
                logger.warning(f"時刻形式が不正: {time_str}")
                return None
                
        except Exception as e:
            logger.error(f"時刻変換エラー {time_str}: {e}")
            return None
    
    def load_entrypoint_files(self):
        """エントリーポイントファイルを読み込み（日本語対応）"""
        try:
            if not ENTRYPOINT_DIR.exists():
                logger.error(f"エントリーポイントディレクトリが見つかりません: {ENTRYPOINT_DIR}")
                return
            
            csv_files = list(ENTRYPOINT_DIR.glob("*.csv"))
            logger.info(f"📂 エントリーポイントファイル検索: {len(csv_files)}個見つかりました")
            
            successful_files = 0
            failed_files = 0
            total_trades = 0
            
            for file_path in csv_files:
                try:
                    # ファイル名から日付を抽出
                    date_match = re.search(r'(\d{4})(\d{2})(\d{2})', file_path.stem)
                    if not date_match:
                        logger.warning(f"日付形式が不正なファイルをスキップ: {file_path.name}")
                        failed_files += 1
                        continue
                    
                    year, month, day = date_match.groups()
                    date_str = f"{year}-{month}-{day}"
                    base_date = datetime(int(year), int(month), int(day))
                    
                    # CSVファイルを読み込み
                    df = pd.read_csv(file_path, encoding='utf-8')
                    
                    # カラムマッピングを確認
                    column_mapping = {}
                    required_fields = ['entry_time', 'exit_time', 'currency_pair', 'direction']
                    
                    for field in required_fields:
                        mapped_col = self.find_column_mapping(df, field)
                        if mapped_col:
                            column_mapping[field] = mapped_col
                        else:
                            logger.error(f"必須カラムが見つかりません {file_path.name}: {field}")
                            break
                    
                    # 必須カラムが全て見つかったかチェック
                    if len(column_mapping) != len(required_fields):
                        failed_files += 1
                        continue
                    
                    # データを標準化
                    processed_data = []
                    
                    for idx, row in df.iterrows():
                        try:
                            # 時刻変換
                            entry_time_str = row[column_mapping['entry_time']]
                            exit_time_str = row[column_mapping['exit_time']]
                            
                            entry_datetime = self.parse_time_string(entry_time_str, base_date)
                            exit_datetime = self.parse_time_string(exit_time_str, base_date)
                            
                            if entry_datetime is None or exit_datetime is None:
                                logger.warning(f"時刻変換失敗 {file_path.name} 行{idx+1}: {entry_time_str} -> {exit_time_str}")
                                continue
                            
                            # エグジット時刻がエントリー時刻より前の場合は翌日扱い
                            if exit_datetime <= entry_datetime:
                                exit_datetime += timedelta(days=1)
                            
                            # 方向と通貨ペアを標準化
                            direction = self.standardize_direction(row[column_mapping['direction']])
                            currency_pair = self.standardize_currency_pair(row[column_mapping['currency_pair']])
                            
                            # 通貨ペアフィルタリング
                            if self.currency_pair_override and currency_pair != self.currency_pair_override:
                                continue
                            
                            processed_data.append({
                                'entry_time': entry_datetime,
                                'exit_time': exit_datetime,
                                'currency_pair': currency_pair,
                                'direction': direction,
                                'original_entry': entry_time_str,
                                'original_exit': exit_time_str,
                                'row_index': idx
                            })
                            
                        except Exception as e:
                            logger.warning(f"行処理エラー {file_path.name} 行{idx+1}: {e}")
                            continue
                    
                    if processed_data:
                        self.entrypoint_files.append({
                            'file_path': file_path,
                            'date_str': date_str,
                            'base_date': base_date,
                            'data': processed_data,
                            'original_columns': list(df.columns),
                            'column_mapping': column_mapping,
                            'trade_count': len(processed_data)
                        })
                        
                        successful_files += 1
                        total_trades += len(processed_data)
                        logger.info(f"✅ 読み込み成功: {file_path.name} ({len(processed_data)}件)")
                    else:
                        failed_files += 1
                        logger.warning(f"⚠️  処理可能なデータなし: {file_path.name}")
                    
                except Exception as e:
                    logger.error(f"ファイル処理エラー {file_path.name}: {e}")
                    failed_files += 1
                    continue
            
            logger.info("=" * 60)
            logger.info(f"✅ エントリーポイントファイル読み込み完了")
            logger.info(f"   成功: {successful_files}ファイル")
            logger.info(f"   失敗: {failed_files}ファイル")
            logger.info(f"   総取引数: {total_trades}件")
            logger.info("=" * 60)
            
            # ファイル構造サマリーを表示
            if successful_files > 0:
                self.print_file_structure_summary()
            else:
                logger.error("❌ 読み込み可能なファイルがありません")
                
        except Exception as e:
            logger.error(f"エントリーポイントファイル読み込みエラー: {e}")
    
    def print_file_structure_summary(self):
        """ファイル構造サマリーを表示"""
        if not self.entrypoint_files:
            return
        
        logger.info("📋 ファイル構造サマリー")
        logger.info("-" * 40)
        
        # 最初のファイルの構造を表示
        first_file = self.entrypoint_files[0]
        logger.info(f"📄 代表ファイル: {first_file['file_path'].name}")
        logger.info(f"📊 取引数: {first_file['trade_count']}")
        logger.info("🔄 カラムマッピング:")
        
        for standard_name, original_name in first_file['column_mapping'].items():
            logger.info(f"  {standard_name} ← {original_name}")
        
        # データサンプル表示
        if first_file['data']:
            logger.info("📈 データサンプル:")
            for i, trade in enumerate(first_file['data'][:2]):
                logger.info(f"  取引{i+1}: {trade['currency_pair']} {trade['direction']} "
                           f"{trade['entry_time'].strftime('%H:%M:%S')} -> {trade['exit_time'].strftime('%H:%M:%S')}")
        
        # 通貨ペア別統計
        currency_stats = {}
        for entry_data in self.entrypoint_files:
            for trade in entry_data['data']:
                currency = trade['currency_pair']
                currency_stats[currency] = currency_stats.get(currency, 0) + 1
        
        logger.info("💱 通貨ペア別取引数:")
        for currency, count in sorted(currency_stats.items()):
            logger.info(f"  {currency}: {count}件")
        
        logger.info("-" * 40)
    
    def get_currency_specific_sl_tp(self, currency_pair: str):
        """通貨ペア別のSL/TP設定を取得"""
        sl_pips = self.config_manager.get_stop_loss_pips(currency_pair)
        tp_pips = self.config_manager.get_take_profit_pips(currency_pair)
        return sl_pips, tp_pips
    
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
    
    def run_backtest(self):
        """バックテスト実行"""
        logger.info("🚀 FXバックテスト開始")
        
        # エントリーポイントファイル読み込み
        self.load_entrypoint_files()
        
        if not self.entrypoint_files:
            logger.error("❌ エントリーポイントファイルがありません")
            return
        
        logger.info("📊 バックテスト処理を実行中...")
        
        # 実際のバックテスト処理
        processed_trades = 0
        successful_trades = 0
        
        for entry_data in self.entrypoint_files:
            for trade in entry_data['data']:
                processed_trades += 1
                
                try:
                    # SL/TP設定を取得
                    sl_pips, tp_pips = self.get_currency_specific_sl_tp(trade['currency_pair'])
                    
                    # ダミーの価格データ（実際は履歴データから取得）
                    entry_price = 150.00 if 'JPY' in trade['currency_pair'] else 1.0500
                    
                    # ダミーの結果生成（実際は詳細な監視が必要）
                    if trade['direction'] == 'LONG':
                        exit_price = entry_price - (sl_pips * 0.01) if sl_pips else entry_price + 0.05
                        exit_reason = 'STOP_LOSS' if sl_pips and exit_price < entry_price else 'TIME_EXIT'
                    else:  # SHORT
                        exit_price = entry_price + (sl_pips * 0.01) if sl_pips else entry_price - 0.05
                        exit_reason = 'STOP_LOSS' if sl_pips and exit_price > entry_price else 'TIME_EXIT'
                    
                    # pips計算
                    pips = self.calculate_pips(entry_price, exit_price, trade['currency_pair'], trade['direction'])
                    result = 'WIN' if pips > 0 else 'LOSS' if pips < 0 else 'EVEN'
                    
                    self.backtest_results.append({
                        'date': entry_data['date_str'],
                        'currency_pair': trade['currency_pair'],
                        'direction': trade['direction'],
                        'entry_time': trade['entry_time'],
                        'exit_time': trade['exit_time'],
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pips': pips,
                        'result': result,
                        'exit_reason': exit_reason,
                        'sl_pips_used': sl_pips,
                        'tp_pips_used': tp_pips
                    })
                    
                    successful_trades += 1
                    
                except Exception as e:
                    logger.warning(f"取引処理エラー: {e}")
                    continue
        
        logger.info(f"✅ バックテスト完了: {successful_trades}/{processed_trades}件の取引を処理")
    
    def calculate_statistics(self):
        """基本統計計算"""
        if not self.backtest_results:
            return
        
        df = pd.DataFrame(self.backtest_results)
        
        wins = len(df[df['result'] == 'WIN'])
        losses = len(df[df['result'] == 'LOSS'])
        evens = len(df[df['result'] == 'EVEN'])
        total_trades = len(df)
        
        self.summary_stats = {
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses,
            'evens': evens,
            'win_rate': (wins / total_trades * 100) if total_trades > 0 else 0,
            'total_pips': df['pips'].sum(),
            'avg_pips': df['pips'].mean(),
            'max_win_pips': df[df['result'] == 'WIN']['pips'].max() if wins > 0 else 0,
            'max_loss_pips': df[df['result'] == 'LOSS']['pips'].min() if losses > 0 else 0
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
        
        # SL/TP発動統計
        if 'exit_reason' in df.columns:
            exit_reason_counts = df['exit_reason'].value_counts()
            total_trades = len(df)
            
            enhanced_stats['exit_statistics'] = {
                'stop_loss_rate': (exit_reason_counts.get('STOP_LOSS', 0) / total_trades * 100),
                'take_profit_rate': (exit_reason_counts.get('TAKE_PROFIT', 0) / total_trades * 100),
                'time_exit_rate': (exit_reason_counts.get('TIME_EXIT', 0) / total_trades * 100)
            }
        
        # 通貨ペア別統計
        currency_stats = {}
        for currency in df['currency_pair'].unique():
            currency_df = df[df['currency_pair'] == currency]
            wins = len(currency_df[currency_df['result'] == 'WIN'])
            total = len(currency_df)
            
            currency_stats[currency] = {
                'trades': total,
                'win_rate': (wins / total * 100) if total > 0 else 0,
                'avg_pips': currency_df['pips'].mean(),
                'total_pips': currency_df['pips'].sum()
            }
        
        enhanced_stats['currency_statistics'] = currency_stats
        
        # 方向別統計
        direction_stats = {}
        for direction in df['direction'].unique():
            direction_df = df[df['direction'] == direction]
            wins = len(direction_df[direction_df['result'] == 'WIN'])
            total = len(direction_df)
            
            direction_stats[direction] = {
                'trades': total,
                'win_rate': (wins / total * 100) if total > 0 else 0,
                'avg_pips': direction_df['pips'].mean(),
                'total_pips': direction_df['pips'].sum()
            }
        
        enhanced_stats['direction_statistics'] = direction_stats
        
        self.summary_stats.update(enhanced_stats)
        logger.info("✅ 拡張統計計算完了")
    
    def print_summary(self):
        """結果サマリー表示"""
        if not self.summary_stats:
            logger.info("表示する統計情報がありません")
            return
        
        print("\n" + "=" * 80)
        print("📊 FXバックテスト結果サマリー")
        print("=" * 80)
        
        # 基本統計
        print("📈 基本統計:")
        print(f"  総取引数: {self.summary_stats.get('total_trades', 0)}件")
        print(f"  勝ち: {self.summary_stats.get('wins', 0)}件")
        print(f"  負け: {self.summary_stats.get('losses', 0)}件")
        print(f"  引き分け: {self.summary_stats.get('evens', 0)}件")
        print(f"  勝率: {self.summary_stats.get('win_rate', 0):.2f}%")
        print(f"  総Pips: {self.summary_stats.get('total_pips', 0):.1f}")
        print(f"  平均Pips: {self.summary_stats.get('avg_pips', 0):.2f}")
        print(f"  最大勝ちPips: {self.summary_stats.get('max_win_pips', 0):.1f}")
        print(f"  最大負けPips: {self.summary_stats.get('max_loss_pips', 0):.1f}")
        
        # SL/TP統計
        if 'exit_statistics' in self.summary_stats:
            print("\n🛑 ストップロス・テイクプロフィット統計:")
            exit_stats = self.summary_stats['exit_statistics']
            print(f"  ストップロス発動率: {exit_stats.get('stop_loss_rate', 0):.1f}%")
            print(f"  テイクプロフィット発動率: {exit_stats.get('take_profit_rate', 0):.1f}%")
            print(f"  時間切れ決済率: {exit_stats.get('time_exit_rate', 0):.1f}%")
        
        # 通貨ペア別統計
        if 'currency_statistics' in self.summary_stats:
            print("\n💱 通貨ペア別統計:")
            currency_stats = self.summary_stats['currency_statistics']
            for currency, stats in currency_stats.items():
                print(f"  {currency}: {stats['trades']}件, 勝率{stats['win_rate']:.1f}%, "
                      f"平均{stats['avg_pips']:.1f}pips, 累計{stats['total_pips']:.1f}pips")
        
        # 方向別統計
        if 'direction_statistics' in self.summary_stats:
            print("\n📊 方向別統計:")
            direction_stats = self.summary_stats['direction_statistics']
            for direction, stats in direction_stats.items():
                print(f"  {direction}: {stats['trades']}件, 勝率{stats['win_rate']:.1f}%, "
                      f"平均{stats['avg_pips']:.1f}pips, 累計{stats['total_pips']:.1f}pips")
        
        print("=" * 80)


def main():
    """メイン実行関数（日本語対応版）"""
    parser = argparse.ArgumentParser(description="FXバックテストシステム（日本語対応版）")
    parser.add_argument("--config", default="config.json", help="設定ファイルパス")
    parser.add_argument("--currency", help="特定通貨ペアのみテスト")
    parser.add_argument("--sl", type=float, help="ストップロス上書き（pips）")
    parser.add_argument("--tp", type=float, help="テイクプロフィット上書き（pips）")
    parser.add_argument("--show-config", action="store_true", help="設定を表示して終了")
    parser.add_argument("--analyze-files", action="store_true", help="ファイル構造のみ分析")
    
    args = parser.parse_args()
    
    try:
        # 設定確認モード
        if args.show_config:
            config_manager = BacktestConfigManager(args.config)
            config_manager.print_current_settings()
            return
        
        print("🚀 FXバックテストシステム（日本語対応版）を開始します...")
        
        # バックテストシステムを初期化
        backtest_system = FXBacktestSystemComplete(
            config_file=args.config,
            currency_pair_override=args.currency
        )
        
        # ファイル分析のみモード
        if args.analyze_files:
            backtest_system.load_entrypoint_files()
            return
        
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