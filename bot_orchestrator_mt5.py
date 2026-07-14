import os
import time
import logging
from datetime import datetime, timezone
from mt5_integration import MT5Integration
from trading_agents import TradingAgents
from performance_tracker import PerformanceTracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MT5TradingBotOrchestrator:
    """
    ตัวควบคุมการเทรดจริงบน MT5 แบบแยกกลยุทธ์ (Multi-Strategy MetaTrader 5 Live Bot Orchestrator)
    """
    def __init__(self, api_key, login=None, password=None, server=None):
        self.mt5_bridge = MT5Integration(login=login, password=password, server=server)
        self.agents = TradingAgents(api_key=api_key)
        self.symbol = "XAUUSD"
        
        # โครงสร้างสำหรับเก็บคอนฟิกแยกรายกลยุทธ์
        self.strategies = {
            "scalping": {
                "magic": 111111,
                "enabled": True,
                "max_lot": 0.05,
                "trailing_enabled": True,
                "trailing_atr_tf": "5m",
                "trailing_activation_mult": 1.5,
                "trailing_distance_mult": 1.5,
                "trailing_step_mult": 0.3,
                "next_run_time": 0
            },
            "daytrading": {
                "magic": 222222,
                "enabled": True,
                "max_lot": 0.05,
                "trailing_enabled": True,
                "trailing_atr_tf": "15m",
                "trailing_activation_mult": 1.5,
                "trailing_distance_mult": 1.5,
                "trailing_step_mult": 0.3,
                "next_run_time": 0
            },
            "swingtrading": {
                "magic": 333333,
                "enabled": True,
                "max_lot": 0.05,
                "trailing_enabled": False,
                "trailing_atr_tf": "1h",
                "trailing_activation_mult": 1.5,
                "trailing_distance_mult": 1.5,
                "trailing_step_mult": 0.3,
                "next_run_time": 0
            }
        }

    def send_discord_message(self, message):
        """ส่งข้อความแจ้งเตือนไปยัง Discord Webhook"""
        import requests
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            return
        try:
            payload = {"content": message}
            requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        except Exception as e:
            logging.error(f"ไม่สามารถส่งการแจ้งเตือนไปยัง Discord ได้: {e}")

    def is_gold_market_open(self):
        """ตรวจสอบว่าตลาดทองคำปิดทำการช่วงวันหยุดหรือไม่ (อิงเวลา UTC)"""
        now_utc = datetime.now(timezone.utc)
        day = now_utc.weekday()
        hour = now_utc.hour
        
        if day in [5, 6]:
            return False
        if day == 4 and hour >= 21:
            return False
        if day == 0 and hour < 0:
            return False
        return True

    def run_cycle(self):
        """
        รันทุกกลยุทธ์ย่อยทีละตัวตามลำดับ (หากไม่มีคิวภายนอกควบคุม)
        """
        for strat_name in ["scalping", "daytrading", "swingtrading"]:
            if self.strategies[strat_name]["enabled"]:
                self.run_strategy_cycle(strat_name)

    def run_strategy_cycle(self, strategy_name):
        """
        รันวงจรการเทรดเฉพาะของแต่ละกลยุทธ์บน MT5 พอร์ตจริง
        """
        if strategy_name not in self.strategies:
            logging.error(f"ไม่พบข้อมูลกลยุทธ์ {strategy_name}")
            return
            
        strat = self.strategies[strategy_name]
        if not strat.get("enabled", True):
            logging.info(f"🚫 Live กลยุทธ์ {strategy_name} ถูกปิดใช้งาน ข้ามรอบ")
            return
            
        magic_number = int(strat.get("magic", 123456))
        
        logging.info(f"⏰ Live === เริ่มรอบการทำงานของกลยุทธ์: {strategy_name.upper()} (Magic: {magic_number}) ===")
        
        # 1. ตรวจสอบสถานะตลาดทองคำ
        if self.is_gold_market_open():
            self.symbol = "XAUUSD"
        else:
            self.symbol = "BTCUSD"
            
        # 2. เชื่อมต่อ MT5
        if not self.mt5_bridge.connect():
            logging.error("ไม่สามารถเชื่อมต่อโปรแกรม MT5 Terminal ได้ ข้ามรอบนี้")
            return
            
        # 3. ดึงราคาและพอร์ตล่าสุด
        price_info = self.mt5_bridge.get_current_price(self.symbol)
        acc_status = self.mt5_bridge.get_account_status()
        
        if not price_info or not acc_status:
            logging.error("ดึงข้อมูลราคาหรือข้อมูลพอร์ตจาก MT5 ล้มเหลว ข้ามรอบ")
            return
            
        current_price = price_info["price"]
        spread = price_info.get("spread", 0.0)
        balance = acc_status["balance"]
        equity = acc_status["equity"]
        
        # ดึงสถานะคัดกรองตาม Magic Number
        open_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
        
        # 4. จัดการ ATR Trailing Stop สำหรับออเดอร์เปิดอยู่
        if open_positions:
            if strat.get("trailing_enabled", True):
                logging.info(f"⚡ Live กลยุทธ์ {strategy_name}: พบออเดอร์ค้าง {len(open_positions)} ไม้ -> รัน ATR Trailing Stop (0 Tokens)")
                
                tf = strat.get("trailing_atr_tf", "5m")
                df_hist = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe=tf, num_candles=100)
                
                if not df_hist.empty:
                    # คำนวณ ATR 14
                    import pandas as pd
                    high_low = df_hist['high'] - df_hist['low']
                    high_cp = (df_hist['high'] - df_hist['close'].shift()).abs()
                    low_cp = (df_hist['low'] - df_hist['close'].shift()).abs()
                    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
                    atr = tr.rolling(14).mean().iloc[-1]
                else:
                    atr = 1.50 if "XAU" in self.symbol.upper() else 50.0
                    
                activation_dist = atr * float(strat.get("trailing_activation_mult", 1.5))
                trail_dist = atr * float(strat.get("trailing_distance_mult", 1.5))
                trail_step = atr * float(strat.get("trailing_step_mult", 0.3))
                
                for pos in open_positions:
                    pos_id = pos['id']
                    direction = pos['direction']
                    entry_price = float(pos['entry_price'])
                    current_sl = pos['sl']
                    
                    trail_updated = False
                    new_sl = None
                    
                    if direction == 'BUY':
                        if current_price - entry_price >= activation_dist:
                            target_sl = current_price - trail_dist
                            if current_sl is None or current_sl == 0 or target_sl > float(current_sl):
                                if current_sl is None or current_sl == 0 or (target_sl - float(current_sl)) >= trail_step:
                                    new_sl = target_sl
                                    trail_updated = True
                    elif direction == 'SELL':
                        if entry_price - current_price >= activation_dist:
                            target_sl = current_price + trail_dist
                            if current_sl is None or current_sl == 0 or target_sl < float(current_sl):
                                if current_sl is None or current_sl == 0 or (float(current_sl) - target_sl) >= trail_step:
                                    new_sl = target_sl
                                    trail_updated = True
                                    
                    if trail_updated:
                        import MetaTrader5 as mt5
                        sym_info = mt5.symbol_info(self.mt5_bridge.resolve_symbol(self.symbol))
                        if sym_info:
                            new_sl = round(round(new_sl / sym_info.trade_tick_size) * sym_info.trade_tick_size, sym_info.digits)
                            
                        self.mt5_bridge.modify_sl_tp(pos_id, new_sl=new_sl)
                        logging.info(f"📈 [Live ATR Trailing Stop] เลื่อน SL ออเดอร์ #{pos_id} ไปที่ {new_sl:.2f}")
                        msg = (
                            f"📈 **[MT5 Live - ATR Trailing Stop]**\n"
                            f"**Order ID:** #{pos_id} | **Asset:** {self.symbol} | **Strategy:** {strategy_name.upper()}\n"
                            f"**Action:** Move SL -> {new_sl:.2f}\n"
                            f"**Reason:** Price moved in favor with ATR-based activation ({activation_dist:.2f} USD)"
                        )
                        self.send_discord_message(msg)
                        pos['sl'] = new_sl
            else:
                logging.info(f"Live: ถือออเดอร์ {len(open_positions)} ไม้ของกลยุทธ์ {strategy_name} ต่อไปโดยไม่มี Trailing Stop")
            return
            
        # 5. ตรวจสอบระยะเวลาพักวิเคราะห์ (Hold) เพื่อประหยัด Token
        now = time.time()
        if now < strat.get("next_run_time", 0):
            remaining_sec = strat["next_run_time"] - now
            logging.info(f"⏳ Live [Hold Active] กลยุทธ์ {strategy_name}: อยู่ในช่วงพักวิเคราะห์ เหลือเวลา {int(remaining_sec/60)} นาที {int(remaining_sec%60)} วินาที...")
            return
            
        logging.info(f"Live กลยุทธ์ {strategy_name}: ไม่มีออเดอร์ค้าง รันระบบวิเคราะห์...")
        
        # 6. ดึงประวัติย้อนหลังและเตรียมข้อมูลสะท้อนตนเอง (Self-Reflection)
        closed_trades = self.mt5_bridge.get_trade_history(symbol=self.symbol, days=15, magic=magic_number)
        perf_stats = PerformanceTracker.calculate_metrics(closed_trades)
        
        # 7. เรียกใช้กลยุทธ์ย่อยวิเคราะห์ตลาดผ่านโมเดล
        decision = None
        if strategy_name == "scalping":
            df_1m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1m", num_candles=100)
            df_5m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="5m", num_candles=100)
            df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
            df_30m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="30m", num_candles=100)
            
            regime = self.agents.analyze_market_regime(df_5m, df_15m, df_30m, symbol=self.symbol)
            decision = self.agents.analyze_scalping(
                df_1m=df_1m, df_5m=df_5m, df_15m=df_15m, df_30m=df_30m,
                balance=balance, symbol=self.symbol,
                leverage=100.0, spread=spread,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime
            )
            
        elif strategy_name == "daytrading":
            df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
            df_1h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1h", num_candles=100)
            df_4h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="4h", num_candles=100)
            
            regime = self.agents.analyze_market_regime(df_15m, df_1h, df_4h, symbol=self.symbol)
            decision = self.agents.analyze_daytrading(
                df_15m=df_15m, df_1h=df_1h, df_4h=df_4h,
                balance=balance, symbol=self.symbol,
                leverage=100.0, spread=spread,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime
            )
            
        elif strategy_name == "swingtrading":
            df_4h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="4h", num_candles=100)
            df_1d = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1d", num_candles=100)
            df_1w = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1w", num_candles=100)
            
            regime = self.agents.analyze_market_regime(df_4h, df_1d, df_1w, symbol=self.symbol)
            decision = self.agents.analyze_swingtrading(
                df_4h=df_4h, df_1d=df_1d, df_1w=df_1w,
                balance=balance, symbol=self.symbol,
                leverage=100.0, spread=spread,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime
            )
            
        if not decision:
            logging.error(f"ไม่ได้รับผลการตัดสินใจของกลยุทธ์ {strategy_name} จาก Agent")
            return
            
        action = decision.get("action")
        reason = decision.get("reasoning")
        logging.info(f"Live ผลลัพธ์กลยุทธ์ {strategy_name}: {action} | เหตุผล: {reason}")
        
        if action in ["BUY", "SELL"]:
            lot = decision.get("lot", 0.01)
            sl = decision.get("sl")
            tp = decision.get("tp")
            
            max_allowed_lot = float(strat.get("max_lot", 0.01))
            if lot > max_allowed_lot:
                lot = max_allowed_lot
                
            res = self.mt5_bridge.open_position(direction=action, lot=lot, sl=sl, tp=tp, magic=magic_number, symbol=self.symbol)
            
            if res.get("status") == "SUCCESS":
                strat["next_run_time"] = 0
                msg = (
                    f"🟢 **[MT5 Live - New Position]**\n"
                    f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                    f"**Action:** {action} | **Lot Size:** {lot:.2f}\n"
                    f"**Target:** SL: {sl or '-'} | TP: {tp or '-'}\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
        else:
            hold_min = int(decision.get("hold_minutes") or 5)
            strat["next_run_time"] = time.time() + (hold_min * 60)
            logging.info(f"Live พักกลยุทธ์ {strategy_name} เป็นเวลา {hold_min} นาที")
            msg = (
                f"🟡 **[MT5 Live - Strategy Alert]**\n"
                f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                f"**Action:** HOLD | **Hold Duration:** พัก {hold_min} นาที\n"
                f"**Reason:** {reason}"
            )
            self.send_discord_message(msg)
            
        logging.info(f"=== จบรอบไลฟ์กลยุทธ์: {strategy_name.upper()} ===\n")
