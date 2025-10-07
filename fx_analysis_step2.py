'''
〇総合スコア
元の fx_analysis_step1.py で算出される基本的な評価スコア
主に勝率スコアと pips スコアの合計から計算される
短期・中期・長期の各期間における勝率やpips値から標準化（Zスコア化）して導き出される
統計的な観点からの純粋なパフォーマンス指標

〇実用スコア
総合スコアを基礎として、追加のボーナスを加えた実践的な評価スコア
総合スコア + 集中度ボーナス + 安定性ボーナス + 長期適合度ボーナス で計算される
追加されるボーナス：

集中度ボーナス（0.5ポイント）: 同じ時間帯・方向で3つ以上の保有期間に高評価が集中している場合
安定性ボーナス（0.3ポイント）: 短期・中期・長期すべてで一貫して良いパフォーマンスを示す場合
長期適合度ボーナス（0.2ポイント）: 長期的な視点でも優れた結果を示す場合

実用スコアは、単なる統計的なパフォーマンスだけでなく、実際の取引で重要となる「安定性」や「一貫性」といった要素も考慮した、より実践的な評価指標となっています。
このスコアが高い戦略は、実際のトレードにおいてより信頼性が高いと考えられます。

'''


import pandas as pd
import numpy as np
from collections import defaultdict
import os
import glob
import re
from datetime import datetime

def find_latest_csv(directory, pattern="全結果_*.csv"):
    """
    指定したディレクトリから最新の全結果CSVファイルを見つける
    """
    pattern_path = os.path.join(directory, pattern)
    files = glob.glob(pattern_path)
    
    if not files:
        raise FileNotFoundError(f"No files matching '{pattern}' found in '{directory}'")
    
    # ファイル名から日時を抽出してソート
    def extract_datetime(filename):
        match = re.search(r"_(\d{8})_(\d{6})", os.path.basename(filename))
        if match:
            date_str = match.group(1) + match.group(2)
            return datetime.strptime(date_str, "%Y%m%d%H%M%S")
        return datetime.min
    
    latest_file = max(files, key=extract_datetime)
    return latest_file

