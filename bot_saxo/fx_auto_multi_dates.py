#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FX自動エントリー・イグジット監視スクリプト（複数日付対応版）
- フォルダ内のCSVファイルからエントリー・イグジットの時間を読み込む
- 過去日付のエントリーポイントは過去レートを取得
- 今日のエントリーポイントは指定時間にリアルタイムレートを取得
- エントリーとイグジットのレートを記録し、pips差を計算
- 結果をCSVファイルに保存
"""

import os
import sys
import csv
import time
import json
import logging
import argparse
import pandas as pd
import requests
import threading
import schedule
import re
from datetime import datetime, timedelta, date
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("fx_auto_trade.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("FXAutoTrade")

# ディレクトリパス設定
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "entrypoint_fx")
RESULTS_DIR = os.path.join(DATA_DIR, "results")

# 結果保存用ディレクトリの作成
if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

# Saxo Bank API設定 (LIVE環境)
CLIENT_ID = "67a87ac462994c4b805a0811aa966a50"
CLIENT_SECRET = "950d065d7a3145c5800abd730ff43eaf"
AUTH_URL = "https://live.logonvalidation.net/authorize"
TOKEN_URL = "https://live.logonvalidation.net/token"
GATEWAY_URL = "https://gateway.saxobank.com/openapi"
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token_live.json")

# 既知のUIC（必要な通貨ペア）
KNOWN_UICS = {
    "USDJPY": 42,  # 米ドル/円
    "EURJPY": 18,  # ユーロ/円
    "EURUSD": 21,  # ユーロ/米ドル
    "GBPJPY": 26,  # 英ポンド/円
    "AUDJPY": 2,   # 豪ドル/円
    "CHFJPY": 8,   # スイスフラン/円
    "CADJPY": 6,   # カナダドル/円
}

# グローバル変数
auth_code = None
global_access_token = None
entry_exit_data = {}  # エントリー・イグジット情報の保存用
results_data = []     # 結果データの保存用
trading_complete = False  # 全ての取引が完了したかのフラグ
historical_files_processed = 0  # 処理済み過去ファイル数
future_files_to_process = 0    # スケジュール予定の未来ファイル数

# コールバックハンドラ
class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        qs = parse_qs(parsed.query)
        if "code" in qs:
            auth_code = qs["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>Authorization code を取得しました。ターミナルに戻ってください。</h2>"
                .encode("utf-8")
            )
            threading.Thread(target=self.server.shutdown).start()
        else:
            self.send_error(400, "No code in query")
    
    # ログ出力を抑制
    def log_message(self, format, *args):
        return

def start_local_server():
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    logger.info(">> ローカルサーバー起動中: http://localhost:8080/callback で code を待機…")
    server.serve_forever()
    server.server_close()

def save_tokens(tokens: dict):
    logger.info(f">> トークンを保存しています: {TOKEN_FILE}")
    # リフレッシュトークン作成日時を記録（期限管理用）
    if "refresh_token_created_at" not in tokens:
        tokens["refresh_token_created_at"] = time.time()
    
    # 人間が読める形式の日付を追加
    expires_at = datetime.fromtimestamp(tokens.get("expires_at", 0))
    tokens["expires_at_human"] = expires_at.strftime('%Y-%m-%d %H:%M:%S')
    
    if "refresh_token_created_at" in tokens:
        refresh_created = datetime.fromtimestamp(tokens["refresh_token_created_at"])
        refresh_expires = refresh_created + timedelta(days=90)
        tokens["refresh_token_created_at_human"] = refresh_created.strftime('%Y-%m-%d')
        tokens["refresh_token_expires_at_human"] = refresh_expires.strftime('%Y-%m-%d')
        tokens["refresh_token_days_left"] = (refresh_expires - datetime.now()).days
    
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    logger.info(f">> トークンを保存しました")
    
    # 有効期限を表示
    expires_at = datetime.fromtimestamp(tokens.get("expires_at", 0))
    logger.info(f">> トークン有効期限：{expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

def load_tokens() -> dict:
    logger.info(f">> トークンファイルを確認中: {TOKEN_FILE}")
    if not os.path.exists(TOKEN_FILE):
        logger.info(f">> トークンファイルが見つかりません: {TOKEN_FILE}")
        return {}
        
    try:
        with open(TOKEN_FILE, "r") as f:
            tokens = json.load(f)
        # 有効期限を確認して表示
        expires_at = datetime.fromtimestamp(tokens.get("expires_at", 0))
        logger.info(f">> 保存済トークン有効期限：{expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return tokens
    except Exception as e:
        logger.error(f">> トークンファイル読み込みエラー: {e}")
        return {}

def is_valid(tokens: dict) -> bool:
    return tokens.get("expires_at", 0) > time.time() + 30

def fetch_new_token_by_code(code: str) -> dict:
    data = {
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
        "client_id":    CLIENT_ID
    }
    logger.info(">> 認証コードからトークンを取得中...")
    resp = requests.post(TOKEN_URL, data=data, auth=(CLIENT_ID, CLIENT_SECRET))
    resp.raise_for_status()
    tok = resp.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 0)
    # リフレッシュトークン作成日時を記録
    tok["refresh_token_created_at"] = time.time()
    return tok

def refresh_token(tokens: dict) -> dict:
    data = {
        "grant_type":    "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id":     CLIENT_ID
    }
    logger.info(">> リフレッシュトークンでアクセストークンを更新中...")
    resp = requests.post(TOKEN_URL, data=data, auth=(CLIENT_ID, CLIENT_SECRET))
    resp.raise_for_status()
    tok = resp.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 0)
    
    # 重要: リフレッシュトークン作成日時は引き継ぐ
    if "refresh_token_created_at" in tokens:
        tok["refresh_token_created_at"] = tokens["refresh_token_created_at"]
    else:
        # なければ新規作成（正確性は低下）
        tok["refresh_token_created_at"] = tokens.get("expires_at", time.time()) - tok.get("expires_in", 0)
    
    return tok

def ensure_access_token() -> str:
    """有効なアクセストークンを取得（必要に応じて更新または新規取得）"""
    global global_access_token
    
    # 既に有効なトークンがある場合は再利用
    if global_access_token:
        return global_access_token
    
    toks = load_tokens()
    if toks and is_valid(toks):
        logger.info(">> 有効なトークンが見つかりました")
        global_access_token = toks["access_token"]
        return global_access_token
    
    if toks.get("refresh_token"):
        try:
            logger.info(">> リフレッシュトークンを使用して更新します")
            toks = refresh_token(toks)
            save_tokens(toks)
            global_access_token = toks["access_token"]
            return global_access_token
        except Exception as e:
            logger.error(f">> リフレッシュトークンエラー: {e}")
            logger.info(">> 新規認証を開始します")
    
    logger.info(">> 初回認証が必要です：ブラウザでログイン＆承認してください。")
    
    params = {
        "response_type": "code",
        "client_id":     CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "scope":         "trading openapi"
    }
    url = AUTH_URL + "?" + "&".join(f"{k}={requests.utils.requote_uri(v)}" for k,v in params.items())
    logger.info(f">> 認証URL: {url}")
    
    threading.Thread(target=start_local_server, daemon=True).start()
    webbrowser.open(url)
    
    timeout = time.time() + 300  # 5分のタイムアウト
    while auth_code is None and time.time() < timeout:
        time.sleep(0.1)
    
    if auth_code is None:
        raise TimeoutError("認証タイムアウト：5分以内に認証を完了してください")
    
    toks = fetch_new_token_by_code(auth_code)
    save_tokens(toks)
    global_access_token = toks["access_token"]
    return global_access_token

def get_snapshot(uic: int) -> dict:
    """価格スナップショット取得"""
    # トークンが有効かを確認し、必要なら更新
    access_token = ensure_access_token()
    
    url = f"{GATEWAY_URL}/trade/v1/infoprices"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "AssetType":   "FxSpot",
        "Uic":         uic,
        "FieldGroups": "DisplayAndFormat,PriceInfo"
    }
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        # レスポンスからレート情報を抽出
        if "Data" in data and len(data["Data"]) > 0:
            item = data["Data"][0]
            return {
                "bid": item.get("Quote", {}).get("Bid"),
                "ask": item.get("Quote", {}).get("Ask"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        else:
            return {
                "bid": data.get("Quote", {}).get("Bid"),
                "ask": data.get("Quote", {}).get("Ask"),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
    except Exception as e:
        logger.error(f"スナップショット取得エラー: {e}")
        return None

def get_historical_price(currency_pair, timestamp_iso, uic=None):
    """Chart APIを使用して過去の特定時間のレートを取得する（改良版）"""
    access_token = ensure_access_token()
    
    if not uic and currency_pair in KNOWN_UICS:
        uic = KNOWN_UICS[currency_pair]
    
    if not uic:
        logger.error(f"未知の通貨ペア: {currency_pair}")
        return None
    
    try:
        # タイムスタンプからDatetime型に変換
        dt = datetime.strptime(timestamp_iso, "%Y-%m-%dT%H:%M:%SZ")
        
        # 現在時刻との差を計算（日数）
        days_diff = (datetime.now() - dt).days
        
        logger.info(f"Chart API呼び出し: {currency_pair} (UIC: {uic}), 時刻: {timestamp_iso} ({days_diff}日前)")
        
        # Chart API URL構築
        chart_url = f"{GATEWAY_URL}/chart/v1/charts"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # 複数の時間軸で試行する（1分、5分、60分）
        horizons_to_try = [1, 5, 60]  # 1分、5分、1時間
        
        for horizon in horizons_to_try:
            logger.debug(f"Horizon {horizon}分で試行中...")
            
            # Chart API パラメータ設定
            params = {
                'Uic': uic,
                'AssetType': 'FxSpot',
                'Horizon': horizon,
                'Mode': 'UpTo',         # 指定時刻まで
                'Time': timestamp_iso,  # ISO8601形式
                'Count': 5,             # 複数取得して最適なものを選択
                'FieldGroups': 'Data'
            }
            
            logger.debug(f"API パラメータ: {params}")
            
            resp = requests.get(chart_url, headers=headers, params=params, timeout=30)
            
            logger.debug(f"API応答ステータス: {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                logger.debug(f"応答データキー: {list(data.keys())}")
                
                # データがある場合
                if "Data" in data and data["Data"]:
                    # 最も新しいデータを取得
                    candle = data["Data"][-1]  # 最後のデータ（最新）
                    
                    logger.debug(f"取得したCandle: {candle}")
                    
                    # Bid/Askレートを取得
                    bid = candle.get("CloseBid") or candle.get("OpenBid")
                    ask = candle.get("CloseAsk") or candle.get("OpenAsk")
                    
                    if bid is not None and ask is not None:
                        mid = (float(bid) + float(ask)) / 2
                        
                        # データの時刻を確認
                        data_time = candle.get("Time", "")
                        logger.info(f"Chart API価格取得成功: {currency_pair}")
                        logger.info(f"  要求時刻: {timestamp_iso}")
                        logger.info(f"  データ時刻: {data_time}")
                        logger.info(f"  Horizon: {horizon}分, Bid={bid}, Ask={ask}")
                        
                        return {
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "timestamp": data_time,
                            "target_timestamp": timestamp_iso,
                            "horizon_used": horizon,
                            "time_diff_minutes": 0,
                            "is_chart_data": True
                        }
                    else:
                        logger.warning(f"Horizon {horizon}分: Bid/Askデータが不完全: {candle}")
                else:
                    logger.warning(f"Horizon {horizon}分: データなし")
                    if "Data" in data:
                        logger.debug(f"Data配列長: {len(data['Data'])}")
            
            elif resp.status_code == 401:
                logger.warning("認証エラー。トークンを更新して再試行...")
                # トークン更新
                global global_access_token
                global_access_token = None
                access_token = ensure_access_token()
                headers["Authorization"] = f"Bearer {access_token}"
                continue  # 同じhorizonで再試行
                
            else:
                logger.warning(f"Horizon {horizon}分: APIエラー {resp.status_code}")
                logger.debug(f"エラーレスポンス: {resp.text}")
        
        # すべてのhorizonで失敗した場合、より柔軟なアプローチを試行
        logger.info(f"標準的なChart API呼び出しが失敗。代替手段を試行中...")
        
        # より長い期間で取得を試行（日次データなど）
        alternative_horizons = [1440, 10080]  # 日次、週次
        
        for horizon in alternative_horizons:
            logger.debug(f"代替Horizon {horizon}分で試行中...")
            
            params = {
                'Uic': uic,
                'AssetType': 'FxSpot',
                'Horizon': horizon,
                'Mode': 'UpTo',
                'Time': timestamp_iso,
                'Count': 1,
                'FieldGroups': 'Data'
            }
            
            resp = requests.get(chart_url, headers=headers, params=params, timeout=30)
            
            if resp.status_code == 200:
                data = resp.json()
                
                if "Data" in data and data["Data"]:
                    candle = data["Data"][-1]
                    
                    bid = candle.get("CloseBid") or candle.get("OpenBid")
                    ask = candle.get("CloseAsk") or candle.get("OpenAsk")
                    
                    if bid is not None and ask is not None:
                        mid = (float(bid) + float(ask)) / 2
                        
                        logger.info(f"代替手段で価格取得成功: {currency_pair}")
                        logger.info(f"  Horizon: {horizon}分, Bid={bid}, Ask={ask}")
                        
                        return {
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "timestamp": candle.get("Time", dt.strftime("%Y-%m-%d %H:%M:%S")),
                            "target_timestamp": timestamp_iso,
                            "horizon_used": horizon,
                            "time_diff_minutes": 0,
                            "is_chart_data": True,
                            "is_alternative": True
                        }
        
        # すべての方法が失敗した場合、現在価格APIも試してみる
        if days_diff <= 7:  # 1週間以内なら現在価格も試行
            logger.info(f"最終手段として現在価格APIを試行...")
            
            try:
                price_url = f"{GATEWAY_URL}/trade/v1/infoprices"
                price_params = {
                    "AssetType": "FxSpot",
                    "Uic": uic,
                    "FieldGroups": "Quote"
                }
                price_resp = requests.get(price_url, headers=headers, params=price_params, timeout=30)
                
                if price_resp.status_code == 200:
                    price_data = price_resp.json()
                    logger.debug(f"現在価格API応答: {price_data}")
                    
                    quote = None
                    if "Quote" in price_data:
                        quote = price_data["Quote"]
                    elif "Data" in price_data and price_data["Data"]:
                        quote = price_data["Data"][0].get("Quote", {})
                    
                    if quote and "Bid" in quote and "Ask" in quote:
                        bid = quote["Bid"]
                        ask = quote["Ask"]
                        mid = (float(bid) + float(ask)) / 2
                        
                        logger.info(f"現在価格で代替取得: {currency_pair}, Bid={bid}, Ask={ask}")
                        
                        return {
                            "bid": bid,
                            "ask": ask,
                            "mid": mid,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "target_timestamp": timestamp_iso,
                            "time_diff_minutes": 0,
                            "is_current_price": True
                        }
                    else:
                        logger.warning(f"現在価格APIの応答にBid/Askがありません: {quote}")
                else:
                    logger.warning(f"現在価格API呼び出し失敗: {price_resp.status_code}")
                    
            except Exception as e:
                logger.error(f"現在価格API呼び出しエラー: {e}")
        
        # すべての方法が失敗
        logger.error(f"{currency_pair}の過去価格をどの方法でも取得できませんでした")
        logger.error(f"要求時刻: {timestamp_iso} ({days_diff}日前)")
        return None
        
    except Exception as e:
        logger.error(f"履歴レート取得エラー: {e}")
        logger.exception("詳細なエラー情報:")
        return None
                
def calculate_pips_profit(entry_rate, exit_rate, direction, currency_pair):
    """エントリーとイグジットのレートからpips獲得を計算する"""
    if not entry_rate or not exit_rate:
        return 0, 0
        
    try:
        # 文字列型の場合は数値に変換
        entry_bid = float(entry_rate["bid"])
        entry_ask = float(entry_rate["ask"])
        exit_bid = float(exit_rate["bid"])
        exit_ask = float(exit_rate["ask"])
        
        # 方向による計算方法の変更（Long=買い、Short=売り）
        if direction.lower() == 'long':
            # 買いの場合: (exit_bid - entry_ask)
            pips_diff = exit_bid - entry_ask
        else:  # Short
            # 売りの場合: (entry_bid - exit_ask)
            pips_diff = entry_bid - exit_ask
        
        # 通貨ペアによってpipsの計算方法を調整
        # 多くのJPY通貨ペアは2桁、その他は4桁（通常）
        if 'JPY' in currency_pair:
            pips = pips_diff * 100  # 例: 0.01 = 1 pip for USD/JPY
        else:
            pips = pips_diff * 10000  # 例: 0.0001 = 1 pip for EUR/USD
        
        # 数値をそのまま返す（文字列ではなく）
        return round(pips, 2), round(pips_diff, 6)
    except (TypeError, ValueError) as e:
        logger.error(f"pips計算エラー: {e}, entry_rate={entry_rate}, exit_rate={exit_rate}")
        return 0, 0
            
def get_rate_for_pair(currency_pair):
    """指定通貨ペアの現在レートを取得"""
    if currency_pair not in KNOWN_UICS:
        logger.error(f"未知の通貨ペア: {currency_pair}")
        return None
    
    uic = KNOWN_UICS[currency_pair]
    
    try:
        rate_info = get_snapshot(uic)
        if rate_info:
            # Midレートを追加
            rate_info["mid"] = (float(rate_info["bid"]) + float(rate_info["ask"])) / 2
            logger.info(f"{currency_pair}: Bid={rate_info['bid']}, Ask={rate_info['ask']}")
        return rate_info
    except Exception as e:
        logger.error(f"{currency_pair}のレート取得エラー: {e}")
        return None

def get_current_date():
    """今日の日付を取得（YYYYMMDD形式）"""
    return datetime.now().strftime("%Y%m%d")

def list_entry_point_files():
    """entrypoint_fxフォルダ内のCSVファイルをリストアップ"""
    files = []
    
    pattern = re.compile(r'entrypoints_(\d{8})\.csv')
    today_str = get_current_date()
    
    for filename in os.listdir(DATA_DIR):
        match = pattern.match(filename)
        if match:
            date_str = match.group(1)
            filepath = os.path.join(DATA_DIR, filename)
            is_today = (date_str == today_str)
            
            files.append({
                "date_str": date_str,
                "filepath": filepath,
                "is_today": is_today,
                "is_past": date_str < today_str,
                "is_future": date_str > today_str
            })
    
    # 日付順にソート
    files.sort(key=lambda x: x["date_str"])
    
    return files

def read_entry_points(filepath):
    """CSVファイルからエントリーポイントを読み込む"""
    try:
        df = pd.read_csv(filepath)
        logger.info(f"{filepath} から {len(df)} 件のエントリーポイントを読み込みました")
        return df
    except Exception as e:
        logger.error(f"CSVファイル読み込みエラー: {e}")
        raise

def parse_time_string(time_str, target_date):
    """時刻文字列（HH:MM:SS）と指定日付をdatetimeオブジェクトに変換"""
    parts = time_str.split(':')
    
    if len(parts) == 3:  # HH:MM:SS
        hour, minute, second = map(int, parts)
    elif len(parts) == 2:  # HH:MM
        hour, minute = map(int, parts)
        second = 0
    else:
        raise ValueError(f"不正な時刻形式: {time_str}")
    
    return datetime(target_date.year, target_date.month, target_date.day, hour, minute, second)

def process_historical_file(file_info, output_file):
    """過去日付のファイルを処理し、過去レートを取得"""
    global results_data, historical_files_processed
    
    date_str = file_info["date_str"]
    filepath = file_info["filepath"]
    
    logger.info(f"過去日付ファイル処理中: {date_str}")
    
    try:
        # ファイル読み込み
        df = read_entry_points(filepath)
        
        # 日付文字列をdatetimeオブジェクトに変換
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        target_date = date(year, month, day)
        
        for index, row in df.iterrows():
            try:
                no = int(row['No'])
                currency_pair = str(row['通貨ペア'])
                entry_time_str = str(row['Entry'])
                exit_time_str = str(row['Exit'])
                direction = str(row['方向'])
                
                logger.info(f"[{date_str}-{no}] {currency_pair} {direction} の過去データ処理中... {entry_time_str} → {exit_time_str}")
                
                # ISO8601形式のタイムスタンプを生成
                entry_datetime = parse_time_string(entry_time_str, target_date)
                exit_datetime = parse_time_string(exit_time_str, target_date)
                
                entry_iso_timestamp = entry_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
                exit_iso_timestamp = exit_datetime.strftime("%Y-%m-%dT%H:%M:%SZ")
                
                # エントリーとイグジットのレート取得（過去データ）
                logger.info(f"[{date_str}-{no}] エントリーレート取得中... {entry_iso_timestamp}")
                entry_rate = get_historical_price(currency_pair, entry_iso_timestamp)
                
                if not entry_rate:
                    logger.warning(f"[{date_str}-{no}] エントリーレート取得失敗。スキップします。")
                    continue
                
                # レート取得間隔を空ける（API制限回避）
                time.sleep(2)
                
                logger.info(f"[{date_str}-{no}] イグジットレート取得中... {exit_iso_timestamp}")
                exit_rate = get_historical_price(currency_pair, exit_iso_timestamp)
                
                if not exit_rate:
                    logger.warning(f"[{date_str}-{no}] イグジットレート取得失敗。スキップします。")
                    continue
                
                # pips差と価格差を計算
                pips, price_diff = calculate_pips_profit(
                    entry_rate, 
                    exit_rate, 
                    direction,
                    currency_pair
                )
                
                # 結果をまとめる
                result = {
                    "Date": date_str,
                    "No": no,
                    "通貨ペア": currency_pair,
                    "Entry": entry_time_str,
                    "Exit": exit_time_str,
                    "方向": direction,
                    "実用スコア": row['実用スコア'],
                    "総合スコア": row['総合スコア'],
                    "Entry_Bid": entry_rate["bid"],
                    "Entry_Ask": entry_rate["ask"],
                    "Entry_Mid": entry_rate["mid"],
                    "Entry_Timestamp": entry_rate["timestamp"],
                    "Exit_Bid": exit_rate["bid"],
                    "Exit_Ask": exit_rate["ask"],
                    "Exit_Mid": exit_rate["mid"],
                    "Exit_Timestamp": exit_rate["timestamp"],
                    "Pips": pips,
                    "Price_Diff": price_diff,
                    "Entry_TimeDiff_Min": entry_rate.get("time_diff_minutes", 0),
                    "Exit_TimeDiff_Min": exit_rate.get("time_diff_minutes", 0)
                }
                
                # 勝率情報がある場合は追加
                if '短期勝率' in row:
                    result["短期勝率"] = row['短期勝率']
                if '中期勝率' in row:
                    result["中期勝率"] = row['中期勝率']
                if '長期勝率' in row:
                    result["長期勝率"] = row['長期勝率']
                
                results_data.append(result)
                
                logger.info(f"[{date_str}-{no}] {currency_pair} {direction}: 獲得pips = {pips:.2f}")
                
                # レート取得間隔を空ける（API制限回避）
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"エントリーポイント処理エラー ({date_str}, 行 {index+1}): {e}")
        
        # 次のファイル処理前に結果を保存
        save_results(output_file)
        
        historical_files_processed += 1
        logger.info(f"過去日付ファイル処理完了: {date_str}, 合計: {historical_files_processed}件")
        
    except Exception as e:
        logger.error(f"過去ファイル処理エラー ({date_str}): {e}")

def schedule_entry_points(df, date_str, output_file):
    """今日および未来のエントリーポイントの監視をスケジューリング"""
    global entry_exit_data, trading_complete, future_files_to_process
    
    entry_times = {}  # 既にスケジュール済みの時間を記録
    
    # 日付文字列をdatetimeオブジェクトに変換
    year = int(date_str[:4])
    month = int(date_str[4:6])
    day = int(date_str[6:8])
    target_date = date(year, month, day)
    
    today = date.today()
    is_today = (target_date == today)
    
    logger.info(f"{'今日' if is_today else '未来日付'} の予定データをスケジュール中: {date_str}")
    
    # エントリータイムとイグジットタイムを指定日付と結合
    for index, row in df.iterrows():
        try:
            no = int(row['No'])
            currency_pair = str(row['通貨ペア'])
            entry_time_str = str(row['Entry'])
            exit_time_str = str(row['Exit'])
            direction = str(row['方向'])
            
            # 時刻をパース
            entry_datetime = parse_time_string(entry_time_str, target_date)
            exit_datetime = parse_time_string(exit_time_str, target_date)
            
            # 今日なら現在時刻と比較して、既に過ぎている時間はスキップ
            if is_today:
                now = datetime.now()
                if entry_datetime < now:
                    logger.warning(f"エントリー時間が過ぎています: {entry_time_str}, スキップします")
                    continue
                
                if exit_datetime < now:
                    logger.warning(f"イグジット時間が過ぎています: {exit_time_str}, スキップします")
                    continue
            
            # エントリー・イグジットデータを保存
            entry_key = f"{date_str}_{no}_{currency_pair}"
            entry_exit_data[entry_key] = {
                "date_str": date_str,
                "no": no,
                "currency_pair": currency_pair,
                "entry_time": entry_time_str,
                "exit_time": exit_time_str,
                "direction": direction,
                "entry_rate": None,
                "exit_rate": None,
                "score1": row['実用スコア'],
                "score2": row['総合スコア'],
                "short_win_rate": row.get('短期勝率', None),
                "mid_win_rate": row.get('中期勝率', None),
                "long_win_rate": row.get('長期勝率', None)
            }
            
            # スケジュールするのは今日のイベントのみ
            if is_today:
                # エントリー時間に実行するジョブを登録
                entry_time_id = f"{date_str}_{entry_time_str}_{currency_pair}_{no}"
                if entry_time_id not in entry_times:
                    logger.info(f"スケジュール登録: {entry_time_str} に {currency_pair} {direction} のエントリーレート取得")
                    
                    # 固有のジョブIDを作成して実行関数に渡す
                    schedule.every().day.at(entry_time_str).do(
                        get_entry_rate, 
                        entry_key=entry_key, 
                        currency_pair=currency_pair,
                        job_id=entry_time_id
                    ).tag(f"entry_{entry_key}")
                    
                    entry_times[entry_time_id] = True
                
                # イグジット時間に実行するジョブを登録
                exit_time_id = f"{date_str}_{exit_time_str}_{currency_pair}_{no}"
                if exit_time_id not in entry_times:
                    logger.info(f"スケジュール登録: {exit_time_str} に {currency_pair} {direction} のイグジットレート取得")
                    
                    # 固有のジョブIDを作成して実行関数に渡す
                    schedule.every().day.at(exit_time_str).do(
                        get_exit_rate, 
                        entry_key=entry_key, 
                        currency_pair=currency_pair,
                        output_file=output_file,
                        job_id=exit_time_id
                    ).tag(f"exit_{entry_key}")
                    
                    entry_times[exit_time_id] = True
            else:
                # 未来日付はスケジュールせずにカウントのみ
                future_files_to_process += 1
                
        except Exception as e:
            logger.error(f"スケジュール登録エラー ({date_str}, 行 {index+1}): {e}")
    
    # 今日のデータがある場合のみ終了タイマーを設定
    if is_today and entry_times:
        # 最も遅いイグジット時間を見つける
        latest_exit_time = None
        for key, data in entry_exit_data.items():
            if data.get("date_str") == date_str:  # 今日のデータのみ対象
                exit_time = parse_time_string(data["exit_time"], target_date)
                if latest_exit_time is None or exit_time > latest_exit_time:
                    latest_exit_time = exit_time
        
        if latest_exit_time:
            # 最終イグジット時間の10分後に全実行を終了する
            finish_time = latest_exit_time + timedelta(minutes=10)
            finish_time_str = finish_time.strftime("%H:%M:%S")
            logger.info(f"全プロセス終了予定時刻: {finish_time_str}")
            
            # 終了タイマー設定
            schedule.every().day.at(finish_time_str).do(mark_trading_complete)
            
            return True
    
    # 今日のデータがなければfalseを返す
    return is_today and bool(entry_times)

def mark_trading_complete():
    """全取引完了をマーク"""
    global trading_complete
    logger.info("全ての予定取引が完了しました。プログラムを終了します。")
    trading_complete = True
    return schedule.CancelJob

def get_entry_rate(entry_key, currency_pair, job_id):
    """エントリー時点のレートを取得"""
    global entry_exit_data
    
    logger.info(f"[{entry_key}] {currency_pair} エントリーレート取得中...")
    
    try:
        # レート取得
        rate_info = get_rate_for_pair(currency_pair)
        
        if rate_info:
            # データを保存
            entry_exit_data[entry_key]["entry_rate"] = rate_info
            
            # ログ出力
            direction = entry_exit_data[entry_key]["direction"]
            entry_time = entry_exit_data[entry_key]["entry_time"]
            logger.info(f"[{entry_key}] {currency_pair} {direction} エントリー完了: {entry_time}")
            logger.info(f"[{entry_key}] Bid: {rate_info['bid']}, Ask: {rate_info['ask']}")
        else:
            logger.error(f"[{entry_key}] {currency_pair} エントリーレート取得失敗")
    
    except Exception as e:
        logger.error(f"エントリーレート取得エラー: {e}")
    
    # このジョブは1回だけ実行
    return schedule.CancelJob

def get_exit_rate(entry_key, currency_pair, output_file, job_id):
    """イグジット時点のレートを取得して結果を記録"""
    global entry_exit_data, results_data
    
    logger.info(f"[{entry_key}] {currency_pair} イグジットレート取得中...")
    
    try:
        # レート取得
        rate_info = get_rate_for_pair(currency_pair)
        
        if rate_info and entry_key in entry_exit_data:
            # データを保存
            entry_exit_data[entry_key]["exit_rate"] = rate_info
            
            # エントリーデータ取得
            entry_data = entry_exit_data[entry_key]
            entry_rate = entry_data.get("entry_rate")
            
            # エントリーレートがない場合（何らかの理由でスキップされた場合）
            if not entry_rate:
                logger.warning(f"[{entry_key}] エントリーレートがありません。イグジットのみ記録します。")
                
                result = {
                    "Date": entry_data.get("date_str", get_current_date()),
                    "No": entry_data["no"],
                    "通貨ペア": currency_pair,
                    "Entry": entry_data["entry_time"],
                    "Exit": entry_data["exit_time"],
                    "方向": entry_data["direction"],
                    "実用スコア": entry_data["score1"],
                    "総合スコア": entry_data["score2"],
                    "Exit_Bid": rate_info["bid"],
                    "Exit_Ask": rate_info["ask"],
                    "Exit_Mid": rate_info["mid"],
                    "Exit_Timestamp": rate_info["timestamp"],
                    "Pips": "N/A",
                    "Price_Diff": "N/A"
                }
                
                # 勝率情報がある場合は追加
                if entry_data.get("short_win_rate"):
                    result["短期勝率"] = entry_data["short_win_rate"]
                if entry_data.get("mid_win_rate"):
                    result["中期勝率"] = entry_data["mid_win_rate"]
                if entry_data.get("long_win_rate"):
                    result["長期勝率"] = entry_data["long_win_rate"]
                
                results_data.append(result)
            else:
                # pips差と価格差を計算
                pips, price_diff = calculate_pips_profit(
                    entry_rate, 
                    rate_info, 
                    entry_data["direction"],
                    currency_pair
                )
                
                # 結果をまとめる
                result = {
                    "Date": entry_data.get("date_str", get_current_date()),
                    "No": entry_data["no"],
                    "通貨ペア": currency_pair,
                    "Entry": entry_data["entry_time"],
                    "Exit": entry_data["exit_time"],
                    "方向": entry_data["direction"],
                    "実用スコア": entry_data["score1"],
                    "総合スコア": entry_data["score2"],
                    "Entry_Bid": entry_rate["bid"],
                    "Entry_Ask": entry_rate["ask"],
                    "Entry_Mid": entry_rate["mid"],
                    "Entry_Timestamp": entry_rate["timestamp"],
                    "Exit_Bid": rate_info["bid"],
                    "Exit_Ask": rate_info["ask"],
                    "Exit_Mid": rate_info["mid"],
                    "Exit_Timestamp": rate_info["timestamp"],
                    "Pips": pips,
                    "Price_Diff": price_diff
                }
                
                # 勝率情報がある場合は追加
                if entry_data.get("short_win_rate"):
                    result["短期勝率"] = entry_data["short_win_rate"]
                if entry_data.get("mid_win_rate"):
                    result["中期勝率"] = entry_data["mid_win_rate"]
                if entry_data.get("long_win_rate"):
                    result["長期勝率"] = entry_data["long_win_rate"]
                
                results_data.append(result)
                
                # ログ出力
                direction = entry_data["direction"]
                exit_time = entry_data["exit_time"]
                logger.info(f"[{entry_key}] {currency_pair} {direction} イグジット完了: {exit_time}")
                logger.info(f"[{entry_key}] Bid: {rate_info['bid']}, Ask: {rate_info['ask']}")
                logger.info(f"[{entry_key}] 獲得pips: {pips}")
            
            # 結果をCSVに保存
            save_results(output_file)
        else:
            logger.error(f"[{entry_key}] {currency_pair} イグジットレート取得失敗または無効なエントリーキー")
    
    except Exception as e:
        logger.error(f"イグジットレート取得エラー: {e}")
    
    # このジョブは1回だけ実行
    return schedule.CancelJob

def save_results(output_file):
    """現在までの結果をCSVファイルに保存"""
    global results_data
    
    if not results_data:
        logger.warning("保存するデータがありません")
        return
    
    try:
        # 各行のデータタイプを確認・修正
        for result in results_data:
            # Pipsが数値でない場合は0に設定
            if not isinstance(result.get('Pips'), (int, float)) or isinstance(result.get('Pips'), str):
                if result.get('Pips') == "N/A":
                    pass  # N/Aはそのまま
                else:
                    logger.warning(f"無効なPips値を修正: {result.get('Pips')} → 0")
                    result['Pips'] = 0
                    
            # Price_Diffが数値でない場合は0に設定
            if not isinstance(result.get('Price_Diff'), (int, float)) or isinstance(result.get('Price_Diff'), str):
                if result.get('Price_Diff') == "N/A":
                    pass  # N/Aはそのまま
                else:
                    logger.warning(f"無効なPrice_Diff値を修正: {result.get('Price_Diff')} → 0")
                    result['Price_Diff'] = 0
                    
        # DataFrameに変換
        result_df = pd.DataFrame(results_data)
        
        # 各列のデータ型を確認
        logger.info(f"保存前のデータ型確認: Pips={result_df['Pips'].dtype}, Price_Diff={result_df['Price_Diff'].dtype}")
        
        # CSVに保存
        result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        logger.info(f"{len(results_data)} 件のトレード結果を {output_file} に保存しました")
        
        # 統計情報を表示
        if any(isinstance(r.get('Pips'), (int, float)) for r in results_data):
            # 有効なPips値を持つ結果のみフィルタリング
            valid_results = [r for r in results_data if isinstance(r.get('Pips'), (int, float)) and not isinstance(r.get('Pips'), str)]
            
            if valid_results:
                positive_pips = sum(1 for r in valid_results if r['Pips'] > 0)
                total = len(valid_results)
                win_rate = (positive_pips / total * 100) if total > 0 else 0
                avg_pips = sum(r['Pips'] for r in valid_results) / total if total > 0 else 0
                
                logger.info(f"現在の勝率: {win_rate:.2f}% ({positive_pips}/{total})")
                logger.info(f"平均獲得pips: {avg_pips:.2f}")
                
                # 方向別統計
                long_results = [r for r in valid_results if r['方向'].lower() == 'long']
                short_results = [r for r in valid_results if r['方向'].lower() == 'short']
                
                # Long統計
                if long_results:
                    long_positive = sum(1 for r in long_results if r['Pips'] > 0)
                    long_total = len(long_results)
                    long_win_rate = (long_positive / long_total * 100) if long_total > 0 else 0
                    avg_long_pips = sum(r['Pips'] for r in long_results) / long_total if long_total > 0 else 0
                    logger.info(f"Long勝率: {long_win_rate:.2f}% ({long_positive}/{long_total}), 平均: {avg_long_pips:.2f} pips")
                
                # Short統計
                if short_results:
                    short_positive = sum(1 for r in short_results if r['Pips'] > 0)
                    short_total = len(short_results)
                    short_win_rate = (short_positive / short_total * 100) if short_total > 0 else 0
                    avg_short_pips = sum(r['Pips'] for r in short_results) / short_total if short_total > 0 else 0
                    logger.info(f"Short勝率: {short_win_rate:.2f}% ({short_positive}/{short_total}), 平均: {avg_short_pips:.2f} pips")
    
    except Exception as e:
        logger.error(f"結果保存エラー: {e}")

def run_scheduler():
    """スケジューラを実行し、定期的にトークンも更新"""
    global trading_complete
    
    logger.info("スケジューラ開始: エントリー/イグジットのレート取得を待機中...")
    
    # トークン更新を30分ごとにスケジュール
    schedule.every(30).minutes.do(ensure_access_token)
    
    while not trading_complete:
        # スケジュール済みジョブを実行
        schedule.run_pending()
        
        # CPU負荷軽減のため1秒スリープ
        time.sleep(1)
    
    logger.info("スケジューラ終了")

def main():
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(description="FX自動エントリー・イグジット監視ツール（複数日付対応版）")
    parser.add_argument("--output", help="出力ファイル名（デフォルトは fx_results_YYYYMMDD.csv）")
    parser.add_argument("--debug", action="store_true", help="デバッグモード")
    parser.add_argument("--today-only", action="store_true", help="今日のデータのみ処理")
    parser.add_argument("--historical-only", action="store_true", help="過去データのみ処理")
    
    args = parser.parse_args()
    
    # デバッグモード設定
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 出力ファイル名設定
    current_date = get_current_date()
    output_file = args.output if args.output else os.path.join(RESULTS_DIR, f"fx_results_multi_{current_date}.csv")
    
    logger.info("============================================")
    logger.info("=== FX自動エントリー監視ツール（複数日付対応版） ===")
    logger.info("============================================")
    logger.info(f"出力ファイル: {output_file}")
    
    try:
        # 1. トークン取得（起動時に一度確認）
        access_token = ensure_access_token()
        logger.info("トークン取得成功")
        
        # 2. フォルダ内のエントリーポイントファイルをリストアップ
        files = list_entry_point_files()
        
        if not files:
            logger.error("エントリーポイントファイルが見つかりません")
            sys.exit(1)
        
        logger.info(f"合計 {len(files)} 件のエントリーポイントファイルを検出")
        
        past_files = [f for f in files if f["is_past"]]
        today_files = [f for f in files if f["is_today"]]
        future_files = [f for f in files if f["is_future"]]
        
        logger.info(f"過去日付: {len(past_files)}件, 今日: {len(today_files)}件, 未来日付: {len(future_files)}件")
        
        # 3. 処理内容を分岐
        scheduled_today = False
        
        # 過去日付の処理
        if (not args.today_only) and past_files:
            logger.info(f"過去日付ファイル処理開始: {len(past_files)}件")
            
            for file_info in past_files:
                if args.debug or args.historical_only:
                    logger.info(f"過去日付ファイル: {file_info['date_str']}, パス: {file_info['filepath']}")
                
                # 過去日付ファイル処理
                process_historical_file(file_info, output_file)
                
                # API制限を考慮して一定間隔空ける
                time.sleep(2)
        
        # 今日および未来日付の処理
        if not args.historical_only:
            # 今日のデータをスケジュール
            if today_files:
                for file_info in today_files:
                    df = read_entry_points(file_info["filepath"])
                    if schedule_entry_points(df, file_info["date_str"], output_file):
                        scheduled_today = True
            
            # 未来日付のデータは表示のみ
            if future_files:
                logger.info(f"未来日付のエントリーポイントファイル: {len(future_files)}件")
                for file_info in future_files:
                    logger.info(f"  - {file_info['date_str']}: {file_info['filepath']}")
        
        # 4. スケジュール実行（今日のデータがある場合のみ）
        if scheduled_today:
            logger.info("今日のエントリーポイントをスケジュール完了。監視開始します。")
            run_scheduler()
        else:
            # 過去データのみ処理してすぐに終了
            if historical_files_processed > 0:
                logger.info(f"過去日付ファイル処理完了: {historical_files_processed}件")
            else:
                logger.warning("処理対象のデータがありませんでした。")
        
        logger.info("処理が完了しました")
        
    except FileNotFoundError as e:
        logger.error(f"ファイルが見つかりません: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()