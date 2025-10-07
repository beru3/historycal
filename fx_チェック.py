#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import pandas as pd
import zipfile
import io
import logging
from pathlib import Path
import glob
import re
from datetime import datetime

# 基本設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(BASE_DIR, "entrypoint_fx_result")
HISTORICAL_DATA_DIR = os.path.join(BASE_DIR, "input")

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# カラム名の正規化マッピング
COLUMN_MAPPING = {
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

def normalize_date(date_str):
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
            
    logger.warning(f"未対応の日付形式: {date_str}")
    return date_str

def convert_currency_name(name):
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

def convert_to_zip_format(currency_pair):
    """通貨ペアをZIPファイル名のフォーマットに変換"""
    return currency_pair.replace("_", "")

def find_csv_in_zip(zip_file_path, currency_pair, date_str):
    """ZIPファイル内の指定日付のCSVファイルを検索。見つからない場合は最も直近の日付のファイルを採用"""
    normalized_date = normalize_date(date_str)
    logger.info(f"検索対象日付: {normalized_date}, ZIPファイル: {os.path.basename(zip_file_path)}")
    
    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            logger.info(f"ZIPファイル内のファイル数: {len(file_list)}")
            
            if len(file_list) > 0:
                logger.info(f"最初のファイル: {file_list[0]}")
            
            # 1. 直接マッチする日付を探す
            direct_matches = []
            for file_path in file_list:
                # 区切り文字を取り除く
                clean_path = file_path.replace('\\', '/').replace('_', '').replace('-', '')
                if normalized_date in clean_path and file_path.endswith('.csv'):
                    direct_matches.append(file_path)
            
            if direct_matches:
                logger.info(f"直接マッチするファイルが見つかりました: {direct_matches[0]}")
                return direct_matches[0]
            
            # 2. 日付が含まれるCSVファイルを全て見つけて日付順にソート
            dated_csv_files = []
            date_pattern = re.compile(r'(\d{8})')  # YYYYMMDD形式の日付を検出
            
            for file_path in file_list:
                if file_path.endswith('.csv'):
                    # パスから日付を抽出
                    clean_path = file_path.replace('\\', '/').replace('_', '').replace('-', '')
                    date_match = date_pattern.search(clean_path)
                    if date_match:
                        file_date = date_match.group(1)
                        # 目標日付との差分（絶対値）を計算
                        try:
                            target_date = datetime.strptime(normalized_date, '%Y%m%d')
                            file_datetime = datetime.strptime(file_date, '%Y%m%d')
                            date_diff = abs((target_date - file_datetime).days)
                            dated_csv_files.append((file_path, file_date, date_diff))
                        except ValueError:
                            # 日付変換に失敗した場合はスキップ
                            continue
            
            # 日付の差分でソート（最も近い日付順）
            if dated_csv_files:
                dated_csv_files.sort(key=lambda x: x[2])
                closest_file = dated_csv_files[0][0]
                closest_date = dated_csv_files[0][1]
                logger.info(f"最も近い日付のファイルが見つかりました: {closest_file} (日付: {closest_date})")
                return closest_file
            
            # 3. CSVファイルで最初に見つかったものを使用
            csv_files = [f for f in file_list if f.endswith('.csv')]
            if csv_files:
                logger.warning(f"日付に一致するファイルが見つからないため、最初のCSVファイルを使用: {csv_files[0]}")
                return csv_files[0]
            
            logger.error(f"ZIPファイル内にCSVファイルが見つかりません: {zip_file_path}")
            return None
            
    except Exception as e:
        logger.error(f"ZIPファイル処理エラー: {str(e)}")
        return None

def get_historical_data(currency_pair, date_str):
    """特定の通貨ペアと日付のヒストリカルデータを取得"""
    try:
        normalized_date = normalize_date(date_str)
        
        # 日付文字列からYYYYMM形式を抽出
        year_month = normalized_date[:6]  # 例: 20250502 -> 202505
        
        # 通貨ペアをZIPファイル名のフォーマットに変換
        zip_currency = convert_to_zip_format(currency_pair)
        
        # 大文字・小文字・年月の組み合わせを用意
        patterns = [
            f"{zip_currency.upper()}_{year_month}.zip",
            f"{zip_currency.lower()}_{year_month}.zip",
            f"{zip_currency}_{year_month}.zip"
        ]
        
        # インプットフォルダ内のすべてのZIPファイルを取得
        all_zip_files = glob.glob(os.path.join(HISTORICAL_DATA_DIR, "*.zip"))
        logger.info(f"入力フォルダ内のZIPファイル: {len(all_zip_files)}件")
        
        # パターンに一致するZIPファイルを検索
        matching_zips = []
        for pattern in patterns:
            expected_path = os.path.join(HISTORICAL_DATA_DIR, pattern)
            if os.path.exists(expected_path):
                matching_zips.append(expected_path)
                logger.info(f"パターンに一致するZIPファイルが見つかりました: {pattern}")
            else:
                # 名前の一部が一致するZIPファイルを探す
                for zip_file in all_zip_files:
                    zip_name = os.path.basename(zip_file)
                    # 通貨ペアと年月が一致するか確認
                    if zip_currency.upper() in zip_name.upper() and year_month in zip_name:
                        matching_zips.append(zip_file)
        
        if not matching_zips:
            logger.warning(f"通貨ペア {currency_pair} の年月 {year_month} に一致するZIPファイルが見つかりません")
            # すべてのZIPファイルをチェック
            for zip_file in all_zip_files:
                zip_name = os.path.basename(zip_file)
                if zip_currency.upper() in zip_name.upper():
                    matching_zips.append(zip_file)
        
        if not matching_zips:
            logger.error(f"通貨ペア {currency_pair} に一致するZIPファイルが見つかりません")
            return None
        
        # 最新のZIPファイルを使用
        zip_file_path = max(matching_zips, key=os.path.getmtime)
        logger.info(f"使用するZIPファイル: {os.path.basename(zip_file_path)}")
        
        # ZIPファイル内のCSVファイルを探す
        csv_file_path = find_csv_in_zip(zip_file_path, currency_pair, normalized_date)
        
        if not csv_file_path:
            logger.error(f"指定日付のCSVファイルが見つかりません: {normalized_date}")
            return None
        
        # CSVファイルを読み込み
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            # ShiftJISなどの可能性があるためエンコーディングを試す
            encodings = ['utf-8', 'shift_jis', 'cp932', 'euc_jp', 'iso-8859-1']
            
            for encoding in encodings:
                try:
                    with zip_ref.open(csv_file_path) as csv_file:
                        csv_content = csv_file.read().decode(encoding)
                        df = pd.read_csv(io.StringIO(csv_content))
                        logger.info(f"CSVファイルを正常に読み込みました: {csv_file_path} (エンコーディング: {encoding})")
                        break
                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"CSVファイル読み込みエラー: {str(e)}")
                    return None
            else:
                logger.error(f"CSVファイルのエンコーディングを特定できません")
                return None
            
            # カラム名を標準化
            renamed_columns = {}
            for col in df.columns:
                # 既知のカラム名マッピングを確認
                if col in COLUMN_MAPPING:
                    renamed_columns[col] = COLUMN_MAPPING[col]
            
            if renamed_columns:
                df = df.rename(columns=renamed_columns)
                logger.info(f"カラム名を標準化しました: {renamed_columns}")
            
            return df
        
    except Exception as e:
        logger.error(f"ヒストリカルデータ取得エラー: {str(e)}")
        return None

