import pandas as pd

def filter_win_rates(data):
    """
    指定された勝率条件でデータをフィルタリングする関数
    
    条件:
    - 短期勝率: 80%以上
    - 中期勝率: 69%以上
    - 長期勝率: 50%以上
    """
    
    # CSVデータを読み込む
    df = pd.read_csv(data, sep=',')
    
    # 条件に合うデータをフィルタリング
    filtered_df = df[
        (df['短期勝率'] >= 80) &
        (df['中期勝率'] >= 69) &
        (df['長期勝率'] >= 50)
    ]
    
    return filtered_df

# ファイルパスを指定してデータを処理
result = filter_win_rates(r'C:\Users\eggss\Dropbox\004_py\highlow\historycal\output\全結果_20241213_020412.csv')

# 結果を表示
print("条件:")
print("- 短期勝率: 80%以上")
print("- 中期勝率: 69%以上")
print("- 長期勝率: 50%以上")
print("\n条件に合致するエントリーポイント:")
print(result[['保有期間', '通貨ペア', '開始時刻', '方向', '短期勝率', '中期勝率', '長期勝率']])
print(f"\n合計データ数: {len(result)}件")