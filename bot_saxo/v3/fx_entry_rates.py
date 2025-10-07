#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
エントリーポイントデータからFXレートを取得するスクリプト
- 指定された日付のCSVファイルを読み込む
- 各エントリーポイントの通貨ペアとタイムスタンプを抽出
- Saxo Bank APIを使用してレートを取得
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
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("fx_auto_entry.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("FXEntryPoint")

# ディレクトリパス設定
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR)

# Saxo Bank API設定 (LIVE環境)
CLIENT_ID = "67a87ac462994c4b805a0811aa966a50"
CLIENT_SECRET = "950d065d7a3145c5800abd730ff43eaf"
AUTH_URL = "https://live.logonvalidation.net/authorize"
TOKEN_URL = "https://live.logonvalidation.net/token"
GATEWAY_URL = "https://gateway.saxobank.com/openapi"
REDIRECT_URI = "http://localhost:8080/callback"
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token_live.json")

# 既知のUIC（最低限必要な通貨ペア）
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
    
    # リフレッシュトークンの有効期限も計算して表示
    if "refresh_token_created_at" in tokens:
        refresh_created = datetime.fromtimestamp(tokens["refresh_token_created_at"])
        refresh_expires = refresh_created + timedelta(days=90)  # 通常90日
        logger.info(f">> リフレッシュトークン作成日: {refresh_created.strftime('%Y-%m-%d')}")
        logger.info(f">> リフレッシュトークン推定期限: {refresh_expires.strftime('%Y-%m-%d')} (約90日後)")

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

def ensure_tokens(headless_mode=False) -> dict:
    """有効なトークンを取得（必要に応じて更新または新規取得）"""
    toks = load_tokens()
    if toks and is_valid(toks):
        logger.info(">> 有効なトークンが見つかりました")
        return toks
    
    if toks.get("refresh_token"):
        try:
            logger.info(">> リフレッシュトークンを使用して更新します")
            toks = refresh_token(toks)
            save_tokens(toks)
            return toks
        except Exception as e:
            logger.error(f">> リフレッシュトークンエラー: {e}")
            if headless_mode:
                raise RuntimeError(f"リフレッシュトークンでの更新に失敗し、ヘッドレスモードなので手動認証できません")
            logger.info(">> 新規認証を開始します")
    
    if headless_mode:
        raise RuntimeError("有効なトークンが見つからず、ヘッドレスモードなので手動認証できません")
    
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
    return toks

def get_snapshot(uic: int, access_token: str) -> dict:
    """価格スナップショット取得"""
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
    logger.debug(f">> スナップショット取得中: UIC={uic}")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def extract_rate_info(data: dict, symbol: str, uic: int) -> dict:
    """スナップショットから必要な情報を抽出"""
    if "Quote" in data:
        # 単一商品のレスポンス
        actual_symbol = data.get('DisplayAndFormat', {}).get('Symbol', 'Unknown')
        description = data.get('DisplayAndFormat', {}).get('Description', 'Unknown')
        bid = data.get('Quote', {}).get('Bid', 'N/A')
        ask = data.get('Quote', {}).get('Ask', 'N/A')
        market = data.get('Quote', {}).get('MarketState', 'Unknown')
        last_update = data.get('Quote', {}).get('LastUpdated', 'Unknown')
        
        # レート情報を辞書で返す
        rate_info = {
            "symbol": actual_symbol,
            "description": description,
            "bid": bid,
            "ask": ask,
            "mid": (float(bid) + float(ask)) / 2 if bid != 'N/A' and ask != 'N/A' else 'N/A',
            "market": market,
            "timestamp": last_update
        }
        
        return rate_info
        
    elif "Data" in data and data["Data"]:
        # 複数商品のレスポンス（最初のアイテムのみ）
        q = data["Data"][0]
        instrument = q.get('InstrumentName', 'Unknown')
        bid = q.get('Bid', 'N/A')
        ask = q.get('Ask', 'N/A')
        timestamp = q.get('Timestamp', 'Unknown')
        
        return {
            "symbol": symbol,
            "description": instrument,
            "bid": bid,
            "ask": ask,
            "mid": (float(bid) + float(ask)) / 2 if bid != 'N/A' and ask != 'N/A' else 'N/A',
            "timestamp": timestamp
        }
    else:
        logger.error(f"予期しないレスポンス形式")
        return {
            "symbol": symbol,
            "error": "Invalid response format"
        }

def get_current_date():
    """今日の日付を取得（YYYYMMDD形式）"""
    return datetime.now().strftime("%Y%m%d")

