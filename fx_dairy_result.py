#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import json
import sys
import glob
import matplotlib.pyplot as plt
import logging
from pathlib import Path
import zipfile
import io
import re
import argparse

# 基本設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORICAL_DATA_DIR = os.path.join(BASE_DIR, "input")

# エントリーポイントタイプの設定
ENTRYPOINT_CONFIGS = {
    'yokubari': {
        'name': 'よくばりエントリー',
        'input_dir': os.path.join(BASE_DIR, "entrypoint_fx_よくばり"),
        'output_dir': os.path.join(BASE_DIR, "entrypoint_fx_よくばり_result"),
        'file_pattern': "よくばりエントリー_*.csv",
        'log_prefix': "yokubari",
        'output_prefix': "fx_results_yokubari"
    },
    'standard': {
        'name': '標準エントリー',
        'input_dir': os.path.join(BASE_DIR, "entrypoint_fx"),
        'output_dir': os.path.join(BASE_DIR, "entrypoint_fx_result"),
        'file_pattern': "entrypoints_*.csv",
        'log_prefix': "standard",
        'output_prefix': "fx_results_standard"
    }
}

# カラム名の正規化マッピング
COLUMN_MAPPING = {
    "úŽž": "timestamp",
    "日時": "timestamp",
    "Žn'l(BID)": "open_bid",
    "始値(BID)": "open_bid",
    "‚'l(BID)": "high_bid",
    "高値(BID)": "high_bid",
    "ˆÀ'l(BID)": "low_bid",
    "安値(BID)": "low_bid",
    "I'l(BID)": "close_bid",
    "終値(BID)": "close_bid",
    "Žn'l(ASK)": "open_ask",
    "始値(ASK)": "open_ask",
    "‚'l(ASK)": "high_ask",
    "高値(ASK)": "high_ask",
    "ˆÀ'l(ASK)": "low_ask",
    "安値(ASK)": "low_ask",
    "I'l(ASK)": "close_ask",
    "終値(ASK)": "close_ask"
}

