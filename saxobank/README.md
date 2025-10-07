# サクソバンクAPI FX自動エントリーシステム (OAuth対応版)

24時間限定トークンからOAuth認証 + 自動トークン更新方式に対応したFX自動エントリーシステムです。

## 📋 概要

- **OAuth2認証**: PKCE対応の安全な認証フロー
- **自動トークン更新**: 期限切れ前に自動でトークンを更新
- **エントリーポイント自動実行**: step3のエントリーポイントに基づく自動取引
- **詳細ログ**: 取引・エラー・認証の詳細ログ
- **Simulation環境対応**: 安全なテスト環境での動作

## 🚀 セットアップ手順

### 1. サクソバンク開発者ポータルでアプリ登録

1. [Saxo Developer Portal](https://www.developer.saxo/openapi/appmanagement) にアクセス
2. 新しいアプリケーションを作成
3. 以下の設定を行う：
   ```
   Application Name: FX Auto Entry System
   Redirect URI: http://localhost:8080/callback
   Grant Types: Authorization Code
   Scopes: openapi
   ```
4. `CLIENT_ID` と `CLIENT_SECRET` をメモ

### 2. 環境設定

```bash
# リポジトリクローン（または既存プロジェクト）
cd your_project_directory

# 必要なライブラリインストール
pip install requests pandas

# .gitignoreファイル配置（重要：認証情報保護）
# 提供された.gitignoreファイルをプロジェクトルートに配置
```

### 3. 設定ファイル編集

`config.py` を編集：

```python
# OAuth認証設定
CLIENT_ID = "your_client_id_here"          # 👈 開発者ポータルで取得
CLIENT_SECRET = "your_client_secret_here"  # 👈 開発者ポータルで取得
REDIRECT_URI = "http://localhost:8080/callback"

# 環境設定
ENVIRONMENT = 'sim'  # 'sim' (Simulation) または 'live' (Production)
```

### 4. ファイル構成

```
your_project/
├── oauth_auth.py          # OAuth認証モジュール
├── config.py              # 設定ファイル
├── bot_saxo.py            # メインシステム (OAuth対応版)
├── oauth_test.py          # 認証テストスクリプト
├── fx_rate_collector.py   # レート収集システム
├── .gitignore             # セキュリティ設定
├── log/                   # ログディレクトリ（自動作成）
└── backup/                # バックアップディレクトリ（自動作成）
```

## 🔧 使用方法

### 1. 認証テスト

最初に認証システムの動作を確認：

```bash
python oauth_test.py
```

**期待される動作:**
1. ブラウザが自動で開く
2. サクソバンクログインページが表示
3. ユーザー名・パスワードでログイン
4. 認証後、`saxo_tokens.json` が生成される
5. 各種APIテストが実行される

### 2. FX自動エントリーシステム実行

```bash
python bot_saxo.py
```

**システムの動作:**
1. OAuth認証（初回のみブラウザ認証、2回目以降は自動）
2. エントリーポイントファイル読み込み
3. 毎分00秒にエントリー・エグジット条件をチェック
4. 条件一致時に自動取引実行（現在はシミュレーション）

### 3. レート収集システム実行

```bash
python fx_rate_collector.py
```

## 📊 ログファイル

システム実行により以下のログが生成されます：

```
log/
├── fx_auto_entry_detailed_YYYYMMDD.log  # 詳細ログ
├── fx_auto_entry_errors_YYYYMMDD.log    # エラーログ
├── fx_trades_YYYYMMDD.log               # 取引ログ
└── oauth_test_YYYYMMDD.log              # 認証テストログ
```

## 🔐 OAuth認証フロー

### 初回認証

1. **認証URL生成**: PKCE対応の安全な認証URL
2. **ブラウザ認証**: 自動でブラウザが開き、サクソバンクのログインページへ
3. **認証コード取得**: ローカルサーバーでコールバックを受信
4. **トークン取得**: 認証コードをアクセストークンに交換
5. **トークン保存**: `saxo_tokens.json` に暗号化せずに保存

### 自動更新

- **期限監視**: 10分前に自動でトークン更新を実行
- **バックグラウンド更新**: メインシステムを停止せずに更新
- **エラーハンドリング**: 更新失敗時は再認証を促す

## ⚙️ 設定項目

### トレーディング設定 (`config.py`)

```python
DEFAULT_TRADING_SETTINGS = {
    'max_positions': 5,           # 最大同時ポジション数
    'risk_per_trade': 0.02,       # 1取引あたりのリスク（2%）
    'default_amount': 10000,      # デフォルト取引単位
    'leverage': 20,               # レバレッジ倍率
    'order_type': 'Market',       # 注文タイプ
}
```

### ログ設定

```python
LOG_SETTINGS = {
    'level': 'INFO',              # ログレベル
    'max_files': 30,              # 保持ファイル数
    'file_rotation': 'daily',     # ローテーション
}
```

## 🛡️ セキュリティ

### 重要な注意事項

1. **認証情報の保護**
   - `CLIENT_SECRET` は絶対に公開リポジトリにコミットしない
   - `.gitignore` で `saxo_tokens.json` を除外済み

2. **トークンファイル**
   - `saxo_tokens.json` は機密情報を含む
   - 定期的にバックアップを取る
   - 他人との共有は禁止

3. **環境設定**
   - 本番環境では必ず `ENVIRONMENT = 'live'` に変更
   - Simulation環境での十分なテストを推奨

## 🔧 トラブルシューティング

### よくある問題

#### 1. 認証エラー

```
❌ OAuth認証失敗
```

**解決方法:**
- `CLIENT_ID` と `CLIENT_SECRET` が正しいか確認
- リダイレクトURIが開発者ポータルと一致するか確認
- ポート8080が他のプロセスで使用されていないか確認

#### 2. API接続エラー

```
❌ API接続テスト失敗: 401
```

**解決方法:**
- トークンが期限切れの可能性 → `saxo_tokens.json` を削除して再認証
- 権限設定の確認 → 開発者ポータルでスコープ設定を確認

#### 3. ファイル読み込みエラー

```
❌ エントリーポイントファイルが見つかりません
```

**解決方法:**
- `config.py` の `ENTRYPOINT_PATH` を正しいパスに設定
- ファイルが存在し、読み込み権限があるか確認

### ログ確認方法

詳細なエラー情報は以下のログファイルを確認：

```bash
# 最新の詳細ログ
tail -f log/fx_auto_entry_detailed_$(date +%Y%m%d).log

# エラーログのみ
tail -f log/fx_auto_entry_errors_$(date +%Y%m%d).log
```

## 📈 システム監視

### リアルタイム監視

```bash
# システム実行中のログをリアルタイム表示
tail -f log/fx_auto_entry_detailed_$(date +%Y%m%d).log | grep -E "(TRADE|ERROR|WARNING)"
```

### 統計情報

システムは10分ごとに以下の統計を出力：

- 稼働時間
- 総エントリー数・エグジット数
- 累計pips
- アクティブポジション数
- 平均pips/取引

## 🔄 本番環境への移行

### Simulation → Live環境

1. **十分なテスト**: Simulation環境で1週間以上の動作確認
2. **設定変更**: `config.py` で `ENVIRONMENT = 'live'` に変更
3. **新規認証**: Live環境用の新しい認証が必要
4. **実取引有効化**: `bot_saxo.py` のコメントアウトされた注文処理を有効化

### 注意事項

- **資金管理**: 十分な証拠金の確保
- **リスク設定**: `risk_per_trade` の適切な設定
- **監視体制**: 24時間監視可能な体制の構築

## 📞 サポート

### 技術的な問題

1. **ログファイル確認**: エラーの詳細情報を収集
2. **設定検証**: `python config.py` で設定の妥当性をチェック
3. **認証テスト**: `python oauth_test.py` で認証システムの動作確認

### サクソバンクAPI関連

- [サクソバンク開発者ドキュメント](https://www.developer.saxo/openapi/learn)
- [API リファレンス](https://www.developer.saxo/openapi/referencedocs)

---

## 📄 ライセンス

このプロジェクトは個人使用を目的としています。商用利用の場合は、サクソバンクの利用規約を確認してください。

## ⚠️ 免責事項

- このシステムは教育・研究目的で作成されています
- 実際の取引による損失について、開発者は一切の責任を負いません
- 使用前に十分なテストと理解を行ってください
- FX取引にはリスクが伴います。自己責任で使用してください