# fx_analysis_step3.py (特定FX業者営業日対応版)
"""
抽出要件 (Step‑3) - 特定FX業者営業日対応版
=================
FXTF、サクソバンク、GMOコインの営業日ルールに基づいた判定
"""

from __future__ import annotations

import re
import requests
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import calendar

import pandas as pd

# ------------------------- 設定 ------------------------- #
BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "output_fx"
OUTPUT_DIR = BASE_DIR / "entrypoint_fx"
CACHE_DIR = BASE_DIR / "trading_day_cache"  # キャッシュ専用フォルダ
OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)  # キャッシュフォルダを作成

FILE_PATTERN = re.compile(r"analyzed_high_scores_(\d{8})_\d+\.csv")

# FX業者別営業日ルール
FX_BROKER_RULES = {
    'FXTF': {
        'name': 'ゴールデンウェイ・ジャパン（FXTF）',
        'weekend_closed': True,  # 土日休業
        'new_year_holiday': True,  # 元旦休業
        'christmas_closed': True,  # クリスマス休業（短縮取引）
        'japanese_holidays_trading': True,  # 日本祝日でも取引可能
        'us_holidays_affected': True,  # 米国祝日で流動性低下
        'trading_hours': {
            'standard': '月曜07:00-土曜07:00',
            'summer': '月曜07:00-土曜06:00'
        }
    },
    'saxo_bank': {
        'name': 'サクソバンク証券',
        'weekend_closed': True,  # 土日休業
        'new_year_holiday': True,  # 元旦休業
        'christmas_closed': True,  # クリスマス休業
        'japanese_holidays_trading': True,  # 日本祝日でも取引可能
        'us_holidays_affected': True,  # 米国祝日で流動性低下
        'early_trading_start': True,  # 月曜早朝取引開始
        'trading_hours': {
            'standard': '月曜04:00-土曜06:59',  # オーストラリア標準時間・米国夏時間
            'summer': '月曜03:00-土曜05:59'     # オーストラリア夏時間・米国夏時間
        }
    },
    'gmo_coin': {
        'name': 'GMOコイン（FX）',
        'weekend_closed': True,  # 土日休業
        'new_year_holiday': True,  # 元旦休業
        'christmas_closed': True,  # クリスマス休業
        'japanese_holidays_trading': True,  # 日本祝日でも取引可能
        'us_holidays_affected': True,  # 米国祝日で流動性低下
        'no_summer_time_change': True,  # サマータイム変更なし
        'trading_hours': {
            'all_year': '月曜07:00-土曜05:59'  # 年間固定
        }
    }
}

# 使用する業者（設定で変更可能）
SELECTED_BROKER = 'gmo_coin'  # 'FXTF', 'saxo_bank', 'gmo_coin'から選択

# ------------------- FX業者営業日判定機能 -------------------- #

