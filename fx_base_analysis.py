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
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import stats
import pickle
import json
import argparse


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

def load_incremental_data(zip_folder, last_analyzed_date):
    new_data = []
    zip_files = sorted(glob.glob(os.path.join(zip_folder, "*.zip")))
    
    for zip_file_path in zip_files:
        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                for member_name in zip_ref.namelist():
                    if member_name.endswith('.csv') and not member_name.startswith('._'):
                        # ZIPファイルから直接CSVを読み込む
                        with zip_ref.open(member_name) as csv_file_in_zip:
                            df = pd.read_csv(csv_file_in_zip, parse_dates=['日時'], encoding='shift_jis')
                            
                            # 分析済みの日付より新しいデータのみを抽出
                            new_records = df[df['日時'].dt.date > last_analyzed_date]
                            if not new_records.empty:
                                file_name = os.path.basename(member_name)
                                currency_pair = file_name.split('_')[0]
                                new_records['通貨ペア'] = currency_pair
                                new_data.append(new_records)
        except Exception as e:
            print(f"警告: {zip_file_path} の読み込み中にエラーが発生しました: {str(e)}")
    
    if not new_data:
        return pd.DataFrame()
    
    combined_data = pd.concat(new_data, ignore_index=True)
    combined_data.sort_values('日時', ascending=True, inplace=True) # 時系列順にソート
    combined_data.drop_duplicates(subset=['日時', '通貨ペア'], keep='first', inplace=True)
    combined_data.set_index('日時', inplace=True) # 日時をインデックスに設定
    
    print(f"新しく読み込まれたデータ行数: {len(combined_data)}")
    print(f"データ期間: {combined_data.index.min().date()} から {combined_data.index.max().date()} まで")
    
    return combined_data

def calculate_pips(entry_price, exit_price, currency_pair):
    if 'JPY' in currency_pair:
        return (exit_price - entry_price) * 100
    else:
        return (exit_price - entry_price) * 10000

def analyze_single_combination(df, currency_pair, start_time, holding_period, direction):
    daily_results = []
    
    # データフレーム内のユニークな日付ごとにループ
    for trade_date in df.index.normalize().unique(): # インデックスから日付を取得
        # エントリーと決済の正確な日時を構築
        entry_datetime = datetime.combine(trade_date, start_time)
        exit_datetime = entry_datetime + timedelta(minutes=holding_period)
        
        # インデックスを使ってエントリーと決済の行を高速検索
        entry_row = df.loc[(df.index == entry_datetime) & (df['通貨ペア'] == currency_pair)]
        exit_row = df.loc[(df.index == exit_datetime) & (df['通貨ペア'] == currency_pair)]
        
        if not entry_row.empty and not exit_row.empty:
            if direction == 'HIGH':
                entry_price = entry_row['始値(ASK)'].iloc[0]
                exit_price = exit_row['始値(BID)'].iloc[0]
            else:  # LOW
                entry_price = entry_row['始値(BID)'].iloc[0]
                exit_price = exit_row['始値(ASK)'].iloc[0]
            
            pips = calculate_pips(entry_price, exit_price, currency_pair)
            if direction == 'LOW':
                pips = -pips
            daily_results.append({'date': trade_date, 'pips': pips, 'win': pips > 0})
    
    return pd.DataFrame(daily_results)

def update_analysis_results(old_results, new_data, currency_pair, start_time_range, holding_period_range):
    updated_results = old_results.copy()
    
    # total_combinations の計算を動的に変更
    total_combinations = len(start_time_range) * len(holding_period_range) * 2  # 時間帯 * 保有期間 * 方向
    completed = 0

    for start_time in start_time_range:
        for holding_period in holding_period_range:
            for direction in ['HIGH', 'LOW']:
                key = (currency_pair, start_time, holding_period, direction)
                old_daily_results = updated_results.get(key, {'date': [], 'pips': [], 'win': []})
                
                new_results = analyze_single_combination(new_data, currency_pair, start_time, holding_period, direction)
                
                if not new_results.empty:
                    old_daily_results['date'].extend(new_results['date'].tolist())
                    old_daily_results['pips'].extend(new_results['pips'].tolist())
                    old_daily_results['win'].extend(new_results['win'].tolist())
                
                # 最新の365日分のデータのみを保持
                if len(old_daily_results['date']) > 365:
                    excess = len(old_daily_results['date']) - 365
                    old_daily_results['date'] = old_daily_results['date'][excess:]
                    old_daily_results['pips'] = old_daily_results['pips'][excess:]
                    old_daily_results['win'] = old_daily_results['win'][excess:]
                
                updated_results[key] = old_daily_results

                completed += 1
                

    print()  # 改行を追加して、次の出力が新しい行から始まるようにします
    return updated_results

def calculate_score(row):
    win_rate_score = sum((row[f'{period}勝率'] - 50) * (row[f'{period}データ日数'] / expected_days) 
                         for period, expected_days in [('短期', 30), ('中期', 90), ('長期', 365)])
    pips_score = sum(row[f'{period}平均pips'] * (row[f'{period}データ日数'] / expected_days) 
                     for period, expected_days in [('短期', 30), ('中期', 90), ('長期', 365)])
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
        
        for period, days in [('短期', 30), ('中期', 90), ('長期', 365)]:
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

