import os
import pandas as pd
from datetime import datetime

# 入力ファイルのパスをインタラクティブに取得
input_file = input("CSVファイルのパスを入力してください: ").strip().strip('"').strip("'")

# 入力ファイル名から日付を取得
try:
    file_date = pd.to_datetime(os.path.basename(input_file).split('_')[1], format='%Y%m%d').strftime('%Y%m%d')
except (IndexError, ValueError):
    file_date = datetime.now().strftime('%Y%m%d')  # 日付が取得できない場合は現在の日付を使用

# 日付フォルダの作成
output_folder = os.path.join(os.path.dirname(__file__), 'output2', file_date)
os.makedirs(output_folder, exist_ok=True)

try:
    # CSVファイルを読み込む (macOS向けに文字コードを拡張)
    data_csv = pd.read_csv(input_file, encoding='utf-8')

    # 不要な列を削除
    columns_to_drop = ['短期データ日数', '中期データ日数', '長期データ日数', '勝率スコア', 'pipsスコア', '総合スコア']
    data_csv = data_csv.drop(columns=[col for col in columns_to_drop if col in data_csv.columns], errors='ignore')

    # OR条件に基づくフィルタリング
    filtered_data_or = data_csv[
        (data_csv['保有期間'].isin([1, 3, 5])) |  # 保有期間が1, 3, 5のいずれか
        ((pd.to_datetime(data_csv['開始時刻'], format='%H:%M:%S') + pd.to_timedelta(data_csv['保有期間'], unit='m')).dt.minute == 0)
    ]

    # 新しい条件: 短期勝率70%以上、かつ中期勝率60%以上、かつ長期勝率50%以上の抽出
    filtered_data_and = filtered_data_or[
        (filtered_data_or['短期勝率'] >= 70) &
        (filtered_data_or['中期勝率'] >= 60) &
        (filtered_data_or['長期勝率'] >= 50)
    ]

    # スコア計算の関数
    def calculate_scores(data, ranking_columns, score_name):
        for col in ranking_columns:
            data[f'{col}_ランク'] = data[col].rank(ascending=False, method='min')
        data[score_name] = data[[f'{col}_ランク' for col in ranking_columns]].sum(axis=1)
        return data

    # 1. 勝率重視型
    win_rate_columns = ['短期勝率', '中期勝率', '長期勝率']
    win_rate_data_and = calculate_scores(filtered_data_and.copy(), win_rate_columns, '勝率スコア')
    win_rate_data_and = win_rate_data_and.sort_values(by=['開始時刻', '勝率スコア'])

    # 2. 利益重視型
    profit_columns = ['短期平均pips', '中期平均pips', '長期平均pips']
    profit_data_and = calculate_scores(filtered_data_and.copy(), profit_columns, '利益スコア')
    profit_data_and = profit_data_and.sort_values(by=['開始時刻', '利益スコア'])

    # 3. バランス型（勝率 + 平均pips）
    balance_columns = win_rate_columns + profit_columns
    balance_data_and = calculate_scores(filtered_data_and.copy(), balance_columns, 'バランススコア')
    balance_data_and = balance_data_and.sort_values(by=['開始時刻', 'バランススコア'])

    # エントリーポイントの選定後、No.列を追加
    entry_data = win_rate_data_and.loc[win_rate_data_and.groupby('開始時刻')['勝率スコア'].idxmin()] # 開始時刻ごとに勝率スコアが最も低い行（ランキングが高い行）を選定
    entry_data = entry_data.sort_values('開始時刻').reset_index(drop=True)  # インデックスをリセット
    entry_data.index = entry_data.index + 1  # インデックスを1から始める
    entry_data = entry_data.reset_index()  # インデックスを'index'列として追加
    entry_data = entry_data.rename(columns={'index': 'No.'})  # 列名を'No.'に変更

    # 結果をそれぞれのCSVファイルに保存
    win_rate_file = os.path.join(output_folder, 'BO_勝率重視型_条件付き.csv')
    profit_file = os.path.join(output_folder, 'BO_利益重視型_条件付き.csv')
    balance_file = os.path.join(output_folder, 'BO_バランス型_条件付き.csv')
    entry_file = os.path.join(output_folder, 'BO_エントリー.csv')

    win_rate_data_and.to_csv(win_rate_file, index=False, encoding='utf-8-sig')
    profit_data_and.to_csv(profit_file, index=False, encoding='utf-8-sig')
    balance_data_and.to_csv(balance_file, index=False, encoding='utf-8-sig')
    entry_data.to_csv(entry_file, index=False, encoding='utf-8-sig')

    print("結果が 'output2/{file_date}' フォルダに保存されました:", win_rate_file, profit_file, balance_file, entry_file)

except FileNotFoundError:
    print("エラー: 指定されたファイルが見つかりません。パスを確認してください。")
except UnicodeDecodeError:
    print("エラー: ファイルの文字コードを確認してください。適切なエンコーディングを指定してください。")
except Exception as e:
    print(f"予期しないエラーが発生しました: {e}")
