import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import glob
import zipfile
import shutil
import time
import traceback
import requests
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import stats
import pickle
import json

# Webhook URL（GASでデプロイしたURL）
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyg1dMZEouYwtv8X8z_w7V3mnkryqPaJwOEiwObJ6Xb6lMg6rlvEODUp1ZSOQrPry0K/exec"


def load_currency_settings(settings_file):
    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            settings = json.load(f)
        return settings.get('currency_pairs', {})
    except FileNotFoundError:
        print(f"警告: 設定ファイル {settings_file} が見つかりません。デフォルト設定を使用します。")
        return create_default_settings(settings_file)
    except json.JSONDecodeError:
        print(f"警告: 設定ファイル {settings_file} の形式が不正です。デフォルト設定を使用します。")
        return create_default_settings(settings_file)

def create_default_settings(settings_file):
    default_settings = {
        "currency_pairs": {
            "USDJPY": True,
            "EURJPY": True,
            "GBPJPY": True,
            "AUDJPY": True,
            "EURUSD": True,
            "GBPUSD": True,
            "AUDUSD": True
        }
    }
    
    os.makedirs(os.path.dirname(settings_file), exist_ok=True)
    with open(settings_file, 'w', encoding='utf-8') as f:
        json.dump(default_settings, f, indent=4, ensure_ascii=False)
    
    print(f"デフォルト設定ファイルを作成しました: {settings_file}")
    return default_settings['currency_pairs']


def remove_folder_with_retry(folder_path, max_retries=5, delay=1):
    for i in range(max_retries):
        try:
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)
            return True
        except Exception as e:
            if i < max_retries - 1:
                time.sleep(delay)
            else:
                print(f"警告: {folder_path} を削除できませんでした。エラー: {str(e)}")
                return False

def find_csv_files(folder):
    csv_files = []
    for root, dirs, files in os.walk(folder):
        if 'EX' in root.split(os.path.sep):
            continue
        for file in files:
            if file.endswith('.csv') and not file.startswith('._'):
                csv_files.append(os.path.join(root, file))
    return csv_files

def save_analysis_results(results, file_path):
    with open(file_path, 'wb') as f:
        pickle.dump(results, f)

def load_analysis_results(file_path):
    try:
        with open(file_path, 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError, pickle.UnpicklingError) as e:
        print(f"警告: 分析結果ファイルの読み込みに失敗しました: {str(e)}")
        print("新しい分析を最初から開始します。")
        return {}

def load_incremental_data(zip_folder, temp_folder, last_analyzed_date):
    new_data = []
    zip_files = sorted(glob.glob(os.path.join(zip_folder, "*.zip")), reverse=True)
    
    for zip_file in zip_files:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(temp_folder)
        
        csv_files = find_csv_files(temp_folder)
        
        for csv_file in csv_files:
            try:
                df = pd.read_csv(csv_file, parse_dates=['日時'], encoding='shift_jis')
                # 分析済みの日付より新しいデータのみを抽出
                new_records = df[df['日時'].dt.date > last_analyzed_date]
                if not new_records.empty:
                    file_name = os.path.basename(csv_file)
                    currency_pair = file_name.split('_')[0]
                    new_records['通貨ペア'] = currency_pair
                    new_data.append(new_records)
            except Exception as e:
                print(f"警告: {csv_file} の読み込み中にエラーが発生しました: {str(e)}")
        
        remove_folder_with_retry(temp_folder)
    
    if not new_data:
        return pd.DataFrame()
    
    combined_data = pd.concat(new_data, ignore_index=True)
    combined_data.sort_values('日時', ascending=False, inplace=True)
    combined_data.drop_duplicates(subset=['日時', '通貨ペア'], keep='first', inplace=True)
    
    print(f"新しく読み込まれたデータ行数: {len(combined_data)}")
    print(f"データ期間: {combined_data['日時'].min().date()} から {combined_data['日時'].max().date()} まで")
    
    return combined_data

def calculate_pips(entry_price, exit_price, currency_pair):
    if 'JPY' in currency_pair:
        return (exit_price - entry_price) * 100
    else:
        return (exit_price - entry_price) * 10000