def analyze_forex_data(csv_file_path):
    """
    CSVファイルから高評価ポイントを抽出し、ボーナス評価を行う関数
    
    Parameters:
    -----------
    csv_file_path : str
        分析対象のCSVファイルパス
    
    Returns:
    --------
    pd.DataFrame
        評価結果を含むデータフレーム
    """
    print(f"Analyzing file: {csv_file_path}")
    
    # 複数のエンコーディングと区切り文字を試行
    encodings = ['utf-8', 'utf-8-sig', 'cp932', 'shift_jis']
    separators = [',', '\t', ' ']
    
    df = None
    for encoding in encodings:
        for sep in separators:
            try:
                # CSV読み込みを試行
                test_df = pd.read_csv(csv_file_path, sep=sep, encoding=encoding)
                
                # 必要なカラムがあるか確認
                required_columns = ['保有期間', '通貨ペア', '開始時刻', '方向']
                if all(col in test_df.columns for col in required_columns):
                    print(f"Successfully read file with encoding {encoding} and separator '{sep}'")
                    df = test_df
                    break
                
                # 最初の列に複数のカラム名が含まれている場合（カンマ区切りが正しく機能していない）
                if len(test_df.columns) == 1 and ',' in test_df.columns[0]:
                    first_col_name = test_df.columns[0]
                    # カンマで分割して列名を作成
                    column_names = first_col_name.split(',')
                    # 最初の行をデータとして扱う
                    test_df = pd.read_csv(csv_file_path, sep=sep, encoding=encoding, names=column_names, skiprows=1)
                    if all(col in test_df.columns for col in required_columns):
                        print(f"Successfully read file with manual column splitting")
                        df = test_df
                        break
            except Exception as e:
                print(f"Failed with encoding {encoding} and separator '{sep}': {e}")
                continue
        
        if df is not None:
            break
    
    # まだ失敗している場合は、行ごとに手動で解析
    if df is None:
        print("All standard parsing methods failed. Attempting manual parsing...")
        try:
            with open(csv_file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            # 最初の行からヘッダーを取得
            header_line = lines[0].strip()
            if ',' in header_line:
                headers = header_line.split(',')
            else:
                # スペースが多い場合はスペースで分割
                headers = re.split(r'\s+', header_line)
            
            # 残りの行からデータを取得
            data = []
            for line in lines[1:]:
                line = line.strip()
                if ',' in line:
                    values = line.split(',')
                else:
                    values = re.split(r'\s+', line)
                
                if len(values) >= len(headers):
                    row = {headers[i]: values[i] for i in range(len(headers))}
                    data.append(row)
            
            df = pd.DataFrame(data)
            print("Successfully parsed file manually")
        except Exception as e:
            print(f"Manual parsing failed: {e}")
            raise ValueError("Failed to parse the CSV file with all methods")
    
    # カラム名を確認
    print("Available columns:", df.columns.tolist())
    
    # 数値型に変換
    numeric_columns = ['保有期間', '短期勝率', '短期平均pips', '短期データ日数', 
                      '中期勝率', '中期平均pips', '中期データ日数',
                      '長期勝率', '長期平均pips', '長期データ日数',
                      '勝率スコア', 'pipsスコア', '総合スコア']
    
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 必要なカラムが存在することを確認
    required_columns = ['保有期間', '通貨ペア', '開始時刻', '方向', '短期勝率', '短期平均pips', 
                        '中期勝率', '中期平均pips', '総合スコア']
    
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Required column '{col}' not found in CSV file")
    
    # データの基本情報を表示
    print(f"Total entries: {len(df)}")
    print(f"Unique currency pairs: {df['通貨ペア'].nunique()}")
    print(f"Unique entry times: {df['開始時刻'].nunique()}")
    
    # 1. 基本評価: 総合スコア5.5以上のポイントをフィルタリング
    high_score_df = df[df['総合スコア'] >= 5.5].copy()
    
    if high_score_df.empty:
        print("No entries with score >= 5.5 found")
        return pd.DataFrame(), {}
    
    print(f"Found {len(high_score_df)} entries with score >= 5.5")
    
    # エントリーのキーを作成 (通貨ペア + 開始時刻 + 方向)
    high_score_df['entry_key'] = high_score_df['通貨ペア'] + ' ' + high_score_df['開始時刻'].astype(str) + ' ' + high_score_df['方向']
    
    # キーごとのエントリー数をカウント
    entry_counts = high_score_df['entry_key'].value_counts()
    
    # 2. 集中度ボーナス: 同一時間帯・方向で複数の保有期間に高評価が集中
    high_score_df['concentration_bonus'] = high_score_df['entry_key'].map(lambda x: 0.5 if entry_counts[x] >= 3 else 0)
    
    # 短期平均pips、中期平均pips、長期平均pipsの全体平均を計算
    avg_short_pips = df['短期平均pips'].mean()
    avg_mid_pips = df['中期平均pips'].mean()
    avg_long_pips = df['長期平均pips'].mean()
    
    print(f"Average short-term pips: {avg_short_pips:.2f}")
    print(f"Average mid-term pips: {avg_mid_pips:.2f}")
    print(f"Average long-term pips: {avg_long_pips:.2f}")
    
    # 3. 安定性ボーナス: 短期・中期・長期すべてで安定したパフォーマンスを示すポイント
    high_score_df['stability_bonus'] = np.where(
        (high_score_df['短期勝率'] >= 70) & 
        (high_score_df['中期勝率'] >= 55) & 
        (high_score_df['長期勝率'] >= 50) &  # 長期勝率の条件を追加
        (high_score_df['短期平均pips'] >= avg_short_pips) & 
        (high_score_df['中期平均pips'] >= avg_mid_pips) &
        (high_score_df['長期平均pips'] >= avg_long_pips),  # 長期平均pipsの条件を追加
        0.3, 0
    )
    
    # 長期勝率と長期pipsも考慮した総合適合度を計算
    long_term_fit = np.where(
        (high_score_df['長期勝率'] >= 55) &  # 長期勝率55%以上
        (high_score_df['長期平均pips'] >= avg_long_pips * 0.8),  # 長期平均pipsが全体平均の80%以上
        0.2, 0  # 条件を満たせば0.2ポイント追加
    )
    
    # 実用スコアに長期適合度ボーナスを追加
    high_score_df['長期適合度ボーナス'] = long_term_fit
    high_score_df['実用スコア'] = high_score_df['総合スコア'] + high_score_df['concentration_bonus'] + high_score_df['stability_bonus'] + high_score_df['長期適合度ボーナス']
    
    # 時間順にソート
    high_score_df['時間数値'] = high_score_df['開始時刻'].apply(
        lambda x: int(str(x).split(':')[0]) * 60 + int(str(x).split(':')[1]) if ':' in str(x) else 0
    )
    high_score_df = high_score_df.sort_values(by=['時間数値', '通貨ペア', '方向', '保有期間'])
    
    # 同じエントリーごとにグループ化
    entry_groups = defaultdict(list)
    for _, row in high_score_df.iterrows():
        key = row['entry_key']
        entry_groups[key].append({
            '時間': row['開始時刻'],
            '通貨ペア': row['通貨ペア'],
            '方向': row['方向'],
            '保有期間': row['保有期間'],
            '総合スコア': row['総合スコア'],
            '短期勝率': row['短期勝率'],
            '短期平均pips': row['短期平均pips'],
            '中期勝率': row['中期勝率'],
            '中期平均pips': row['中期平均pips'],
            '集中度ボーナス': row['concentration_bonus'],
            '安定性ボーナス': row['stability_bonus'],
            '実用スコア': row['実用スコア']
        })
    
    # 結果の表示と整形されたデータフレームを返す
    result_df = high_score_df[[
        '開始時刻', '通貨ペア', '方向', '保有期間', '総合スコア', '短期勝率', '短期平均pips',
        '中期勝率', '中期平均pips', '長期勝率', '長期平均pips', 'concentration_bonus', 
        'stability_bonus', '長期適合度ボーナス', '実用スコア'
    ]].rename(columns={
        '開始時刻': '時間',
        'concentration_bonus': '集中度ボーナス',
        'stability_bonus': '安定性ボーナス'
    })
    
    # エントリーグループ情報も出力
    print(f"Found {len(entry_groups)} unique entry points with score >= 5.5")
    
    return result_df, entry_groups

def print_entry_groups(entry_groups):
    """
    エントリーグループを整形して表示する関数
    """
    print("\n==== エントリー時間別グループ ====")
    
    # スコアが高い順にグループをソート
    sorted_groups = sorted(
        entry_groups.items(), 
        key=lambda x: max([item['実用スコア'] for item in x[1]]), 
        reverse=True
    )
    
    for key, entries in sorted_groups:
        print(f"\n## {key} ({len(entries)}件)")
        print("| 保有期間 | 総合スコア | 短期勝率 | 短期Pips | 中期勝率 | 中期Pips | 実用スコア |")
        print("|----------|------------|----------|----------|----------|----------|------------|")
        
        # 保有期間順にソート
        entries_sorted = sorted(entries, key=lambda x: x['保有期間'])
        
        for entry in entries_sorted:
            print(f"| {entry['保有期間']}分 | {entry['総合スコア']:.2f} | {entry['短期勝率']:.2f}% | {entry['短期平均pips']:.2f} | {entry['中期勝率']:.2f}% | {entry['中期平均pips']:.2f} | {entry['実用スコア']:.2f} |")

def print_top_scores(result_df, top_n=20):
    """
    実用スコアが高い順にトップNエントリーを表示
    """
    print(f"\n==== 実用スコア上位{top_n}件 ====")
    top_df = result_df.sort_values(by='実用スコア', ascending=False).head(top_n)
    
    print("| 時間 | 通貨ペア | 方向 | 保有期間 | 総合スコア | 集中度 | 安定性 | 長期適合度 | 実用スコア |")
    print("|------|----------|------|----------|------------|--------|--------|------------|------------|")
    
    for _, row in top_df.iterrows():
        print(f"| {row['時間']} | {row['通貨ペア']} | {row['方向']} | {row['保有期間']}分 | {row['総合スコア']:.2f} | {'+0.5' if row['集中度ボーナス'] > 0 else '-'} | {'+0.3' if row['安定性ボーナス'] > 0 else '-'} | {'+0.2' if row['長期適合度ボーナス'] > 0 else '-'} | {row['実用スコア']:.2f} |")

def save_results_to_excel(result_df, entry_groups, output_path):
    """
    分析結果をExcelファイルに保存する
    """
    try:
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # 1. すべての高評価エントリー（時間順に並び替え）
            result_time_sorted = result_df.copy()
            # 時間を一時的に datetime に変換して並べ替え
            result_time_sorted['時間_sort'] = pd.to_datetime(result_time_sorted['時間'].astype(str), format='%H:%M:%S', errors='coerce')
            result_time_sorted = result_time_sorted.sort_values(by=['時間_sort', '通貨ペア', '方向', '保有期間'])
            result_time_sorted = result_time_sorted.drop(columns=['時間_sort'])
            result_time_sorted.to_excel(writer, sheet_name='全高評価ポイント', index=False)
            
            # 2. 実用スコア上位20（時間順に並び替え）
            top20 = result_df.sort_values(by='実用スコア', ascending=False).head(20).copy()
            top20['時間_sort'] = pd.to_datetime(top20['時間'].astype(str), format='%H:%M:%S', errors='coerce')
            top20 = top20.sort_values(by=['時間_sort', '通貨ペア', '方向', '保有期間'])
            top20 = top20.drop(columns=['時間_sort'])
            top20.to_excel(writer, sheet_name='実用スコア上位20', index=False)
            
            # 3. エントリー時間別シート
            # 時間順にグループをソート
            # グループのキーから時間部分を抽出して並べ替える
            def extract_time(key):
                parts = key.split()
                if len(parts) >= 2:
                    time_str = parts[1]
                    try:
                        return pd.to_datetime(time_str, format='%H:%M:%S', errors='coerce')
                    except:
                        return pd.NaT
                return pd.NaT
            
            sorted_groups = sorted(
                entry_groups.items(), 
                key=lambda x: extract_time(x[0])
            )
            
            # 時間帯ごとに1グループ以上、バランスよく選択する
            # 時間帯ごとにグループを分類
            time_groups = {}
            for key, entries in sorted_groups:
                # キーから時間部分を抽出
                time_match = re.search(r'(\d{1,2}:\d{2})', key)
                if time_match:
                    hour = time_match.group(1).split(':')[0]
                    if hour not in time_groups:
                        time_groups[hour] = []
                    time_groups[hour].append((key, entries))
            
            # 各時間帯から少なくとも1つのグループを選択
            selected_groups = []
            for hour in sorted(time_groups.keys()):
                # 各時間帯の最高スコアのグループを選択
                hour_groups = sorted(time_groups[hour], 
                                    key=lambda x: max([item['実用スコア'] for item in x[1]]), 
                                    reverse=True)
                if hour_groups:
                    selected_groups.append(hour_groups[0])
            
            # 残りの枠があれば、未選択の中から高スコア順に追加
            remaining_slots = 20 - len(selected_groups)
            if remaining_slots > 0:
                # 既に選択されたキーのリスト
                selected_keys = [group[0] for group in selected_groups]
                
                # 未選択グループからスコア順に選択
                remaining_groups = [(key, entries) for key, entries in sorted_groups 
                                   if key not in selected_keys]
                remaining_groups = sorted(remaining_groups, 
                                         key=lambda x: max([item['実用スコア'] for item in x[1]]), 
                                         reverse=True)
                
                # 残りのスロットを埋める
                selected_groups.extend(remaining_groups[:remaining_slots])
            
            # 最終的に選択されたグループを時間順にソート
            selected_groups = sorted(selected_groups, key=lambda x: extract_time(x[0]))
            
            # 選択されたグループをエクセルに書き込み
            for i, (key, entries) in enumerate(selected_groups):
                    
                # シート名は30文字以内に制限（無効な文字を削除）
                sheet_name = ''.join(c for c in key[:30] if c.isalnum() or c in ' _-')
                if not sheet_name:
                    sheet_name = f"Group_{i+1}"
                
                # エントリーリストをデータフレームに変換
                group_df = pd.DataFrame(entries)
                group_df = group_df.sort_values(by='保有期間')
                
                # Excelに書き込み
                try:
                    group_df.to_excel(writer, sheet_name=sheet_name, index=False)
                except Exception as e:
                    print(f"Warning: Could not create sheet for {key}: {e}")
    except Exception as e:
        print(f"Error saving Excel file: {e}")
        import traceback
        traceback.print_exc()

def main():
    # 1. 最新の全結果CSVファイルを見つける
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.join(script_dir, 'output')
    output_dir = os.path.join(script_dir, 'output_fx')
    
    # input_dirが存在しない場合
    if not os.path.exists(input_dir):
        input_dir = script_dir  # スクリプトと同じディレクトリを使用
    
    # output_dirがなければ作成
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created output directory: {output_dir}")
        
    try:
        latest_csv = find_latest_csv(input_dir)
        print(f"Found latest CSV file: {latest_csv}")
        
        # 2. CSVファイルを分析
        result_df, entry_groups = analyze_forex_data(latest_csv)
        
        if not result_df.empty:
            # 3. 結果を保存
            # 結果ファイルの名前を生成（元ファイル名に基づく）
            base_filename = os.path.basename(latest_csv)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_csv = os.path.join(output_dir, f"analyzed_high_scores_{timestamp}.csv")
            results_excel = os.path.join(output_dir, f"analyzed_high_scores_{timestamp}.xlsx")
            
            # CSVに保存
            result_df.to_csv(results_csv, index=False, encoding='utf-8-sig')
            print(f"Results saved to {results_csv}")
            
            # Excelに保存（より詳細な情報）
            try:
                save_results_to_excel(result_df, entry_groups, results_excel)
                print(f"Detailed results saved to {results_excel}")
            except Exception as e:
                print(f"Warning: Could not save Excel file: {e}")
            
            # 4. コンソールに結果を表示
            # 実用スコア上位20件を表示
            print_top_scores(result_df)
            
            # エントリーグループ情報を表示
            print_entry_groups(entry_groups)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()