class FXBrokerTradingDayChecker:
    """特定FX業者の営業日判定クラス"""
    
    def __init__(self, broker_key: str = SELECTED_BROKER):
        self.broker_key = broker_key
        self.broker_rules = FX_BROKER_RULES.get(broker_key, FX_BROKER_RULES['gmo_coin'])
        self.cache = {}  # 結果をキャッシュ
        self.cache_file = CACHE_DIR / f'trading_day_cache_{broker_key}.json'
        self.load_cache()
    
    def load_cache(self):
        """キャッシュを読み込み"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    self.cache = json.load(f)
        except Exception as e:
            print(f"キャッシュ読み込みエラー: {e}")
            self.cache = {}
    
    def save_cache(self):
        """キャッシュを保存"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"キャッシュ保存エラー: {e}")
    
    def is_trading_day(self, date: datetime) -> bool:
        """
        FX業者の営業日判定
        
        Parameters:
        -----------
        date : datetime
            判定する日付
        
        Returns:
        --------
        bool
            取引日の場合True
        """
        date_str = date.strftime('%Y-%m-%d')
        
        # キャッシュを確認
        if date_str in self.cache:
            print(f"キャッシュから取得 ({self.broker_rules['name']}): {date_str} = {self.cache[date_str]}")
            return self.cache[date_str]
        
        # 営業日判定
        result = self._check_trading_day(date)
        
        # キャッシュに保存
        self.cache[date_str] = result
        self.save_cache()
        
        return result
    
    def _check_trading_day(self, date: datetime) -> bool:
        """FX業者固有の営業日判定ロジック"""
        
        # 1. 土日チェック（FXの基本ルール）
        if self.broker_rules.get('weekend_closed', True) and date.weekday() >= 5:
            print(f"{self.broker_rules['name']}: 土日のため休業")
            return False
        
        # 2. 元旦チェック（世界共通の休業日）
        if self.broker_rules.get('new_year_holiday', True) and date.month == 1 and date.day == 1:
            print(f"{self.broker_rules['name']}: 元旦のため休業")
            return False
        
        # 3. クリスマスチェック（西欧系の休業日）
        if self.broker_rules.get('christmas_closed', True) and date.month == 12 and date.day == 25:
            print(f"{self.broker_rules['name']}: クリスマスのため休業")
            return False
        
        # 4. 年末年始特別期間チェック（流動性激減）
        if self._is_year_end_special_period(date):
            print(f"{self.broker_rules['name']}: 年末年始特別期間のため流動性低下")
            return self._year_end_trading_decision(date)
        
        # 5. 米国祝日チェック（流動性への影響のみ）
        if self._is_us_major_holiday(date):
            if self.broker_rules.get('us_holidays_affected', True):
                print(f"{self.broker_rules['name']}: 米国祝日のため流動性低下、取引は可能だが注意")
                return self._us_holiday_trading_decision(date)
            else:
                return True
        
        # 6. その他の特別条件チェック
        if self._has_special_market_conditions(date):
            print(f"{self.broker_rules['name']}: 特別な市場条件あり")
            return False
        
        # 上記に該当しない場合は営業日（日本の祝日含む）
        print(f"{self.broker_rules['name']}: 通常営業日")
        return True
    
    def _is_year_end_special_period(self, date: datetime) -> bool:
        """年末年始の特別期間判定"""
        # 12月29日-1月3日を特別期間とする
        if date.month == 12 and date.day >= 29:
            return True
        if date.month == 1 and date.day <= 3:
            return True
        return False
    
    def _year_end_trading_decision(self, date: datetime) -> bool:
        """年末年始期間の取引判定"""
        # 12月31日と1月1日は完全休業
        if (date.month == 12 and date.day == 31) or (date.month == 1 and date.day == 1):
            return False
        
        # その他の年末年始期間は流動性低下を考慮
        # 保守的に休業日として扱う
        return False
    
    def _is_japanese_holiday(self, date: datetime) -> bool:
        """日本の祝日判定（FXでは元旦以外全て取引可能）"""
        # FXは日本の祝日でも取引可能
        # 東京市場が休場でも海外市場（ロンドン・NY）は稼働
        # 元旦のみ世界的な休業のため別途チェック済み
        
        # この関数は基本的にFalseを返す（祝日でも取引可能）
        return False
    

    
    def _is_us_major_holiday(self, date: datetime) -> bool:
        """米国の主要祝日判定"""
        month = date.month
        day = date.day
        
        # 固定祝日
        us_fixed_holidays = [
            (1, 1),   # New Year's Day
            (7, 4),   # Independence Day
            (12, 25), # Christmas Day
        ]
        
        if (month, day) in us_fixed_holidays:
            return True
        
        # 移動祝日（簡易版）
        # Thanksgiving（11月第4木曜日）
        if month == 11 and self._is_nth_weekday(date, 4, 4):  # 木曜日=4
            return True
        
        # Memorial Day（5月最終月曜日）
        if month == 5 and self._is_last_weekday(date, 1):  # 月曜日=1
            return True
        
        # Labor Day（9月第1月曜日）
        if month == 9 and self._is_nth_weekday(date, 1, 1):
            return True
        
        return False
    
    def _is_last_weekday(self, date: datetime, weekday: int) -> bool:
        """指定月の最終指定曜日かどうか判定"""
        # 月の最終日
        last_day = date.replace(day=calendar.monthrange(date.year, date.month)[1])
        
        # 最終指定曜日を見つける
        days_back = (last_day.weekday() - weekday) % 7
        target_date = last_day - timedelta(days=days_back)
        
        return target_date.date() == date.date()
    
    def _us_holiday_trading_decision(self, date: datetime) -> bool:
        """米国祝日時の取引判定"""
        # 米国の主要祝日は流動性が低下するが、取引は可能
        # 保守的にエントリーポイント生成を控える場合はFalseを返す
        
        # 特に影響の大きい祝日
        major_impact_holidays = [
            (7, 4),   # Independence Day
            (12, 25), # Christmas Day
        ]
        
        if (date.month, date.day) in major_impact_holidays:
            return False  # 大きな影響がある祝日は避ける
        
        # その他の米国祝日は取引可能だが注意
        return True
    
    def _has_special_market_conditions(self, date: datetime) -> bool:
        """特別な市場条件の確認"""
        # 将来的にAPIで経済指標発表日や特別イベントをチェック
        # 現在は固定ルールのみ
        
        # 例：米雇用統計発表日（毎月第1金曜日）などは避ける場合
        # if date.weekday() == 4 and self._is_first_friday_of_month(date):
        #     return True
        
        return False