def save_results(results, output_folder, currency_settings, target_currency_pair=None, analysis_mode='short_term'):
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
        
        # ファイル名に通貨ペアとモードを追加
        if target_currency_pair:
            all_results_file = os.path.join(output_folder, f"全結果_{analysis_mode}_{target_currency_pair}_{timestamp}.csv")
        else:
            all_results_file = os.path.join(output_folder, f"全結果_{analysis_mode}_{timestamp}.csv")

        filtered_results.to_csv(all_results_file, index=False, encoding='utf-8-sig', float_format='%.2f')
        print(f"全結果を保存しました: {all_results_file}")
        print(f"出力対象の通貨ペア: {', '.join(enabled_pairs)}")
        
        if filtered_results.empty:
            print("警告: 指定された通貨ペアの結果がありません。")
            
    except Exception as e:
        print(f"結果の保存中にエラーが発生しました: {str(e)}")
        print("エラーの詳細:")
        import traceback
        traceback.print_exc()

def load_broker_settings(settings_file):
    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"エラー: 業者設定ファイル {settings_file} が見つかりません。")
        return None
    except json.JSONDecodeError:
        print(f"エラー: 業者設定ファイル {settings_file} の形式が不正です。")
        return None

def run_short_term_analysis(old_results, new_data, currency_settings, output_folder, results_file, target_currency_pair):
    print("\n--- ショートターム分析 (1-15分保有) を開始します ---")
    start_time_range = pd.date_range("00:00", "23:59", freq="1min").time
    holding_period_range = range(1, 16) # 1分から15分

    if target_currency_pair:
        target_pairs_to_analyze = [target_currency_pair]
        print(f"分析対象通貨ペア: {target_currency_pair}")
    else:
        target_pairs_to_analyze = [pair for pair, enabled in currency_settings.items() if enabled]
        print(f"分析対象通貨ペア: {', '.join(target_pairs_to_analyze)}")

    total_currency_pairs = len(target_pairs_to_analyze)

    with ProcessPoolExecutor() as executor:
        futures = []
        for i, currency_pair in enumerate(target_pairs_to_analyze, 1):
            print(f"\n{currency_pair} の分析を並列で開始します... ({i}/{total_currency_pairs})")
            pair_data = new_data[new_data['通貨ペア'] == currency_pair]
            futures.append(executor.submit(update_analysis_results, old_results.copy(), pair_data, currency_pair, start_time_range, holding_period_range))

        for future in as_completed(futures):
            try:
                result_for_pair = future.result()
                old_results.update(result_for_pair)
            except Exception as exc:
                print(f'通貨ペアの分析中にエラーが発生しました: {exc}')

    save_analysis_results(old_results, results_file)
    processed_results = process_results(old_results)
    save_results(processed_results, output_folder, currency_settings, target_currency_pair, '15m')

def run_long_term_analysis(old_results, new_data, currency_settings, output_folder, results_file, target_currency_pair, broker_settings_file):
    print("\n--- ロングターム分析 (業者満期時刻を終点に最大120分保有) を開始します ---")
    
    broker_settings = load_broker_settings(broker_settings_file)
    if not broker_settings:
        print("業者設定ファイルの読み込みに失敗しました。ロングターム分析を中断します。")
        return

    all_long_term_combinations = []
    for broker_name, broker_info in broker_settings.items():
        for expiry_str in broker_info["expiries"]:
            expiry_time = datetime.strptime(expiry_str, "%H:%M").time()
            trade_duration_hours = broker_info["trade_duration_hours"]
            close_minute_before = broker_info["close_minute_before"]

            # 満期時刻から逆算してエントリー可能な時間帯と保有期間の組み合わせを生成
            for holding_period in range(1, 121): # 1分から120分
                entry_time_dt = (datetime.combine(datetime.now().date(), expiry_time) - timedelta(minutes=holding_period))
                entry_time = entry_time_dt.time()

                # 取引受付時間内かチェック
                start_of_trade_dt = (datetime.combine(datetime.now().date(), expiry_time) - timedelta(hours=trade_duration_hours))
                end_of_trade_dt = (datetime.combine(datetime.now().date(), expiry_time) - timedelta(minutes=close_minute_before))

                if start_of_trade_dt.time() <= entry_time < end_of_trade_dt.time():
                    all_long_term_combinations.append({
                        'entry_time': entry_time,
                        'holding_period': holding_period,
                        'expiry_time': expiry_time,
                        'broker_name': broker_name
                    })
    
    if not all_long_term_combinations:
        print("ロングターム分析の組み合わせが見つかりませんでした。業者設定を確認してください。")
        return

    print(f"生成されたロングターム分析の組み合わせ数: {len(all_long_term_combinations)}")

    if target_currency_pair:
        target_pairs_to_analyze = [target_currency_pair]
        print(f"分析対象通貨ペア: {target_currency_pair}")
    else:
        target_pairs_to_analyze = [pair for pair, enabled in currency_settings.items() if enabled]
        print(f"分析対象通貨ペア: {', '.join(target_pairs_to_analyze)}")

    total_currency_pairs = len(target_pairs_to_analyze)

    with ProcessPoolExecutor() as executor:
        futures = []
        for i, currency_pair in enumerate(target_pairs_to_analyze, 1):
            print(f"\n{currency_pair} の分析を並列で開始します... ({i}/{total_currency_pairs})")
            pair_data = new_data[new_data['通貨ペア'] == currency_pair]
            
            # ロングターム分析用のstart_time_rangeとholding_period_rangeを生成
            # ここでは、all_long_term_combinationsから通貨ペアに紐づくものをフィルタリング
            combinations_for_pair = [
                (combo['entry_time'], combo['holding_period'])
                for combo in all_long_term_combinations
            ]
            # 重複を排除
            unique_start_times = sorted(list(set([c[0] for c in combinations_for_pair])))
            unique_holding_periods = sorted(list(set([c[1] for c in combinations_for_pair])))

            futures.append(executor.submit(update_analysis_results, old_results.copy(), pair_data, currency_pair, unique_start_times, unique_holding_periods))

        for future in as_completed(futures):
            try:
                result_for_pair = future.result()
                old_results.update(result_for_pair)
            except Exception as exc:
                print(f'通貨ペアの分析中にエラーが発生しました: {exc}')

    save_analysis_results(old_results, results_file)
    processed_results = process_results(old_results)
    save_results(processed_results, output_folder, currency_settings, target_currency_pair, '120m')