def analyze_single_combination(df, currency_pair, start_time, holding_period, direction):
    end_time = (datetime.combine(datetime.min, start_time) + timedelta(minutes=holding_period)).time()
    
    if end_time > datetime.strptime("20:15", "%H:%M").time():
        return pd.DataFrame()
    
    daily_results = []
    for date, group in df.groupby(df['日時'].dt.date):
        entry_mask = (group['日時'].dt.time == start_time)
        exit_mask = (group['日時'].dt.time == end_time)
        
        if entry_mask.any() and exit_mask.any():
            if direction == 'HIGH':
                entry_price = group.loc[entry_mask, '始値(ASK)'].iloc[0]
                exit_price = group.loc[exit_mask, '始値(BID)'].iloc[0]
            else:  # LOW
                entry_price = group.loc[entry_mask, '始値(BID)'].iloc[0]
                exit_price = group.loc[exit_mask, '始値(ASK)'].iloc[0]
            
            pips = calculate_pips(entry_price, exit_price, currency_pair)
            if direction == 'LOW':
                pips = -pips
            daily_results.append({'date': date, 'pips': pips, 'win': pips > 0})
    
    return pd.DataFrame(daily_results)

def update_analysis_results(old_results, new_data, currency_pair):
    updated_results = old_results.copy()
    total_combinations = len(pd.date_range("08:00", "19:59", freq="1min")) * 15 * 2  # 時間帯 * 保有期間 * 方向
    completed = 0

    for start_time in pd.date_range("08:00", "19:59", freq="1min").time:
        for holding_period in range(1, 16):
            for direction in ['HIGH', 'LOW']:
                key = (currency_pair, start_time, holding_period, direction)
                old_daily_results = updated_results.get(key, {'date': [], 'pips': [], 'win': []})
                
                new_results = analyze_single_combination(new_data, currency_pair, start_time, holding_period, direction)
                
                if not new_results.empty:
                    old_daily_results['date'].extend(new_results['date'].tolist())
                    old_daily_results['pips'].extend(new_results['pips'].tolist())
                    old_daily_results['win'].extend(new_results['win'].tolist())
                
                # 最新の730日分のデータのみを保持
                if len(old_daily_results['date']) > 730:
                    excess = len(old_daily_results['date']) - 730
                    old_daily_results['date'] = old_daily_results['date'][excess:]
                    old_daily_results['pips'] = old_daily_results['pips'][excess:]
                    old_daily_results['win'] = old_daily_results['win'][excess:]
                
                updated_results[key] = old_daily_results

                completed += 1
                print(f"\r{currency_pair} の処理中: {completed}/{total_combinations} ({completed/total_combinations*100:.2f}%)", end="", flush=True)

    print()  # 改行を追加して、次の出力が新しい行から始まるようにします
    return updated_results

def calculate_score(row):
    win_rate_score = sum((row[f'{period}勝率'] - 50) * (row[f'{period}データ日数'] / expected_days) 
                         for period, expected_days in [('短期', 30), ('中期', 90), ('長期', 730)])
    pips_score = sum(row[f'{period}平均pips'] * (row[f'{period}データ日数'] / expected_days) 
                     for period, expected_days in [('短期', 30), ('中期', 90), ('長期', 730)])
    return win_rate_score, pips_score

