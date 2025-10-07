# config.py - サクソバンクAPI設定ファイル（OAuth版）
"""
サクソバンクAPI OAuth設定
注意: このファイルは.gitignoreに追加してください
"""

# ===========================================
# OAuth認証設定
# ===========================================

# アプリケーション認証情報（OpenAPI Portalで取得）
CLIENT_ID = "5f19317941744e688ca30be6b2f53659"
CLIENT_SECRET = "a83b3a8b9a85464ba600f63565d644d9"

# リダイレクトURI（OpenAPI Portalに登録したもの）
REDIRECT_URI = "http://localhost:8080/callback"

# ===========================================
# 環境設定
# ===========================================

# 環境選択: 'sim' (Simulation) または 'live' (Production)
ENVIRONMENT = 'sim'

# ===========================================
# エンドポイント設定（環境に応じて自動設定）
# ===========================================

# Simulation環境
if ENVIRONMENT == 'sim':
    API_BASE_URL = "https://gateway.saxobank.com/sim/openapi"
    AUTH_BASE_URL = "https://sim.logonvalidation.net"
# Production環境
else:
    API_BASE_URL = "https://gateway.saxobank.com/openapi"
    AUTH_BASE_URL = "https://logonvalidation.net"

# ===========================================
# トレーディング設定
# ===========================================

# デフォルトトレーディング設定
DEFAULT_TRADING_SETTINGS = {
    'max_positions': 5,           
    'risk_per_trade': 0.02,       
    'default_amount': 10000,      
    'leverage': 20,               
    'order_type': 'Market',
    # 追加：デフォルト残高設定
    'fallback_balance': 1000000,  # 100万円（API取得失敗時）
}

# ===========================================
# ログ設定
# ===========================================

LOG_SETTINGS = {
    'level': 'INFO',              # ログレベル: DEBUG, INFO, WARNING, ERROR
    'max_files': 30,              # 保持するログファイル数
    'file_rotation': 'daily',     # ローテーション: daily, weekly
}

# ===========================================
# ファイルパス設定
# ===========================================

# エントリーポイントファイルのパス
ENTRYPOINT_PATH = r"C:\Users\beru\Dropbox\006_TRADE\historycal\entrypoint_fx"

# 検証ファイルのパス
VERIFICATION_PATH = r"C:\Users\beru\Downloads"

# スプレッドシートWebhook URL
SPREADSHEET_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxwox807RBi4yJG2rHSklR5wiW5uA2Z38rxaJVs-WPJ/exec"

# ===========================================
# 通貨ペア設定
# ===========================================

# 対応通貨ペア一覧
SUPPORTED_CURRENCY_PAIRS = [
    'USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY', 'CHFJPY',
    'EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD', 'USDCAD'
]

# ===========================================
# APIレート制限設定
# ===========================================

# API呼び出し間隔（秒）
API_CALL_INTERVAL = 0.5

# タイムアウト設定（秒）
REQUEST_TIMEOUT = 30

# リトライ設定
RETRY_SETTINGS = {
    'max_retries': 3,
    'backoff_factor': 1.0,
    'status_forcelist': [500, 502, 503, 504]
}

# ===========================================
# OAuth認証用ヘルパー関数
# ===========================================

def get_oauth_config():
    """OAuth設定を取得"""
    return {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'environment': ENVIRONMENT
    }

def get_api_endpoints():
    """API エンドポイントを取得"""
    return {
        'api_base_url': API_BASE_URL,
        'auth_base_url': AUTH_BASE_URL
    }

def is_simulation_environment():
    """シミュレーション環境かどうかを判定"""
    return ENVIRONMENT == 'sim'

# ===========================================
# バリデーション
# ===========================================

def validate_config():
    """設定の妥当性チェック"""
    errors = []
    
    if not CLIENT_ID or CLIENT_ID == "your_client_id_here":
        errors.append("CLIENT_ID が設定されていません")
    
    if not CLIENT_SECRET or CLIENT_SECRET == "your_client_secret_here":
        errors.append("CLIENT_SECRET が設定されていません")
    
    if not REDIRECT_URI or "localhost" not in REDIRECT_URI:
        errors.append("REDIRECT_URI が適切に設定されていません")
    
    if ENVIRONMENT not in ['sim', 'live']:
        errors.append("ENVIRONMENT は 'sim' または 'live' を指定してください")
    
    return errors

# ===========================================
# 設定情報表示
# ===========================================

def print_config_info():
    """設定情報を表示"""
    print("=" * 60)
    print("🔧 サクソバンクAPI設定情報")
    print("=" * 60)
    print(f"環境: {ENVIRONMENT}")
    print(f"APIベースURL: {API_BASE_URL}")
    print(f"認証URL: {AUTH_BASE_URL}")
    print(f"リダイレクトURI: {REDIRECT_URI}")
    print(f"最大ポジション数: {DEFAULT_TRADING_SETTINGS['max_positions']}")
    print(f"リスク/取引: {DEFAULT_TRADING_SETTINGS['risk_per_trade'] * 100}%")
    print(f"レバレッジ: {DEFAULT_TRADING_SETTINGS['leverage']}倍")
    print("=" * 60)
    
    # 設定検証
    errors = validate_config()
    if errors:
        print("⚠️  設定エラー:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("✅ 設定検証: OK")
    print("=" * 60)

if __name__ == "__main__":
    print_config_info()