def should_create_entrypoint_file(broker_key: str = SELECTED_BROKER) -> bool:
    """
    指定FX業者の営業日に基づいてファイル作成判定
    
    Parameters:
    -----------
    broker_key : str
        FX業者キー ('FXTF', 'saxo_bank', 'gmo_coin')
    
    Returns:
    --------
    bool
        ファイル作成すべき場合True
    """
    today = datetime.today()
    checker = FXBrokerTradingDayChecker(broker_key)
    
    if not checker.is_trading_day(today):
        print(f"今日（{today.strftime('%Y-%m-%d')}）は{checker.broker_rules['name']}の休業日のため、エントリーポイントファイルを作成しません。")
        return False
    
    print(f"今日（{today.strftime('%Y-%m-%d')}）は{checker.broker_rules['name']}の取引日です。エントリーポイントファイルを作成します。")
    return True

# --------------------- ユーティリティ ------------------- #

def latest_csv(dir_path: Path) -> Path:
    """output_fx で最新日付の CSV を取得"""
    files: List[Tuple[datetime, Path]] = []
    for fp in dir_path.glob("analyzed_high_scores_*.csv"):
        m = FILE_PATTERN.match(fp.name)
        if m:
            try:
                files.append((datetime.strptime(m.group(1), "%Y%m%d"), fp))
            except ValueError:
                continue
    if not files:
        raise FileNotFoundError("analyzed_high_scores_*.csv が見つかりません")
    return max(files, key=lambda t: t[0])[1]

def has_consecutive(nums: List[int]) -> bool:
    s = sorted(set(nums))
    return any(s[i] == s[i - 1] + 1 for i in range(1, len(s)))

# -------------------- クラスター抽出 --------------------- #

