#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
optimized_15min_gradient_calculator.py - 15分以内保有に最適化された勾配パラメータ計算
短期保有に特化した時間軸選定と指標設計
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

class Optimized15MinGradientCalculator:
    """15分以内保有に最適化された勾配計算クラス"""
    
    def __init__(self):
        # 15分以内保有に最適化された時間軸
        self.timeframes = {
            '30sec': '30s',      # エントリータイミング精密化
            '1min': '1min',      # 基本時間軸
            '2min': '2min',      # エントリー後の初期確認
            '3min': '3min',      # 早期トレンド確認
            '5min': '5min',      # 中期トレンド
            '10min': '10min',    # 保有期間カバー
            '15min': '15min'     # 最大保有期間
        }
        
        # 短期保有特化の勾配パラメータ
        self.gradient_params = {
            'ema_fast': {'period': 5},    # 超高速EMA
            'ema_medium': {'period': 12}, # 標準EMA
            'ema_slow': {'period': 21},   # やや遅いEMA
            'macd': {'fast': 5, 'slow': 13, 'signal': 5},  # 高感度MACD
            'atr': {'period': 7},         # 短期ATR
            'momentum': {'period': 3},    # 短期モメンタム
            'rsi': {'period': 7}          # 短期RSI
        }
        
        # 時間軸別重要度（15分以内での影響度）
        self.timeframe_importance = {
            '30sec': 0.05,   # エントリー精度
            '1min': 0.25,    # 最重要（基準）
            '2min': 0.20,    # 初期確認
            '3min': 0.15,    # トレンド確認
            '5min': 0.20,    # 中期確認
            '10min': 0.10,   # 後期確認
            '15min': 0.05    # 最終確認
        }
    
    def analyze_entry_timing_gradients(self, df, tf_name):
        """エントリータイミング特化勾配分析"""
        if df.empty or len(df) < 15:
            return self._get_empty_gradients()
        
        try:
            gradients = {}
            
            # 1. 超高速EMA勾配（エントリータイミング）
            gradients['ema_fast'] = self._calculate_ema_gradient(df, 5)
            
            # 2. 標準EMA勾配（トレンド確認）
            gradients['ema_medium'] = self._calculate_ema_gradient(df, 12)
            
            # 3. 高感度MACD勾配（モメンタム）
            gradients['macd'] = self._calculate_fast_macd_gradient(df)
            
            # 4. 短期ATR勾配（ボラティリティ変化）
            gradients['atr'] = self._calculate_short_atr_gradient(df)
            
            # 5. 短期モメンタム（価格勢い）
            gradients['momentum'] = self._calculate_momentum_gradient(df)
            
            # 6. 短期RSI勾配（過買い・過売り）
            gradients['rsi'] = self._calculate_short_rsi_gradient(df)
            
            # 7. 価格勢い（直接的変化率）
            gradients['price_velocity'] = self._calculate_price_velocity(df)
            
            # 8. 時間軸特化複合スコア
            gradients['composite'] = self._calculate_15min_composite(gradients, tf_name)
            
            return gradients
            
        except Exception as e:
            logging.error(f"勾配計算エラー ({tf_name}): {e}")
            return self._get_empty_gradients()
    
    def _get_empty_gradients(self):
        """空の勾配辞書"""
        return {
            'ema_fast': 0.0,
            'ema_medium': 0.0,
            'macd': 0.0,
            'atr': 0.0,
            'momentum': 0.0,
            'rsi': 0.0,
            'price_velocity': 0.0,
            'composite': 0.0
        }
    
    def _calculate_ema_gradient(self, df, period):
        """EMA勾配計算（短期特化）"""
        try:
            ema = df['close'].ewm(span=period, adjust=False).mean()
            
            # 短期保有なので3期間の変化率を使用
            if len(ema) >= 3:
                current = ema.iloc[-1]
                past = ema.iloc[-3]
                if past != 0:
                    gradient = ((current - past) / past) * 100
                    return max(-100, min(100, gradient))
            return 0.0
        except:
            return 0.0
    
    def _calculate_fast_macd_gradient(self, df):
        """高感度MACD勾配（短期特化）"""
        try:
            # より感度の高いMACDパラメータ
            ema_fast = df['close'].ewm(span=5, adjust=False).mean()
            ema_slow = df['close'].ewm(span=13, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            
            # 3期間変化率
            if len(macd_line) >= 3:
                current = macd_line.iloc[-1]
                past = macd_line.iloc[-3]
                if past != 0:
                    gradient = ((current - past) / abs(past)) * 100
                    return max(-100, min(100, gradient))
            return 0.0
        except:
            return 0.0
    
    def _calculate_short_atr_gradient(self, df):
        """短期ATR勾配"""
        try:
            # 短期ATR（7期間）
            df_copy = df.copy()
            df_copy['prev_close'] = df_copy['close'].shift(1)
            df_copy['tr1'] = df_copy['high'] - df_copy['low']
            df_copy['tr2'] = abs(df_copy['high'] - df_copy['prev_close'])
            df_copy['tr3'] = abs(df_copy['low'] - df_copy['prev_close'])
            df_copy['true_range'] = df_copy[['tr1', 'tr2', 'tr3']].max(axis=1)
            
            atr = df_copy['true_range'].rolling(window=7).mean()
            
            if len(atr) >= 3:
                current = atr.iloc[-1]
                past = atr.iloc[-3]
                if past != 0:
                    gradient = ((current - past) / past) * 100
                    return max(-100, min(100, gradient))
            return 0.0
        except:
            return 0.0
    
    def _calculate_momentum_gradient(self, df):
        """短期モメンタム勾配"""
        try:
            # 3期間モメンタム
            if len(df) >= 6:
                current_momentum = df['close'].iloc[-1] / df['close'].iloc[-4]
                past_momentum = df['close'].iloc[-3] / df['close'].iloc[-6]
                
                gradient = ((current_momentum - past_momentum) / past_momentum) * 100
                return max(-100, min(100, gradient))
            return 0.0
        except:
            return 0.0
    
    def _calculate_short_rsi_gradient(self, df):
        """短期RSI勾配"""
        try:
            # 7期間RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=7).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=7).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            if len(rsi) >= 3:
                current = rsi.iloc[-1]
                past = rsi.iloc[-3]
                gradient = current - past  # RSIは差分
                return max(-50, min(50, gradient))  # RSI用の範囲調整
            return 0.0
        except:
            return 0.0
    
    def _calculate_price_velocity(self, df):
        """価格勢い（velocity）"""
        try:
            if len(df) >= 3:
                # 直近3期間の価格変化率
                current = df['close'].iloc[-1]
                past = df['close'].iloc[-3]
                if past != 0:
                    velocity = ((current - past) / past) * 100
                    return max(-100, min(100, velocity))
            return 0.0
        except:
            return 0.0
    
    def _calculate_15min_composite(self, gradients, tf_name):
        """15分以内保有特化複合スコア"""
        try:
            # 時間軸別重み付け
            weights = self._get_15min_weights(tf_name)
            
            composite = (
                gradients['ema_fast'] * weights['ema_fast'] +
                gradients['ema_medium'] * weights['ema_medium'] +
                gradients['macd'] * weights['macd'] +
                gradients['momentum'] * weights['momentum'] +
                gradients['price_velocity'] * weights['price_velocity']
            )
            
            return round(composite, 2)
        except:
            return 0.0
    
    def _get_15min_weights(self, tf_name):
        """時間軸別重み設定（15分以内特化）"""
        
        # 超短期（30秒〜2分）: 瞬発力重視
        if tf_name in ['30sec', '1min', '2min']:
            return {
                'ema_fast': 0.4,        # 瞬発力最重視
                'ema_medium': 0.2,
                'macd': 0.2,
                'momentum': 0.15,
                'price_velocity': 0.05
            }
        
        # 短期（3分〜5分）: バランス重視
        elif tf_name in ['3min', '5min']:
            return {
                'ema_fast': 0.3,
                'ema_medium': 0.25,
                'macd': 0.25,
                'momentum': 0.15,
                'price_velocity': 0.05
            }
        
        # 中期（10分〜15分）: 持続性重視
        else:
            return {
                'ema_fast': 0.2,
                'ema_medium': 0.3,      # 持続性重視
                'macd': 0.3,
                'momentum': 0.15,
                'price_velocity': 0.05
            }
    
    def generate_15min_optimized_pattern(self, historical_data):
        """15分最適化パターン生成"""
        print("⚡ 15分以内保有最適化勾配分析開始")
        print("=" * 60)
        
        # 時間軸別リサンプル
        print("📊 短期特化時間軸リサンプル:")
        df_indexed = historical_data.set_index('timestamp')
        timeframe_data = {}
        
        for tf_name, freq in self.timeframes.items():
            try:
                resampled = df_indexed.resample(freq).agg({
                    'open': 'first',
                    'high': 'max',
                    'low': 'min',
                    'close': 'last'
                }).dropna()
                
                timeframe_data[tf_name] = resampled
                importance = self.timeframe_importance[tf_name]
                print(f"   {tf_name:>6}: {len(resampled):>4}本 (重要度: {importance:.2f})")
                
            except Exception as e:
                print(f"   {tf_name:>6}: エラー - {e}")
                timeframe_data[tf_name] = pd.DataFrame()
        
        # 各時間軸の詳細勾配計算
        print("\n⚡ 15分特化勾配計算:")
        optimized_pattern = {}
        
        for tf_name in self.timeframes.keys():
            if tf_name in timeframe_data and not timeframe_data[tf_name].empty:
                gradients = self.analyze_entry_timing_gradients(timeframe_data[tf_name], tf_name)
                optimized_pattern[tf_name] = gradients
                
                importance = self.timeframe_importance[tf_name]
                weighted_score = gradients['composite'] * importance
                
                print(f"   {tf_name:>6}: {gradients['composite']:>8.2f}% " + 
                      f"(重み付け: {weighted_score:>6.2f}) " +
                      f"[EMA:{gradients['ema_fast']:>5.1f}, MACD:{gradients['macd']:>5.1f}]")
            else:
                optimized_pattern[tf_name] = self._get_empty_gradients()
                print(f"   {tf_name:>6}: データ不足")
        
        return optimized_pattern
    
    def get_15min_summary(self, optimized_pattern):
        """15分特化サマリー"""
        # フェーズ別分析
        phases = {
            'エントリー': ['30sec', '1min', '2min'],      # 0-2分
            '初期確認': ['3min', '5min'],                  # 3-5分
            '中期確認': ['10min'],                         # 10分
            '最終確認': ['15min']                          # 15分
        }
        
        summary = {}
        for phase_name, tf_list in phases.items():
            scores = []
            weighted_scores = []
            
            for tf in tf_list:
                if tf in optimized_pattern and optimized_pattern[tf]['composite'] != 0:
                    score = optimized_pattern[tf]['composite']
                    weight = self.timeframe_importance[tf]
                    scores.append(score)
                    weighted_scores.append(score * weight)
            
            if scores:
                summary[phase_name] = {
                    'average': round(np.mean(scores), 2),
                    'weighted_avg': round(sum(weighted_scores), 2),
                    'max': round(max(scores), 2),
                    'min': round(min(scores), 2),
                    'trend': self._get_trend_emoji(np.mean(scores))
                }
            else:
                summary[phase_name] = {
                    'average': 0.0,
                    'weighted_avg': 0.0,
                    'max': 0.0,
                    'min': 0.0,
                    'trend': '❌データなし'
                }
        
        return summary
    
    def _get_trend_emoji(self, score):
        """トレンド絵文字取得"""
        if score > 15:
            return '🚀超強'
        elif score > 5:
            return '🟢強'
        elif score > -5:
            return '🟡中立'
        elif score > -15:
            return '🔴弱'
        else:
            return '💥超弱'
    
    def display_15min_results(self, optimized_pattern, current_price):
        """15分特化結果表示"""
        print("\n" + "=" * 70)
        print("⚡ 15分以内保有最適化勾配分析結果")
        print("=" * 70)
        print(f"💹 現在価格: {current_price:.3f}")
        print(f"⏰ 分析時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # フェーズ別サマリー
        summary = self.get_15min_summary(optimized_pattern)
        print("\n📊 保有フェーズ別分析:")
        for phase, data in summary.items():
            print(f"   {phase:>8}: {data['weighted_avg']:>8.2f}% {data['trend']} " + 
                  f"(平均:{data['average']:>6.1f}%, 最大:{data['max']:>6.1f}%)")
        
        # 重要時間軸詳細
        print("\n🎯 重要時間軸詳細:")
        key_timeframes = ['1min', '3min', '5min', '10min', '15min']
        for tf in key_timeframes:
            if tf in optimized_pattern:
                grad = optimized_pattern[tf]
                importance = self.timeframe_importance[tf]
                weighted = grad['composite'] * importance
                trend = self._get_trend_emoji(grad['composite'])
                print(f"   {tf:>6}: {grad['composite']:>8.2f}% {trend} " + 
                      f"(重み付け: {weighted:>6.2f}, 重要度: {importance:.2f})")
        
        # 15分以内保有推奨判定
        total_weighted_score = sum([
            optimized_pattern[tf]['composite'] * self.timeframe_importance[tf]
            for tf in self.timeframes.keys() 
            if tf in optimized_pattern and optimized_pattern[tf]['composite'] != 0
        ])
        
        if total_weighted_score > 3.0:
            recommendation = "🚀 積極的エントリー推奨"
        elif total_weighted_score > 1.0:
            recommendation = "📈 エントリー推奨"
        elif total_weighted_score > -1.0:
            recommendation = "🟡 様子見推奨"
        elif total_weighted_score > -3.0:
            recommendation = "📉 エントリー非推奨"
        else:
            recommendation = "🔴 エントリー禁止"
        
        print(f"\n🏆 15分以内保有判定: {recommendation}")
        print(f"    総合重み付けスコア: {total_weighted_score:.2f}")
        print(f"    想定保有時間: 1-15分")
        print("=" * 70)

# 使用例
def main():
    """15分最適化勾配分析のデモ"""
    # ダミーデータ生成（実際はリアルタイムデータを使用）
    end_time = datetime.now().replace(second=0, microsecond=0)
    start_time = end_time - timedelta(hours=6)  # 6時間分（15分以内保有には十分）
    
    timestamps = pd.date_range(start=start_time, end=end_time, freq='30s')  # 30秒足
    np.random.seed(42)
    
    base_price = 143.50
    price_changes = np.random.normal(0, 0.002, len(timestamps))  # より短期的な変動
    prices = base_price + np.cumsum(price_changes)
    
    historical_data = pd.DataFrame({
        'timestamp': timestamps,
        'open': prices,
        'high': prices + np.random.uniform(0, 0.005, len(timestamps)),
        'low': prices - np.random.uniform(0, 0.005, len(timestamps)),
        'close': prices
    })
    
    # 15分最適化勾配分析実行
    calculator = Optimized15MinGradientCalculator()
    optimized_pattern = calculator.generate_15min_optimized_pattern(historical_data)
    calculator.display_15min_results(optimized_pattern, prices[-1])

if __name__ == "__main__":
    main()