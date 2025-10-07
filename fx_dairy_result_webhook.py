#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FX取引結果集計スクリプト (修正版)
- 全CSVファイルのpips集計
- 日付別の累積pips集計
- 通貨ペア別、時間帯別の分析
- グラフ生成
- スプレッドシートへのデータ送信
"""

import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import re
import logging
from pathlib import Path
import locale
import json

# 日本語ロケールの設定
try:
    locale.setlocale(locale.LC_ALL, 'ja_JP.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'Japanese_Japan.932')
    except:
        pass  # どちらも失敗した場合はデフォルトのままにする

# 基本設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(BASE_DIR, "entrypoint_fx_result")
OUTPUT_DIR = os.path.join(RESULT_DIR, "summary")
Path(OUTPUT_DIR).mkdir(exist_ok=True, parents=True)

# ロギング設定
LOG_DIR = os.path.join(OUTPUT_DIR, "log")
Path(LOG_DIR).mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "pips_summary_log.txt"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

def normalize_column_names(df):
    """カラム名を標準化"""
    column_mapping = {}
    for col in df.columns:
        col_str = str(col).lower()
        
        if 'no' in col_str or '#' in col_str:
            column_mapping[col] = 'No'
        elif any(term in col_str for term in ['currency', 'pair', 'ペア', 'К‰Э']):
            column_mapping[col] = '通貨ペア'
        elif any(term in col_str for term in ['direction', 'type', '方向', '•ыЊь']):
            column_mapping[col] = '方向'
        elif 'entry' in col_str and not any(term in col_str for term in ['price', '価格', '‰їЉi']):
            column_mapping[col] = 'Entry'
        elif 'exit' in col_str and not any(term in col_str for term in ['price', '価格', '‰їЉi']):
            column_mapping[col] = 'Exit'
        elif any(term in col_str for term in ['entry price', 'entry_price', '価格', 'entry‰їЉi']):
            column_mapping[col] = 'Entry価格'
        elif any(term in col_str for term in ['exit price', 'exit_price', '価格', 'exit‰їЉi']):
            column_mapping[col] = 'Exit価格'
        elif any(term in col_str for term in ['result', 'win', 'loss', '勝敗', 'Џџ"s']):
            column_mapping[col] = '勝敗'
        elif 'pips' in col_str:
            column_mapping[col] = 'pips'
        elif any(term in col_str for term in ['date', '日付', '"ъ•t']):
            column_mapping[col] = '日付'
        elif any(term in col_str for term in ['score', 'スコア', 'ѓXѓR']):
            if any(term in col_str for term in ['practical', '実用', 'ЋА—p']):
                column_mapping[col] = '実用スコア'
            elif any(term in col_str for term in ['total', '総合', 'ЌЌ‡']):
                column_mapping[col] = '総合スコア'
        elif any(term in col_str for term in ['rate', '勝率', 'Џџ—¦']):
            if any(term in col_str for term in ['short', '短期', 'ZЉъ']):
                column_mapping[col] = '短期勝率'
            elif any(term in col_str for term in ['mid', '中期', '†Љъ']):
                column_mapping[col] = '中期勝率'
            elif any(term in col_str for term in ['long', '長期', '·Љъ']):
                column_mapping[col] = '長期勝率'
    
    if column_mapping:
        df = df.rename(columns=column_mapping)
    
    return df

def read_fx_csv_file(file_path):
    """CSVファイルを読み込み、データを標準化して返す（O列日付無視版）"""
    try:
        # ファイル名から日付を取得
        file_name = os.path.basename(file_path)
        date_match = re.search(r'(\d{8})', file_name)
        file_date = None
        
        if date_match:
            date_str = date_match.group(1)
            file_date = datetime.strptime(date_str, '%Y%m%d')
            logger.info(f"ファイル名から取得した日付: {file_date.strftime('%Y/%m/%d')}")
        else:
            logger.warning(f"ファイル名 {file_name} から日付を取得できませんでした")
            # 現在の日付をフォールバックとして使用
            file_date = datetime.now()
        
        # エンコーディングを検出
        file_encoding = detect_encoding(file_path)
        
        # CSVファイルを読み込み
        df = pd.read_csv(file_path, encoding=file_encoding)
        
        # カラム名を標準化
        df = normalize_column_names(df)
        
        # 必要なカラムが存在するか確認
        if 'pips' not in df.columns:
            logger.warning(f"pipsカラムがありません: {file_path}")
            return None
        
        # 合計行を取り除く（「合計」という文字列を含む行または最終行）
        if "No" in df.columns:
            total_mask = df["No"].astype(str).str.contains("合計|合計値|Ќ‡Њv", na=False)
            if total_mask.any():
                df = df[~total_mask]
            else:
                # 最終行が合計行である場合が多いので、最終行を削除
                df = df.iloc[:-1]
        else:
            # 最終行が合計行である場合が多いので、最終行を削除
            df = df.iloc[:-1]
        
        # 日付列を明示的に設定（CSVのO列は無視）
        df['日付'] = file_date
        
        # pipsを数値型に変換
        df['pips'] = pd.to_numeric(df['pips'], errors='coerce')
        
        return df
    
    except Exception as e:
        logger.error(f"ファイル読み込みエラー: {file_path} - {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def collect_all_fx_data(result_dir):
    """全てのFX結果ファイルを収集して結合"""
    # CSVファイル一覧を取得
    csv_files = glob.glob(os.path.join(result_dir, "fx_results_*.csv"))
    
    if not csv_files:
        logger.error(f"結果ファイルが見つかりません: {result_dir}")
        return None
    
    logger.info(f"CSVファイル数: {len(csv_files)}")
    logger.info(f"データファイル: {[os.path.basename(f) for f in sorted(csv_files)]}")
    
    # 全データを結合
    all_data = []
    
    for file_path in sorted(csv_files):
        logger.info(f"ファイル処理中: {os.path.basename(file_path)}")
        df = read_fx_csv_file(file_path)
        if df is not None and not df.empty:
            all_data.append(df)
    
    if not all_data:
        logger.error("有効なデータがありません")
        return None
    
    # データを結合
    combined_df = pd.concat(all_data, ignore_index=True)
    
    # 日付でソート
    if '日付' in combined_df.columns:
        combined_df = combined_df.sort_values('日付')
    
    logger.info(f"総取引数: {len(combined_df)}行")
    return combined_df

def calculate_daily_summary(df):
    """日次の取引集計を計算"""
    if '日付' not in df.columns:
        logger.error("日付列がありません。日次集計ができません。")
        return None
    
    # 日付ごとにグループ化
    daily_summary = df.groupby('日付').agg({
        'pips': ['sum', 'count'],
        '勝敗': lambda x: (x == 'WIN').sum()
    })
    
    # カラム名を整理
    daily_summary.columns = ['pips', '取引数', '勝数']
    daily_summary['勝率'] = (daily_summary['勝数'] / daily_summary['取引数'] * 100).round(1)
    daily_summary['累積pips'] = daily_summary['pips'].cumsum()
    
    return daily_summary

def calculate_currency_summary(df):
    """通貨ペア別の集計を計算"""
    if '通貨ペア' not in df.columns:
        logger.error("通貨ペア列がありません。通貨別集計ができません。")
        return None
    
    # 通貨ペアごとにグループ化
    currency_summary = df.groupby('通貨ペア').agg({
        'pips': ['sum', 'count', 'mean'],
        '勝敗': lambda x: (x == 'WIN').sum()
    })
    
    # カラム名を整理
    currency_summary.columns = ['合計pips', '取引数', '平均pips', '勝数']
    currency_summary['勝率'] = (currency_summary['勝数'] / currency_summary['取引数'] * 100).round(1)
    
    # 合計pipsでソート
    currency_summary = currency_summary.sort_values('合計pips', ascending=False)
    
    return currency_summary

def calculate_hourly_summary(df):
    """時間帯別の集計を計算"""
    if 'Entry' not in df.columns:
        logger.error("Entry列がありません。時間帯別集計ができません。")
        return None
    
    # 時間を抽出
    df['hour'] = df['Entry'].apply(lambda x: int(str(x).split(':')[0]) if ':' in str(x) else None)
    
    # 時間帯ごとにグループ化
    hourly_summary = df.groupby('hour').agg({
        'pips': ['sum', 'count', 'mean'],
        '勝敗': lambda x: (x == 'WIN').sum()
    })
    
    # カラム名を整理
    hourly_summary.columns = ['合計pips', '取引数', '平均pips', '勝数']
    hourly_summary['勝率'] = (hourly_summary['勝数'] / hourly_summary['取引数'] * 100).round(1)
    
    return hourly_summary

def calculate_direction_summary(df):
    """売買方向別の集計を計算"""
    if '方向' not in df.columns:
        logger.error("方向列がありません。方向別集計ができません。")
        return None
    
    # 方向ごとにグループ化
    direction_summary = df.groupby('方向').agg({
        'pips': ['sum', 'count', 'mean'],
        '勝敗': lambda x: (x == 'WIN').sum()
    })
    
    # カラム名を整理
    direction_summary.columns = ['合計pips', '取引数', '平均pips', '勝数']
    direction_summary['勝率'] = (direction_summary['勝数'] / direction_summary['取引数'] * 100).round(1)
    
    return direction_summary

def create_daily_pips_chart(daily_summary, output_path, title="日次pips推移"):
    """日次pipsチャートを作成"""
    plt.figure(figsize=(12, 6))
    
    # フォント設定
    plt.rcParams['font.family'] = 'sans-serif'
    if os.name == 'nt':  # Windows
        plt.rcParams['font.sans-serif'] = ['MS Gothic', 'Yu Gothic', 'Meiryo']
    else:  # macOS/Linux
        plt.rcParams['font.sans-serif'] = ['Hiragino Sans', 'Hiragino Kaku Gothic Pro', 'Noto Sans CJK JP']
    
    # 日付のフォーマット設定
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    plt.gca().xaxis.set_major_locator(mdates.DayLocator(interval=5))
    
    # 日々のpipsのバーチャート
    ax1 = plt.gca()
    bars = ax1.bar(daily_summary.index, daily_summary['pips'], 
             color=[('green' if x >= 0 else 'red') for x in daily_summary['pips']], 
             alpha=0.7, label='日次pips')
    
    # 各バーに値を表示
    for bar in bars:
        height = bar.get_height()
        if height >= 0:
            y_pos = height + 0.5
        else:
            y_pos = height - 3
        ax1.text(bar.get_x() + bar.get_width()/2., y_pos,
                f'{height:.1f}', ha='center', va='bottom' if height >= 0 else 'top',
                fontsize=8)
    
    # 累積pipsの折れ線グラフ
    ax2 = ax1.twinx()
    ax2.plot(daily_summary.index, daily_summary['累積pips'], 
             color='blue', marker='o', linestyle='-', linewidth=2, label='累積pips')
    
    # 最終累積pipsを表示
    last_date = daily_summary.index[-1]
    last_cum_pips = daily_summary['累積pips'].iloc[-1]
    ax2.annotate(f'累積: {last_cum_pips:.1f} pips',
                xy=(last_date, last_cum_pips),
                xytext=(10, 0),
                textcoords='offset points',
                ha='left',
                va='center',
                fontsize=10,
                bbox=dict(boxstyle='round,pad=0.3', fc='yellow', alpha=0.5))
    
    # ゼロライン
    ax1.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    
    # ラベルとタイトル
    ax1.set_xlabel('日付')
    ax1.set_ylabel('日次pips')
    ax2.set_ylabel('累積pips')
    plt.title(title)
    
    # 凡例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    
    # グリッド
    ax1.grid(True, linestyle='--', alpha=0.7)
    
    # 図の余白調整
    plt.tight_layout()
    
    # 保存
    plt.savefig(output_path)
    plt.close()
    
    logger.info(f"日次pipsチャートを保存しました: {output_path}")

def create_currency_pips_chart(currency_summary, output_path, title="通貨ペア別pips"):
    """通貨ペア別pipsチャートを作成"""
    plt.figure(figsize=(12, 6))
    
    # フォント設定
    plt.rcParams['font.family'] = 'sans-serif'
    if os.name == 'nt':  # Windows
        plt.rcParams['font.sans-serif'] = ['MS Gothic', 'Yu Gothic', 'Meiryo']
    else:  # macOS/Linux
        plt.rcParams['font.sans-serif'] = ['Hiragino Sans', 'Hiragino Kaku Gothic Pro', 'Noto Sans CJK JP']
    
    # 通貨ペア別pipsのバーチャート
    bars = plt.bar(currency_summary.index, currency_summary['合計pips'],
                  color=[('green' if x >= 0 else 'red') for x in currency_summary['合計pips']])
    
    # 各バーに値とパーセントを表示
    total_pips = currency_summary['合計pips'].sum()
    for bar in bars:
        height = bar.get_height()
        percentage = height / total_pips * 100 if total_pips != 0 else 0
        if height >= 0:
            y_pos = height + 0.5
            va = 'bottom'
        else:
            y_pos = height - 3
            va = 'top'
        plt.text(bar.get_x() + bar.get_width()/2., y_pos,
                f'{height:.1f}\n({percentage:.1f}%)', ha='center', va=va)
    
    # ゼロライン
    plt.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    
    # ラベルとタイトル
    plt.xlabel('通貨ペア')
    plt.ylabel('合計pips')
    plt.title(title)
    
    # グリッド
    plt.grid(True, axis='y', linestyle='--', alpha=0.7)
    
    # 図の余白調整
    plt.tight_layout()
    
    # 保存
    plt.savefig(output_path)
    plt.close()
    
    logger.info(f"通貨ペア別pipsチャートを保存しました: {output_path}")

def create_hourly_pips_chart(hourly_summary, output_path, title="時間帯別pips"):
    """時間帯別pipsチャートを作成"""
    plt.figure(figsize=(12, 6))
    
    # フォント設定
    plt.rcParams['font.family'] = 'sans-serif'
    if os.name == 'nt':  # Windows
        plt.rcParams['font.sans-serif'] = ['MS Gothic', 'Yu Gothic', 'Meiryo']
    else:  # macOS/Linux
        plt.rcParams['font.sans-serif'] = ['Hiragino Sans', 'Hiragino Kaku Gothic Pro', 'Noto Sans CJK JP']
    
    # 時間帯別グラフ
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    # pipsのバーチャート
    bars = ax1.bar(hourly_summary.index, hourly_summary['合計pips'],
                  color=[('green' if x >= 0 else 'red') for x in hourly_summary['合計pips']])
    
    # 各バーに値を表示
    for bar in bars:
        height = bar.get_height()
        if height >= 0:
            y_pos = height + 0.5
            va = 'bottom'
        else:
            y_pos = height - 3
            va = 'top'
        ax1.text(bar.get_x() + bar.get_width()/2., y_pos,
                f'{height:.1f}', ha='center', va=va)
    
    # 勝率の折れ線グラフ
    ax2 = ax1.twinx()
    ax2.plot(hourly_summary.index, hourly_summary['勝率'], 
             color='blue', marker='o', linestyle='-', linewidth=2)
    
    # 各ポイントに勝率を表示
    for i, rate in enumerate(hourly_summary['勝率']):
        ax2.annotate(f'{rate:.1f}%', 
                    xy=(hourly_summary.index[i], rate),
                    xytext=(0, 10),
                    textcoords='offset points',
                    ha='center',
                    fontsize=8)
    
    # ゼロライン
    ax1.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    
    # ラベルとタイトル
    ax1.set_xlabel('時間')
    ax1.set_ylabel('合計pips')
    ax2.set_ylabel('勝率 (%)')
    ax2.set_ylim(0, 100)
    plt.title(title)
    
    # x軸の目盛りを整数にする
    plt.xticks(hourly_summary.index)
    
    # グリッド
    ax1.grid(True, axis='y', linestyle='--', alpha=0.7)
    
    # 図の余白調整
    plt.tight_layout()
    
    # 保存
    plt.savefig(output_path)
    plt.close()
    
    logger.info(f"時間帯別pipsチャートを保存しました: {output_path}")

def create_summary_html(daily_summary, currency_summary, hourly_summary, direction_summary, output_path):
    """集計結果のHTMLレポートを作成"""
    try:
        # 全体の統計
        total_trades = daily_summary['取引数'].sum()
        total_wins = daily_summary['勝数'].sum()
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        total_pips = daily_summary['pips'].sum()
        avg_pips_per_trade = total_pips / total_trades if total_trades > 0 else 0
        
        # 日付範囲
        date_range = f"{daily_summary.index.min().strftime('%Y/%m/%d')} 〜 {daily_summary.index.max().strftime('%Y/%m/%d')}"
        
        # 最高・最低の日
        best_day = daily_summary['pips'].idxmax()
        best_day_pips = daily_summary.loc[best_day, 'pips']
        worst_day = daily_summary['pips'].idxmin()
        worst_day_pips = daily_summary.loc[worst_day, 'pips']
        
        # HTMLの生成
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FX取引pips集計レポート</title>
            <style>
                body {{ font-family: 'Segoe UI', 'Meiryo UI', Meiryo, sans-serif; margin: 20px; }}
                h1, h2, h3 {{ color: #2c3e50; }}
                table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                th, td {{ text-align: left; padding: 8px; border: 1px solid #ddd; }}
                th {{ background-color: #f2f2f2; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .summary {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                img {{ max-width: 100%; height: auto; margin: 20px 0; }}
                .chart-container {{ margin-bottom: 30px; }}
            </style>
        </head>
        <body>
            <h1>FX取引pips集計レポート</h1>
            
            <div class="summary">
                <h2>全体統計</h2>
                <p>期間: {date_range}</p>
                <p>総取引数: {total_trades}回</p>
                <p>勝率: {win_rate:.1f}% ({total_wins}/{total_trades})</p>
                <p>合計pips: <span class="{'positive' if total_pips >= 0 else 'negative'}">{total_pips:.1f}</span></p>
                <p>取引あたり平均pips: <span class="{'positive' if avg_pips_per_trade >= 0 else 'negative'}">{avg_pips_per_trade:.1f}</span></p>
                <p>最高の日: {best_day.strftime('%Y/%m/%d')} <span class="positive">+{best_day_pips:.1f} pips</span></p>
                <p>最低の日: {worst_day.strftime('%Y/%m/%d')} <span class="negative">{worst_day_pips:.1f} pips</span></p>
            </div>
            
            <div class="chart-container">
                <h2>日次pips推移</h2>
                <img src="daily_pips_chart.png" alt="日次pips推移">
            </div>
            
            <div class="chart-container">
                <h2>直近1ヶ月pips推移</h2>
                <img src="monthly_pips_chart.png" alt="直近1ヶ月pips推移">
            </div>
            
            <div class="chart-container">
                <h2>通貨ペア別pips</h2>
                <img src="currency_pips_chart.png" alt="通貨ペア別pips">
            </div>
            
            <div class="chart-container">
                <h2>時間帯別pips</h2>
                <img src="hourly_pips_chart.png" alt="時間帯別pips">
            </div>
            
            <h2>通貨ペア別パフォーマンス</h2>
            <table>
                <tr>
                    <th>通貨ペア</th>
                    <th>取引数</th>
                    <th>勝数</th>
                    <th>勝率</th>
                    <th>合計pips</th>
                    <th>平均pips</th>
                </tr>
        """
        
        # 通貨ペア別テーブル
        for currency, row in currency_summary.iterrows():
            html_content += f"""
                <tr>
                    <td>{currency}</td>
                    <td>{int(row['取引数'])}</td>
                    <td>{int(row['勝数'])}</td>
                    <td>{row['勝率']:.1f}%</td>
                    <td class="{'positive' if row['合計pips'] >= 0 else 'negative'}">{row['合計pips']:.1f}</td>
                    <td class="{'positive' if row['平均pips'] >= 0 else 'negative'}">{row['平均pips']:.1f}</td>
                </tr>
            """
        
        html_content += """
            </table>
            
            <h2>時間帯別パフォーマンス</h2>
            <table>
                <tr>
                    <th>時間</th>
                    <th>取引数</th>
                    <th>勝数</th>
                    <th>勝率</th>
                    <th>合計pips</th>
                    <th>平均pips</th>
                </tr>
        """
        
        # 時間帯別テーブル
        for hour, row in hourly_summary.iterrows():
            html_content += f"""
                <tr>
                    <td>{hour}時</td>
                    <td>{int(row['取引数'])}</td>
                    <td>{int(row['勝数'])}</td>
                    <td>{row['勝率']:.1f}%</td>
                    <td class="{'positive' if row['合計pips'] >= 0 else 'negative'}">{row['合計pips']:.1f}</td>
                    <td class="{'positive' if row['平均pips'] >= 0 else 'negative'}">{row['平均pips']:.1f}</td>
                </tr>
            """
        
        html_content += """
            </table>
            
            <h2>売買方向別パフォーマンス</h2>
            <table>
                <tr>
                    <th>方向</th>
                    <th>取引数</th>
                    <th>勝数</th>
                    <th>勝率</th>
                    <th>合計pips</th>
                    <th>平均pips</th>
                </tr>
        """
        
        # 売買方向別テーブル
        for direction, row in direction_summary.iterrows():
            html_content += f"""
                <tr>
                    <td>{direction}</td>
                    <td>{int(row['取引数'])}</td>
                    <td>{int(row['勝数'])}</td>
                    <td>{row['勝率']:.1f}%</td>
                    <td class="{'positive' if row['合計pips'] >= 0 else 'negative'}">{row['合計pips']:.1f}</td>
                    <td class="{'positive' if row['平均pips'] >= 0 else 'negative'}">{row['平均pips']:.1f}</td>
                </tr>
            """
        
        html_content += """
            </table>
            
            <h2>日次取引詳細</h2>
            <table>
                <tr>
                    <th>日付</th>
                    <th>取引数</th>
                    <th>勝数</th>
                    <th>勝率</th>
                    <th>pips</th>
                    <th>累積pips</th>
                </tr>
        """
        
        # 日次テーブル
        for date, row in daily_summary.iterrows():
            html_content += f"""
                <tr>
                    <td>{date.strftime('%Y/%m/%d')}</td>
                    <td>{int(row['取引数'])}</td>
                    <td>{int(row['勝数'])}</td>
                    <td>{row['勝率']:.1f}%</td>
                    <td class="{'positive' if row['pips'] >= 0 else 'negative'}">{row['pips']:.1f}</td>
                    <td class="{'positive' if row['累積pips'] >= 0 else 'negative'}">{row['累積pips']:.1f}</td>
                </tr>
            """
        
        html_content += """
            </table>
        </body>
        </html>
        """
        
        # HTMLファイルに保存
        with open(output_path, 'w', encoding='utf-8') as file:
            file.write(html_content)
        
        logger.info(f"HTMLレポートを保存しました: {output_path}")
        
    except Exception as e:
        logger.error(f"HTMLレポート生成エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


def prepare_data_for_spreadsheet(daily_summary, currency_summary, hourly_summary, direction_summary):
    """スプレッドシートに送信するデータを準備"""
    # 全体の統計を計算
    total_trades = daily_summary['取引数'].sum()
    total_wins = daily_summary['勝数'].sum()
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    total_pips = daily_summary['pips'].sum()
    avg_pips_per_trade = total_pips / total_trades if total_trades > 0 else 0
    
    # 日付範囲
    date_range = f"{daily_summary.index.min().strftime('%Y/%m/%d')} 〜 {daily_summary.index.max().strftime('%Y/%m/%d')}"
    
    # 最高・最低の日
    best_day = daily_summary['pips'].idxmax()
    best_day_pips = daily_summary.loc[best_day, 'pips']
    worst_day = daily_summary['pips'].idxmin()
    worst_day_pips = daily_summary.loc[worst_day, 'pips']
    
    # 全体統計データ
    overall_stats = {
        'date_range': date_range,
        'total_trades': int(total_trades),
        'total_wins': int(total_wins),
        'win_rate': float(win_rate),
        'total_pips': float(total_pips),
        'avg_pips_per_trade': float(avg_pips_per_trade),
        'best_day': best_day.strftime('%Y/%m/%d'),
        'best_day_pips': float(best_day_pips),
        'worst_day': worst_day.strftime('%Y/%m/%d'),
        'worst_day_pips': float(worst_day_pips)
    }
    
    return {
        'daily_summary': daily_summary,
        'currency_summary': currency_summary,
        'hourly_summary': hourly_summary,
        'direction_summary': direction_summary,
        'overall_stats': overall_stats
    }

def save_data_to_json(data, output_path):
    """集計データをJSONファイルに保存"""
    try:
        import json
        from datetime import datetime
        import pandas as pd
        
        # JSONエンコーダを拡張して、特殊な型を処理
        class CustomJSONEncoder(json.JSONEncoder):
            def default(self, obj):
                # Timestamp型を処理
                if isinstance(obj, pd.Timestamp):
                    return obj.strftime('%Y-%m-%d')
                # datetime型を処理
                elif isinstance(obj, datetime):
                    return obj.strftime('%Y-%m-%d')
                # その他のPandas特殊型を処理
                elif hasattr(obj, 'to_dict'):
                    return obj.to_dict()
                # NumPy型を処理
                elif hasattr(obj, 'item'):
                    return obj.item()
                # 他の変換できない型はデフォルトの挙動
                return super().default(obj)
        
        # データの準備 - reset_indexを先に適用
        daily_data = data['daily_summary'].reset_index().to_dict(orient='records')
        currency_data = data['currency_summary'].reset_index().to_dict(orient='records')
        hourly_data = data['hourly_summary'].reset_index().to_dict(orient='records')
        direction_data = data['direction_summary'].reset_index().to_dict(orient='records')
        
        # 整形したJSONデータ
        json_data = {
            'daily_summary': daily_data,
            'currency_summary': currency_data,
            'hourly_summary': hourly_data,
            'direction_summary': direction_data,
            'overall_stats': data['overall_stats']
        }
        
        # カスタムエンコーダを使用してJSONに保存
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, cls=CustomJSONEncoder, ensure_ascii=False, indent=2)
        
        logger.info(f"集計データをJSONに保存しました: {output_path}")
        return True
    except Exception as e:
        logger.error(f"JSON保存エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def send_data_to_gas_webhook(data, webhook_url):
    """データをGASのWebhookに送信（日付形式修正版）"""
    try:
        import requests
        import json
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # データの準備 - 日付情報を文字列として直接送信
        daily_data = []
        for idx, row in data['daily_summary'].iterrows():
            # 日付はindexに入っている
            daily_row = row.to_dict()
            # 日付を文字列形式で追加
            daily_row['date'] = idx.strftime('%Y/%m/%d')
            daily_data.append(daily_row)
        
        # 他のデータの準備
        currency_data = data['currency_summary'].reset_index().to_dict(orient='records')
        hourly_data = data['hourly_summary'].reset_index().to_dict(orient='records')
        direction_data = data['direction_summary'].reset_index().to_dict(orient='records')
        
        # 整形したJSONデータ
        json_data = {
            'daily_summary': daily_data,
            'currency_summary': currency_data,
            'hourly_summary': hourly_data,
            'direction_summary': direction_data,
            'overall_stats': data['overall_stats']
        }
        
        # JSONシリアライザ - カスタムクラスなしでシンプルに
        def json_serial(obj):
            """JSONシリアライズできないオブジェクトを変換"""
            if isinstance(obj, (datetime, pd.Timestamp)):
                return obj.strftime('%Y/%m/%d')
            if isinstance(obj, (np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64)):
                return int(obj)
            if isinstance(obj, (np.float_, np.float16, np.float32, np.float64)):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # GASのWebhookにPOSTリクエスト
        logger.info(f"データをGASのWebhookに送信しています: {webhook_url}")
        response = requests.post(
            webhook_url,
            json=json.loads(json.dumps(json_data, default=json_serial))
        )
        
        # レスポンスをチェック
        if response.status_code == 200:
            logger.info(f"データをスプレッドシートに正常に送信しました。")
            logger.info(f"レスポンス: {response.text}")
            return True
        else:
            logger.error(f"データ送信エラー: ステータスコード {response.status_code}")
            logger.error(f"レスポンス: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"GAS Webhook送信エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """メイン処理（ファイル日付使用版）"""
    try:
        logger.info("FX取引pips集計処理を開始します")
        logger.info(f"入力データフォルダ: {RESULT_DIR}")
        
        # 入力フォルダの確認
        if not os.path.exists(RESULT_DIR):
            logger.error(f"入力フォルダが存在しません: {RESULT_DIR}")
            return False
        
        # フォルダ内のCSVファイルを確認
        csv_files = glob.glob(os.path.join(RESULT_DIR, "fx_results_*.csv"))
        if not csv_files:
            logger.error(f"入力フォルダにCSVファイルが見つかりません: {RESULT_DIR}")
            all_files = os.listdir(RESULT_DIR)
            logger.error(f"入力フォルダ内のファイル: {all_files}")
            return False
        
        # ファイル名と日付の対応を表示
        for csv_file in sorted(csv_files):
            file_name = os.path.basename(csv_file)
            date_match = re.search(r'(\d{8})', file_name)
            if date_match:
                date_str = date_match.group(1)
                file_date = datetime.strptime(date_str, '%Y%m%d')
                logger.info(f"ファイル: {file_name} → 日付: {file_date.strftime('%Y/%m/%d')}")
            else:
                logger.warning(f"ファイル名から日付を取得できません: {file_name}")
        
        # 全FXデータを収集
        all_fx_data = collect_all_fx_data(RESULT_DIR)
        
        if all_fx_data is None or all_fx_data.empty:
            logger.error("有効なデータがありません。処理を中止します。")
            return False
        
        # 各種集計を計算
        daily_summary = calculate_daily_summary(all_fx_data)
        currency_summary = calculate_currency_summary(all_fx_data)
        hourly_summary = calculate_hourly_summary(all_fx_data)
        direction_summary = calculate_direction_summary(all_fx_data)
        
        if daily_summary is None:
            logger.error("日次集計ができません。処理を中止します。")
            return False
        
        # データ確認
        logger.info(f"日次集計行数: {len(daily_summary)}")
        logger.info(f"日付リスト: {[d.strftime('%Y/%m/%d') for d in daily_summary.index]}")
        
        # スプレッドシート用のデータを準備
        spreadsheet_data = prepare_data_for_spreadsheet(
            daily_summary, currency_summary, hourly_summary, direction_summary
        )
        
        # JSONファイルに保存（スプレッドシートからの取り込み用）
        save_data_to_json(
            spreadsheet_data,
            os.path.join(OUTPUT_DIR, "fx_summary_data.json")
        )
        
        # グラフの作成と保存
        # 全期間のグラフ
        create_daily_pips_chart(
            daily_summary, 
            os.path.join(OUTPUT_DIR, "daily_pips_chart.png"),
            "全期間 日次pips推移"
        )
        
        # 直近1ヶ月のグラフ
        one_month_ago = datetime.now() - timedelta(days=30)
        monthly_data = daily_summary[daily_summary.index >= one_month_ago]
        if not monthly_data.empty:
            create_daily_pips_chart(
                monthly_data, 
                os.path.join(OUTPUT_DIR, "monthly_pips_chart.png"),
                "直近1ヶ月 日次pips推移"
            )
        
        # 通貨ペア別グラフ
        if currency_summary is not None:
            create_currency_pips_chart(
                currency_summary,
                os.path.join(OUTPUT_DIR, "currency_pips_chart.png")
            )
        
        # 時間帯別グラフ
        if hourly_summary is not None:
            create_hourly_pips_chart(
                hourly_summary,
                os.path.join(OUTPUT_DIR, "hourly_pips_chart.png")
            )
        
        # HTMLレポートの作成
        create_summary_html(
            daily_summary,
            currency_summary if currency_summary is not None else pd.DataFrame(),
            hourly_summary if hourly_summary is not None else pd.DataFrame(),
            direction_summary if direction_summary is not None else pd.DataFrame(),
            os.path.join(OUTPUT_DIR, "fx_pips_summary.html")
        )
        
        # GASのWebhookへデータを送信 - 正しいURLを設定
        webhook_url = "https://script.google.com/macros/s/AKfycby4-AGZdrWxYQ3m-u7u9kAcdHHBwwCYXvcxQ7tzrNM2Vraxou_XXG5WCfco3VJrXlM/exec"
        
        logger.info(f"スプレッドシートへデータを送信します。Webhook URL: {webhook_url}")
        
        # WebhookにPOSTリクエストを送信
        if send_data_to_gas_webhook(spreadsheet_data, webhook_url):
            logger.info("スプレッドシートへのデータ送信が完了しました。")
        else:
            logger.warning("スプレッドシートへのデータ送信に失敗しました。")
        
        logger.info("処理が完了しました")
        return True
        
    except Exception as e:
        logger.error(f"実行エラー: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False
        
if __name__ == "__main__":
    main()