def detect_clusters(df: pd.DataFrame) -> List[Dict]:
    df = df.copy()
    df["minute_idx"] = (
        pd.to_datetime(df["時間"], format="%H:%M:%S").dt.hour * 60
        + pd.to_datetime(df["時間"], format="%H:%M:%S").dt.minute
    )

    minute_rows = []
    for (t, pair, d), g in df.groupby(["時間", "通貨ペア", "方向"]):
        if len(g) < 2 or not has_consecutive(g["保有期間"]):
            continue
        minute_rows.append({
            "時間": t, "通貨ペア": pair, "方向": d,
            "minute_idx": g["minute_idx"].iloc[0], "rows": len(g)
        })

    if not minute_rows:
        return []

    mdf = pd.DataFrame(minute_rows).sort_values(["通貨ペア", "方向", "minute_idx"], ignore_index=True)

    clusters: List[List[dict]] = []
    block: List[dict] = [mdf.iloc[0].to_dict()]
    for _, row in mdf.iloc[1:].iterrows():
        prev = block[-1]
        if row["通貨ペア"] == prev["通貨ペア"] and row["方向"] == prev["方向"] and row["minute_idx"] == prev["minute_idx"] + 1:
            block.append(row.to_dict())
        else:
            if len(block) > 1:
                clusters.append(block)
            block = [row.to_dict()]
    if len(block) > 1:
        clusters.append(block)

    results = []
    for cl in clusters:
        pair, direct = cl[0]["通貨ペア"], cl[0]["方向"]
        tot_rows, best_score, best_row = 0, -float("inf"), None
        for rec in cl:
            sub = df[(df["時間"] == rec["時間"]) & (df["通貨ペア"] == pair) & (df["方向"] == direct)]
            tot_rows += len(sub)
            top = sub.loc[sub["実用スコア"].idxmax()]
            if top["実用スコア"] > best_score:
                best_score, best_row = top["実用スコア"], top
        results.append({"rows": tot_rows, "best": best_row})
    return results

# -------------- 重複排除 ------------------------------- #

def overlap(a: pd.Series, b: pd.Series) -> bool:
    s1 = datetime.strptime(a["時間"], "%H:%M:%S")
    e1 = s1 + timedelta(minutes=int(a["保有期間"]))
    s2 = datetime.strptime(b["時間"], "%H:%M:%S")
    e2 = s2 + timedelta(minutes=int(b["保有期間"]))
    return not (e1 <= s2 or e2 <= s1)

def resolve_overlaps(clusters: List[Dict]) -> List[pd.Series]:
    chosen: List[pd.Series] = []
    clusters = sorted(clusters, key=lambda x: (-x["rows"], -x["best"]["実用スコア"]))
    for cl in clusters:
        cand = cl["best"]
        if all(not overlap(cand, c) for c in chosen):
            chosen.append(cand)
    return chosen

# --------------------- MAIN ----------------------------- #

def main() -> None:
    # FX業者別営業日判定
    print(f"使用FX業者: {FX_BROKER_RULES[SELECTED_BROKER]['name']}")
    
    if not should_create_entrypoint_file(SELECTED_BROKER):
        return
    
    try:
        df = pd.read_csv(latest_csv(INPUT_DIR))
    except FileNotFoundError as e:
        print(f"エラー: {e}")
        return
    except Exception as e:
        print(f"ファイル読み込みエラー: {e}")
        return

    points = resolve_overlaps(detect_clusters(df))
    if not points:
        print("抽出ポイントなし")
        return

    cols = [
        "時間", "通貨ペア", "方向", "保有期間",
        "実用スコア", "総合スコア", "短期勝率", "中期勝率", "長期勝率"
    ]
    out = pd.DataFrame(points)[cols]

    # Exit 計算
    out.insert(
        1,
        "Exit",
        (
            pd.to_datetime(out["時間"], format="%H:%M:%S")
            + pd.to_timedelta(out["保有期間"], unit="m")
        ).dt.strftime("%H:%M:%S")
    )

    # 方向変換と列整形
    out = out.rename(columns={"時間": "Entry"})
    out["方向"] = out["方向"].map({"HIGH": "Long", "LOW": "Short"})

    # Entry 昇順でソートして連番振り直し
    out = out.sort_values("Entry").reset_index(drop=True)
    out.insert(0, "No", range(1, len(out) + 1))

    out = out[[
        "No", "通貨ペア", "Entry", "Exit", "方向",
        "実用スコア", "総合スコア", "短期勝率", "中期勝率", "長期勝率"
    ]]

    fname = OUTPUT_DIR / f"entrypoints_{datetime.today():%Y%m%d}.csv"
    out.to_csv(fname, index=False, encoding="utf-8-sig")
    print(f"{len(out)} 行を書き出しました → {fname}")
    print(f"使用した営業日ルール: {FX_BROKER_RULES[SELECTED_BROKER]['name']}")


if __name__ == "__main__":
    main()