def get_rate_at_time(df, time_str, direction):
    """指定時間のレートを取得（LONGならASK、SHORTならBID）"""
    try:
        logger.info(f"方向{direction}で時間指定レートを探しています: {time_str}")
        
        # 時間文字列をパース
        # 秒がない場合は追加
        if len(time_str.split(':')) == 2:
            time_str += ":00"
            
        target_time = pd.to_datetime(time_str)
        
        # timestampカラムの確認
        if 'timestamp' in df.columns:
            # タイムスタンプ列をdatetime型に変換
            if df['timestamp'].dtype == object:
                # サンプルデータを確認
                sample_timestamp = df['timestamp'].iloc[0] if not df.empty else None
                
                # 日付+時間形式の場合
                if isinstance(sample_timestamp, str) and '/' in sample_timestamp:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], format='%Y/%m/%d %H:%M:%S', errors='coerce')
                else:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                
                logger.info(f"タイムスタンプ列をdatetime型に変換しました")
        
            # 最も近い時間のデータを取得
            if 'timestamp' in df.columns and not df.empty:
                # タイムスタンプから時間部分のみを抽出
                df['time_only'] = df['timestamp'].dt.time
                target_time_only = target_time.time()
                
                # 時間部分が一致するデータを検索
                exact_match = df[df['time_only'] == target_time_only]
                
                if not exact_match.empty:
                    logger.info(f"完全一致するデータが見つかりました: {target_time_only}")
                    row = exact_match.iloc[0]
                    
                    # 方向に応じて適切な価格を返す
                    if direction.upper() in ["BUY", "LONG", "買い", "Long"]:
                        return row.get('open_ask')  # 買いの場合はASK価格
                    else:  # "SELL", "SHORT", "売り", "Short"
                        return row.get('open_bid')  # 売りの場合はBID価格
                
                # 完全一致がなければ、差分を計算して最も近いデータを取得
                df['time_diff'] = df['time_only'].apply(lambda t: 
                    abs((t.hour * 3600 + t.minute * 60 + t.second) - 
                        (target_time_only.hour * 3600 + target_time_only.minute * 60 + target_time_only.second)))
                
                closest_idx = df['time_diff'].idxmin()
                closest_row = df.loc[closest_idx]
                
                logger.info(f"最も近い時間のデータ: {closest_row.get('timestamp')}")
                
                # 方向に応じて適切な価格を返す
                if direction.upper() in ["BUY", "LONG", "買い", "Long"]:
                    return closest_row.get('open_ask')  # 買いの場合はASK価格
                else:  # "SELL", "SHORT", "売り", "Short"
                    return closest_row.get('open_bid')  # 売りの場合はBID価格
        
        logger.warning(f"指定時間のレートが見つかりません: {time_str}")
        return None
        
    except Exception as e:
        logger.error(f"レート取得エラー: {str(e)}")
        return None

