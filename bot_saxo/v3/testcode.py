#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Saxo Bank OpenAPI LIVE/SIM環境向け
- 初回：認可コード取得 → トークン取得 → token.json 保存
- 2回目以降：token.json を読み込み → refresh_token で更新
- FXSpot 銘柄検索 → USD/JPY の UIC を取得
- リアルタイムスナップショット（InfoPrices）取得 → 出力

エラーハンドリングと複数検索方法を強化したバージョン
UICリスト取得機能を追加
トークン自動更新と期限切れ監視機能を追加
"""

import os
import sys
import time
import json
import threading
import webbrowser
import argparse
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests
from datetime import datetime, timedelta

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("saxo_api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("SaxoAPI")

# ──────────────── 設定部 ────────────────
# SIMかLIVEかを選択（切り替え可能）
USE_SIM = False  # TrueでSIM環境、FalseでLIVE環境

# SIM環境
SIM_CLIENT_ID     = "5f19317941744e688ca30be6b2f53659"
SIM_CLIENT_SECRET = "7e7f99b6a65343ebae16c915daddf80" # または "a83b3a8b9a85464ba600f63565d644d9"
SIM_AUTH_URL      = "https://sim.logonvalidation.net/authorize"
SIM_TOKEN_URL     = "https://sim.logonvalidation.net/token"
SIM_GATEWAY_URL   = "https://gateway.saxobank.com/sim/openapi"

# LIVE環境
LIVE_CLIENT_ID    = "67a87ac462994c4b805a0811aa966a50"
LIVE_CLIENT_SECRET = "950d065d7a3145c5800abd730ff43eaf"
LIVE_AUTH_URL     = "https://live.logonvalidation.net/authorize"
LIVE_TOKEN_URL    = "https://live.logonvalidation.net/token"
LIVE_GATEWAY_URL  = "https://gateway.saxobank.com/openapi"

# 環境に応じた設定を適用
CLIENT_ID     = SIM_CLIENT_ID if USE_SIM else LIVE_CLIENT_ID
CLIENT_SECRET = SIM_CLIENT_SECRET if USE_SIM else LIVE_CLIENT_SECRET
AUTH_URL      = SIM_AUTH_URL if USE_SIM else LIVE_AUTH_URL
TOKEN_URL     = SIM_TOKEN_URL if USE_SIM else LIVE_TOKEN_URL
GATEWAY_URL   = SIM_GATEWAY_URL if USE_SIM else LIVE_GATEWAY_URL

REDIRECT_URI  = "http://localhost:8080/callback"

# 銘柄検索用
SYMBOL        = "USDJPY"  # スラッシュを削除
FIELD_GROUPS  = "DisplayAndFormat,PriceInfo"

# トークン保存ファイル（スクリプトと同じディレクトリに作成）
script_dir = os.path.dirname(os.path.abspath(__file__))
token_filename = "token_sim.json" if USE_SIM else "token_live.json"
TOKEN_FILE = os.path.join(script_dir, token_filename)

# リフレッシュトークンの警告日数（期限切れが近づいたら警告）
REFRESH_TOKEN_WARNING_DAYS = 85  # 90日の期限に対して85日で警告
OUTPUT_CSV_FILE = os.path.join(script_dir, "fx_rates.csv")

# 既知のUICマッピング（APIが失敗した場合のフォールバック）
KNOWN_UICS = {
    "AUDJPY": 2,  # 豪ドル/円
    "AUDUSD": 4,  # 豪ドル/米ドル
    "CADJPY": 6,  # カナダドル/円
    "CADUSD": 3946,  # カナダドル/米ドル
    "CHFJPY": 8,  # スイスフラン/円
    "CHFUSD": 17746,  # スイスフラン/米ドル
    "CNHJPY": 52873,  # 中国元/円
    "DKKJPY": 4727,  # デンマーククローネ/円
    "EURJPY": 18,  # ユーロ/円
    "EURUSD": 21,  # ユーロ/米ドル
    "GBPJPY": 26,  # 英ポンド/円
    "GBPUSD": 31,  # 英ポンド/米ドル
    "HKDJPY": 8943,  # 香港ドル/円
    "HUFJPY": 37129,  # ハンガリーフォリント/円
    "MXNJPY": 23581,  # メキシコペソ/円
    "NOKJPY": 46,  # ノルウェークローネ/円
    "NOKUSD": 17764,  # ノルウェークローネ/米ドル
    "NZDJPY": 36,  # ニュージーランドドル/円
    "NZDUSD": 37,  # ニュージーランドドル/米ドル
    "PLNJPY": 3901,  # ポーランドズロチ/円
    "SEKJPY": 2870,  # スウェーデンクローナ/円
    "SGDJPY": 48,  # シンガポールドル/円
    "TRYJPY": 23582,  # トルコリラ/円
    "USDAED": 1363,  # 米ドル/アラブディルハム
    "USDAUD": 22413,  # 米ドル/豪ドル
    "USDCAD": 38,  # 米ドル/カナダドル
    "USDCHF": 39,  # 米ドル/スイスフラン
    "USDCNH": 52872,  # 米ドル/中国元
    "USDCZK": 40,  # 米ドル/チェココルナ
    "USDDKK": 41,  # 米ドル/デンマーククローネ
    "USDHKD": 1345,  # 米ドル/香港ドル
    "USDHUF": 2075,  # 米ドル/ハンガリーフォリント
    "USDILS": 4773,  # 米ドル/イスラエルシュケル
    "USDJPY": 42,  # 米ドル/円
    "USDMXN": 1348,  # 米ドル/メキシコペソ
    "USDNOK": 43,  # 米ドル/ノルウェークローネ
    "USDPLN": 47,  # 米ドル/ポーランドズロチ
    "USDRON": 24407,  # 米ドル/ルーマニアレウ
    "USDSEK": 44,  # 米ドル/スウェーデンクローナ
    "USDSGD": 45,  # 米ドル/シンガポールドル
    "USDTHB": 1351,  # 米ドル/タイバーツ
    "USDTRY": 13928,  # 米ドル/トルコリラ
    "USDZAR": 1296,  # 米ドル/南アフリカランド
    "XAGJPY": 19847,  # 銀/円
    "XAGUSD": 8177,  # 銀ドル (FX口座)
    "XAUJPY": 19719,  # 金/円
    "XAUUSD": 8176,  # 金/ドル
    "XPTUSD": 107830,  # プラチナ/ドル
    "ZARJPY": 21281,  # 南アフリカランド/円
}
# ────────────────────────────────────────────

auth_code = None

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
        
        # リフレッシュトークンの期限切れが近いか確認
        check_refresh_token_expiry(tokens)
        
        return tokens
    except Exception as e:
        logger.error(f">> トークンファイル読み込みエラー: {e}")
        return {}

def check_refresh_token_expiry(tokens: dict) -> bool:
    """リフレッシュトークンの期限切れが近いかチェック"""
    if not tokens or "refresh_token" not in tokens:
        return False
    
    # リフレッシュトークン取得日時がなければ今作成
    if "refresh_token_created_at" not in tokens:
        tokens["refresh_token_created_at"] = time.time()
        save_tokens(tokens)
        return False
    
    # 経過日数を計算
    days_passed = (time.time() - tokens["refresh_token_created_at"]) / (60 * 60 * 24)
    
    # 通知すべき日数を超えていれば通知
    if days_passed > REFRESH_TOKEN_WARNING_DAYS:
        refresh_created = datetime.fromtimestamp(tokens["refresh_token_created_at"])
        refresh_expires = refresh_created + timedelta(days=90)  # 通常90日
        days_left = 90 - days_passed
        
        logger.warning("⚠️ 警告: リフレッシュトークンの期限切れが近づいています！")
        logger.warning(f"   リフレッシュトークン作成日: {refresh_created.strftime('%Y-%m-%d')}")
        logger.warning(f"   推定有効期限: {refresh_expires.strftime('%Y-%m-%d')}")
        logger.warning(f"   残り推定日数: 約{int(days_left)}日")
        logger.warning(f"   90日以内に手動で再認証してください。")
        return True
    
    return False

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
    logger.info(f">> {('SIM' if USE_SIM else 'LIVE')}環境を使用しています")
    
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

def ensure_tokens_for_automation() -> dict:
    """自動実行用のトークン取得・更新処理（ヘッドレスモード）"""
    try:
        return ensure_tokens(headless_mode=True)
    except Exception as e:
        logger.error(f"自動化用トークン取得エラー: {e}")
        # エラーメッセージをファイルに出力
        with open("token_error.txt", "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - トークンエラー: {e}\n")
        raise

def _dump_with_keywords(access_token: str, keyword: str) -> list:
    """キーワード指定で商品一覧を取得"""
    url = f"{GATEWAY_URL}/ref/v1/instruments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "Keywords": keyword,
        "IncludeNonTradable": "false",
        "$top": 100
    }
    logger.info(f"\n>> キーワード '{keyword}' で商品検索中...")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    
    data = resp.json()
    total_count = data.get("__count", 0)
    items = data.get("Data", [])
    
    logger.info(f"キーワード '{keyword}': {total_count} 件の商品が見つかりました。最初の {len(items)} 件を表示:")
    
    # アセットタイプごとにカウント
    asset_types = {}
    for item in items:
        asset_type = item.get("AssetType", "Unknown")
        asset_types[asset_type] = asset_types.get(asset_type, 0) + 1
    
    logger.info(f"キーワード '{keyword}' - アセットタイプ別商品数:")
    for asset_type, count in asset_types.items():
        logger.info(f"  {asset_type}: {count}件")
    
    # FXSpotの商品を詳細表示
    fx_items = [item for item in items if item.get("AssetType") == "FxSpot"]
    
    if fx_items:
        logger.info(f"\nキーワード '{keyword}' - FxSpot商品一覧:")
        for i, item in enumerate(fx_items):
            logger.info(f"\n[{i+1}] {item.get('Description', 'No description')}")
            # 重要なキー一覧を表示
            important_keys = ["Uic", "Symbol", "AssetType", "Description", "Identifier"]
            for key in important_keys:
                if key in item:
                    logger.info(f"  {key}: {item[key]}")
            
            # USDJPYを探している場合、発見したらコード例を表示
            if keyword.upper() == "USDJPY" or (
                "USD" in item.get("Symbol", "").upper() and "JPY" in item.get("Symbol", "").upper()
            ):
                logger.info(f"\n>> [発見] USDJPY関連の商品を発見: {item.get('Description', '')}")

                # UIcがない場合はIdentifierを試す
                uic_value = None
                if "Uic" in item:
                    uic_value = item["Uic"]
                elif "Identifier" in item:
                    uic_value = item["Identifier"]
                
                if uic_value:
                    logger.info(f">> UIC: {uic_value}")
                    logger.info(f">> 以下のコードを使用してください:")
                    logger.info(f'KNOWN_UICS["{item.get("Symbol", "")}"] = {uic_value}  # {item.get("Description", "")}')
                else:
                    logger.info(">> UICが見つかりません。レスポンス全体を確認してください:")
                    logger.info(json.dumps(item, indent=2))
    else:
        logger.info(f"\nキーワード '{keyword}' - FxSpot商品は見つかりませんでした")
        
    return fx_items

def dump_available_instruments(access_token: str) -> None:
    """利用可能な商品一覧をダンプして分析"""
    try:
        # 基本的な検索方法を試す
        fx_usd = _dump_with_keywords(access_token, "USD")
        fx_jpy = _dump_with_keywords(access_token, "JPY")
        
        # USD/JPYに関連する商品を特に検索
        fx_usdjpy = _dump_with_keywords(access_token, "USDJPY")
        
        # すべての検索結果をまとめて表示
        all_fx_items = fx_usd + fx_jpy + fx_usdjpy
        
        # 重複を削除
        unique_fx_items = {}
        for item in all_fx_items:
            symbol = item.get("Symbol", "")
            if symbol and symbol not in unique_fx_items:
                unique_fx_items[symbol] = item
        
        if unique_fx_items:
            logger.info("\n=== 発見した主要な通貨ペア ===")
            code_lines = []
            for symbol, item in unique_fx_items.items():
                # UIcがない場合はIdentifierを試す
                uic_value = None
                if "Uic" in item:
                    uic_value = item["Uic"]
                elif "Identifier" in item:
                    uic_value = item["Identifier"]
                
                if uic_value:
                    code_line = f'    "{symbol}": {uic_value},  # {item.get("Description", "")}'
                    code_lines.append(code_line)
                    logger.info(code_line)
            
            if code_lines:
                logger.info("\n以下のように KNOWN_UICS を更新してください:")
                logger.info("KNOWN_UICS = {")
                for line in sorted(code_lines):
                    logger.info(line)
                logger.info("}")
            else:
                logger.info("UICを持つ商品が見つかりませんでした。レスポンスの構造を確認してください。")
            
    except Exception as e:
        logger.error(f"商品一覧取得エラー: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logger.error(f"レスポンス: {e.response.text}")

def dump_all_fx_uics(access_token: str, filename="fx_uics.json") -> None:
    """利用可能なすべてのFX通貨ペアのUICを取得してファイルに保存"""
    logger.info(f"\n>> すべてのFX通貨ペアのUICを取得中...")
    fx_uics = {}
    
    # 1. 最初に通貨ペアを検索するためのキーワードリスト
    base_currencies = ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
    
    # 2. 各通貨ペアの組み合わせを検索
    for base in base_currencies:
        for quote in base_currencies:
            if base != quote:  # 同じ通貨同士はスキップ
                symbol = f"{base}{quote}"
                try:
                    logger.info(f"  {symbol}を検索中...")
                    url = f"{GATEWAY_URL}/ref/v1/instruments"
                    headers = {
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json"
                    }
                    params = {
                        "Keywords": symbol,
                        "AssetTypes": "FxSpot"
                    }
                    resp = requests.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    
                    data = resp.json()
                    items = data.get("Data", [])
                    
                    for item in items:
                        if item.get("Symbol", "") == symbol:
                            uic = item.get("Uic")
                            if not uic and "Identifier" in item:
                                uic = item["Identifier"]
                            
                            if uic:
                                fx_uics[symbol] = {
                                    "Uic": uic,
                                    "Description": item.get("Description", ""),
                                    "AssetType": item.get("AssetType", "")
                                }
                                logger.info(f"    ✓ {symbol} -> UIC: {uic}")
                                break
                except Exception as e:
                    logger.error(f"    ✗ {symbol}の検索中にエラー: {e}")
    
    # 3. 全体リストの取得（追加の通貨ペアを見つけるため）
    try:
        logger.info(f"\n>> 全通貨ペアリストを取得中...")
        url = f"{GATEWAY_URL}/ref/v1/instruments"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }
        params = {
            "AssetTypes": "FxSpot",
            "$top": 1000  # 最大1000件
        }
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        
        data = resp.json()
        items = data.get("Data", [])
        
        for item in items:
            symbol = item.get("Symbol", "")
            uic = item.get("Uic")
            if not uic and "Identifier" in item:
                uic = item["Identifier"]
                
            if symbol and uic and symbol not in fx_uics:
                fx_uics[symbol] = {
                    "Uic": uic,
                    "Description": item.get("Description", ""),
                    "AssetType": item.get("AssetType", "")
                }
                logger.info(f"  + {symbol} -> UIC: {uic}")
    except Exception as e:
        logger.error(f"  ✗ 全通貨ペア取得中にエラー: {e}")
    
    # 4. 結果をファイルに保存
    file_path = os.path.join(script_dir, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(fx_uics, f, indent=2, ensure_ascii=False)
    
    logger.info(f"\n>> {len(fx_uics)}件のFX通貨ペアUICを {file_path} に保存しました")
    
    # 5. サンプルコードとして主要通貨ペアを表示
    logger.info("\n主要通貨ペアのUIC:")
    major_pairs = ["USDJPY", "EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF"]
    for pair in major_pairs:
        if pair in fx_uics:
            logger.info(f'KNOWN_UICS["{pair}"] = {fx_uics[pair]["Uic"]}  # {fx_uics[pair]["Description"]}')
        else:
            logger.info(f'# {pair} のUICは見つかりませんでした')

def get_fx_uic(symbol: str, access_token: str) -> int:
    """通貨ペアのUICを取得（複数の方法で試行）"""
    # 既知のUICマッピングがあれば使用
    if symbol.upper() in KNOWN_UICS:
        uic = KNOWN_UICS[symbol.upper()]
        logger.info(f">> 既知のUIC情報を使用: {symbol} -> {uic}")
        return uic
    
    # まずは全商品からの詳細検索を試行
    try:
        uic = _find_uic_from_dump(symbol, access_token)
        if uic:
            logger.info(f">> 商品一覧から{symbol}のUICを特定: {uic}")
            return uic
    except Exception as e:
        logger.error(f">> 商品一覧検索エラー: {e}")
    
    # 以下はAPIメソッドによる検索
    search_methods = [
        _try_get_fx_uic_default,
        _try_get_fx_uic_search,
        _try_get_fx_uic_keyword
    ]
    
    for i, method in enumerate(search_methods, 1):
        try:
            logger.info(f">> 検索方法{i}を試行中...")
            uic = method(symbol, access_token)
            if uic:
                logger.info(f">> 検索方法{i}で成功: UIC = {uic}")
                # KNOWN_UICのアップデート方法を表示
                logger.info(f'KNOWN_UICS["{symbol}"] = {uic}  # 今後のためにこの行をコードに追加してください')
                return uic
        except Exception as e:
            logger.error(f">> 検索方法{i}で例外発生: {e}")
    
    # すべての方法が失敗した場合は、手動での入力を促す
    logger.warning("\n>> 警告：自動UIC検索に失敗しました。")
    logger.warning(f">> {symbol}のUICを手動で入力する場合は、以下のように設定してください:")
    logger.warning(f'KNOWN_UICS["{symbol}"] = 123  # 適切な値に置き換えてください')
    
    raise RuntimeError(f"{symbol} の UIC が見つかりませんでした。")

def _find_uic_from_dump(symbol: str, access_token: str) -> int:
    """利用可能な全商品から適切なUICを探す"""
    url = f"{GATEWAY_URL}/ref/v1/instruments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "Keywords": symbol,  # 検索条件として必須
        "IncludeNonTradable": "false",
        "$top": 1000  # 最大1000件
    }
    logger.info(f">> 商品一覧からの検索を試行中...")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    
    data = resp.json()
    items = data.get("Data", [])
    
    # シンボル名での完全一致を探す
    symbol_upper = symbol.upper()
    direct_matches = [item for item in items 
                     if item.get("Symbol", "").upper() == symbol_upper]
    
    if direct_matches:
        item = direct_matches[0]
        logger.info(f">> シンボル完全一致: {item.get('Description', '')}")
        if "Uic" in item:
            return item["Uic"]
        elif "Identifier" in item:
            return item["Identifier"]
    
    # 部分一致を探す
    partial_matches = [item for item in items 
                      if symbol_upper in item.get("Symbol", "").upper()]
    
    if partial_matches:
        # FxSpotタイプを優先
        fx_matches = [item for item in partial_matches 
                     if item.get("AssetType") == "FxSpot"]
        
        if fx_matches:
            item = fx_matches[0]
            logger.info(f">> FxSpotで部分一致: {item.get('Description', '')}")
            if "Uic" in item:
                return item["Uic"]
            elif "Identifier" in item:
                return item["Identifier"]
        else:
            item = partial_matches[0]
            logger.info(f">> 部分一致: {item.get('Description', '')}")
            if "Uic" in item:
                return item["Uic"]
            elif "Identifier" in item:
                return item["Identifier"]
    
    return None

def _try_get_fx_uic_default(symbol: str, access_token: str) -> int:
    """デフォルトのインストゥルメント検索方法"""
    url = f"{GATEWAY_URL}/ref/v1/instruments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "AssetTypes": "FxSpot",
        "Keywords": symbol
    }
    logger.info(f">> 方法1: AssetTypesとKeywords検索を試行中")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    
    data = resp.json()
    logger.debug(f"  レスポンス構造: {json.dumps(data, indent=2)[:200]}...")
    
    if "Data" in data and data["Data"]:
        items = data["Data"]
        logger.info(f"  {len(items)}件のアイテムが見つかりました")
        
        for item in items:
            if "Uic" in item:
                return item["Uic"]
            elif "Identifier" in item:
                return item["Identifier"]
        
        # キーがなければ詳細を表示
        logger.debug(f"  最初のアイテムの詳細: {items[0]}")
        
    return None

def _try_get_fx_uic_search(symbol: str, access_token: str) -> int:
    """検索APIを使用する方法"""
    url = f"{GATEWAY_URL}/ref/v1/instruments/search"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "AssetTypes": "FxSpot",
        "Keywords": symbol
    }
    logger.info(f">> 方法2: 検索APIを試行中")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    
    data = resp.json()
    logger.debug(f"  レスポンス構造: {json.dumps(data, indent=2)[:200]}...")
    
    if "Data" in data and data["Data"]:
        items = data["Data"]
        logger.info(f"  {len(items)}件のアイテムが見つかりました")
        
        for item in items:
            if "Uic" in item:
                return item["Uic"]
            elif "Identifier" in item:
                return item["Identifier"]
            elif "Id" in item:
                return item["Id"]
        
        # キーがなければ詳細を表示
        logger.debug(f"  最初のアイテムの詳細: {items[0]}")
            
    return None

def _try_get_fx_uic_keyword(symbol: str, access_token: str) -> int:
    """キーワード検索のみを使用する方法"""
    url = f"{GATEWAY_URL}/ref/v1/instruments"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept":        "application/json"
    }
    params = {
        "Keywords": symbol,
        "IncludeNonTradable": "false"
    }
    logger.info(f">> 方法3: 通貨ペアの単純キーワード検索を試行中")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    
    data = resp.json()
    logger.debug(f"  レスポンス構造: {json.dumps(data, indent=2)[:200]}...")
    
    if "Data" in data and data["Data"]:
        items = data["Data"]
        logger.info(f"  {len(items)}件のアイテムが見つかりました")
        
        # FxSpotタイプを優先
        fx_items = [item for item in items if item.get("AssetType") == "FxSpot"]
        if fx_items:
            logger.info(f"  {len(fx_items)}件のFxSpotアイテムが見つかりました")
            item = fx_items[0]
            if "Uic" in item:
                return item["Uic"]
            elif "Identifier" in item:
                return item["Identifier"]
            # キーがなければ詳細を表示
            logger.debug(f"  最初のFxSpotアイテムの詳細: {item}")
        
        # FxSpotがなければ他のアイテムを探す
        item = items[0]
        if "Uic" in item:
            return item["Uic"]
        elif "Identifier" in item:
            return item["Identifier"]
        # キーがなければ詳細を表示
        logger.debug(f"  最初のアイテムの詳細: {item}")
            
    return None

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
        "FieldGroups": FIELD_GROUPS
    }
    logger.info(f">> スナップショット取得中: UIC={uic}")
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def show_snapshot_result(data, symbol, uic):
    """スナップショット結果を表示"""
    logger.info(f"\n=== スナップショット結果 (UIC: {uic}) ===")
    
    # レスポンスの構造を確認して適切に表示
    if "Quote" in data:
        # 単一商品のレスポンス
        actual_symbol = data.get('DisplayAndFormat', {}).get('Symbol', 'Unknown')
        description = data.get('DisplayAndFormat', {}).get('Description', 'Unknown')
        bid = data.get('Quote', {}).get('Bid', 'N/A')
        ask = data.get('Quote', {}).get('Ask', 'N/A')
        market = data.get('Quote', {}).get('MarketState', 'Unknown')
        last_update = data.get('LastUpdated', 'Unknown')
        
        logger.info(f"Symbol:      {actual_symbol}")
        logger.info(f"Description: {description}")
        logger.info(f"Bid:         {bid}")
        logger.info(f"Ask:         {ask}")
        logger.info(f"Market:      {market}")
        logger.info(f"Last Update: {last_update}")
        
        # レート情報を辞書で返す
        rate_info = {
            "symbol": actual_symbol,
            "description": description,
            "bid": bid,
            "ask": ask,
            "market": market,
            "timestamp": last_update
        }
        
        # 実際に取得した通貨ペアが意図したものと異なる場合の警告
        if actual_symbol.upper() != symbol.upper():
            logger.warning(f"\n⚠️ 警告: 要求した通貨ペア {symbol} と異なる {actual_symbol} が返されました")
            logger.warning(f"   KNOWN_UICS辞書の値を更新してください")
            logger.warning(f'KNOWN_UICS["{actual_symbol}"] = {uic}')
        
        return rate_info
        
    elif "Data" in data and data["Data"]:
        # 複数商品のレスポンス（最初のアイテムのみ表示）
        q = data["Data"][0]
        instrument = q.get('InstrumentName', 'Unknown')
        bid = q.get('Bid', 'N/A')
        ask = q.get('Ask', 'N/A')
        timestamp = q.get('Timestamp', 'Unknown')
        
        logger.info(f"Instrument: {instrument}")
        logger.info(f"Bid:        {bid}")
        logger.info(f"Ask:        {ask}")
        logger.info(f"Timestamp:  {timestamp}")
        
        return {
            "symbol": symbol,
            "description": instrument,
            "bid": bid,
            "ask": ask,
            "timestamp": timestamp
        }
    else:
        logger.error(f"予期しないレスポンス形式: {json.dumps(data, indent=2)}")
        return None

def show_uic_mapping_hints(data, symbol, uic):
    """次回のためのUICマッピングヒントを表示"""
    logger.info("\n=== 次回のための設定例 ===")
    if "DisplayAndFormat" in data and "Symbol" in data["DisplayAndFormat"]:
        actual_symbol = data["DisplayAndFormat"]["Symbol"]
        real_uic = data.get("Uic", uic)
        logger.info(f'KNOWN_UICS["{actual_symbol}"] = {real_uic}  # {data["DisplayAndFormat"].get("Description", "")}')
        
        # もし意図した通貨ペアと違った場合のサンプル
        if actual_symbol != symbol:
            logger.info(f"\n# 別の通貨ペアでも試してみてください:")
            logger.info(f'SYMBOL = "{actual_symbol}"  # {data["DisplayAndFormat"].get("Description", "")}')

def debug_api_response(url, headers, params):
    """レスポンス全体をデバッグ表示"""
    logger.info("\n===== API レスポンスデバッグ =====")
    logger.info(f"URL: {url}")
    logger.info(f"パラメータ: {params}")
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        
        data = resp.json()
        logger.debug("\nレスポンス構造:")
        logger.debug(json.dumps(data, indent=2))
        
        if "Data" in data and data["Data"]:
            first_item = data["Data"][0]
            logger.info("\n最初のアイテムのキー:")
            for key in first_item.keys():
                logger.info(f"  - {key}: {first_item[key]}")
        
        return data
    except Exception as e:
        logger.error(f"エラー: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logger.error(f"レスポンス: {e.response.text}")
        return None

def get_fx_rates(currency_pairs=None):
    """指定された通貨ペアのFXレートを取得する自動化関数"""
    if currency_pairs is None:
        # デフォルトの通貨ペア
        currency_pairs = ["USDJPY", "EURJPY", "EURUSD", "GBPUSD", "AUDUSD", "USDCHF"]

    results = {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        # 自動実行モード用のトークン取得
        tokens = ensure_tokens_for_automation()
        token = tokens["access_token"]
        logger.info(f"トークン取得成功 ({timestamp})")
        
        for pair in currency_pairs:
            try:
                # UIC取得
                uic = get_fx_uic(pair, token)
                
                # スナップショット取得
                data = get_snapshot(uic, token)
                
                # レート情報を抽出して結果に追加
                rate_info = show_snapshot_result(data, pair, uic)
                if rate_info:
                    results[pair] = rate_info
            except Exception as e:
                logger.error(f"{pair}の取得でエラー: {e}")
                results[pair] = {"error": str(e)}
        
        # 結果をCSVに追記
        save_rates_to_csv(results, timestamp)
        
        return results
    
    except Exception as e:
        logger.error(f"FXレート取得中のエラー: {e}")
        return {"error": str(e)}

def save_rates_to_csv(rates, timestamp):
    """レート情報をCSVファイルに保存"""
    # ファイルが存在するか確認し、なければヘッダーを書き込む
    file_exists = os.path.isfile(OUTPUT_CSV_FILE)
    
    with open(OUTPUT_CSV_FILE, 'a', encoding='utf-8') as f:
        if not file_exists:
            f.write("Timestamp,Symbol,Bid,Ask\n")
        
        for pair, info in rates.items():
            if "error" not in info:
                f.write(f"{timestamp},{pair},{info.get('bid', 'N/A')},{info.get('ask', 'N/A')}\n")
    
    logger.info(f"FXレート情報を {OUTPUT_CSV_FILE} に保存しました")

def main():
    # コマンドライン引数のパース
    parser = argparse.ArgumentParser(description='Saxo Bank API FXレート取得')
    parser.add_argument('--debug', action='store_true', help='デバッグモードで実行')
    parser.add_argument('--dump-uics', action='store_true', help='UICリストをダンプ')
    parser.add_argument('--symbol', type=str, help='特定の通貨ペアを取得')
    parser.add_argument('--auto', action='store_true', help='自動実行モード（UIなし）')
    parser.add_argument('--pairs', type=str, help='カンマ区切りの通貨ペアリスト（--autoで使用）')
    
    args = parser.parse_args()
    
    # ヘッダー表示
    logger.info("=" * 60)
    logger.info(f"=== Saxo Bank API テスト ({('SIM' if USE_SIM else 'LIVE')}環境) ===")
    logger.info("=" * 60)
    
    # 自動実行モード
    if args.auto:
        currency_pairs = ["USDJPY", "EURJPY", "EURUSD", "GBPUSD"]
        if args.pairs:
            currency_pairs = args.pairs.split(',')
        
        logger.info(f"自動実行モード: {', '.join(currency_pairs)} のレートを取得します")
        results = get_fx_rates(currency_pairs)
        return
    
    # 通貨ペア変数を関数内でローカル化
    symbol = SYMBOL  # グローバル変数から初期値を取得

    # トークン取得 or 更新
    try:
        tokens = ensure_tokens()
        token = tokens["access_token"]
        logger.info(f">> トークン取得成功: {token[:15]}...")
    except Exception as e:
        logger.error(f"トークン取得エラー: {e}")
        sys.exit(1)

    # デバッグモード
    if args.debug:
        logger.info(">> デバッグモードを実行します")
        url = f"{GATEWAY_URL}/ref/v1/instruments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        params = {
            "Keywords": "USDJPY",
            "IncludeNonTradable": "false"
        }
        debug_api_response(url, headers, params)
        return
    
    # UICダンプモード
    if args.dump_uics:
        logger.info(">> UICダンプモードを実行します")
        dump_all_fx_uics(token)
        return
        
    # シンボル指定モード
    if args.symbol:
        symbol = args.symbol
        logger.info(f">> シンボル指定モード: {symbol}")

    # デバッグ用の商品一覧ダンプ
    try:
        dump_available_instruments(token)
    except Exception as e:
        logger.error(f"商品一覧取得エラー: {e}")
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            logger.error(f"レスポンス: {e.response.text}")
        logger.warning("商品一覧取得失敗しましたが、処理を継続します")

    # 指定通貨ペアの UIC を動的に取得
    try:
        # SYMBOL変数ではなくローカル変数symbolを使用
        uic = get_fx_uic(symbol, token)
        logger.info(f">> {symbol} の UIC を取得成功: {uic}")
    except Exception as e:
        logger.error(f"銘柄検索エラー: {e}")
        sys.exit(1)

    # リアルタイムスナップショット取得
    try:
        data = get_snapshot(uic, token)
        show_snapshot_result(data, symbol, uic)
        show_uic_mapping_hints(data, symbol, uic)
    except requests.HTTPError as e:
        logger.error(f"スナップショット取得エラー: {e}")
        logger.error(f"レスポンス: {e.response.text}")
        sys.exit(1)

# このスクリプトがメインで実行された場合のみmain()を呼び出す
if __name__ == "__main__":
    main()