def process_results(results):
    processed_results = []
    for (currency_pair, start_time, holding_period, direction), data in results.items():
        result = {
            '保有期間': holding_period,
            '通貨ペア': currency_pair,
            '開始時刻': start_time.strftime('%H:%M'),
            '方向': direction
        }
        
        for period, days in [('短期', 30), ('中期', 90), ('長期', 730)]:
            period_data = data['win'][-days:]
            period_pips = data['pips'][-days:]
            
            if period_data:
                result[f'{period}勝率'] = np.mean(period_data) * 100
                result[f'{period}平均pips'] = np.mean(period_pips)
                result[f'{period}データ日数'] = len(period_data)
            else:
                result[f'{period}勝率'] = np.nan
                result[f'{period}平均pips'] = np.nan
                result[f'{period}データ日数'] = 0
        
        processed_results.append(result)
    
    results_df = pd.DataFrame(processed_results)
    results_df['勝率スコア'], results_df['pipsスコア'] = zip(*results_df.apply(calculate_score, axis=1))
    
    results_df['勝率スコア'] = stats.zscore(results_df['勝率スコア'])
    results_df['pipsスコア'] = stats.zscore(results_df['pipsスコア'])
    
    results_df['総合スコア'] = results_df['勝率スコア'] + results_df['pipsスコア']
    
    for period in ['短期', '中期', '長期']:
        results_df[f'{period}勝率'] = results_df[f'{period}勝率'].round(2)
        results_df[f'{period}平均pips'] = results_df[f'{period}平均pips'].round(1)
    
    for col in ['勝率スコア', 'pipsスコア', '総合スコア']:
        results_df[col] = results_df[col].round(2)
    
    return results_df