def calculate_pips(entry_price, exit_price, currency_pair, trade_type):
    """pipsを計算"""
    # 通貨ペアに応じてpip値を決定
    if currency_pair.endswith("JPY"):
        pip_value = 0.01
    else:
        pip_value = 0.0001
    
    # 取引タイプに応じて計算方法を変える
    if trade_type.upper() in ["BUY", "LONG", "買い", "Long"]:
        pips = (exit_price - entry_price) / pip_value
    else:  # "SELL", "SHORT", "売り", "Short"
        pips = (entry_price - exit_price) / pip_value
    
    return round(pips, 1)

# def check_prices(results_file):
#     """結果ファイルのチェック"""
#     try:
#         # 結果ファイルを読み込み
#         df = pd.read_csv(results_file, encoding='shift_jis')
#         logger.info(f"結果ファイルを読み込みました: {results_file}")
#         logger.info(f"カラム: {df.columns.tolist()}")
        
#         # カラム名の正規化（文字化け対応）
#         column_mapping = {}
#         for col in df.columns:
#             col_str = str(col)
#             if "'К‰ЭѓyѓA" in col_str or "通貨ペア" in col_str:
#                 column_mapping[col] = "通貨ペア"
#             elif "Entry" in col_str:
#                 column_mapping[col] = "Entry"
#             elif "Exit" in col_str:
#                 column_mapping[col] = "Exit"
#             elif "•ыЊь" in col_str or "方向" in col_str:
#                 column_mapping[col] = "方向"
#             elif '"ъ•t' in col_str or "日付" in col_str:
#                 column_mapping[col] = "日付"
                
#         # カラム名を正規化
#         if column_mapping:
#             df = df.rename(columns=column_mapping)
            
#         # 検証結果用のデータフレーム
#         verification_results = []
        
#         # 各行を検証
#         for idx, row in df.iterrows():
#             currency_name = row['通貨ペア']
#             currency_pair = convert_currency_name(currency_name)
#             entry_time = row['Entry']
#             exit_time = row['Exit']
#             direction = row['方向']
            
#             # 日付の取得
#             record_date = None
#             if '日付' in df.columns and pd.notna(row['日付']):
#                 record_date = row['日付']
            
#             logger.info(f"行 {idx+1} を検証中: {currency_pair}, {entry_time}-{exit_time}, {direction}")
            
#             # ヒストリカルデータの取得
#             historical_data = get_historical_data(currency_pair, record_date)
            
#             if historical_data is None:
#                 logger.error(f"行 {idx+1}: ヒストリカルデータが見つかりません")
#                 verification_results.append({
#                     'No': row.get('No', idx+1),
#                     '通貨ペア': currency_pair,
#                     'Entry': entry_time,
#                     'Exit': exit_time,
#                     '方向': direction,
#                     '実際Entry価格': None,
#                     '実際Exit価格': None,
#                     '実際pips': None
#                 })
#                 continue