class FXResultAnalyzer:
    def __init__(self, entry_type='yokubari'):
        """FX結果分析ツールの初期化
        
        Parameters:
        -----------
        entry_type : str
            'yokubari' または 'standard'
        """
        if entry_type not in ENTRYPOINT_CONFIGS:
            raise ValueError(f"不正なentry_type: {entry_type}. 'yokubari' または 'standard' を指定してください。")
        
        self.entry_type = entry_type
        self.config = ENTRYPOINT_CONFIGS[entry_type]
        self.currency_settings = self.load_currency_settings()
        
        # ディレクトリの作成
        Path(self.config['output_dir']).mkdir(exist_ok=True)
        
        # ログ設定
        log_dir = os.path.join(self.config['output_dir'], "log")
        Path(log_dir).mkdir(exist_ok=True)
        
        # ロギング設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(log_dir, f"fx_result_{self.config['log_prefix']}_log.txt"), encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        
        self.logger.info(f"🚀 FX結果分析ツール初期化: {self.config['name']}")
        self.logger.info(f"📁 入力ディレクトリ: {self.config['input_dir']}")
        self.logger.info(f"📁 出力ディレクトリ: {self.config['output_dir']}")
        
    def load_currency_settings(self):
        """通貨設定の読み込み"""
        default_settings = {
            "USD_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "EUR_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "GBP_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "EUR_USD": {"pip_value": 0.0001, "lot_size": 10000},
            "GBP_USD": {"pip_value": 0.0001, "lot_size": 10000},
            "AUD_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "NZD_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "CAD_JPY": {"pip_value": 0.01, "lot_size": 10000},
            "CHF_JPY": {"pip_value": 0.01, "lot_size": 10000}
        }
        return default_settings
    
    def extract_date_from_filename(self, file_path):
        """ファイル名から日付を抽出"""
        filename = os.path.basename(file_path)
        
        if self.entry_type == 'yokubari':
            # よくばりエントリー_20250502.csv
            match = re.search(r'よくばりエントリー_(\d{8})\.csv', filename)
        else:  # standard
            # entrypoints_20250502.csv
            match = re.search(r'entrypoints_(\d{8})\.csv', filename)
        
        if match:
            return match.group(1)
        return None
    
    def get_unprocessed_files(self):
        """未処理のエントリーポイントファイルを取得（当日分除外）"""
        # input側のすべてのファイルを取得
        input_files = glob.glob(os.path.join(self.config['input_dir'], self.config['file_pattern']))
        
        if not input_files:
            self.logger.warning(f"📁 {self.config['name']}ファイルが見つかりません: {self.config['input_dir']}")
            return []
        
        self.logger.info(f"📁 {self.config['name']}ファイル発見: {len(input_files)}件")
        
        # 当日の日付を取得
        today = datetime.now().strftime('%Y%m%d')
        self.logger.info(f"📅 当日日付: {today} (当日分は除外されます)")
        
        # 未処理ファイルのリスト
        unprocessed_files = []
        excluded_today = 0
        
        for input_file in sorted(input_files):
            file_date = self.extract_date_from_filename(input_file)
            if not file_date:
                self.logger.warning(f"⚠️  ファイル名から日付を抽出できませんでした: {os.path.basename(input_file)}")
                continue
            
            # 当日分は除外
            if file_date == today:
                self.logger.info(f"⏭️  当日分のため除外: {os.path.basename(input_file)} (日付: {file_date})")
                excluded_today += 1
                continue
            
            # 対応するoutput側ファイルの確認
            output_file = os.path.join(
                self.config['output_dir'], 
                f"{self.config['output_prefix']}_{file_date}.csv"
            )
            
            if not os.path.exists(output_file):
                unprocessed_files.append((input_file, file_date))
                self.logger.info(f"✅ 未処理ファイル発見: {os.path.basename(input_file)} (日付: {file_date})")
            else:
                self.logger.info(f"⏭️  既に処理済み: {os.path.basename(input_file)} → {os.path.basename(output_file)}")
        
        # 結果サマリー
        if excluded_today > 0:
            self.logger.info(f"📅 当日分除外: {excluded_today}件")
        
        if not unprocessed_files:
            self.logger.info("🎉 すべてのファイルが処理済みです（当日分除く）")
        else:
            self.logger.info(f"📊 未処理ファイル総数: {len(unprocessed_files)}件")
        
        return unprocessed_files
    
    def normalize_date(self, date_str):
        """日付文字列をYYYYMMDD形式に標準化"""
        if not date_str:
            return None
            
        # YYYY/MM/DD -> YYYYMMDD
        if '/' in date_str:
            parts = date_str.split('/')
            if len(parts) == 3:
                return f"{parts[0]}{int(parts[1]):02d}{int(parts[2]):02d}"
        
        # すでにYYYYMMDD形式の場合
        if len(date_str) == 8 and date_str.isdigit():
            return date_str
        
        # その他の形式（例：YYYY-MM-DD）
        if '-' in date_str:
            parts = date_str.split('-')
            if len(parts) == 3:
                return f"{parts[0]}{int(parts[1]):02d}{int(parts[2]):02d}"
                
        self.logger.warning(f"未対応の日付形式: {date_str}")
        return date_str
    
    def convert_currency_name(self, name):
        """通貨ペア名を標準フォーマットに変換"""
        conversion = {
            "米ドル/円": "USD_JPY",
            "ユーロ/円": "EUR_JPY",
            "英ポンド/円": "GBP_JPY",
            "豪ドル/円": "AUD_JPY",
            "NZドル/円": "NZD_JPY",
            "ユーロ/米ドル": "EUR_USD",
            "英ポンド/米ドル": "GBP_USD",
            "加ドル/円": "CAD_JPY",
            "スイスフラン/円": "CHF_JPY",
            "USDJPY": "USD_JPY",
            "EURJPY": "EUR_JPY",
            "GBPJPY": "GBP_JPY",
            "AUDJPY": "AUD_JPY",
            "NZDJPY": "NZD_JPY",
            "EURUSD": "EUR_USD",
            "GBPUSD": "GBP_USD",
            "CADJPY": "CAD_JPY",
            "CHFJPY": "CHF_JPY"
        }
        return conversion.get(name, name)
    
    def parse_entry_data(self, entry_str):
        """エントリーデータを解析して価格と時間を抽出"""
        if not entry_str or not isinstance(entry_str, str):
            return None, None
            
        # カンマで分割されている場合の処理
        parts = entry_str.split(',')
        if len(parts) > 1:
            price_str = parts[0].strip()
            time_str = parts[1].strip()
            
            try:
                price = float(price_str.replace(',', ''))
                return price, time_str
            except ValueError:
                pass
        
        # 時間のパターンを検出
        time_patterns = [
            r'\d{1,2}:\d{2}:\d{2}',  # 14:30:00
            r'\d{1,2}:\d{2}',         # 14:30
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, entry_str)
            if match:
                time_str = match.group(0)
                price_part = entry_str.replace(time_str, '').strip()
                if price_part:
                    try:
                        price = float(price_part.replace(',', ''))
                        return price, time_str
                    except ValueError:
                        pass
                return None, time_str
        
        # 数値のみの場合
        try:
            price = float(entry_str.replace(',', ''))
            return price, None
        except ValueError:
            return None, None
    
    def convert_to_zip_format(self, currency_pair):
        """通貨ペアをZIPファイル名のフォーマットに変換"""
        return currency_pair.replace("_", "")
    
    def calculate_pips(self, entry_price, exit_price, currency_pair, trade_type):
        """pipsを計算"""
        if currency_pair not in self.currency_settings:
            self.logger.warning(f"通貨ペア{currency_pair}の設定が見つかりません。デフォルト設定を使用します。")
            pip_value = 0.01 if currency_pair.endswith("JPY") else 0.0001
        else:
            pip_value = self.currency_settings[currency_pair]["pip_value"]
        
        if trade_type.upper() in ["BUY", "LONG", "買い", "Long"]:
            pips = (exit_price - entry_price) / pip_value
        else:  # SELL, SHORT, 売り, Short
            pips = (entry_price - exit_price) / pip_value
        
        return round(pips, 1)
    
    def find_csv_in_zip(self, zip_file_path, currency_pair, date_str):
        """ZIPファイル内の指定日付のCSVファイルを検索"""
        normalized_date = self.normalize_date(date_str)
        self.logger.info(f"検索対象日付: {normalized_date}, ZIPファイル: {zip_file_path}")
        
        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                self.logger.info(f"ZIPファイル内のファイル数: {len(file_list)}")
                
                # 1. 直接マッチする日付を探す
                direct_matches = []
                for file_path in file_list:
                    clean_path = file_path.replace('\\', '/').replace('_', '').replace('-', '')
                    if normalized_date in clean_path and file_path.endswith('.csv'):
                        direct_matches.append(file_path)
                
                if direct_matches:
                    self.logger.info(f"直接マッチするファイルが見つかりました: {direct_matches}")
                    return direct_matches[0]
                
                # 2. サブフォルダ内の日付ファイルを探す
                for file_path in file_list:
                    path_parts = file_path.replace('\\', '/').split('/')
                    if len(path_parts) > 1 and path_parts[-1].endswith('.csv'):
                        if normalized_date in path_parts[-1].replace('_', '').replace('-', ''):
                            self.logger.info(f"サブフォルダ内のファイルが見つかりました: {file_path}")
                            return file_path
                
                # 3. 年月のみのマッチング
                year_month = normalized_date[:6]
                for file_path in file_list:
                    if year_month in file_path.replace('_', '').replace('-', '') and file_path.endswith('.csv'):
                        day_part = normalized_date[6:]
                        if day_part in file_path.replace('_', '').replace('-', ''):
                            self.logger.info(f"年月+日マッチするファイルが見つかりました: {file_path}")
                            return file_path
                
                # 4. CSVファイルで最初に見つかったものを使用
                csv_files = [f for f in file_list if f.endswith('.csv')]
                if csv_files:
                    self.logger.warning(f"日付に一致するファイルが見つからないため、最初のCSVファイルを使用: {csv_files[0]}")
                    return csv_files[0]
                
                self.logger.error(f"ZIPファイル内にCSVファイルが見つかりません: {zip_file_path}")
                return None
                
        except Exception as e:
            self.logger.error(f"ZIPファイル処理エラー: {str(e)}")
            return None
    
    def get_historical_data(self, currency_pair, date_str):
        """特定の通貨ペアと日付のヒストリカルデータを取得"""
        try:
            normalized_date = self.normalize_date(date_str)
            year_month = normalized_date[:6]
            zip_currency = self.convert_to_zip_format(currency_pair)
            
            patterns = [
                f"{zip_currency.upper()}_{year_month}.zip",
                f"{zip_currency.lower()}_{year_month}.zip",
                f"{zip_currency}_{year_month}.zip"
            ]
            
            all_zip_files = glob.glob(os.path.join(HISTORICAL_DATA_DIR, "*.zip"))
            
            matching_zips = []
            for pattern in patterns:
                expected_path = os.path.join(HISTORICAL_DATA_DIR, pattern)
                if os.path.exists(expected_path):
                    matching_zips.append(expected_path)
                else:
                    for zip_file in all_zip_files:
                        zip_name = os.path.basename(zip_file)
                        if zip_currency.upper() in zip_name.upper() and year_month in zip_name:
                            matching_zips.append(zip_file)
            
            if not matching_zips:
                for zip_file in all_zip_files:
                    zip_name = os.path.basename(zip_file)
                    if zip_currency.upper() in zip_name.upper():
                        matching_zips.append(zip_file)
            
            if not matching_zips:
                self.logger.error(f"通貨ペア {currency_pair} に一致するZIPファイルが見つかりません")
                return None
            
            zip_file_path = max(matching_zips, key=os.path.getmtime)
            csv_file_path = self.find_csv_in_zip(zip_file_path, currency_pair, normalized_date)
            
            if not csv_file_path:
                self.logger.error(f"指定日付のCSVファイルが見つかりません: {normalized_date}")
                return None
            
            # CSVファイルを読み込み
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                encodings = ['utf-8', 'shift_jis', 'cp932', 'euc_jp', 'iso-8859-1']
                
                for encoding in encodings:
                    try:
                        with zip_ref.open(csv_file_path) as csv_file:
                            csv_content = csv_file.read().decode(encoding)
                            df = pd.read_csv(io.StringIO(csv_content))
                            break
                    except UnicodeDecodeError:
                        continue
                    except Exception as e:
                        self.logger.error(f"CSVファイル読み込みエラー: {str(e)}")
                        return None
                else:
                    self.logger.error(f"CSVファイルのエンコーディングを特定できません")
                    return None
                
                # カラム名を標準化
                renamed_columns = {}
                for col in df.columns:
                    if col in COLUMN_MAPPING:
                        renamed_columns[col] = COLUMN_MAPPING[col]
                    else:
                        col_str = str(col)
                        if "BID" in col_str.upper() and "始値" in col_str:
                            renamed_columns[col] = "open_bid"
                        elif "BID" in col_str.upper() and "高値" in col_str:
                            renamed_columns[col] = "high_bid"
                        elif "BID" in col_str.upper() and "安値" in col_str:
                            renamed_columns[col] = "low_bid"
                        elif "BID" in col_str.upper() and "終値" in col_str:
                            renamed_columns[col] = "close_bid"
                        elif "ASK" in col_str.upper() and "始値" in col_str:
                            renamed_columns[col] = "open_ask"
                        elif "ASK" in col_str.upper() and "高値" in col_str:
                            renamed_columns[col] = "high_ask"
                        elif "ASK" in col_str.upper() and "安値" in col_str:
                            renamed_columns[col] = "low_ask"
                        elif "ASK" in col_str.upper() and "終値" in col_str:
                            renamed_columns[col] = "close_ask"
                        elif "日時" in col_str:
                            renamed_columns[col] = "timestamp"
                
                if renamed_columns:
                    df = df.rename(columns=renamed_columns)
                
                return df
            
        except Exception as e:
            self.logger.error(f"ヒストリカルデータ取得エラー: {str(e)}")
            return None
    
    def get_rate_at_time(self, df, time_str):
        """指定時間のレートを取得"""
        try:
            if len(time_str.split(':')) == 2:
                time_str += ":00"
                
            target_time = pd.to_datetime(time_str)
            
            if 'timestamp' in df.columns:
                if df['timestamp'].dtype == object:
                    sample_timestamp = df['timestamp'].iloc[0] if not df.empty else None
                    
                    if isinstance(sample_timestamp, str) and '/' in sample_timestamp:
                        df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y/%m/%d %H:%M:%S', errors='coerce')
                    else:
                        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            
                if 'timestamp' in df.columns and not df.empty:
                    df['time_only'] = df['timestamp'].dt.time
                    target_time_only = target_time.time()
                    
                    exact_match = df[df['time_only'] == target_time_only]
                    
                    if not exact_match.empty:
                        row = exact_match.iloc[0]
                        return {
                            "bid": row.get('close_bid'),
                            "ask": row.get('close_ask'),
                            "timestamp": row.get('timestamp')
                        }
                    
                    df['time_diff'] = df['time_only'].apply(lambda t: 
                        abs((t.hour * 3600 + t.minute * 60 + t.second) - 
                            (target_time_only.hour * 3600 + target_time_only.minute * 60 + target_time_only.second)))
                    
                    closest_idx = df['time_diff'].idxmin()
                    closest_row = df.loc[closest_idx]
                    
                    return {
                        "bid": closest_row.get('close_bid'),
                        "ask": closest_row.get('close_ask'),
                        "timestamp": closest_row.get('timestamp')
                    }
                else:
                    target_idx = (target_time.hour * 60) + target_time.minute
                    
                    if 0 <= target_idx < len(df):
                        row = df.iloc[target_idx]
                        return {
                            "bid": row.get('close_bid'),
                            "ask": row.get('close_ask'),
                            "timestamp": target_time
                        }
            
            return None
            
        except Exception as e:
            self.logger.error(f"レート取得エラー: {str(e)}")
            return None
    
    def standardize_columns(self, df):
        """エントリータイプに応じたカラム名の標準化"""
        column_mappings = {}
        
        for col in df.columns:
            col_str = str(col)
            
            if any(keyword in col_str for keyword in ['К‰ЭѓyѓA', 'currency', 'pair', '通貨']):
                column_mappings[col] = '通貨ペア'
            elif any(keyword in col_str for keyword in ['Entry', 'entry', 'エントリー']):
                column_mappings[col] = 'Entry'
            elif any(keyword in col_str for keyword in ['Exit', 'exit', 'エグジット']):
                column_mappings[col] = 'Exit'
            elif any(keyword in col_str for keyword in ['•ыЊь', 'direction', 'type', '方向']):
                column_mappings[col] = '方向'
            elif any(keyword in col_str for keyword in ['"ъ•t', 'date', '日付']):
                column_mappings[col] = '日付'
            elif 'score' in col_str.lower() or 'スコア' in col_str:
                if '実用' in col_str or 'practical' in col_str:
                    column_mappings[col] = '実用スコア'
                elif '総合' in col_str or 'total' in col_str:
                    column_mappings[col] = '総合スコア'
            elif '勝率' in col_str or 'win' in col_str.lower():
                if '短期' in col_str or 'short' in col_str:
                    column_mappings[col] = '短期勝率'
                elif '中期' in col_str or 'mid' in col_str:
                    column_mappings[col] = '中期勝率'
                elif '長期' in col_str or 'long' in col_str:
                    column_mappings[col] = '長期勝率'
        
        if column_mappings:
            df = df.rename(columns=column_mappings)
            self.logger.info(f"カラム名を置換しました: {column_mappings}")
        
        return df

    def process_single_file(self, file_path, file_date):
        """単一ファイルの処理"""
        self.logger.info(f"📊 処理開始: {os.path.basename(file_path)} (日付: {file_date})")
        
        # 結果ファイルのパス
        result_file = os.path.join(
            self.config['output_dir'], 
            f"{self.config['output_prefix']}_{file_date}.csv"
        )
        
        try:
            # CSVファイルを読み込み
            encodings = ['utf-8', 'utf-8-sig', 'shift_jis', 'cp932', 'euc_jp']
            df = None
            
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    self.logger.info(f"CSVファイルを読み込みました: エンコーディング {encoding}")
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    self.logger.error(f"CSV読み込みエラー ({encoding}): {str(e)}")
            
            if df is None:
                self.logger.error(f"CSVファイルを読み込めませんでした: {file_path}")
                return False
            
            # カラム名の標準化
            df = self.standardize_columns(df)
            
            # 必要なカラムの確認
            required_columns = ['通貨ペア', 'Entry', '方向']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                self.logger.error(f"必要なカラムがありません: {', '.join(missing_columns)}")
                return False
            
            # 結果用のカラムを追加
            result_columns = ['Entry価格', 'Exit価格', '勝敗', 'pips']
            for col in result_columns:
                if col not in df.columns:
                    df[col] = None
            
            # 各エントリーポイントを処理
            for idx, row in df.iterrows():
                currency_name = row['通貨ペア']
                currency_pair = self.convert_currency_name(currency_name)
                entry_str = row['Entry']
                
                # エントリーデータの解析
                entry_price, entry_time = self.parse_entry_data(entry_str)
                
                if not entry_time and isinstance(entry_str, str) and ':' in entry_str:
                    entry_time = entry_str
                
                if not entry_price and not entry_time:
                    self.logger.warning(f"行 {idx+1}: エントリーデータの解析に失敗しました: {entry_str}")
                    continue
                
                # Exit時刻の取得
                exit_time = None
                if 'Exit' in df.columns and pd.notna(row['Exit']):
                    exit_str = row['Exit']
                    _, exit_time = self.parse_entry_data(exit_str)
                    if not exit_time and isinstance(exit_str, str) and ':' in exit_str:
                        exit_time = exit_str
                
                if not exit_time:
                    self.logger.warning(f"行 {idx+1}: Exit時刻が取得できませんでした")
                    continue
                
                # ヒストリカルデータを取得
                historical_data = self.get_historical_data(currency_pair, file_date)
                
                if historical_data is None:
                    self.logger.error(f"行 {idx+1}: ヒストリカルデータが見つかりません")
                    continue
                
                # Entry価格の取得
                if not entry_price and entry_time:
                    rate_at_entry = self.get_rate_at_time(historical_data, entry_time)
                    if rate_at_entry:
                        trade_direction = row['方向']
                        if trade_direction.upper() in ["BUY", "LONG", "買い", "Long"]:
                            entry_price = rate_at_entry["ask"]
                        else:
                            entry_price = rate_at_entry["bid"]
                        self.logger.info(f"行 {idx+1}: Entry時間 {entry_time} のレート: {entry_price}")
                    else:
                        self.logger.warning(f"行 {idx+1}: Entry時間 {entry_time} のレートが見つかりませんでした")
                        continue
                
                # Exit価格の取得（修正箇所）
                trade_direction = row['方向']
                rate_at_exit = self.get_rate_at_time(historical_data, exit_time)
                
                if rate_at_exit:
                    if trade_direction.upper() in ["BUY", "LONG", "買い", "Long"]:
                        exit_price = rate_at_exit["bid"]  # 買いポジションの決済はBID
                    else:  # "SELL", "SHORT", "売り", "Short"
                        exit_price = rate_at_exit["ask"]  # 売りポジションの決済はASK
                    
                    self.logger.info(f"行 {idx+1}: Exit時間 {exit_time} のレート: {exit_price}")
                else:
                    self.logger.warning(f"行 {idx+1}: Exit時間 {exit_time} のレートが見つかりませんでした")
                    continue
                
                # pipsの計算
                pips = self.calculate_pips(entry_price, exit_price, currency_pair, trade_direction)
                
                # 勝敗判定
                if pips > 0:
                    win_loss = "WIN"
                elif pips < 0:
                    win_loss = "LOSS"
                else:
                    win_loss = "EVEN"
                
                # 結果を更新
                df.at[idx, 'Entry価格'] = entry_price
                df.at[idx, 'Exit価格'] = exit_price
                df.at[idx, '勝敗'] = win_loss
                df.at[idx, 'pips'] = pips
            
            # 結果を保存
            df.to_csv(result_file, index=False, encoding='shift_jis')
            self.logger.info(f"結果を保存しました: {result_file}")
            
            # 結果の要約を表示
            wins = df[df['勝敗'] == 'WIN'].shape[0]
            losses = df[df['勝敗'] == 'LOSS'].shape[0]
            evens = df[df['勝敗'] == 'EVEN'].shape[0]
            total_pips = df['pips'].sum()
            
            self.logger.info(f"分析結果:")
            self.logger.info(f"  エントリータイプ: {self.config['name']}")
            self.logger.info(f"  分析対象日: {file_date}")
            self.logger.info(f"  総取引数: {len(df)}")
            self.logger.info(f"  勝ち: {wins}, 負け: {losses}, 引き分け: {evens}")
            if wins + losses > 0:
                self.logger.info(f"  勝率: {wins/(wins+losses)*100:.1f}%")
            self.logger.info(f"  合計pips: {total_pips:.1f}")
            
            # グラフを生成
            self.generate_report(df, file_date)
            
            return True
            
        except Exception as e:
            self.logger.error(f"処理エラー: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def process_all_unprocessed_files(self):
        """未処理のすべてのファイルを処理"""
        unprocessed_files = self.get_unprocessed_files()
        
        if not unprocessed_files:
            self.logger.info("🎉 処理対象のファイルがありません。すべてのファイルが処理済みです。")
            return True
        
        self.logger.info(f"🚀 一括処理開始: {len(unprocessed_files)}件のファイルを処理します")
        
        success_count = 0
        failure_count = 0
        
        for i, (file_path, file_date) in enumerate(unprocessed_files, 1):
            self.logger.info(f"📊 進捗: {i}/{len(unprocessed_files)} - {os.path.basename(file_path)}")
            
            if self.process_single_file(file_path, file_date):
                success_count += 1
                self.logger.info(f"✅ 処理成功: {os.path.basename(file_path)}")
            else:
                failure_count += 1
                self.logger.error(f"❌ 処理失敗: {os.path.basename(file_path)}")
        
        # 処理結果の集計
        self.logger.info(f"📊 一括処理完了:")
        self.logger.info(f"  対象ファイル数: {len(unprocessed_files)}")
        self.logger.info(f"  成功: {success_count}")
        self.logger.info(f"  失敗: {failure_count}")
        
        if failure_count == 0:
            self.logger.info("🎉 すべてのファイルが正常に処理されました！")
        else:
            self.logger.warning(f"⚠️  {failure_count}件のファイルで処理に失敗しました。ログを確認してください。")
        
        return failure_count == 0

    def generate_report(self, df, file_date):
        """結果レポートとグラフを生成"""
        try:
            # グラフ用ディレクトリ
            chart_dir = os.path.join(self.config['output_dir'], "charts")
            Path(chart_dir).mkdir(exist_ok=True)
            
            # 結果の概要グラフ
            plt.figure(figsize=(10, 6))
            
            # 日本語フォントの設定
            import matplotlib as mpl
            plt.rcParams['font.family'] = 'sans-serif'
            
            # Windows環境
            if os.name == 'nt':
                font_dirs = [os.path.join(os.environ['WINDIR'], 'Fonts')]
                font_files = mpl.font_manager.findSystemFonts(fontpaths=font_dirs)
                
                for font_file in font_files:
                    if any(name in font_file.lower() for name in ['msgothic', 'meiryo', 'yugothic', 'arial', 'tahoma']):
                        mpl.font_manager.fontManager.addfont(font_file)
                
                plt.rcParams['font.sans-serif'] = ['MS Gothic', 'Meiryo', 'Yu Gothic', 'Arial', 'Tahoma', 'DejaVu Sans']
            # macOS環境
            elif sys.platform == 'darwin':
                plt.rcParams['font.sans-serif'] = ['Hiragino Sans', 'Hiragino Kaku Gothic Pro', 'AppleGothic', 'Arial', 'Tahoma', 'DejaVu Sans']
            # Linux環境
            else:
                plt.rcParams['font.sans-serif'] = ['IPAGothic', 'VL Gothic', 'Noto Sans CJK JP', 'Takao Gothic', 'Arial', 'Tahoma', 'DejaVu Sans']
            
            # 勝敗円グラフ
            plt.subplot(1, 2, 1)
            win_counts = df['勝敗'].value_counts()
            if not win_counts.empty:
                labels = win_counts.index
                sizes = win_counts.values
                colors = ['green' if x == 'WIN' else 'red' if x == 'LOSS' else 'gray' for x in labels]
                plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
                plt.axis('equal')
                plt.title(f'{self.config["name"]} - Trading Results')
            else:
                plt.text(0.5, 0.5, 'No Data', horizontalalignment='center', verticalalignment='center')
            
            # 通貨ペア別pipsのバーグラフ
            plt.subplot(1, 2, 2)
            currency_pips = df.groupby('通貨ペア')['pips'].sum()
            if not currency_pips.empty:
                colors = ['green' if x >= 0 else 'red' for x in currency_pips.values]
                currency_pips.plot(kind='bar', color=colors)
                plt.title(f'{self.config["name"]} - Pips by Currency Pair')
                plt.ylabel('pips')
            else:
                plt.text(0.5, 0.5, 'No Data', horizontalalignment='center', verticalalignment='center')
                
            plt.tight_layout()
            
            # グラフの保存
            chart_path = os.path.join(chart_dir, f"{self.config['output_prefix']}_{file_date}.png")
            plt.savefig(chart_path)
            plt.close()
            
            self.logger.info(f"グラフを保存しました: {chart_path}")
            
            # HTMLレポートの生成
            self.generate_html_report(df, file_date)
                
        except Exception as e:
            self.logger.error(f"レポート生成エラー: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

    def generate_html_report(self, df, file_date):
        """HTMLレポート生成"""
        try:
            html_content = f"""
            <!DOCTYPE html>
            <html lang="ja">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>FX取引結果 {file_date} - {self.config['name']}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    h1, h2 {{ color: #2c3e50; }}
                    table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                    th, td {{ text-align: left; padding: 8px; border: 1px solid #ddd; }}
                    th {{ background-color: #f2f2f2; }}
                    tr:nth-child(even) {{ background-color: #f9f9f9; }}
                    .win {{ color: green; }}
                    .loss {{ color: red; }}
                    .even {{ color: gray; }}
                    .summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                    img {{ max-width: 100%; height: auto; margin: 20px 0; }}
                    .analysis-info {{ background-color: #e3f2fd; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                    .entry-type {{ background-color: #fff3e0; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
                </style>
            </head>
            <body>
                <h1>FX取引結果レポート - {file_date}</h1>
                
                <div class="entry-type">
                    <h2>📊 エントリータイプ: {self.config['name']}</h2>
                    <p><strong>入力フォルダ:</strong> {self.config['input_dir']}</p>
                    <p><strong>出力フォルダ:</strong> {self.config['output_dir']}</p>
                </div>
                
                <div class="analysis-info">
                    <h2>📊 分析情報</h2>
                    <p><strong>分析対象日:</strong> {file_date}</p>
                    <p><strong>分析方式:</strong> 未処理ファイル自動検出・一括処理</p>
                    <p><strong>処理ロジック:</strong> input側存在 ∧ output側未存在 → 分析実行</p>
                </div>
                
                <div class="summary">
                    <h2>取引概要</h2>
                    <p>総取引数: {len(df)}</p>
            """
            
            # 勝敗データを安全に取得
            win_count = df[df['勝敗'] == 'WIN'].shape[0]
            loss_count = df[df['勝敗'] == 'LOSS'].shape[0]
            even_count = df[df['勝敗'] == 'EVEN'].shape[0]
            pips_sum = df['pips'].sum() if not df.empty and 'pips' in df.columns and df['pips'].notna().any() else 0.0
            
            html_content += f"""
                    <p>勝ち: <span class="win">{win_count}</span></p>
                    <p>負け: <span class="loss">{loss_count}</span></p>
                    <p>引き分け: <span class="even">{even_count}</span></p>
            """
            
            # 勝率の計算（ゼロ除算を回避）
            if win_count + loss_count > 0:
                win_rate = win_count / (win_count + loss_count) * 100
                html_content += f'    <p>勝率: {win_rate:.1f}%</p>\n'
            else:
                html_content += '    <p>勝率: 0.0%</p>\n'
                
            html_content += f'    <p>合計pips: {pips_sum:.1f}</p>\n'
            html_content += """
                </div>
                
                <h2>取引詳細</h2>
                <table>
                    <tr>
                        <th>No</th>
                        <th>通貨ペア</th>
                        <th>方向</th>
                        <th>Entry</th>
            """
            
            # Exitカラムがある場合は追加
            if 'Exit' in df.columns:
                html_content += "<th>Exit</th>"
            
            html_content += """
                        <th>Entry価格</th>
                        <th>Exit価格</th>
                        <th>勝敗</th>
                        <th>pips</th>
                    </tr>
            """
            
            for idx, row in df.iterrows():
                win_class = "win" if row['勝敗'] == 'WIN' else "loss" if row['勝敗'] == 'LOSS' else "even"
                
                # 各値の安全な取得（NaN対策）
                entry_price = row['Entry価格'] if pd.notna(row['Entry価格']) else ""
                entry_price_fmt = f"{entry_price:.3f}" if isinstance(entry_price, (int, float)) else entry_price
                
                exit_price = row['Exit価格'] if pd.notna(row['Exit価格']) else ""
                exit_price_fmt = f"{exit_price:.3f}" if isinstance(exit_price, (int, float)) else exit_price
                
                pips = row['pips'] if pd.notna(row['pips']) else ""
                pips_fmt = f"{pips:.1f}" if isinstance(pips, (int, float)) else pips
                
                no = row.get('No', idx+1)
                currency = row['通貨ペア'] if pd.notna(row['通貨ペア']) else ""
                direction = row['方向'] if pd.notna(row['方向']) else ""
                entry = row['Entry'] if pd.notna(row['Entry']) else ""
                win_loss = row['勝敗'] if pd.notna(row['勝敗']) else ""
                
                html_content += f"""
                    <tr>
                        <td>{no}</td>
                        <td>{currency}</td>
                        <td>{direction}</td>
                        <td>{entry}</td>
                """
                
                # Exitカラムがある場合は追加
                if 'Exit' in df.columns:
                    exit_col = row['Exit'] if pd.notna(row['Exit']) else ""
                    html_content += f"<td>{exit_col}</td>"
                
                html_content += f"""
                        <td>{entry_price_fmt}</td>
                        <td>{exit_price_fmt}</td>
                        <td class="{win_class}">{win_loss}</td>
                        <td class="{win_class}">{pips_fmt}</td>
                    </tr>
                """
            
            html_content += f"""
                </table>
                
                <h2>グラフ</h2>
                <img src="charts/{self.config['output_prefix']}_{file_date}.png" alt="FX取引結果グラフ">
                
                <div class="analysis-info">
                    <h2>📝 注意事項</h2>
                    <p>• このレポートは{file_date}の{self.config['name']}を分析した結果です</p>
                    <p>• 自動的に未処理ファイルを検出し、一括処理を実行しています</p>
                    <p>• output側のファイルを削除することで、再分析が可能です</p>
                </div>
            </body>
            </html>
            """
            
            # HTMLレポートの保存
            html_path = os.path.join(self.config['output_dir'], f"{self.config['output_prefix']}_{file_date}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
                
            self.logger.info(f"HTMLレポートを保存しました: {html_path}")
        
        except Exception as e:
            self.logger.error(f"HTMLレポート生成エラー: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='FX結果分析ツール（一括処理版）')
    parser.add_argument('--type', choices=['yokubari', 'standard', 'both'], default='both',
                        help='分析するエントリーポイントのタイプ (default: both - 両方実行)')
    
    args = parser.parse_args()
    
    try:
        if args.type == 'both':
            # 両方のタイプを処理
            print("🚀 FX結果分析を開始します（よくばりエントリー + 標準エントリー）")
            print("📅 処理ロジック: input側存在 ∧ output側未存在 → 自動分析")
            print("💡 利便性: output側削除 → 再分析可能")
            
            success_count = 0
            total_count = 2
            
            # よくばりエントリー分析
            print("\n" + "="*60)
            print("📊 Step 1/2: よくばりエントリー分析開始")
            print("="*60)
            try:
                analyzer_yokubari = FXResultAnalyzer(entry_type='yokubari')
                if analyzer_yokubari.process_all_unprocessed_files():
                    print("✅ よくばりエントリー分析完了")
                    success_count += 1
                else:
                    print("⚠️  よくばりエントリー分析で一部失敗")
            except Exception as e:
                print(f"❌ よくばりエントリー分析エラー: {str(e)}")
            
            # 標準エントリー分析
            print("\n" + "="*60)
            print("📊 Step 2/2: 標準エントリー分析開始")
            print("="*60)
            try:
                analyzer_standard = FXResultAnalyzer(entry_type='standard')
                if analyzer_standard.process_all_unprocessed_files():
                    print("✅ 標準エントリー分析完了")
                    success_count += 1
                else:
                    print("⚠️  標準エントリー分析で一部失敗")
            except Exception as e:
                print(f"❌ 標準エントリー分析エラー: {str(e)}")
            
            # 全体結果
            print("\n" + "="*60)
            print("📋 全体処理結果")
            print("="*60)
            print(f"処理完了: {success_count}/{total_count}")
            
            if success_count == total_count:
                print("🎉 すべての分析が正常に完了しました！")
            elif success_count > 0:
                print("⚠️  一部の分析が完了しました。失敗した分析のログを確認してください。")
            else:
                print("❌ すべての分析が失敗しました。設定とログを確認してください。")
                
        else:
            # 単一タイプを処理
            print(f"🚀 FX結果分析を開始します（{ENTRYPOINT_CONFIGS[args.type]['name']}）")
            print(f"📅 処理ロジック: input側存在 ∧ output側未存在 → 自動分析")
            print(f"💡 利便性: output側削除 → 再分析可能")
            print(f"📁 入力: {ENTRYPOINT_CONFIGS[args.type]['input_dir']}")
            print(f"📁 出力: {ENTRYPOINT_CONFIGS[args.type]['output_dir']}")
            
            analyzer = FXResultAnalyzer(entry_type=args.type)
            
            if analyzer.process_all_unprocessed_files():
                print("✅ すべてのファイルが正常に処理されました")
            else:
                print("⚠️  一部のファイルで処理に失敗しました。ログを確認してください。")
            
    except Exception as e:
        print(f"実行エラー: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()