def get_entry_points_file(date_str=None):
    """指定日付（または今日）のエントリーポイントファイルパスを取得"""
    if not date_str:
        date_str = get_current_date()
    
    filename = f"entrypoints_{date_str}.csv"
    filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"エントリーポイントファイルが見つかりません: {filepath}")
    
    return filepath

def read_entry_points(filepath):
    """CSVファイルからエントリーポイントを読み込む"""
    try:
        df = pd.read_csv(filepath)
        logger.info(f"{filepath} から {len(df)} 件のエントリーポイントを読み込みました")
        return df
    except Exception as e:
        logger.error(f"CSVファイル読み込みエラー: {e}")
        raise

def get_rate_for_entry_point(currency_pair, access_token):
    """指定通貨ペアの現在レートを取得"""
    if currency_pair not in KNOWN_UICS:
        logger.error(f"未知の通貨ペア: {currency_pair}")
        return None
    
    uic = KNOWN_UICS[currency_pair]
    
    try:
        data = get_snapshot(uic, access_token)
        rate_info = extract_rate_info(data, currency_pair, uic)
        logger.info(f"{currency_pair}: Bid={rate_info['bid']}, Ask={rate_info['ask']}")
        return rate_info
    except Exception as e:
        logger.error(f"{currency_pair}のレート取得エラー: {e}")
        return None

def process_entry_points(df, access_token, output_file):
    """エントリーポイントごとにレート取得とCSV出力"""
    # 結果格納用のリスト
    results = []
    
    # 各エントリーポイントを処理
    for index, row in df.iterrows():
        try:
            currency_pair = row['通貨ペア']
            entry_time = row['Entry']
            exit_time = row['Exit']
            direction = row['方向']
            
            # レート取得
            rate_info = get_rate_for_entry_point(currency_pair, access_token)
            
            if rate_info:
                # 結果を辞書として保存
                result = {
                    'No': row['No'],
                    '通貨ペア': currency_pair,
                    'Entry': entry_time,
                    'Exit': exit_time,
                    '方向': direction,
                    '実用スコア': row['実用スコア'],
                    '総合スコア': row['総合スコア'],
                    'Bid': rate_info['bid'],
                    'Ask': rate_info['ask'],
                    'Mid': rate_info['mid']
                }
                
                # 短期・中期・長期勝率があれば追加
                if '短期勝率' in row:
                    result['短期勝率'] = row['短期勝率']
                if '中期勝率' in row:
                    result['中期勝率'] = row['中期勝率']
                if '長期勝率' in row:
                    result['長期勝率'] = row['長期勝率']
                
                results.append(result)
                logger.info(f"[{row['No']}] {currency_pair} {direction} エントリー: {entry_time}, Bid/Ask: {rate_info['bid']}/{rate_info['ask']}")
            else:
                # レート取得失敗の場合
                logger.warning(f"[{row['No']}] {currency_pair} のレート取得に失敗しました")
        except Exception as e:
            logger.error(f"エントリーポイント処理エラー: {e}")
    
    # 結果をCSVに出力
    if results:
        try:
            result_df = pd.DataFrame(results)
            result_df.to_csv(output_file, index=False)
            logger.info(f"{len(results)} 件のエントリーポイント情報を {output_file} に保存しました")
        except Exception as e:
            logger.error(f"CSV出力エラー: {e}")
    else:
        logger.warning("出力するデータがありません")

def main():
    # コマンドライン引数の解析
    parser = argparse.ArgumentParser(description="エントリーポイントFXレート取得ツール")
    parser.add_argument("--date", help="対象日付（YYYYMMDD形式、デフォルトは本日）")
    parser.add_argument("--output", help="出力ファイル名（デフォルトは rates_entrypoints_YYYYMMDD.csv）")
    parser.add_argument("--debug", action="store_true", help="デバッグモード")
    
    args = parser.parse_args()
    
    # デバッグモード設定
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 日付設定
    date_str = args.date if args.date else get_current_date()
    
    # 出力ファイル名設定
    output_file = args.output if args.output else os.path.join(DATA_DIR, f"rates_entrypoints_{date_str}.csv")
    
    logger.info("=== エントリーポイントFXレート取得ツール ===")
    logger.info(f"対象日付: {date_str}")
    logger.info(f"出力ファイル: {output_file}")
    
    try:
        # 1. トークン取得
        tokens = ensure_tokens()
        access_token = tokens["access_token"]
        logger.info("トークン取得成功")
        
        # 2. エントリーポイントファイル読み込み
        entry_points_file = get_entry_points_file(date_str)
        entry_points = read_entry_points(entry_points_file)
        
        # 3. 各エントリーポイントのレート取得と出力
        process_entry_points(entry_points, access_token, output_file)
        
        logger.info("処理が完了しました")
        
    except Exception as e:
        logger.error(f"エラーが発生しました: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()