def check_prices(results_file):
    """結果ファイルのチェック"""
    try:
        # ファイル名から日付を抽出
        file_name = os.path.basename(results_file)
        file_date_match = re.search(r'_(\d{8})', file_name)
        file_date = file_date_match.group(1) if file_date_match else None
        
        logger.info(f"ファイル名から抽出した日付: {file_date}")
        
        # 結果ファイルを読み込み
        df = pd.read_csv(results_file, encoding='shift_jis')
        logger.info(f"結果ファイルを読み込みました: {results_file}")
        logger.info(f"カラム: {df.columns.tolist()}")
        
        # カラム名の正規化（文字化け対応）
        column_mapping = {}
        for col in df.columns:
            col_str = str(col)
            if "'К‰ЭѓyѓA" in col_str or "通貨ペア" in col_str:
                column_mapping[col] = "通貨ペア"
            elif "Entry" in col_str:
                column_mapping[col] = "Entry"
            elif "Exit" in col_str:
                column_mapping[col] = "Exit"
            elif "•ыЊь" in col_str or "方向" in col_str:
                column_mapping[col] = "方向"
                
        # カラム名を正規化
        if column_mapping:
            df = df.rename(columns=column_mapping)
            
        # 検証結果用のデータフレーム
        verification_results = []
        
        # 各行を検証
        for idx, row in df.iterrows():
            currency_name = row['通貨ペア']
            currency_pair = convert_currency_name(currency_name)
            entry_time = row['Entry']
            exit_time = row['Exit']
            direction = row['方向']
            
            # CSVの日付カラムは使わず、ファイル名の日付を使用
            record_date = file_date
            
            logger.info(f"行 {idx+1} を検証中: {currency_pair}, {entry_time}-{exit_time}, {direction}")
            
            # ヒストリカルデータの取得
            historical_data = get_historical_data(currency_pair, record_date)
            
            if historical_data is None:
                logger.error(f"行 {idx+1}: ヒストリカルデータが見つかりません")
                verification_results.append({
                    'No': row.get('No', idx+1),
                    '通貨ペア': currency_pair,
                    'Entry': entry_time,
                    'Exit': exit_time,
                    '方向': direction,
                    '実際Entry価格': None,
                    '実際Exit価格': None,
                    '実際pips': None
                })
                continue
            
            # Entry価格の検証
            actual_entry_price = get_rate_at_time(historical_data, entry_time, direction)
            if actual_entry_price is None:
                logger.warning(f"行 {idx+1}: Entry時間 {entry_time} の実際のレートが見つかりません")
            
            # Exit価格の検証 - 方向の逆を指定
            exit_direction = "SELL" if direction.upper() in ["BUY", "LONG", "買い", "Long"] else "BUY"
            actual_exit_price = get_rate_at_time(historical_data, exit_time, exit_direction)
            if actual_exit_price is None:
                logger.warning(f"行 {idx+1}: Exit時間 {exit_time} の実際のレートが見つかりません")
            
            # 価格が取得できた場合のみpipsを計算
            actual_pips = None
            if actual_entry_price is not None and actual_exit_price is not None:
                actual_pips = calculate_pips(actual_entry_price, actual_exit_price, currency_pair, direction)
            
            # 検証結果を追加
            verification_results.append({
                'No': row.get('No', idx+1),
                '通貨ペア': currency_pair,
                'Entry': entry_time,
                'Exit': exit_time,
                '方向': direction,
                '実際Entry価格': actual_entry_price,
                '実際Exit価格': actual_exit_price,
                '実際pips': actual_pips
            })
        
        # 検証結果をデータフレームに変換
        verification_df = pd.DataFrame(verification_results)
        
        # 結果を保存
        output_file = os.path.join(os.path.dirname(results_file), "price_verification_results.csv")
        verification_df.to_csv(output_file, index=False, encoding='shift_jis')
        logger.info(f"検証結果を保存しました: {output_file}")
        
        return verification_df
        
    except Exception as e:
        logger.error(f"検証処理エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    
def main():
    """メイン処理"""
    try:
        # よくばりエントリーファイルを探す
        entrypoint_dir = os.path.join(BASE_DIR, "entrypoint_fx_よくばり")
        entry_files = glob.glob(os.path.join(entrypoint_dir, "よくばりエントリー_*.csv"))
        
        if not entry_files:
            logger.error("よくばりエントリーファイルが見つかりません")
            return
        
        # 最新のよくばりエントリーファイルを使用
        latest_file = max(entry_files, key=os.path.getmtime)
        logger.info(f"最新のよくばりエントリーファイル: {os.path.basename(latest_file)}")
        
        # 価格の検証
        verification_results = check_prices(latest_file)
        
        if verification_results is not None:
            # 検証結果を表示
            print("\n価格検証結果:")
            for idx, row in verification_results.iterrows():
                entry_msg = f"実際Entry価格: {row['実際Entry価格']:.3f}" if pd.notna(row['実際Entry価格']) else "実際Entry価格: データなし"
                exit_msg = f"実際Exit価格: {row['実際Exit価格']:.3f}" if pd.notna(row['実際Exit価格']) else "実際Exit価格: データなし"
                pips_msg = f"実際pips: {row['実際pips']:.1f}" if pd.notna(row['実際pips']) else "実際pips: データなし"
                
                print(f"\n取引 {int(row['No'])}: {row['通貨ペア']} {row['方向']} ({row['Entry']}-{row['Exit']})")
                print(f"  {entry_msg}")
                print(f"  {exit_msg}")
                print(f"  {pips_msg}")
            
            # 結果の要約
            print(f"\n検証結果サマリー:")
            print(f"  総レコード数: {len(verification_results)}")
            
    except Exception as e:
        logger.error(f"実行エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()