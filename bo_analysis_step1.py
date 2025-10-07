import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import json
import traceback
from scipy import stats
import pickle

# --- 設定項目 ---
TARGET_BROKER = "外貨ネクストバイナリー"  # 分析したい業者名を指定
TARGET_EXPIRY = "14:20"              # 分析したい満期時刻を "HH:MM" 形式で指定
# --------------

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

def load_analysis_results(file_path):
    try:
        with open(file_path, 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError, pickle.UnpicklingError):
        return {}

def calculate_pips(entry_price, exit_price, currency_pair):
    if 'JPY' in currency_pair:
        return (exit_price - entry_price) * 100
    else:
        return (exit_price - entry_price) * 10000

def analyze_single_combination(df, currency_pair, start_time, holding_period, direction):
    end_time = (datetime.combine(datetime.min, start_time) + timedelta(minutes=holding_period)).time()
    
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
    
    if not processed_results:
        return pd.DataFrame()

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

def save_bo_analysis_results(results_df, output_folder, broker_name, expiry_time):
    try:
        os.makedirs(output_folder, exist_ok=True)
        
        filename_expiry = expiry_time.replace(":", "")
        output_file = os.path.join(output_folder, f"{broker_name}_{filename_expiry}_analysis.csv")

        columns_order = [
            '保有期間', '通貨ペア', '開始時刻', '方向', 
            '短期勝率', '短期平均pips', '短期データ日数',
            '中期勝率', '中期平均pips', '中期データ日数',
            '長期勝率', '長期平均pips', '長期データ日数',
            '勝率スコア', 'pipsスコア', '総合スコア'
        ]
        
        results_df = results_df[columns_order].copy()
        results_df = results_df.sort_values(by='総合スコア', ascending=False)
        
        results_df.to_csv(output_file, index=False, encoding='utf-8-sig', float_format='%.2f')
        print(f"\n分析結果を保存しました: {output_file}")

    except Exception as e:
        print(f"結果の保存中にエラーが発生しました: {str(e)}")
        traceback.print_exc()

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    broker_settings_file = os.path.join(script_dir, "config", "bo_brokers.json")
    analysis_cache_file = os.path.join(script_dir, "output", "analysis_results.pkl")
    output_folder = os.path.join(script_dir, "output", "bo_analysis")

    broker_settings = load_broker_settings(broker_settings_file)
    if not broker_settings:
        return

    if TARGET_BROKER not in broker_settings:
        print(f"エラー: 指定された業者 '{TARGET_BROKER}' は設定ファイルに存在しません。")
        return

    broker_info = broker_settings[TARGET_BROKER]
    if TARGET_EXPIRY not in broker_info["expiries"]:
        print(f"エラー: 指定された満期時刻 '{TARGET_EXPIRY}' は業者 '{TARGET_BROKER}' の設定に存在しません。")
        return

    print(f"業者: {TARGET_BROKER}")
    print(f"満期時刻: {TARGET_EXPIRY}")

    # --- ここから分析ロジック ---
    # 1. 既存の分析結果(pickle)を読み込む
    all_results = load_analysis_results(analysis_cache_file)
    if not all_results:
        print("警告: 分析キャッシュが見つかりません。fx_base_analysis.py を先に実行してキャッシュを作成してください。")
        return

    # 2. 分析条件を決定
    expiry_dt = datetime.strptime(TARGET_EXPIRY, "%H:%M")
    trade_duration = timedelta(hours=broker_info["trade_duration_hours"])
    close_before = timedelta(minutes=broker_info["close_minute_before"])
    
    start_of_trade_dt = expiry_dt - trade_duration
    end_of_trade_dt = expiry_dt - close_before

    # 3. 該当する結果を抽出・処理
    final_results = {}
    for (currency_pair, start_time, holding_period, direction), data in all_results.items():
        start_dt = datetime.combine(datetime.min.date(), start_time)
        end_dt = start_dt + timedelta(minutes=holding_period)

        # エントリー時刻が受付時間内か？
        if not (start_of_trade_dt <= start_dt < end_of_trade_dt):
            continue
        
        # 判定時刻が満期時刻と一致するか？
        if end_dt.time() != expiry_dt.time():
            continue

        final_results[(currency_pair, start_time, holding_period, direction)] = data

    if not final_results:
        print("分析対象のデータが見つかりませんでした。")
        return

    # 4. 結果をDataFrameに変換して保存
    processed_df = process_results(final_results)
    save_bo_analysis_results(processed_df, output_folder, TARGET_BROKER, TARGET_EXPIRY)

if __name__ == "__main__":
    main()
