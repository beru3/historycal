#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fx_comparison_analysis.py - FX結果比較分析ツール
よくばり版と標準版の結果を包括的に比較分析
"""

import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import glob
import json
import warnings
warnings.filterwarnings('ignore')

# 日本語フォント設定
import matplotlib
import platform

def setup_japanese_font():
    """日本語フォントを設定"""
    system = platform.system()
    
    if system == "Windows":
        # Windows用フォント
        fonts = ['MS Gothic', 'Yu Gothic', 'Meiryo', 'MS UI Gothic']
    elif system == "Darwin":  # macOS
        # macOS用フォント
        fonts = ['Hiragino Sans', 'Hiragino Kaku Gothic Pro', 'Arial Unicode MS']
    else:  # Linux
        # Linux用フォント
        fonts = ['Noto Sans CJK JP', 'IPAexGothic', 'IPAPGothic', 'VL PGothic', 'Takao Gothic']
    
    # フォントを順番に試す
    for font in fonts:
        try:
            matplotlib.font_manager.fontManager.findfont(font, fallback_to_default=False)
            plt.rcParams['font.family'] = font
            print(f"日本語フォント設定: {font}")
            return
        except:
            continue
    
    # フォールバック
    plt.rcParams['font.family'] = 'DejaVu Sans'
    print("警告: 日本語フォントが見つかりません。文字化けする可能性があります。")

# フォント設定を実行
setup_japanese_font()
plt.rcParams['axes.unicode_minus'] = False  # マイナス記号の文字化け防止

class FXComparisonAnalyzer:
    def __init__(self):
        """比較分析ツールの初期化"""
        self.yokubari_folder = "entrypoint_fx_よくばり_result"
        self.standard_folder = "entrypoint_fx_result"
        
        # データ保存用
        self.yokubari_data = []
        self.standard_data = []
        self.comparison_results = {}
        
    def load_csv_files(self, folder_path, file_pattern):
        """指定フォルダからCSVファイルを読み込み"""
        csv_files = glob.glob(os.path.join(folder_path, file_pattern))
        all_data = []
        
        print(f"📁 {folder_path} から {len(csv_files)} ファイルを読み込み中...")
        
        for file_path in csv_files:
            try:
                # ファイル名から日付を抽出
                filename = os.path.basename(file_path)
                if "yokubari" in filename:
                    date_str = filename.split('_')[3].split('.')[0]
                else:
                    date_str = filename.split('_')[3].split('.')[0]
                
                # CSVファイル読み込み（複数エンコーディング対応）
                df = None
                encodings = ['utf-8-sig', 'utf-8', 'shift_jis', 'cp932']
                
                for encoding in encodings:
                    try:
                        df = pd.read_csv(file_path, encoding=encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                
                if df is None:
                    print(f"⚠️  {filename}: エンコーディング解決失敗")
                    continue
                
                # カラム名の正規化
                df.columns = [col.strip() for col in df.columns]
                
                # 日付列追加
                df['取引日'] = pd.to_datetime(date_str, format='%Y%m%d')
                df['ファイル名'] = filename
                
                # pips列の数値変換
                if 'pips' in df.columns:
                    df['pips'] = pd.to_numeric(df['pips'], errors='coerce')
                
                all_data.append(df)
                print(f"  ✅ {filename}: {len(df)}行")
                
            except Exception as e:
                print(f"  ❌ {filename}: エラー - {str(e)}")
                continue
        
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            print(f"📊 合計: {len(combined_df)}行のデータを読み込み\n")
            return combined_df
        else:
            print("❌ データの読み込みに失敗しました\n")
            return pd.DataFrame()
    
    def calculate_basic_stats(self, df, name):
        """基本統計の計算"""
        if df.empty:
            return {}
        
        # 勝敗の統計
        win_count = len(df[df['勝敗'] == 'WIN']) if '勝敗' in df.columns else 0
        loss_count = len(df[df['勝敗'] == 'LOSS']) if '勝敗' in df.columns else 0
        total_trades = len(df)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        # pips統計
        total_pips = df['pips'].sum() if 'pips' in df.columns else 0
        avg_pips = df['pips'].mean() if 'pips' in df.columns else 0
        win_pips = df[df['勝敗'] == 'WIN']['pips'].sum() if 'pips' in df.columns and '勝敗' in df.columns else 0
        loss_pips = df[df['勝敗'] == 'LOSS']['pips'].sum() if 'pips' in df.columns and '勝敗' in df.columns else 0
        
        # 日次統計
        daily_stats = df.groupby('取引日').agg({
            'pips': 'sum',
            'No': 'count'
        }).rename(columns={'No': '取引数'})
        
        avg_daily_pips = daily_stats['pips'].mean()
        avg_daily_trades = daily_stats['取引数'].mean()
        
        # 最大ドローダウン計算
        cumulative_pips = daily_stats['pips'].cumsum()
        running_max = cumulative_pips.expanding().max()
        drawdown = running_max - cumulative_pips
        max_drawdown = drawdown.max()
        
        return {
            'name': name,
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_rate,
            'total_pips': total_pips,
            'avg_pips_per_trade': avg_pips,
            'win_pips': win_pips,
            'loss_pips': loss_pips,
            'avg_daily_pips': avg_daily_pips,
            'avg_daily_trades': avg_daily_trades,
            'max_drawdown': max_drawdown,
            'trading_days': len(daily_stats),
            'daily_stats': daily_stats
        }
    
    def create_comparison_charts(self, output_dir):
        """比較チャートの作成"""
        plt.style.use('default')
        
        # 1. 累積pips比較チャート（大きく表示）
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('FX取引結果比較分析', fontsize=18, fontweight='bold')
        
        # 累積pips推移（メインチャート）
        ax1 = axes[0, 0]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_cumsum = self.comparison_results['yokubari']['daily_stats']['pips'].cumsum()
            standard_cumsum = self.comparison_results['standard']['daily_stats']['pips'].cumsum()
            
            ax1.plot(yokubari_cumsum.index, yokubari_cumsum.values, 
                    label='よくばり版', linewidth=3, marker='o', markersize=6, color='#2E8B57')
            ax1.plot(standard_cumsum.index, standard_cumsum.values, 
                    label='標準版', linewidth=3, marker='s', markersize=6, color='#4169E1')
            ax1.set_title('累積Pips推移', fontsize=14, fontweight='bold')
            ax1.set_ylabel('累積Pips', fontsize=12)
            ax1.legend(fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.tick_params(axis='x', rotation=45)
            
            # 最終値を表示
            final_yokubari = yokubari_cumsum.iloc[-1] if not yokubari_cumsum.empty else 0
            final_standard = standard_cumsum.iloc[-1] if not standard_cumsum.empty else 0
            ax1.text(0.02, 0.98, f'よくばり版最終: {final_yokubari:.1f}pips\n標準版最終: {final_standard:.1f}pips', 
                    transform=ax1.transAxes, verticalalignment='top', 
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
        
        # 勝率比較
        ax2 = axes[0, 1]
        win_rates = [
            self.comparison_results['yokubari']['win_rate'],
            self.comparison_results['standard']['win_rate']
        ]
        colors = ['#2E8B57', '#4169E1']
        bars = ax2.bar(['よくばり版', '標準版'], win_rates, color=colors, alpha=0.8, width=0.6)
        ax2.set_title('勝率比較', fontsize=14, fontweight='bold')
        ax2.set_ylabel('勝率 (%)', fontsize=12)
        ax2.set_ylim(0, max(win_rates) * 1.2)
        
        # バーの上に数値表示
        for bar, rate in zip(bars, win_rates):
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(win_rates) * 0.02, 
                    f'{rate:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=11)
        
        # 日次pips分布
        ax3 = axes[1, 0]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_daily = self.comparison_results['yokubari']['daily_stats']['pips']
            standard_daily = self.comparison_results['standard']['daily_stats']['pips']
            
            ax3.hist(yokubari_daily, bins=15, alpha=0.7, label='よくばり版', color='#2E8B57', edgecolor='black')
            ax3.hist(standard_daily, bins=15, alpha=0.7, label='標準版', color='#4169E1', edgecolor='black')
            ax3.set_title('日次Pips分布', fontsize=14, fontweight='bold')
            ax3.set_xlabel('日次Pips', fontsize=12)
            ax3.set_ylabel('日数', fontsize=12)
            ax3.legend(fontsize=12)
            ax3.grid(True, alpha=0.3)
        
        # 月次比較
        ax4 = axes[1, 1]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            # 月次集計
            yokubari_monthly = self.yokubari_data.groupby(
                self.yokubari_data['取引日'].dt.to_period('M'))['pips'].sum()
            standard_monthly = self.standard_data.groupby(
                self.standard_data['取引日'].dt.to_period('M'))['pips'].sum()
            
            months = list(set(yokubari_monthly.index) | set(standard_monthly.index))
            months.sort()
            
            yokubari_values = [yokubari_monthly.get(m, 0) for m in months]
            standard_values = [standard_monthly.get(m, 0) for m in months]
            
            x = np.arange(len(months))
            width = 0.35
            
            bars1 = ax4.bar(x - width/2, yokubari_values, width, label='よくばり版', 
                           color='#2E8B57', alpha=0.8, edgecolor='black')
            bars2 = ax4.bar(x + width/2, standard_values, width, label='標準版', 
                           color='#4169E1', alpha=0.8, edgecolor='black')
            
            ax4.set_title('月次Pips比較', fontsize=14, fontweight='bold')
            ax4.set_ylabel('月次Pips', fontsize=12)
            ax4.set_xticks(x)
            ax4.set_xticklabels([str(m) for m in months], rotation=45)
            ax4.legend(fontsize=12)
            ax4.grid(True, alpha=0.3)
            
            # 値をバーの上に表示
            for bars in [bars1, bars2]:
                for bar in bars:
                    height = bar.get_height()
                    if abs(height) > 0.1:  # 小さすぎる値は表示しない
                        ax4.text(bar.get_x() + bar.get_width()/2., height + (1 if height >= 0 else -3),
                                f'{height:.1f}', ha='center', va='bottom' if height >= 0 else 'top', 
                                fontsize=9)
        
        plt.tight_layout()
        chart_path = os.path.join(output_dir, 'comparison_charts.png')
        plt.savefig(chart_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        return chart_path
    
    def create_cumulative_chart(self, output_dir):
        """累積チャート専用（大きく見やすく）"""
        fig, ax = plt.subplots(1, 1, figsize=(16, 10))
        
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_cumsum = self.comparison_results['yokubari']['daily_stats']['pips'].cumsum()
            standard_cumsum = self.comparison_results['standard']['daily_stats']['pips'].cumsum()
            
            # より見やすいスタイルで描画
            ax.plot(yokubari_cumsum.index, yokubari_cumsum.values, 
                   label='よくばり版', linewidth=4, marker='o', markersize=8, 
                   color='#2E8B57', markerfacecolor='white', markeredgewidth=2)
            ax.plot(standard_cumsum.index, standard_cumsum.values, 
                   label='標準版', linewidth=4, marker='s', markersize=8, 
                   color='#4169E1', markerfacecolor='white', markeredgewidth=2)
            
            ax.set_title('累積Pips推移（詳細）', fontsize=20, fontweight='bold', pad=20)
            ax.set_xlabel('取引日', fontsize=14)
            ax.set_ylabel('累積Pips', fontsize=14)
            ax.legend(fontsize=16, loc='upper left')
            ax.grid(True, alpha=0.3, linestyle='--')
            ax.tick_params(axis='x', rotation=45, labelsize=12)
            ax.tick_params(axis='y', labelsize=12)
            
            # 背景色を設定
            ax.set_facecolor('#f8f9fa')
            
            # 0ラインを強調
            ax.axhline(y=0, color='red', linestyle='-', alpha=0.7, linewidth=2)
            
            # 最終値と差分を表示
            final_yokubari = yokubari_cumsum.iloc[-1] if not yokubari_cumsum.empty else 0
            final_standard = standard_cumsum.iloc[-1] if not standard_cumsum.empty else 0
            diff = final_yokubari - final_standard
            
            info_text = f'''最終累積Pips:
よくばり版: {final_yokubari:.1f} pips
標準版: {final_standard:.1f} pips
差分: {diff:+.1f} pips ({diff/abs(final_standard)*100:+.1f}%)''' if final_standard != 0 else f'''最終累積Pips:
よくばり版: {final_yokubari:.1f} pips
標準版: {final_standard:.1f} pips
差分: {diff:+.1f} pips'''
            
            ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
                   verticalalignment='top', fontsize=12, 
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='gray'))
            
        plt.tight_layout()
        cumulative_path = os.path.join(output_dir, 'cumulative_pips_chart.png')
        plt.savefig(cumulative_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        return cumulative_path
    
    def create_detailed_analysis_chart(self, output_dir):
        """詳細分析チャートの作成"""
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        fig.suptitle('詳細パフォーマンス分析', fontsize=16, fontweight='bold')
        
        # 1. 通貨ペア別パフォーマンス
        ax1 = axes[0, 0]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_by_pair = self.yokubari_data.groupby('通貨ペア')['pips'].sum()
            standard_by_pair = self.standard_data.groupby('通貨ペア')['pips'].sum()
            
            all_pairs = list(set(yokubari_by_pair.index) | set(standard_by_pair.index))
            
            yokubari_values = [yokubari_by_pair.get(pair, 0) for pair in all_pairs]
            standard_values = [standard_by_pair.get(pair, 0) for pair in all_pairs]
            
            x = np.arange(len(all_pairs))
            width = 0.35
            
            ax1.bar(x - width/2, yokubari_values, width, label='よくばり版', alpha=0.7)
            ax1.bar(x + width/2, standard_values, width, label='標準版', alpha=0.7)
            
            ax1.set_title('通貨ペア別パフォーマンス')
            ax1.set_ylabel('合計Pips')
            ax1.set_xticks(x)
            ax1.set_xticklabels(all_pairs, rotation=45)
            ax1.legend()
            ax1.grid(True, alpha=0.3)
        
        # 2. 時間帯別パフォーマンス
        ax2 = axes[0, 1]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            # Entry時間から時間帯を抽出
            self.yokubari_data['時間帯'] = pd.to_datetime(self.yokubari_data['Entry'], format='%H:%M:%S').dt.hour
            self.standard_data['時間帯'] = pd.to_datetime(self.standard_data['Entry'], format='%H:%M:%S').dt.hour
            
            yokubari_by_hour = self.yokubari_data.groupby('時間帯')['pips'].sum()
            standard_by_hour = self.standard_data.groupby('時間帯')['pips'].sum()
            
            all_hours = list(set(yokubari_by_hour.index) | set(standard_by_hour.index))
            all_hours.sort()
            
            yokubari_hourly = [yokubari_by_hour.get(hour, 0) for hour in all_hours]
            standard_hourly = [standard_by_hour.get(hour, 0) for hour in all_hours]
            
            ax2.plot(all_hours, yokubari_hourly, marker='o', label='よくばり版', linewidth=2)
            ax2.plot(all_hours, standard_hourly, marker='s', label='標準版', linewidth=2)
            
            ax2.set_title('時間帯別パフォーマンス')
            ax2.set_xlabel('時間帯')
            ax2.set_ylabel('合計Pips')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
        
        # 3. 取引方向別パフォーマンス
        ax3 = axes[0, 2]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_by_direction = self.yokubari_data.groupby('方向')['pips'].sum()
            standard_by_direction = self.standard_data.groupby('方向')['pips'].sum()
            
            directions = list(set(yokubari_by_direction.index) | set(standard_by_direction.index))
            
            yokubari_dir_values = [yokubari_by_direction.get(direction, 0) for direction in directions]
            standard_dir_values = [standard_by_direction.get(direction, 0) for direction in directions]
            
            x = np.arange(len(directions))
            width = 0.35
            
            ax3.bar(x - width/2, yokubari_dir_values, width, label='よくばり版', alpha=0.7)
            ax3.bar(x + width/2, standard_dir_values, width, label='標準版', alpha=0.7)
            
            ax3.set_title('取引方向別パフォーマンス')
            ax3.set_ylabel('合計Pips')
            ax3.set_xticks(x)
            ax3.set_xticklabels(directions)
            ax3.legend()
            ax3.grid(True, alpha=0.3)
        
        # 4. ドローダウン推移
        ax4 = axes[1, 0]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            yokubari_cumsum = self.comparison_results['yokubari']['daily_stats']['pips'].cumsum()
            standard_cumsum = self.comparison_results['standard']['daily_stats']['pips'].cumsum()
            
            yokubari_running_max = yokubari_cumsum.expanding().max()
            standard_running_max = standard_cumsum.expanding().max()
            
            yokubari_drawdown = yokubari_running_max - yokubari_cumsum
            standard_drawdown = standard_running_max - standard_cumsum
            
            ax4.fill_between(yokubari_drawdown.index, 0, -yokubari_drawdown.values, 
                           alpha=0.6, label='よくばり版', color='red')
            ax4.fill_between(standard_drawdown.index, 0, -standard_drawdown.values, 
                           alpha=0.4, label='標準版', color='orange')
            
            ax4.set_title('ドローダウン推移')
            ax4.set_ylabel('ドローダウン (Pips)')
            ax4.legend()
            ax4.grid(True, alpha=0.3)
            ax4.tick_params(axis='x', rotation=45)
        
        # 5. リスクリターン分析
        ax5 = axes[1, 1]
        if not self.yokubari_data.empty and not self.standard_data.empty:
            methods = ['よくばり版', '標準版']
            returns = [
                self.comparison_results['yokubari']['avg_daily_pips'],
                self.comparison_results['standard']['avg_daily_pips']
            ]
            risks = [
                self.comparison_results['yokubari']['daily_stats']['pips'].std(),
                self.comparison_results['standard']['daily_stats']['pips'].std()
            ]
            
            colors = ['#2E8B57', '#4169E1']
            for i, (method, ret, risk, color) in enumerate(zip(methods, returns, risks, colors)):
                ax5.scatter(risk, ret, s=200, alpha=0.7, color=color, label=method)
                ax5.annotate(method, (risk, ret), xytext=(5, 5), 
                           textcoords='offset points', fontsize=10, fontweight='bold')
            
            ax5.set_title('リスクリターン分析')
            ax5.set_xlabel('リスク (日次Pips標準偏差)')
            ax5.set_ylabel('リターン (平均日次Pips)')
            ax5.grid(True, alpha=0.3)
            ax5.legend()
        
        # 6. 実用スコア分布比較
        ax6 = axes[1, 2]
        if not self.yokubari_data.empty and not self.standard_data.empty and '実用スコア' in self.yokubari_data.columns:
            ax6.hist(self.yokubari_data['実用スコア'], bins=15, alpha=0.6, 
                    label='よくばり版', color='#2E8B57')
            ax6.hist(self.standard_data['実用スコア'], bins=15, alpha=0.6, 
                    label='標準版', color='#4169E1')
            ax6.set_title('実用スコア分布')
            ax6.set_xlabel('実用スコア')
            ax6.set_ylabel('取引数')
            ax6.legend()
            ax6.grid(True, alpha=0.3)
        
        plt.tight_layout()
        detailed_chart_path = os.path.join(output_dir, 'detailed_analysis_charts.png')
        plt.savefig(detailed_chart_path, dpi=300, bbox_inches='tight')
        plt.close()
        
        return detailed_chart_path
    
    def generate_summary_report(self, output_dir):
        """要約レポートの生成"""
        yokubari_stats = self.comparison_results['yokubari']
        standard_stats = self.comparison_results['standard']
        
        # 改善率計算
        pips_improvement = ((yokubari_stats['total_pips'] - standard_stats['total_pips']) / 
                          abs(standard_stats['total_pips']) * 100) if standard_stats['total_pips'] != 0 else 0
        
        winrate_improvement = yokubari_stats['win_rate'] - standard_stats['win_rate']
        
        daily_pips_improvement = ((yokubari_stats['avg_daily_pips'] - standard_stats['avg_daily_pips']) / 
                                abs(standard_stats['avg_daily_pips']) * 100) if standard_stats['avg_daily_pips'] != 0 else 0
        
        # HTMLレポート生成
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>FX取引結果比較分析レポート</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
                h1, h2 {{ color: #2c3e50; }}
                .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
                .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; border-left: 4px solid #3498db; }}
                .yokubari {{ border-left-color: #2E8B57; }}
                .standard {{ border-left-color: #4169E1; }}
                .improvement {{ background: #e8f5e8; border-left-color: #27ae60; }}
                .decline {{ background: #fdf2f2; border-left-color: #e74c3c; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ text-align: left; padding: 12px; border: 1px solid #ddd; }}
                th {{ background-color: #f2f2f2; font-weight: bold; }}
                .positive {{ color: #27ae60; font-weight: bold; }}
                .negative {{ color: #e74c3c; font-weight: bold; }}
                .neutral {{ color: #7f8c8d; }}
                .chart-container {{ text-align: center; margin: 30px 0; }}
                .chart-container img {{ max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 8px; }}
                .highlight {{ background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <h1>🔍 FX取引結果比較分析レポート</h1>
            <p>生成日時: {datetime.now().strftime('%Y年%m月%d日 %H:%M:%S')}</p>
            
            <div class="highlight">
                <h2>📊 総合評価サマリー</h2>
                <p><strong>よくばり版 vs 標準版の比較結果:</strong></p>
                <ul>
                    <li>合計Pips: <span class="{'positive' if pips_improvement > 0 else 'negative'}">{pips_improvement:+.1f}%</span></li>
                    <li>勝率: <span class="{'positive' if winrate_improvement > 0 else 'negative'}">{winrate_improvement:+.1f}%ポイント</span></li>
                    <li>平均日次Pips: <span class="{'positive' if daily_pips_improvement > 0 else 'negative'}">{daily_pips_improvement:+.1f}%</span></li>
                </ul>
            </div>
            
            <div class="summary-grid">
                <div class="stat-card yokubari">
                    <h3>🟢 よくばり版</h3>
                    <p><strong>総取引数:</strong> {yokubari_stats['total_trades']:,}回</p>
                    <p><strong>勝率:</strong> {yokubari_stats['win_rate']:.1f}%</p>
                    <p><strong>合計Pips:</strong> {yokubari_stats['total_pips']:.1f}</p>
                    <p><strong>平均日次Pips:</strong> {yokubari_stats['avg_daily_pips']:.1f}</p>
                    <p><strong>最大ドローダウン:</strong> {yokubari_stats['max_drawdown']:.1f}</p>
                </div>
                
                <div class="stat-card standard">
                    <h3>🔵 標準版</h3>
                    <p><strong>総取引数:</strong> {standard_stats['total_trades']:,}回</p>
                    <p><strong>勝率:</strong> {standard_stats['win_rate']:.1f}%</p>
                    <p><strong>合計Pips:</strong> {standard_stats['total_pips']:.1f}</p>
                    <p><strong>平均日次Pips:</strong> {standard_stats['avg_daily_pips']:.1f}</p>
                    <p><strong>最大ドローダウン:</strong> {standard_stats['max_drawdown']:.1f}</p>
                </div>
            </div>
            
            <h2>📈 詳細比較表</h2>
            <table>
                <tr>
                    <th>項目</th>
                    <th>よくばり版</th>
                    <th>標準版</th>
                    <th>差分</th>
                    <th>改善率</th>
                </tr>
                <tr>
                    <td>総取引数</td>
                    <td>{yokubari_stats['total_trades']:,}</td>
                    <td>{standard_stats['total_trades']:,}</td>
                    <td>{yokubari_stats['total_trades'] - standard_stats['total_trades']:+,}</td>
                    <td class="{'positive' if yokubari_stats['total_trades'] > standard_stats['total_trades'] else 'negative'}">
                        {((yokubari_stats['total_trades'] - standard_stats['total_trades']) / standard_stats['total_trades'] * 100):+.1f}%
                    </td>
                </tr>
                <tr>
                    <td>勝率</td>
                    <td>{yokubari_stats['win_rate']:.1f}%</td>
                    <td>{standard_stats['win_rate']:.1f}%</td>
                    <td class="{'positive' if winrate_improvement > 0 else 'negative'}">{winrate_improvement:+.1f}%ポイント</td>
                    <td class="{'positive' if winrate_improvement > 0 else 'negative'}">{winrate_improvement:+.1f}%ポイント</td>
                </tr>
                <tr>
                    <td>合計Pips</td>
                    <td>{yokubari_stats['total_pips']:.1f}</td>
                    <td>{standard_stats['total_pips']:.1f}</td>
                    <td class="{'positive' if pips_improvement > 0 else 'negative'}">{yokubari_stats['total_pips'] - standard_stats['total_pips']:+.1f}</td>
                    <td class="{'positive' if pips_improvement > 0 else 'negative'}">{pips_improvement:+.1f}%</td>
                </tr>
                <tr>
                    <td>平均日次Pips</td>
                    <td>{yokubari_stats['avg_daily_pips']:.1f}</td>
                    <td>{standard_stats['avg_daily_pips']:.1f}</td>
                    <td class="{'positive' if daily_pips_improvement > 0 else 'negative'}">{yokubari_stats['avg_daily_pips'] - standard_stats['avg_daily_pips']:+.1f}</td>
                    <td class="{'positive' if daily_pips_improvement > 0 else 'negative'}">{daily_pips_improvement:+.1f}%</td>
                </tr>
                <tr>
                    <td>1取引あたり平均Pips</td>
                    <td>{yokubari_stats['avg_pips_per_trade']:.2f}</td>
                    <td>{standard_stats['avg_pips_per_trade']:.2f}</td>
                    <td class="{'positive' if yokubari_stats['avg_pips_per_trade'] > standard_stats['avg_pips_per_trade'] else 'negative'}">
                        {yokubari_stats['avg_pips_per_trade'] - standard_stats['avg_pips_per_trade']:+.2f}
                    </td>
                    <td class="{'positive' if yokubari_stats['avg_pips_per_trade'] > standard_stats['avg_pips_per_trade'] else 'negative'}">
                        {((yokubari_stats['avg_pips_per_trade'] - standard_stats['avg_pips_per_trade']) / abs(standard_stats['avg_pips_per_trade']) * 100) if standard_stats['avg_pips_per_trade'] != 0 else 0:+.1f}%
                    </td>
                </tr>
                <tr>
                    <td>最大ドローダウン</td>
                    <td>{yokubari_stats['max_drawdown']:.1f}</td>
                    <td>{standard_stats['max_drawdown']:.1f}</td>
                    <td class="{'negative' if yokubari_stats['max_drawdown'] > standard_stats['max_drawdown'] else 'positive'}">
                        {yokubari_stats['max_drawdown'] - standard_stats['max_drawdown']:+.1f}
                    </td>
                    <td class="{'negative' if yokubari_stats['max_drawdown'] > standard_stats['max_drawdown'] else 'positive'}">
                        {((yokubari_stats['max_drawdown'] - standard_stats['max_drawdown']) / abs(standard_stats['max_drawdown']) * 100) if standard_stats['max_drawdown'] != 0 else 0:+.1f}%
                    </td>
                </tr>
            </table>
            
            <div class="chart-container">
                <h2>📊 比較チャート</h2>
                <img src="comparison_charts.png" alt="比較チャート">
            </div>
            
            <div class="chart-container">
                <h2>📈 累積Pips推移</h2>
                <img src="cumulative_pips_chart.png" alt="累積Pipsチャート">
            </div>
            
            <div class="chart-container">
                <h2>🔍 詳細分析チャート</h2>
                <img src="detailed_analysis_charts.png" alt="詳細分析チャート">
            </div>
            
            <h2>💡 分析結果と推奨事項</h2>
            <div class="highlight">
                <h3>🎯 主な発見事項</h3>
                <ul>
                    <li><strong>パフォーマンス差:</strong> よくばり版は標準版と比較して合計Pipsで{pips_improvement:+.1f}%の{'改善' if pips_improvement > 0 else '悪化'}を示しています。</li>
                    <li><strong>勝率:</strong> よくばり版の勝率は{yokubari_stats['win_rate']:.1f}%で、標準版の{standard_stats['win_rate']:.1f}%と比較して{winrate_improvement:+.1f}%ポイントの差があります。</li>
                    <li><strong>リスク管理:</strong> 最大ドローダウンは{'よくばり版の方が大きく' if yokubari_stats['max_drawdown'] > standard_stats['max_drawdown'] else 'よくばり版の方が小さく'}、リスク管理の観点では{'注意が必要' if yokubari_stats['max_drawdown'] > standard_stats['max_drawdown'] else '改善されている'}と言えます。</li>
                </ul>
                
                <h3>🚀 推奨事項</h3>
                <ul>
                    <li>{'よくばり版の手法を継続し、さらなる最適化を検討する' if pips_improvement > 10 else '両手法の長所を組み合わせたハイブリッド手法の検討'}</li>
                    <li>リスク管理の観点から、最大ドローダウンの改善策を検討する</li>
                    <li>通貨ペア別・時間帯別のパフォーマンス差を詳細分析し、最適化する</li>
                    <li>定期的な比較分析により、継続的な改善を図る</li>
                </ul>
            </div>
            
            <footer style="margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; color: #7f8c8d;">
                <p>このレポートは自動生成されました。投資判断は自己責任で行ってください。</p>
            </footer>
        </body>
        </html>
        """
        
        report_path = os.path.join(output_dir, 'comparison_summary_report.html')
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return report_path
    
    def save_detailed_csv_reports(self, output_dir):
        """詳細CSVレポートの保存"""
        # 1. 統合データ保存
        combined_data = []
        
        if not self.yokubari_data.empty:
            yokubari_copy = self.yokubari_data.copy()
            yokubari_copy['手法'] = 'よくばり版'
            combined_data.append(yokubari_copy)
        
        if not self.standard_data.empty:
            standard_copy = self.standard_data.copy()
            standard_copy['手法'] = '標準版'
            combined_data.append(standard_copy)
        
        if combined_data:
            combined_df = pd.concat(combined_data, ignore_index=True)
            combined_path = os.path.join(output_dir, 'combined_trading_data.csv')
            combined_df.to_csv(combined_path, index=False, encoding='utf-8-sig')
        
        # 2. 日次サマリー
        daily_summary = []
        for method, data in [('よくばり版', self.yokubari_data), ('標準版', self.standard_data)]:
            if not data.empty:
                daily_stats = data.groupby('取引日').agg({
                    'pips': ['sum', 'mean', 'count'],
                    '勝敗': lambda x: (x == 'WIN').sum()
                }).round(2)
                
                daily_stats.columns = ['合計Pips', '平均Pips', '取引数', '勝ち数']
                daily_stats['手法'] = method
                daily_stats['勝率'] = (daily_stats['勝ち数'] / daily_stats['取引数'] * 100).round(1)
                daily_stats = daily_stats.reset_index()
                daily_summary.append(daily_stats)
        
        if daily_summary:
            daily_df = pd.concat(daily_summary, ignore_index=True)
            daily_path = os.path.join(output_dir, 'daily_summary.csv')
            daily_df.to_csv(daily_path, index=False, encoding='utf-8-sig')
        
        # 3. 通貨ペア別サマリー
        pair_summary = []
        for method, data in [('よくばり版', self.yokubari_data), ('標準版', self.standard_data)]:
            if not data.empty:
                pair_stats = data.groupby('通貨ペア').agg({
                    'pips': ['sum', 'mean', 'count'],
                    '勝敗': lambda x: (x == 'WIN').sum()
                }).round(2)
                
                pair_stats.columns = ['合計Pips', '平均Pips', '取引数', '勝ち数']
                pair_stats['手法'] = method
                pair_stats['勝率'] = (pair_stats['勝ち数'] / pair_stats['取引数'] * 100).round(1)
                pair_stats = pair_stats.reset_index()
                pair_summary.append(pair_stats)
        
        if pair_summary:
            pair_df = pd.concat(pair_summary, ignore_index=True)
            pair_path = os.path.join(output_dir, 'currency_pair_summary.csv')
            pair_df.to_csv(pair_path, index=False, encoding='utf-8-sig')
        
        # 4. 統計サマリー
        stats_summary = pd.DataFrame([
            self.comparison_results['yokubari'],
            self.comparison_results['standard']
        ])
        stats_path = os.path.join(output_dir, 'statistics_summary.csv')
        stats_summary.to_csv(stats_path, index=False, encoding='utf-8-sig')
        
        return {
            'combined': combined_path if combined_data else None,
            'daily': daily_path if daily_summary else None,
            'currency_pair': pair_path if pair_summary else None,
            'statistics': stats_path
        }
    
    def create_json_summary(self, output_dir):
        """JSON形式のサマリー作成"""
        summary_data = {
            'generated_at': datetime.now().isoformat(),
            'analysis_period': {
                'yokubari': {
                    'start_date': self.yokubari_data['取引日'].min().strftime('%Y-%m-%d') if not self.yokubari_data.empty else None,
                    'end_date': self.yokubari_data['取引日'].max().strftime('%Y-%m-%d') if not self.yokubari_data.empty else None,
                    'trading_days': self.comparison_results['yokubari']['trading_days']
                },
                'standard': {
                    'start_date': self.standard_data['取引日'].min().strftime('%Y-%m-%d') if not self.standard_data.empty else None,
                    'end_date': self.standard_data['取引日'].max().strftime('%Y-%m-%d') if not self.standard_data.empty else None,
                    'trading_days': self.comparison_results['standard']['trading_days']
                }
            },
            'comparison_results': {
                'yokubari': {k: float(v) if isinstance(v, (int, float, np.number)) else v 
                           for k, v in self.comparison_results['yokubari'].items() 
                           if k != 'daily_stats'},
                'standard': {k: float(v) if isinstance(v, (int, float, np.number)) else v 
                           for k, v in self.comparison_results['standard'].items() 
                           if k != 'daily_stats'}
            },
            'performance_improvements': {
                'total_pips_improvement_pct': ((self.comparison_results['yokubari']['total_pips'] - 
                                              self.comparison_results['standard']['total_pips']) / 
                                             abs(self.comparison_results['standard']['total_pips']) * 100) 
                                             if self.comparison_results['standard']['total_pips'] != 0 else 0,
                'win_rate_improvement_points': (self.comparison_results['yokubari']['win_rate'] - 
                                              self.comparison_results['standard']['win_rate']),
                'daily_pips_improvement_pct': ((self.comparison_results['yokubari']['avg_daily_pips'] - 
                                              self.comparison_results['standard']['avg_daily_pips']) / 
                                             abs(self.comparison_results['standard']['avg_daily_pips']) * 100) 
                                             if self.comparison_results['standard']['avg_daily_pips'] != 0 else 0
            }
        }
        
        json_path = os.path.join(output_dir, 'analysis_summary.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, ensure_ascii=False, indent=2)
        
        return json_path
    
    def run_analysis(self):
        """分析実行"""
        print("🚀 FX結果比較分析を開始します...\n")
        
        # データ読み込み
        self.yokubari_data = self.load_csv_files(self.yokubari_folder, "fx_results_yokubari_*.csv")
        self.standard_data = self.load_csv_files(self.standard_folder, "fx_results_standard_*.csv")
        
        if self.yokubari_data.empty and self.standard_data.empty:
            print("❌ 分析対象のデータが見つかりませんでした。")
            return False
        
        # 基本統計計算
        print("📊 基本統計を計算中...")
        self.comparison_results['yokubari'] = self.calculate_basic_stats(self.yokubari_data, 'よくばり版')
        self.comparison_results['standard'] = self.calculate_basic_stats(self.standard_data, '標準版')
        
        # 出力ディレクトリ作成
        for folder in [self.yokubari_folder, self.standard_folder]:
            output_dir = os.path.join(folder, 'total')
            os.makedirs(output_dir, exist_ok=True)
            
            print(f"\n📁 {folder}/total にレポートを生成中...")
            
            # チャート作成
            print("  📈 比較チャートを作成中...")
            self.create_comparison_charts(output_dir)
            
            print("  📊 累積チャートを作成中...")
            self.create_cumulative_chart(output_dir)
            
            print("  🔍 詳細分析チャートを作成中...")
            self.create_detailed_analysis_chart(output_dir)
            
            # レポート生成
            print("  📝 HTMLレポートを生成中...")
            self.generate_summary_report(output_dir)
            
            # CSVレポート保存
            print("  💾 詳細CSVレポートを保存中...")
            self.save_detailed_csv_reports(output_dir)
            
            # JSON要約作成
            print("  📋 JSON要約を作成中...")
            self.create_json_summary(output_dir)
            
            print(f"  ✅ {folder}/total に分析結果を保存しました")
        
        # 結果要約表示
        print("\n" + "="*60)
        print("📊 分析結果要約")
        print("="*60)
        
        for method, stats in self.comparison_results.items():
            print(f"\n🔹 {stats['name']}")
            print(f"   総取引数: {stats['total_trades']:,}回")
            print(f"   勝率: {stats['win_rate']:.1f}%")
            print(f"   合計Pips: {stats['total_pips']:.1f}")
            print(f"   平均日次Pips: {stats['avg_daily_pips']:.1f}")
            print(f"   最大ドローダウン: {stats['max_drawdown']:.1f}")
        
        # 改善率表示
        if self.comparison_results['yokubari'] and self.comparison_results['standard']:
            pips_improvement = ((self.comparison_results['yokubari']['total_pips'] - 
                               self.comparison_results['standard']['total_pips']) / 
                              abs(self.comparison_results['standard']['total_pips']) * 100) \
                              if self.comparison_results['standard']['total_pips'] != 0 else 0
            
            winrate_improvement = (self.comparison_results['yokubari']['win_rate'] - 
                                 self.comparison_results['standard']['win_rate'])
            
            print(f"\n🎯 よくばり版の改善状況:")
            print(f"   合計Pips: {pips_improvement:+.1f}%")
            print(f"   勝率: {winrate_improvement:+.1f}%ポイント")
        
        print(f"\n✅ 分析完了！レポートは以下フォルダに保存されました:")
        print(f"   - {self.yokubari_folder}/total/")
        print(f"   - {self.standard_folder}/total/")
        
        return True

def main():
    """メイン実行関数"""
    try:
        analyzer = FXComparisonAnalyzer()
        analyzer.run_analysis()
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()