def main(zip_folder, output_folder, settings_file, target_currency_pair=None, analysis_mode='short_term'):
    start_time = datetime.now()
    print(f"スクリプト実行開始時刻: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    # デバッグ情報を追加
    print(f"\n入力フォルダ: {zip_folder}")
    print(f"zip ファイル一覧: {repr(glob.glob(os.path.join(zip_folder, '*.zip')))}")

    # 設定の読み込み
    currency_settings = load_currency_settings(settings_file)
    print("\n出力対象の通貨ペア設定:")
    for pair, enabled in currency_settings.items():
        status = "有効" if enabled else "無効"
        print(f"{pair}: {status}")

    results_file_base = os.path.join(output_folder, "analysis_results")
    if analysis_mode == 'short_term':
        mode_suffix = "15m"
    elif analysis_mode == 'long_term':
        mode_suffix = "120m"
    else:
        print(f"エラー: 不明な分析モード '{analysis_mode}' が指定されました。short_term または long_term を指定してください。")
        return

    if target_currency_pair:
        results_file = f"{results_file_base}_{mode_suffix}_{target_currency_pair}.pkl"
    else:
        results_file = f"{results_file_base}_{mode_suffix}.pkl"

    os.makedirs(output_folder, exist_ok=True)

    try:
        old_results = load_analysis_results(results_file)
        if old_results:
            last_analyzed_date = datetime.min.date() # 常に全期間を再分析するため、last_analyzed_dateをリセット
            # last_analyzed_date = max(max(data['date']) for data in old_results.values() if data['date'])
        else:
            last_analyzed_date = datetime.min.date()
            old_results = {}

        print(f"\n前回の分析日: {last_analyzed_date}")

        print("増分データを読み込んでいます...")
        new_data = load_incremental_data(zip_folder, last_analyzed_date)
        
        if not new_data.empty:
            print("データを分析しています...")
            print(f"新しいデータが見つかりました: {len(new_data)} 行")
            print(f"データ期間: {new_data.index.min()} から {new_data.index.max()}")
            
            if analysis_mode == 'short_term':
                run_short_term_analysis(old_results, new_data, currency_settings, output_folder, results_file, target_currency_pair)
            elif analysis_mode == 'long_term':
                broker_settings_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "bo_brokers.json")
                run_long_term_analysis(old_results, new_data, currency_settings, output_folder, results_file, target_currency_pair, broker_settings_file)
            
        else:
            print("\n警告: 新しいデータが見つかりませんでした。以下の点を確認してください:")
            print(f"1. 入力フォルダ({zip_folder})に新しいZIPファイルが存在するか")
            print(f"2. 前回の分析日({last_analyzed_date})以降のデータが含まれているか")
            print("3. ZIPファイル内のCSVファイルの形式が正しいか")

    except Exception as e:
        print(f"エラー: データの処理中に問題が発生しました: {str(e)}")
        traceback.print_exc()

    finally:
        end_time = datetime.now()
        execution_time = end_time - start_time
        print(f"\nスクリプト実行終了時刻: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"所要時間: {execution_time}")

if __name__ == "__main__":
    try:
        # コマンドライン引数の設定
        parser = argparse.ArgumentParser(description="FXヒストリカルデータ分析スクリプト")
        parser.add_argument('--currency_pair', '-c', type=str, help='分析対象の通貨ペア (例: USDJPY)')
        parser.add_argument('--mode', type=str, default='short_term', 
                            help='分析モード (short_term: 1-15分保有, long_term: 業者満期時刻を終点に最大120分保有)')
        args = parser.parse_args()

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
        main(zip_folder, output_folder, settings_file, args.currency_pair, args.mode)
        
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