#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config_manager.py - FXバックテスト設定管理クラス
"""

import json
import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class BacktestConfigManager:
    """バックテスト設定管理クラス"""
    
    def __init__(self, config_file: str = "config.json"):
        """初期化
        
        Parameters:
        -----------
        config_file : str
            設定ファイルパス
        """
        self.config_file = Path(config_file)
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """設定ファイルを読み込み"""
        try:
            if not self.config_file.exists():
                logger.warning(f"設定ファイルが見つかりません: {self.config_file}")
                self.create_default_config()
                logger.info(f"デフォルト設定ファイルを作成しました: {self.config_file}")
            
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            logger.info(f"設定ファイル読み込み完了: {self.config_file}")
            self.validate_config()
            
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            logger.warning("デフォルト設定を使用します")
            self.config = self.get_default_config()
    
    def create_default_config(self):
        """デフォルト設定ファイルを作成"""
        default_config = self.get_default_config()
        
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
    
    def get_default_config(self) -> Dict[str, Any]:
        """デフォルト設定を取得"""
        return {
            "backtest_settings": {
                "risk_management": {
                    "stop_loss_pips": 15,
                    "take_profit_pips": 30,
                    "enable_stop_loss": True,
                    "enable_take_profit": False,
                    "slippage_pips": 1
                },
                "advanced_settings": {
                    "weekend_sl_disabled": True,
                    "major_news_sl_disabled": False,
                    "volatile_hours_sl_multiplier": 1.5
                }
            },
            "currency_settings": {
                "USDJPY": {
                    "pip_value": 0.01,
                    "pip_multiplier": 100,
                    "stop_loss_pips": 15,
                    "take_profit_pips": 30
                },
                "EURJPY": {
                    "pip_value": 0.01,
                    "pip_multiplier": 100,
                    "stop_loss_pips": 12,
                    "take_profit_pips": 25
                },
                "GBPJPY": {
                    "pip_value": 0.01,
                    "pip_multiplier": 100,
                    "stop_loss_pips": 20,
                    "take_profit_pips": 40
                },
                "EURUSD": {
                    "pip_value": 0.0001,
                    "pip_multiplier": 10000,
                    "stop_loss_pips": 10,
                    "take_profit_pips": 20
                },
                "GBPUSD": {
                    "pip_value": 0.0001,
                    "pip_multiplier": 10000,
                    "stop_loss_pips": 12,
                    "take_profit_pips": 24
                }
            },
            "system_settings": {
                "log_level": "INFO",
                "save_detailed_logs": True,
                "generate_charts": True,
                "chart_dpi": 300
            }
        }
    
    def validate_config(self):
        """設定の妥当性をチェック"""
        errors = []
        
        # 必須キーの確認
        required_keys = [
            "backtest_settings.risk_management.stop_loss_pips",
            "backtest_settings.risk_management.enable_stop_loss",
            "currency_settings"
        ]
        
        for key_path in required_keys:
            if self.get(key_path) is None:
                errors.append(f"必須設定が不足: {key_path}")
        
        # 数値範囲の確認
        sl_pips = self.get("backtest_settings.risk_management.stop_loss_pips")
        if sl_pips is not None and (sl_pips <= 0 or sl_pips > 100):
            errors.append("stop_loss_pipsは1-100の範囲で設定してください")
        
        tp_pips = self.get("backtest_settings.risk_management.take_profit_pips")
        if tp_pips is not None and tp_pips <= 0:
            errors.append("take_profit_pipsは正の値で設定してください")
        
        if errors:
            for error in errors:
                logger.warning(f"設定警告: {error}")
        
        logger.info("設定の妥当性チェック完了")
    
    def get(self, key_path: str, default=None):
        """ドット記法で設定値を取得
        
        Parameters:
        -----------
        key_path : str
            設定のキーパス（例: "backtest_settings.risk_management.stop_loss_pips"）
        default : Any
            デフォルト値
        
        Returns:
        --------
        Any : 設定値
        """
        keys = key_path.split('.')
        value = self.config
        
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_stop_loss_pips(self, currency_pair: str = None) -> Optional[float]:
        """ストップロス設定を取得
        
        Parameters:
        -----------
        currency_pair : str, optional
            通貨ペア名（指定すると通貨ペア別設定を優先）
        
        Returns:
        --------
        float or None : ストップロス pips値
        """
        # 有効/無効チェック
        if not self.get("backtest_settings.risk_management.enable_stop_loss", True):
            return None
        
        # 通貨ペア別設定を優先
        if currency_pair:
            currency_sl = self.get(f"currency_settings.{currency_pair}.stop_loss_pips")
            if currency_sl is not None:
                return float(currency_sl)
        
        # グローバル設定
        global_sl = self.get("backtest_settings.risk_management.stop_loss_pips")
        return float(global_sl) if global_sl is not None else None
    
    def get_take_profit_pips(self, currency_pair: str = None) -> Optional[float]:
        """テイクプロフィット設定を取得
        
        Parameters:
        -----------
        currency_pair : str, optional
            通貨ペア名（指定すると通貨ペア別設定を優先）
        
        Returns:
        --------
        float or None : テイクプロフィット pips値
        """
        # 有効/無効チェック
        if not self.get("backtest_settings.risk_management.enable_take_profit", False):
            return None
        
        # 通貨ペア別設定を優先
        if currency_pair:
            currency_tp = self.get(f"currency_settings.{currency_pair}.take_profit_pips")
            if currency_tp is not None:
                return float(currency_tp)
        
        # グローバル設定
        global_tp = self.get("backtest_settings.risk_management.take_profit_pips")
        return float(global_tp) if global_tp is not None else None
    
    def get_currency_settings(self, currency_pair: str) -> Dict[str, Any]:
        """通貨ペア設定を取得
        
        Parameters:
        -----------
        currency_pair : str
            通貨ペア名
        
        Returns:
        --------
        dict : 通貨ペア設定
        """
        # 通貨ペア別設定
        currency_config = self.get(f"currency_settings.{currency_pair}", {})
        
        # デフォルト値で補完
        default_settings = {
            "pip_value": 0.01 if 'JPY' in currency_pair else 0.0001,
            "pip_multiplier": 100 if 'JPY' in currency_pair else 10000,
            "stop_loss_pips": self.get("backtest_settings.risk_management.stop_loss_pips", 15),
            "take_profit_pips": self.get("backtest_settings.risk_management.take_profit_pips", 30)
        }
        
        # マージ
        for key, default_value in default_settings.items():
            if key not in currency_config:
                currency_config[key] = default_value
        
        return currency_config
    
    def set(self, key_path: str, value: Any):
        """設定値を更新
        
        Parameters:
        -----------
        key_path : str
            設定のキーパス
        value : Any
            設定値
        """
        keys = key_path.split('.')
        config = self.config
        
        for key in keys[:-1]:
            if key not in config:
                config[key] = {}
            config = config[key]
        
        config[keys[-1]] = value
    
    def save_config(self):
        """設定ファイルを保存"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"設定ファイル保存完了: {self.config_file}")
        except Exception as e:
            logger.error(f"設定ファイル保存エラー: {e}")
    
    def print_current_settings(self):
        """現在の設定を表示"""
        print("\n" + "=" * 50)
        print("📋 現在のバックテスト設定")
        print("=" * 50)
        
        # リスク管理設定
        print("🛡️  リスク管理設定:")
        sl_enabled = self.get("backtest_settings.risk_management.enable_stop_loss", True)
        tp_enabled = self.get("backtest_settings.risk_management.enable_take_profit", False)
        sl_pips = self.get("backtest_settings.risk_management.stop_loss_pips", 15)
        tp_pips = self.get("backtest_settings.risk_management.take_profit_pips", 30)
        
        print(f"  ストップロス: {'有効' if sl_enabled else '無効'} ({sl_pips}pips)")
        print(f"  テイクプロフィット: {'有効' if tp_enabled else '無効'} ({tp_pips}pips)")
        
        # 通貨ペア別設定
        print("\n💱 通貨ペア別設定:")
        currency_settings = self.get("currency_settings", {})
        for currency, settings in currency_settings.items():
            sl = settings.get('stop_loss_pips', '未設定')
            tp = settings.get('take_profit_pips', '未設定')
            print(f"  {currency}: SL={sl}pips, TP={tp}pips")
        
        print("=" * 50)

# グローバル設定インスタンス
config_manager = BacktestConfigManager()