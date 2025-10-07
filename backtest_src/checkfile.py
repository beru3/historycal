#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_entrypoint_files.py - エントリーポイントファイル構造確認スクリプト
"""

import pandas as pd
from pathlib import Path

# エントリーポイントディレクトリ
ENTRYPOINT_DIR = Path(__file__).parent.parent / "entrypoint_fx"

def check_file_structure():
    """ファイル構造を確認"""
    csv_files = list(ENTRYPOINT_DIR.glob("*.csv"))
    
    if not csv_files:
        print(f"❌ CSVファイルが見つかりません: {ENTRYPOINT_DIR}")
        return
    
    print(f"📂 CSVファイル数: {len(csv_files)}")
    
    # 最初の3ファイルの構造を確認
    for i, file_path in enumerate(csv_files[:3]):
        print(f"\n{'='*60}")
        print(f"📄 ファイル {i+1}: {file_path.name}")
        print('='*60)
        
        try:
            # ファイルを読み込み
            df = pd.read_csv(file_path)
            
            print(f"📊 行数: {len(df)}")
            print(f"📋 カラム数: {len(df.columns)}")
            print(f"📝 カラム名: {list(df.columns)}")
            
            # 最初の数行を表示
            print(f"\n📈 データサンプル:")
            print(df.head(3).to_string())
            
            # データ型確認
            print(f"\n🔢 データ型:")
            print(df.dtypes.to_string())
            
        except Exception as e:
            print(f"❌ ファイル読み込みエラー: {e}")

if __name__ == "__main__":
    check_file_structure()