def save_results(results, output_folder, currency_settings):
    try:
        # 出力フォルダの作成
        os.makedirs(output_folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 列の順序を指定
        columns_order = [
            '保有期間', '通貨ペア', '開始時刻', '方向', 
            '短期勝率', '短期平均pips', '短期データ日数',
            '中期勝率', '中期平均pips', '中期データ日数',
            '長期勝率', '長期平均pips', '長期データ日数',
            '勝率スコア', 'pipsスコア', '総合スコア'
        ]
        
        # 結果を指定された列順序で並べ替え
        results_ordered = results[columns_order].copy()
        
        # 並び順の設定
        results_ordered['開始時刻'] = pd.to_datetime(results_ordered['開始時刻'], format='%H:%M').dt.time
        results_ordered['方向_sort'] = results_ordered['方向'].map({'HIGH': 0, 'LOW': 1})
        
        # ソート実行
        results_ordered = results_ordered.sort_values(
            by=['開始時刻', '方向_sort', '保有期間'],
            ascending=[True, True, True]
        )
        
        # 不要な列を削除
        results_ordered = results_ordered.drop(columns=['方向_sort'])
        
        # 設定で有効な通貨ペアのみをフィルタリング
        enabled_pairs = [pair for pair, enabled in currency_settings.items() if enabled]
        filtered_results = results_ordered[results_ordered['通貨ペア'].isin(enabled_pairs)].copy()
        
        # 全結果の保存（フィルタリング適用）
        all_results_file = os.path.join(output_folder, f"全結果_{timestamp}.csv")
        filtered_results.to_csv(all_results_file, index=False, encoding='utf-8-sig', float_format='%.2f')
        print(f"全結果を保存しました: {all_results_file}")
        print(f"出力対象の通貨ペア: {', '.join(enabled_pairs)}")
        
        if not filtered_results.empty:
            # ベスト20の保存（フィルタリング適用）
            best_results = filtered_results.sort_values('総合スコア', ascending=False).head(20)
            best_results_file = os.path.join(output_folder, f"ベスト20結果_{timestamp}.csv")
            best_results.to_csv(best_results_file, index=False, encoding='utf-8-sig', float_format='%.2f')
            print(f"ベスト20結果を保存しました: {best_results_file}")
            
            # ベスト20を表示（フィルタリング適用）
            print("\nベスト20結果:")
            display_columns = [
                '保有期間', '通貨ペア', '開始時刻', '方向', 
                '短期勝率', '中期勝率', '長期勝率', 
                '短期平均pips', '中期平均pips', '長期平均pips', 
                '勝率スコア', 'pipsスコア', '総合スコア'
            ]
            print(best_results[display_columns])
            
            # BOエントリー分析の追加
            # output_boフォルダの作成
            output_bo_folder = os.path.join(os.path.dirname(output_folder), "output_bo")
            os.makedirs(output_bo_folder, exist_ok=True)
            
            # OR条件フィルタリング
            filtered_bo = filtered_results[
                (filtered_results['保有期間'].isin([1, 3, 5])) |
                ((pd.to_datetime(filtered_results['開始時刻'].astype(str)) + 
                  pd.to_timedelta(filtered_results['保有期間'], unit='m')).dt.minute == 0)
            ]
            
            # AND条件フィルタリング
            filtered_bo_and = filtered_bo[
                (filtered_bo['短期勝率'] >= 70) &
                (filtered_bo['中期勝率'] >= 60) &
                (filtered_bo['長期勝率'] >= 50)
            ]
            
            # 勝率スコアの計算
            win_rate_columns = ['短期勝率', '中期勝率', '長期勝率']
            for col in win_rate_columns:
                filtered_bo_and[f'{col}_ランク'] = filtered_bo_and[col].rank(ascending=False, method='min')
            filtered_bo_and['勝率スコア'] = filtered_bo_and[[f'{col}_ランク' for col in win_rate_columns]].sum(axis=1)
            
            # 開始時刻ごとに勝率スコアが最も低い行を選定
            entry_data = filtered_bo_and.loc[filtered_bo_and.groupby('開始時刻')['勝率スコア'].idxmin()]

            # BOエントリー結果の出力準備
            if not entry_data.empty:
                # 列を選択し、新しい順序で並び替え
                entry_columns = [
                    '保有期間', '通貨ペア', '開始時刻', '方向',
                    '短期勝率', '短期平均pips',
                    '中期勝率', '中期平均pips',
                    '長期勝率', '長期平均pips',
                    '短期勝率_ランク', '中期勝率_ランク', '長期勝率_ランク',
                    '勝率スコア'
                ]
                
                # 行番号（No.）を追加
                entry_data_final = entry_data[entry_columns].copy()
                entry_data_final.insert(0, 'No.', range(1, len(entry_data_final) + 1))
                
                # 結果を保存
                date_str = datetime.now().strftime("%Y%m%d")
                entry_file = os.path.join(output_bo_folder, f"{date_str}_BO_エントリー.csv")
                entry_data_final.to_csv(entry_file, index=False, encoding='utf-8-sig')
                print(f"\nBOエントリー結果を保存しました: {entry_file}")

                # entrypoint.csvファイルをスクリプトと同じ階層に保存
                script_dir = os.path.dirname(os.path.abspath(__file__))
                entrypoint_file = os.path.join(script_dir, "entrypoint.csv")
                entry_data_final.to_csv(entrypoint_file, index=False, encoding='utf-8-sig')
                print(f"エントリーポイントファイルを保存しました: {entrypoint_file}")

                # スプレッドシートにアップロード
                send_to_webhook(entry_file)
                print(f"\nスプレッドシートにアップロードしました: {entry_file}")

        else:
            print("警告: 指定された通貨ペアの結果がありません。")
            
    except Exception as e:
        print(f"結果の保存中にエラーが発生しました: {str(e)}")
        print("エラーの詳細:")
        import traceback
        traceback.print_exc()

def send_to_webhook(entry_file):
    """ CSV ファイルを Google Apps Script の Webhook に送信 """
    data = []
    with open(entry_file, mode="r", encoding="utf-8-sig") as f:
        reader = pd.read_csv(f)
        data = reader.to_dict(orient='records')
    
    headers = {"Content-Type": "application/json"}
    response = requests.post(WEBHOOK_URL, data=json.dumps(data), headers=headers)
    print("Response:", response.text)

def main(zip_folder, output_folder, settings_file):
    start_time = datetime.now()
    print(f"スクリプト実行開始時刻: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # デバッグ情報を追加
    print(f"\n入力フォルダ: {zip_folder}")
    print(f"zip ファイル一覧: {glob.glob(os.path.join(zip_folder, '*.zip'))}")

    # 設定の読み込み
    currency_settings = load_currency_settings(settings_file)
    print("\n出力対象の通貨ペア設定:")
    for pair, enabled in currency_settings.items():
        status = "有効" if enabled else "無効"
        print(f"{pair}: {status}")

    temp_folder = "temp_extracted_files"
    results_file = os.path.join(output_folder, "analysis_results.pkl")
    os.makedirs(temp_folder, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    try:
        old_results = load_analysis_results(results_file)
        if old_results:
            last_analyzed_date = max(max(data['date']) for data in old_results.values() if data['date'])
        else:
            last_analyzed_date = datetime.min.date()
            old_results = {}

        print(f"\n前回の分析日: {last_analyzed_date}")

        print("増分データを読み込んでいます...")
        new_data = load_incremental_data(zip_folder, temp_folder, last_analyzed_date)
        
        if not new_data.empty:
            print("データを分析しています...")
            print(f"新しいデータが見つかりました: {len(new_data)} 行")
            print(f"データ期間: {new_data['日時'].min()} から {new_data['日時'].max()}")
            print(f"通貨ペア: {new_data['通貨ペア'].unique()}")
            total_currency_pairs = len(new_data['通貨ペア'].unique())
            
            # すべての通貨ペアを分析
            for i, currency_pair in enumerate(new_data['通貨ペア'].unique(), 1):
                print(f"\n{currency_pair} の分析を開始します... ({i}/{total_currency_pairs})")
                pair_data = new_data[new_data['通貨ペア'] == currency_pair]
                updated_results = update_analysis_results(old_results, pair_data, currency_pair)
                old_results.update(updated_results)
            
            save_analysis_results(old_results, results_file)
            
            print("\n結果を処理しています...")
            processed_results = process_results(old_results)
            
            # 結果の保存（フィルタリングはsave_results内で実行）
            save_results(processed_results, output_folder, currency_settings)
            
        else:
            print("\n警告: 新しいデータが見つかりませんでした。以下の点を確認してください:")
            print(f"1. 入力フォルダ({zip_folder})に新しいZIPファイルが存在するか")
            print(f"2. 前回の分析日({last_analyzed_date})以降のデータが含まれているか")
            print("3. ZIPファイル内のCSVファイルの形式が正しいか")

    except Exception as e:
        print(f"エラー: データの処理中に問題が発生しました: {str(e)}")
        traceback.print_exc()

    finally:
        try:
            if os.path.exists(temp_folder):
                if not remove_folder_with_retry(temp_folder):
                    print(f"警告: 一時フォルダ {temp_folder} を完全に削除できませんでした。手動で削除してください。")
            else:
                print(f"注意: 一時フォルダ {temp_folder} は既に存在しません。")
        except Exception as e:
            print(f"警告: 一時フォルダの削除中にエラーが発生しました: {str(e)}")
        
        end_time = datetime.now()
        execution_time = end_time - start_time
        print(f"\nスクリプト実行終了時刻: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"所要時間: {execution_time}")

if __name__ == "__main__":
    try:
        # スクリプトのディレクトリパスを取得
        script_dir = os.path.dirname(os.path.abspath(__file__))
        zip_folder = os.path.join(script_dir, "input")
        output_folder = os.path.join(script_dir, "output")
        settings_file = os.path.join(script_dir, "config", "currency_settings.json")
        log_file = os.path.join(script_dir, "task_log.txt")
        
        # 開始時刻を記録
        start_time = datetime.now()
        
        # ログ出力関数
        def write_log(message):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_message = f"[{timestamp}] {message}\n"
            print(message)
            with open(log_file, "a", encoding='utf-8') as f:
                f.write(log_message)

        # 実行開始ログ
        write_log("=== 分析処理開始 ===")
        write_log(f"出力フォルダ: {output_folder}")
        
        # 出力フォルダの作成
        os.makedirs(output_folder, exist_ok=True)
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        
        # メイン処理の実行
        write_log("メイン処理を開始します")
        main(zip_folder, output_folder, settings_file)
        
        # 終了時刻と実行時間の記録
        end_time = datetime.now()
        execution_time = end_time - start_time
        write_log(f"処理が完了しました")
        write_log(f"実行時間: {execution_time}")
        write_log("=== 分析処理終了 ===")
        write_log("-" * 50)
        
    except Exception as e:
        # エラー発生時のログ出力
        error_message = f"エラーが発生しました: {str(e)}"
        if 'write_log' in locals():
            write_log(error_message)
            write_log(traceback.format_exc())
        else:
            # write_log関数が定義される前にエラーが発生した場合
            with open(log_file, "a", encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_message}\n")
                f.write(traceback.format_exc())
