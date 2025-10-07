#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FX分析ステップ4: エントリーポイント収集・精査処理（時間区間重複検出版）

機能:
1. 最近7日間のエントリーポイントファイルを収集
2. 時間区間の重複に基づいてクラスターを抽出
   - 「通貨ペア×方向」が同じで、EntryとExitの時間区間が重複するものを同一クラスターとして扱う
   - 各クラスターから1つの最適ポイントを選択:
     * 実用スコアが最も高いポイント
     * 同スコアなら日付が最新のものを優先
3. 最終的に選択されたポイントを時間順にソート

出力:
- 統合かつ精査済みのエントリーポイントファイル
"""

import os
import pandas as pd
import numpy as np
import glob
from datetime import datetime, timedelta
import logging
from pathlib import Path
import shutil
import re
import networkx as nx

# 基本設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT_DIR = os.path.join(BASE_DIR, "entrypoint_fx")
OUTPUT_DIR = os.path.join(BASE_DIR, "entrypoint_fx_よくばり")

# 日数設定
DAYS_TO_COLLECT = 7

# ログ保存先ディレクトリ
LOG_DIR = os.path.join(OUTPUT_DIR, "log")
Path(LOG_DIR).mkdir(exist_ok=True, parents=True)

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "step4_log.txt"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 出力ディレクトリ確認
Path(OUTPUT_DIR).mkdir(exist_ok=True)

# ユーティリティ関数
def detect_encoding(file_path):
    """ファイルのエンコーディングを検出"""
    encodings = ['utf-8', 'shift_jis', 'cp932', 'euc_jp', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                f.read()
                return encoding
        except UnicodeDecodeError:
            continue
    
    # デフォルトのエンコーディング
    return 'utf-8'

def get_recent_files():
    """最近のエントリーポイントファイルを取得"""
    # 全CSVファイルを取得
    files = glob.glob(os.path.join(ENTRYPOINT_DIR, "entrypoints_*.csv"))
    
    if not files:
        logger.error("エントリーポイントファイルが見つかりません")
        return []
    
    # 現在の日付を取得
    now = datetime.now()
    cutoff_date = now - timedelta(days=DAYS_TO_COLLECT)
    
    recent_files = []
    
    for file_path in files:
        # ファイル名から日付を抽出
        try:
            file_name = os.path.basename(file_path)
            date_str = file_name.split('_')[1].split('.')[0]  # entrypoints_20250506.csv -> 20250506
            
            # 日付文字列をdatetimeに変換
            file_date = datetime.strptime(date_str, "%Y%m%d")
            
            # 過去7日以内かチェック
            if file_date >= cutoff_date:
                recent_files.append((file_path, file_date))
        except (IndexError, ValueError) as e:
            logger.warning(f"ファイル名の解析エラー: {file_path} - {str(e)}")
    
    # 日付でソート（新しい順）
    recent_files.sort(key=lambda x: x[1], reverse=True)
    
    return [f[0] for f in recent_files]

def parse_time(time_str):
    """時間文字列をdatetimeオブジェクトに変換"""
    try:
        return datetime.strptime(time_str, "%H:%M:%S")
    except ValueError:
        # 秒がない場合は追加して再試行
        if re.match(r'\d{1,2}:\d{2}$', time_str):
            return datetime.strptime(time_str + ":00", "%H:%M:%S")
        # その他のフォーマット対応が必要な場合はここに追加
        raise

def parse_date(date_str):
    """日付文字列をdatetimeオブジェクトに変換"""
    # 様々な日付フォーマットに対応
    formats = [
        "%Y/%m/%d",  # 2025/4/30
        "%Y-%m-%d",  # 2025-4-30
        "%Y%m%d"     # 20250430
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    # すべてのフォーマットに失敗した場合
    raise ValueError(f"不明な日付形式: {date_str}")

# def has_time_overlap(row1, row2):
#     """2つのエントリーの時間区間が重複するかをチェック"""
#     try:
#         # 通貨ペアと方向が違う場合は重複しない
#         if row1['通貨ペア'] != row2['通貨ペア'] or row1['方向'] != row2['方向']:
#             return False
            
#         # 時間の解析
#         entry1 = parse_time(row1['Entry'])
#         exit1 = parse_time(row1['Exit'])
#         entry2 = parse_time(row2['Entry'])
#         exit2 = parse_time(row2['Exit'])
        
#         # 時間区間の重複チェック
#         # 一方のExitがもう一方のEntryより前なら重複なし
#         # それ以外は重複あり
#         return not (exit1 <= entry2 or exit2 <= entry1)
#     except Exception as e:
#         logger.warning(f"時間重複チェックエラー: {str(e)}")
#         return False

def has_time_overlap(row1, row2):
    """2つのエントリーの時間区間が重複するかをチェック（通貨ペア条件なし版）"""
    try:
        # 方向が違う場合のみ重複しない（通貨ペア条件を削除）
        if row1['方向'] != row2['方向']:
            return False
            
        # 時間の解析
        entry1 = parse_time(row1['Entry'])
        exit1 = parse_time(row1['Exit'])
        entry2 = parse_time(row2['Entry'])
        exit2 = parse_time(row2['Exit'])
        
        # 明示的にログ出力して重複判定を確認
        logger.debug(f"時間重複チェック: {row1['通貨ペア']} {entry1}-{exit1} vs {row2['通貨ペア']} {entry2}-{exit2}")
        
        # 時間区間の重複チェック - 同じ方向で時間が重複する場合は重複と判定
        overlap = not (exit1 <= entry2 or exit2 <= entry1)
        
        if overlap:
            logger.info(f"時間重複検出: [{row1['通貨ペア']}] {row1['Entry']}-{row1['Exit']} と [{row2['通貨ペア']}] {row2['Entry']}-{row2['Exit']}")
            
        return overlap
    except Exception as e:
        logger.warning(f"時間重複チェックエラー: {str(e)}")
        import traceback
        logger.warning(traceback.format_exc())
        return False

def find_clusters(df):
    """時間区間の重複に基づいてクラスターを特定"""
    if df.empty:
        return []
    
    # グラフを作成（同一クラスターを特定するため）
    G = nx.Graph()
    
    # 行番号をノードとして追加
    for idx in df.index:
        G.add_node(idx)
    
    # 時間区間が重複する行同士をエッジで結合
    for i in df.index:
        for j in df.index:
            if i < j:  # 重複チェックは一方向だけで十分
                if has_time_overlap(df.loc[i], df.loc[j]):
                    G.add_edge(i, j)
    
    # 連結成分（クラスター）を抽出
    clusters = list(nx.connected_components(G))
    
    return clusters

def process_file(file_path):
    """1つのファイルを処理"""
    try:
        file_name = os.path.basename(file_path)
        logger.info(f"処理中: {file_name}")
        
        # ファイルのエンコーディングを検出
        file_encoding = detect_encoding(file_path)
        logger.info(f"検出されたエンコーディング: {file_encoding}")
        
        # CSVファイルを読み込み
        df = pd.read_csv(file_path, encoding=file_encoding)
        
        # カラム名の検出と標準化
        columns_mapping = {}
        
        for col in df.columns:
            col_lower = col.lower() if isinstance(col, str) else str(col).lower()
            
            if '通貨' in col_lower or 'currency' in col_lower or 'pair' in col_lower:
                columns_mapping[col] = '通貨ペア'
            elif 'entry' in col_lower or 'エントリー' in col_lower:
                columns_mapping[col] = 'Entry'
            elif 'exit' in col_lower or 'エグジット' in col_lower or '出口' in col_lower:
                columns_mapping[col] = 'Exit'
            elif '方向' in col_lower or 'direction' in col_lower or 'type' in col_lower or 'side' in col_lower:
                columns_mapping[col] = '方向'
            elif 'no' in col_lower or '番号' in col_lower or '#' in col_lower:
                columns_mapping[col] = 'No'
            elif 'score' in col_lower or 'スコア' in col_lower:
                if '実用' in col_lower or 'practical' in col_lower:
                    columns_mapping[col] = '実用スコア'
                elif '総合' in col_lower or 'total' in col_lower:
                    columns_mapping[col] = '総合スコア'
            elif '勝率' in col_lower or 'win' in col_lower:
                if '短期' in col_lower or 'short' in col_lower:
                    columns_mapping[col] = '短期勝率'
                elif '中期' in col_lower or 'mid' in col_lower:
                    columns_mapping[col] = '中期勝率'
                elif '長期' in col_lower or 'long' in col_lower:
                    columns_mapping[col] = '長期勝率'
            elif '日付' in col_lower or 'date' in col_lower:
                columns_mapping[col] = '日付'
        
        # カラムをリネーム
        if columns_mapping:
            df = df.rename(columns=columns_mapping)
            
        # 必要なカラムの確認
        required_columns = ['通貨ペア', 'Entry', 'Exit', '方向']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            logger.warning(f"必要なカラムがありません: {', '.join(missing_columns)} - ファイルをスキップします")
            return None
        
        # ファイル日付を列として追加（既に日付列がある場合は追加しない）
        if '日付' not in df.columns:
            date_str = file_name.split('_')[1].split('.')[0]
            file_date = datetime.strptime(date_str, "%Y%m%d").strftime('%Y/%m/%d')
            df['日付'] = file_date
        
        return df
        
    except Exception as e:
        logger.error(f"ファイル処理エラー: {file_path} - {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def optimize_clusters(combined_df):
    """クラスターを最適化し、各クラスターから最適なポイントを1つ選択"""
    if combined_df.empty:
        return pd.DataFrame()
    
    # データフレームをコピー
    df = combined_df.copy()
    
    # 日付列のフォーマットを統一
    if '日付' in df.columns:
        # 日付を datetime に変換
        try:
            df['日付_dt'] = df['日付'].apply(lambda x: parse_date(str(x)) if pd.notna(x) else None)
        except Exception as e:
            logger.error(f"日付変換エラー: {str(e)}")
            df['日付_dt'] = pd.NaT
    else:
        df['日付'] = None
        df['日付_dt'] = pd.NaT
    
    # クラスターを特定
    logger.info("クラスター特定を開始")
    all_clusters = find_clusters(df)
    
    # 各クラスターから最適なポイントを選択
    best_entries = []
    
    for i, cluster in enumerate(all_clusters):
        cluster_indices = list(cluster)
        if not cluster_indices:
            continue
            
        cluster_df = df.loc[cluster_indices]
        
        # クラスター内のサンプルエントリーを表示
        sample_entry = cluster_df.iloc[0]
        logger.info(f"クラスター {i+1}: {sample_entry['通貨ペア']}, {sample_entry['方向']}, " + 
                   f"{sample_entry['Entry']}-{sample_entry['Exit']} - {len(cluster_df)}行")
        
        # 実用スコアがある場合はそれでソート
        if '実用スコア' in cluster_df.columns:
            # 実用スコアでソート（降順）し、同じスコアなら日付が新しい順
            sorted_cluster = cluster_df.sort_values(
                by=['実用スコア', '日付_dt'], 
                ascending=[False, False]
            )
            
            # 最初の行（最適なポイント）を選択
            best_entry = sorted_cluster.iloc[0].copy()
            best_entries.append(best_entry)
            
            logger.info(f"  最適ポイント選択: 実用スコア={best_entry.get('実用スコア', 'N/A')}, 日付={best_entry.get('日付', 'N/A')}")
        else:
            # 実用スコアがなければ日付が新しい順
            sorted_cluster = cluster_df.sort_values(by=['日付_dt'], ascending=[False])
            best_entry = sorted_cluster.iloc[0].copy()
            best_entries.append(best_entry)
            
            logger.info(f"  最適ポイント選択: 日付={best_entry.get('日付', 'N/A')}")
    
    # 選択されたエントリーでデータフレームを作成
    if best_entries:
        result_df = pd.DataFrame(best_entries)
        
        # 作業用の列を削除
        if '日付_dt' in result_df.columns:
            result_df = result_df.drop('日付_dt', axis=1)
        
        # Entry時間でソート
        result_df = result_df.sort_values(by=['Entry']).reset_index(drop=True)
        
        # 連番を振り直し
        if "No" in result_df.columns:
            result_df["No"] = range(1, len(result_df) + 1)
        else:
            result_df.insert(0, "No", range(1, len(result_df) + 1))
        
        logger.info(f"クラスター最適化完了: {len(df)} 行から {len(result_df)} 行に最適化")
        
        return result_df
    else:
        logger.warning("最適化結果が空です")
        return pd.DataFrame()

def collect_and_filter_entrypoints():
    """エントリーポイントを収集して精査する"""
    recent_files = get_recent_files()
    
    if not recent_files:
        logger.error("最近のエントリーポイントファイルが見つかりません")
        return False
    
    logger.info(f"収集対象ファイル: {len(recent_files)}件")
    
    # ファイルごとに処理
    processed_dfs = []
    
    for file_path in recent_files:
        df = process_file(file_path)
        if df is not None and not df.empty:
            processed_dfs.append(df)
    
    if not processed_dfs:
        logger.error("有効なデータがありません")
        return False
    
    # すべてのデータを結合
    combined_df = pd.concat(processed_dfs, ignore_index=True)
    
    # クラスターの最適化
    optimized_df = optimize_clusters(combined_df)
    
    if optimized_df.empty:
        logger.error("最適化結果が空です")
        return False
    
    # 必要なカラムの確認と追加
    expected_columns = [
        "No", "通貨ペア", "Entry", "Exit", "方向",
        "実用スコア", "総合スコア", "短期勝率", "中期勝率", "長期勝率", "日付"
    ]
    
    for col in expected_columns:
        if col not in optimized_df.columns:
            if col == "No":
                optimized_df[col] = range(1, len(optimized_df) + 1)
            else:
                optimized_df[col] = None
    
    # カラムの順序を整える
    optimized_df = optimized_df[
        [col for col in expected_columns if col in optimized_df.columns] + 
        [col for col in optimized_df.columns if col not in expected_columns]
    ]
    
    # 結果を保存
    now = datetime.now()
    output_file = os.path.join(OUTPUT_DIR, f"よくばりエントリー_{now.strftime('%Y%m%d')}.csv")
    
    # Shift-JISエンコーディングで保存
    optimized_df.to_csv(output_file, index=False, encoding='shift_jis')
    logger.info(f"収集結果を保存しました: {output_file}")
    logger.info(f"総エントリーポイント数: {len(optimized_df)}")
    
    # 元ファイルもコピー
    backup_dir = os.path.join(OUTPUT_DIR, "originals")
    Path(backup_dir).mkdir(exist_ok=True)
    
    for file_path in recent_files:
        file_name = os.path.basename(file_path)
        dest_path = os.path.join(backup_dir, file_name)
        shutil.copy2(file_path, dest_path)
    
    logger.info(f"元ファイルをバックアップしました: {backup_dir}")
    
    return True

def main():
    """メイン処理"""
    try:
        logger.info("FXエントリーポイント収集・精査処理を開始します")
        
        # networkxライブラリが必要
        try:
            import networkx
            logger.info("必要なライブラリが利用可能です")
        except ImportError:
            logger.error("networkxライブラリがインストールされていません。以下のコマンドでインストールしてください：")
            logger.error("pip install networkx")
            return False
        
        if collect_and_filter_entrypoints():
            logger.info("処理が正常に完了しました")
        else:
            logger.error("処理に失敗しました")
    except Exception as e:
        logger.error(f"実行エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()