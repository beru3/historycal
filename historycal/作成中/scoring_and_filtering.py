import os
import pandas as pd
from datetime import datetime

# 入力ファイルのパスをインタラクティブに取得
input_file = input("CSVファイルのパスを入力してください: ").strip().strip('"').strip("'")

# 日付フォルダの作成
current_date = datetime.now().strftime('%Y%m%d')
output_folder = os.path.join(os.path.dirname(__file__), 'output2', current_date)
os.makedirs(output_folder, exist_ok=True)

try:
    # CSVファイルを読み込む (macOS向けに文字コードを拡張)
    data_csv = pd.read_csv(input_file, encoding='utf-8')

    # 不要な列を削除
    columns_to_drop = ['短期データ日数', '中期データ日数', '長期データ日数', '勝率スコア', 'pipsスコア', '総合スコア']
    data_csv = data_csv.drop(columns=[col for col in columns_to_drop if col in data_csv.columns], errors='ignore')

    # OR条件に基づくフィルタリング
    filtered_data_or = data_csv[
        (data_csv['保有期間'].isin([3, 5])) |
        ((pd.to_datetime(data_csv['開始時刻'], format='%H:%M:%S') + pd.to_timedelta(data_csv['保有期間'], unit='m')).dt.minute == 0)
    ]

    # スコア計算の関数
    def calculate_scores(data, ranking_columns, score_name):
        for col in ranking_columns:
            data[f'{col}_ランク'] = data[col].rank(ascending=False, method='min')
        data[score_name] = data[[f'{col}_ランク' for col in ranking_columns]].sum(axis=1)
        return data

    # 1. 勝率重視型 (OR条件)
    win_rate_columns = ['短期勝率', '中期勝率', '長期勝率']
    win_rate_data_or = calculate_scores(filtered_data_or.copy(), win_rate_columns, '勝率スコア')
    win_rate_data_or = win_rate_data_or.sort_values(by='勝率スコア')

    # 勝率スコア列を追加
    win_rate_data_or['勝率スコア'] = win_rate_data_or[[f'{col}_ランク' for col in win_rate_columns]].sum(axis=1)

    # 2. 利益重視型 (OR条件)
    profit_columns = ['短期平均pips', '中期平均pips', '長期平均pips']
    profit_data_or = calculate_scores(filtered_data_or.copy(), profit_columns, '利益スコア')
    profit_data_or = profit_data_or.sort_values(by='利益スコア')

    # 3. バランス型 (OR条件)
    balance_columns = win_rate_columns + profit_columns
    balance_data_or = calculate_scores(filtered_data_or.copy(), balance_columns, 'バランススコア')
    balance_data_or = balance_data_or.sort_values(by='バランススコア')

    # OR条件結果をそれぞれのCSVファイルに保存
    win_rate_file = os.path.join(output_folder, 'BO_勝率重視型.csv')
    profit_file = os.path.join(output_folder, 'BO_利益重視型.csv')
    balance_file = os.path.join(output_folder, 'BO_バランス型.csv')

    win_rate_data_or.to_csv(win_rate_file, index=False, encoding='utf-8-sig')
    profit_data_or.to_csv(profit_file, index=False, encoding='utf-8-sig')
    balance_data_or.to_csv(balance_file, index=False, encoding='utf-8-sig')

    # FX用フィルタリングなしのデータ作成
    win_rate_data_fx = calculate_scores(data_csv.copy(), win_rate_columns, '勝率スコア')
    win_rate_data_fx = win_rate_data_fx.sort_values(by='勝率スコア')

    profit_data_fx = calculate_scores(data_csv.copy(), profit_columns, '利益スコア')
    profit_data_fx = profit_data_fx.sort_values(by='利益スコア')

    balance_data_fx = calculate_scores(data_csv.copy(), balance_columns, 'バランススコア')
    balance_data_fx = balance_data_fx.sort_values(by='バランススコア')

    # FX用結果をそれぞれのCSVファイルに保存
    win_rate_file_fx = os.path.join(output_folder, 'FX_勝率重視型.csv')
    profit_file_fx = os.path.join(output_folder, 'FX_利益重視型.csv')
    balance_file_fx = os.path.join(output_folder, 'FX_バランス型.csv')

    win_rate_data_fx.to_csv(win_rate_file_fx, index=False, encoding='utf-8-sig')
    profit_data_fx.to_csv(profit_file_fx, index=False, encoding='utf-8-sig')
    balance_data_fx.to_csv(balance_file_fx, index=False, encoding='utf-8-sig')

    print("結果が 'output2/{current_date}' フォルダに保存されました:", win_rate_file, profit_file, balance_file, win_rate_file_fx, profit_file_fx, balance_file_fx)

except FileNotFoundError:
    print("エラー: 指定されたファイルが見つかりません。パスを確認してください。")
except UnicodeDecodeError:
    print("エラー: ファイルの文字コードを確認してください。適切なエンコーディングを指定してください。")
except Exception as e:
    print(f"予期しないエラーが発生しました: {e}")
