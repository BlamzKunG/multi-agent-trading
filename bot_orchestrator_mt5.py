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
            },
            "groq_gen2": {
                "magic": 444444,
                "enabled": True,
                "max_lot": 0.05,
                "trailing_enabled": False,
                "trailing_atr_tf": "15m",
                "trailing_activation_mult": 1.5,
                "trailing_distance_mult": 1.5,
                "trailing_step_mult": 0.3,
                "next_run_time": 0
            },
            "custom_agent": {
                "magic": 555555,
                "enabled": True,
                "max_lot": 0.05,
                "lot_size": 0.01,
                "interval": 5,
                "trailing_enabled": True,
                "trailing_atr_tf": "5m",
                "trailing_activation_mult": 1.5,
                "trailing_distance_mult": 1.0,
                "trailing_step_mult": 0.3,
                "breakeven_enabled": True,
                "breakeven_atr_mult": 1.0,
                "quick_close_profit": 9.0,
                "daily_profit_target": 100.0,
                "daily_loss_limit": 30.0,
                "reverse_mode": False,
                "hold_mode_enabled": False,
                "risk_mode": "ATR",
                "fixed_sl_points": 500,
                "fixed_tp_points": 1000,
                "daily_quota_enabled": True,
                "quick_close_enabled": True,
                "next_run_time": 0
            }
        }
        # ตั้งค่าเริ่มต้นของ groq_gen2 ให้รอเริ่มรันที่รอบ M15 ถัดไปที่ตรง 15 นาทีของชั่วโมง
        import datetime
        now_ts = time.time()
        now_dt = datetime.datetime.fromtimestamp(now_ts)
        minute = now_dt.minute
        next_minute = ((minute // 15) + 1) * 15
        if next_minute >= 60:
            next_dt = now_dt.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
        else:
            next_dt = now_dt.replace(minute=next_minute, second=0, microsecond=0)
        self.strategies["groq_gen2"]["next_run_time"] = next_dt.timestamp()
        self.scalping_next_run = {
            "TREND_PULLBACK": 0.0,
            "BREAKOUT": 0.0,
            "MEAN_REVERSION": 0.0,
            "LIQUIDITY_SWEEP": 0.0,
            "MOMENTUM_CONTINUATION": 0.0
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

    def load_bot_state(self):
        """โหลดสถานะประวัติการเทรดและยืนยันสัญญาณจากไฟล์"""
        import json, os
        state_file = "bot_state.json"
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_triggered_signal_time": {}}
        
    def save_bot_state(self, state):
        """บันทึกสถานะลงไฟล์"""
        import json
        try:
            with open("bot_state.json", "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"ไม่สามารถบันทึกสถานะบอทได้: {e}")


    def run_cycle(self):
        """
        รันทุกกลยุทธ์ย่อยทีละตัวตามลำดับ (หากไม่มีคิวภายนอกควบคุม)
        """
        for strat_name in ["scalping", "daytrading", "swingtrading"]:
            if self.strategies[strat_name]["enabled"]:
                self.run_strategy_cycle(strat_name)

    def run_strategy_cycle(self, strategy_name):
        """
        รันวงจรการเทรดของแต่ละกลยุทธ์ โดยกำหนดทิศทางหลักจาก Quantum TrendPulse Indicator (MT5 Global Variables)
        พร้อมใช้ตรรกะการตรวจสอบการยืนยันราคาปิดย้อนหลังของ M1 / M15 / H1
        """
        if strategy_name not in self.strategies:
            logging.error(f"ไม่พบข้อมูลกลยุทธ์ {strategy_name}")
            return
            
        strat = self.strategies[strategy_name]
        if not strat.get("enabled", True):
            logging.info(f"🚫 Live กลยุทธ์ {strategy_name} ถูกปิดใช้งาน ข้ามรอบ")
            return
            
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
        
        # --- [Quantum TrendPulse Multi-Timeframe Integration] ---
        # ดึงสัญญาณทิศทางจาก 3 ไทม์เฟรมหลัก (M1, M5, M15) จาก MT5 Global Variables
        dir_m1 = self.mt5_bridge.get_global_variable("QUANTUM_M1_DIR")
        dir_m5 = self.mt5_bridge.get_global_variable("QUANTUM_M5_DIR")
        dir_m15 = self.mt5_bridge.get_global_variable("QUANTUM_M15_DIR")
        
        quantum_dir = 0.0
        # ตรวจสอบการพ้องทิศทางไหลไปทางเดียวกันทั้งหมด และต้องไม่ใช่ 0.0 (None)
        if dir_m1 is not None and dir_m5 is not None and dir_m15 is not None:
            if dir_m1 == dir_m5 == dir_m15 and dir_m1 != 0.0:
                quantum_dir = dir_m1
                
        quantum_time = self.mt5_bridge.get_global_variable("QUANTUM_M15_TIME") or 0.0
        quantum_price = self.mt5_bridge.get_global_variable("QUANTUM_M15_PRICE") or 0.0
        
        quantum_direction = None
        if quantum_dir == 1.0:
            quantum_direction = "BUY"
        elif quantum_dir == -1.0:
            quantum_direction = "SELL"
            
        # ดึงคู่ระบุไทม์เฟรมตรวจสอบการคอนเฟิร์ม (Trigger TF)
        trigger_tf = None
        trigger_label = None
        trigger_close = current_price
        confirmation_triggered = False
        last_trig_time = 0.0
        
        if strategy_name not in ["groq_gen2", "custom_agent"]:
            quantum_mapping = {
                "scalping": {"trigger_tf": "1m", "label": "M1"},
                "daytrading": {"trigger_tf": "15m", "label": "M15"},
                "swingtrading": {"trigger_tf": "1h", "label": "H1"}
            }
            
            trigger_tf = quantum_mapping[strategy_name]["trigger_tf"]
            trigger_label = quantum_mapping[strategy_name]["label"]
            
            # ดึงราคาปิดล่าสุดบนแท่ง Trigger
            df_trigger = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe=trigger_tf, num_candles=5)
            if not df_trigger.empty:
                trigger_close = float(df_trigger['close'].iloc[-1])
            else:
                trigger_close = current_price
                
            # จัดการเช็คสถานะการยืนยันราคาปิดที่ได้เปรียบ
            if quantum_direction == "BUY" and quantum_price > 0:
                confirmation_triggered = (trigger_close > quantum_price)
            elif quantum_direction == "SELL" and quantum_price > 0:
                confirmation_triggered = (trigger_close < quantum_price)
                
            state = self.load_bot_state()
            last_trig_time = state.setdefault("last_triggered_signal_time", {}).get(strategy_name, 0.0)
            
            # แสดง Log สถานะสัญญาณจากอินดิเคเตอร์
            if quantum_direction:
                import datetime
                sig_time_str = datetime.datetime.fromtimestamp(quantum_time).strftime('%Y-%m-%d %H:%M:%S') if quantum_time else 'N/A'
                logging.info(f"📊 [Quantum Alignment] ทิศทางหลักพ้องสามไทม์เฟรม (M1/M5/M15): {quantum_direction}")
                logging.info(f"📊 [Quantum TrendPulse] {strategy_name.upper()} -> ราคาเกิดสัญญาณ M15: {quantum_price} | เวลาเกิดสัญญาณ M15: {sig_time_str}")
                logging.info(f"🔍 [Quantum Confirm] ราคาปิดปัจจุบัน {trigger_label}: {trigger_close:.2f} | ราคาอ้างอิง M15: {quantum_price:.2f} | การคอนเฟิร์ม: {'YES' if confirmation_triggered else 'WAITING'}")
            else:
                logging.info(f"⏳ [Quantum Alignment] {strategy_name.upper()} -> สัญญาณสามไทม์เฟรมไม่ตรงกัน หรือไม่มีสัญญาณ: M15={dir_m15 or 0.0}, M5={dir_m5 or 0.0}, M1={dir_m1 or 0.0} (ข้ามการเปิดออเดอร์ใหม่)")
            
        # 4. แบ่งการจัดการตามประเภทกลยุทธ์
        if strategy_name == "scalping":
            scalping_info = {
                "TREND_PULLBACK": 1001,
                "BREAKOUT": 1002,
                "MEAN_REVERSION": 1003,
                "LIQUIDITY_SWEEP": 1004,
                "MOMENTUM_CONTINUATION": 1005
            }
            
            # รัน Trailing Stop สำหรับโพซิชันที่ค้างอยู่เสมอ (ไม่ต้องสนว่ายืนยันสัญญาณหรือไม่)
            for sub_name, m_num in scalping_info.items():
                sub_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=m_num)
                if sub_positions:
                    self.manage_trailing_stop(sub_name, sub_positions, strat)
                    
            # ตรวจสอบการยกเลิก Pending Order เก่าหากทิศทางเปลี่ยน
            for sub_name, m_num in scalping_info.items():
                sub_pendings = self.mt5_bridge.get_pending_orders(self.symbol, magic=m_num)
                if sub_pendings and (not quantum_direction or (quantum_time and quantum_time > last_trig_time)):
                    for p in sub_pendings:
                        self.mt5_bridge.cancel_pending_order(p["id"])
                        logging.info(f"🔴 [Scalping] ยกเลิกคำสั่งล่วงหน้า #{p['id']} เพื่อเคลียร์ออเดอร์เก่ารองรับสัญญาณใหม่")
            
            # หากไม่มีสัญญาณทิศทาง หรือยังไม่ได้รับการคอนเฟิร์มตามเงื่อนไข ให้จบการทำงานรอบนี้ทันที
            if not quantum_direction:
                return
                
            if quantum_time and quantum_time > last_trig_time:
                if not confirmation_triggered:
                    logging.info(f"⏳ [Autopilot] Scalping: สัญญาณใหม่ยังไม่เข้าเงื่อนไขคอนเฟิร์มปิดแท่ง M1 สูงกว่า/ต่ำกว่า {quantum_price:.2f} (ข้ามรอบ)")
                    return
            
            # หากมีสัญญาณที่ยืนยันแล้ว หรือต้องการจัดการ Pending จากสัญญาณปัจจุบัน
            strats_to_analyze = []
            pending_orders_dict = {}
            for sub_name, m_num in scalping_info.items():
                sub_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=m_num)
                sub_pendings = self.mt5_bridge.get_pending_orders(self.symbol, magic=m_num)
                pending_orders_dict[sub_name] = sub_pendings
                
                # อนุญาตให้เข้าวิเคราะห์ได้หากไม่มีสถานะค้าง หรือมี Pending ค้างเพื่อแก้ไข/จัดการ
                if not sub_positions:
                    if time.time() >= self.scalping_next_run.get(sub_name, 0.0) or sub_pendings:
                        strats_to_analyze.append(sub_name)
                        
            if not strats_to_analyze:
                return
                
            logging.info(f"⏰ Live === เริ่มประมวลผลกลยุทธ์ Scalping ประจำรอบ (ทิศทางบังคับ: {quantum_direction}) ===")
            
            all_scalp_trades = []
            for m_num in [strat["magic"]] + list(scalping_info.values()):
                all_scalp_trades.extend(self.mt5_bridge.get_trade_history(symbol=self.symbol, days=15, magic=m_num))
            perf_stats = PerformanceTracker.calculate_metrics(all_scalp_trades)
            
            df_5m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="5m", num_candles=100)
            df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
            df_30m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="30m", num_candles=100)
            regime = self.agents.analyze_market_regime(df_5m, df_15m, df_30m, symbol=self.symbol, num_fast=50, num_slow=30)
            
            df_1m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1m", num_candles=100)
            decisions = self.agents.analyze_scalping(
                df_1m=df_1m, df_5m=df_5m, df_15m=df_15m, df_30m=df_30m,
                balance=balance, symbol=self.symbol,
                leverage=100.0, spread=spread,
                performance_stats=perf_stats, trade_history=all_scalp_trades,
                regime_report=regime,
                pending_orders=pending_orders_dict,
                strats_to_analyze=strats_to_analyze,
                quantum_direction=quantum_direction  # บังคับฝั่งทิศทางจากโมดูล
            )
            
            # บันทึกสถานะการทำรายการ
            if decisions and quantum_time and quantum_time > last_trig_time:
                state["last_triggered_signal_time"]["scalping"] = quantum_time
                self.save_bot_state(state)
                
            for sub_name, decision in decisions.items():
                m_num = scalping_info[sub_name]
                self.execute_decision(sub_name, decision, m_num, pending_orders_dict[sub_name], strat)
                
        else:
            # สำหรับ Day Trading และ Swing Trading
            magic_number = int(strat.get("magic", 123456))
            
            open_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
            if open_positions:
                self.manage_trailing_stop(strategy_name, open_positions, strat)
                return
                
            # ดำเนินการเช็คยอดเป้าหมายรายวัน (Daily Quota check) เฉพาะ Custom Agent
            if strategy_name == "custom_agent" and strat.get("daily_quota_enabled", True):
                closed_trades = self.mt5_bridge.get_trade_history(symbol=self.symbol, days=1, magic=magic_number)
                import datetime
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                closed_today = [t for t in closed_trades if t.get("close_time", "").startswith(today_str)]
                closed_pnl = sum(float(t.get("pnl", 0.0)) for t in closed_today)
                
                open_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
                floating_pnl = sum(float(pos.get("pnl", 0.0)) for pos in open_positions)
                
                daily_pnl = closed_pnl + floating_pnl
                daily_profit_target = float(strat.get("daily_profit_target", 100.0))
                daily_loss_limit = float(strat.get("daily_loss_limit", 30.0))
                
                if daily_pnl >= daily_profit_target:
                    logging.info(f"🟢 [Custom Agent] บรรลุเป้าหมายกำไรรายวัน (${daily_pnl:.2f} >= ${daily_profit_target:.2f}) -> ปิดทุกออเดอร์และหยุดพักถึงเที่ยงคืน")
                    for pos in open_positions:
                        self.mt5_bridge.close_position(pos["id"], symbol=self.symbol, comment="Daily Profit Limit Hit")
                    pending_orders = self.mt5_bridge.get_pending_orders(self.symbol, magic=magic_number)
                    for p in pending_orders:
                        self.mt5_bridge.cancel_pending_order(p["id"])
                    
                    tomorrow = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
                    strat["next_run_time"] = tomorrow.timestamp()
                    return
                    
                if daily_pnl <= -daily_loss_limit:
                    logging.info(f"🔴 [Custom Agent] ชนเพดานขาดทุนรายวัน (${daily_pnl:.2f} <= -${daily_loss_limit:.2f}) -> ปิดทุกออเดอร์และหยุดพักถึงเที่ยงคืน")
                    for pos in open_positions:
                        self.mt5_bridge.close_position(pos["id"], symbol=self.symbol, comment="Daily Loss Limit Hit")
                    pending_orders = self.mt5_bridge.get_pending_orders(self.symbol, magic=magic_number)
                    for p in pending_orders:
                        self.mt5_bridge.cancel_pending_order(p["id"])
                    
                    tomorrow = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
                    strat["next_run_time"] = tomorrow.timestamp()
                    return

            pending_orders = self.mt5_bridge.get_pending_orders(self.symbol, magic=magic_number)
            
            # ลบ Pending เก่าถ้าทิศทางเปลี่ยน (เฉพาะกรณี Day/Swing ที่อิงตามตัวสัญญาณอินดิเคเตอร์หลัก)
            if strategy_name not in ["groq_gen2", "custom_agent"]:
                if pending_orders and (not quantum_direction or (quantum_time and quantum_time > last_trig_time)):
                    for p in pending_orders:
                        self.mt5_bridge.cancel_pending_order(p["id"])
                        logging.info(f"🔴 [{strategy_name.upper()}] ยกเลิกคำสั่งล่วงหน้า #{p['id']} เพื่อเคลียร์ออเดอร์เก่า")
            
            # 3. เช็คความพร้อมของเวลาเทรด (Hold Time)
            now = time.time()
            if now < strat.get("next_run_time", 0) and not pending_orders:
                return
                
            # 4. Agent READY! (เช็คเงื่อนไขทิศทางสำหรับ Day/Swing เท่านั้น ส่วน Groq Gen 2 รันอิสระ)
            if strategy_name not in ["groq_gen2", "custom_agent"]:
                if not quantum_direction:
                    logging.info(f"⏳ [Autopilot] {strategy_name.upper()}: Agent READY แต่รออินดิเคเตอร์พ้องทิศทางกัน (ดองสถานะพร้อมเทรด)")
                    return
                    
                if quantum_time and quantum_time > last_trig_time:
                    if not confirmation_triggered:
                        logging.info(f"⏳ [Autopilot] {strategy_name.upper()}: Agent READY แต่รอยืนยันราคาปิด {trigger_label} ปิด {'สูงกว่า' if quantum_direction == 'BUY' else 'ต่ำกว่า'} Ref: {quantum_price:.2f} (ดองสถานะพร้อมเทรด)")
                        return
                
            closed_trades = self.mt5_bridge.get_trade_history(symbol=self.symbol, days=15, magic=magic_number)
            perf_stats = PerformanceTracker.calculate_metrics(closed_trades)
            
            decision = None
            if strategy_name == "daytrading":
                df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
                df_1h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1h", num_candles=100)
                df_4h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="4h", num_candles=100)
                regime = self.agents.analyze_market_regime(df_15m, df_1h, df_4h, symbol=self.symbol, num_fast=50, num_slow=48)
                decision = self.agents.analyze_daytrading(
                    df_15m=df_15m, df_1h=df_1h, df_4h=df_4h,
                    balance=balance, symbol=self.symbol,
                    leverage=100.0, spread=spread,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    regime_report=regime,
                    pending_orders=pending_orders,
                    quantum_direction=quantum_direction
                )
            elif strategy_name == "swingtrading":
                df_4h = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="4h", num_candles=100)
                df_1d = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1d", num_candles=100)
                df_1w = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1w", num_candles=100)
                regime = self.agents.analyze_market_regime(df_4h, df_1d, df_1w, symbol=self.symbol, num_fast=48, num_slow=30)
                decision = self.agents.analyze_swingtrading(
                    df_4h=df_4h, df_1d=df_1d, df_1w=df_1w,
                    balance=balance, symbol=self.symbol,
                    leverage=100.0, spread=spread,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    regime_report=regime,
                    pending_orders=pending_orders,
                    quantum_direction=quantum_direction
                )
            elif strategy_name == "groq_gen2":
                df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
                df_15m_pa = self.agents._analyze_price_action(df_15m)
                atr_15m = float(df_15m_pa['atr_14'].iloc[-1]) if not df_15m_pa.empty else 0.0
                
                decision = self.agents.analyze_groq_gen2(
                    df_15m=df_15m,
                    balance=balance, symbol=self.symbol,
                    leverage=100.0, spread=spread,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    pending_orders=pending_orders
                )
                
                # ประมวลผลเกณฑ์กรองความมั่นใจ Confidence Filter และระดับคำนวณ ATR Mode
                if decision:
                    action = decision.get("action")
                    confidence = int(decision.get("confidence", 0))
                    entry = decision.get("entry")
                    
                    if action in ["BUY", "SELL", "CANCEL_AND_NEW"]:
                        if confidence < 70:
                            logging.info(f"🟡 [Groq Gen2] สัญญาณความมั่นใจ ({confidence}%) ต่ำกว่าเกณฑ์ขั้นต่ำ 70%. บังคับยกเลิกออเดอร์ (เปลี่ยนเป็น HOLD)")
                            decision["action"] = "HOLD"
                            decision["hold_minutes"] = 15
                        else:
                            # คำนวณระยะ SL/TP ตาม ATR Mode (SL = ATR * 2 | TP = ATR * 3)
                            if entry and entry > 0 and atr_15m > 0:
                                if action == "BUY" or (action == "CANCEL_AND_NEW" and "BUY" in str(decision.get("reasoning", "")).upper()):
                                    decision["sl"] = round(entry - (atr_15m * 2.0), 2)
                                    decision["tp"] = round(entry + (atr_15m * 3.0), 2)
                                else:  # SELL
                                    decision["sl"] = round(entry + (atr_15m * 2.0), 2)
                                    decision["tp"] = round(entry - (atr_15m * 3.0), 2)
                                logging.info(f"📐 [Groq Gen2] คำนวณระยะ ATR Mode สำเร็จ: Entry={entry:.2f} | SL={decision['sl']:.2f} (2xATR) | TP={decision['tp']:.2f} (3xATR)")
            elif strategy_name == "custom_agent":
                df_5m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="5m", num_candles=100)
                df_5m_pa = self.agents._analyze_price_action(df_5m)
                atr_5m = float(df_5m_pa['atr_14'].iloc[-1]) if not df_5m_pa.empty else 0.0
                
                hold_mode_enabled = strat.get("hold_mode_enabled", False)
                nohold_mode = not hold_mode_enabled
                
                decision = self.agents.analyze_custom_agent(
                    df_5m=df_5m,
                    balance=balance, symbol=self.symbol,
                    leverage=100.0, spread=spread,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    pending_orders=pending_orders,
                    nohold_mode=nohold_mode
                )
                
                if decision:
                    action = decision.get("action")
                    confidence = int(decision.get("confidence", 0))
                    
                    # กลับฝั่งสัญญาณ (Reverse Mode)
                    reverse_mode = strat.get("reverse_mode", False)
                    if reverse_mode and action in ["BUY", "SELL"]:
                        old_action = action
                        action = "SELL" if action == "BUY" else "BUY"
                        decision["action"] = action
                        logging.info(f"🔄 [Custom Agent] เปิดใช้งาน Reverse Mode: สลับคำสั่งจาก {old_action} เป็น {action}")
                        
                    if action in ["BUY", "SELL"]:
                        if confidence < 70:
                            logging.info(f"🟡 [Custom Agent] สัญญาณความมั่นใจ ({confidence}%) ต่ำกว่าเกณฑ์ขั้นต่ำ 70%. บังคับข้ามรอบ (เปลี่ยนเป็น HOLD)")
                            decision["action"] = "HOLD"
                            decision["hold_minutes"] = 5
                        else:
                            risk_mode = strat.get("risk_mode", "ATR")
                            lot_size = float(strat.get("lot_size", 0.01))
                            decision["lot"] = lot_size
                            
                            # ตัดสินใจการส่งราคาเข้า: อิงตาม entry_type (MARKET หรือ PENDING)
                            entry_type = decision.get("entry_type", "MARKET")
                            entry_price_val = float(decision.get("entry") or current_price)
                            ref_price = current_price if entry_type == "MARKET" else entry_price_val
                            decision["entry"] = ref_price
                            decision["entry_type"] = entry_type
                            
                            # คำนวณ SL / TP
                            if risk_mode == "ATR":
                                if action == "BUY":
                                    decision["sl"] = round(ref_price - (atr_5m * 2.0), 2)
                                    decision["tp"] = round(ref_price + (atr_5m * 3.0), 2)
                                else:
                                    decision["sl"] = round(ref_price + (atr_5m * 2.0), 2)
                                    decision["tp"] = round(ref_price - (atr_5m * 3.0), 2)
                                logging.info(f"📐 [Custom Agent] คำนวณ SL/TP (ATR Mode): SL={decision['sl']:.2f} (2xATR) | TP={decision['tp']:.2f} (3xATR)")
                            else: # Fixed Mode
                                sym_info = mt5.symbol_info(self.mt5_bridge.resolve_symbol(self.symbol))
                                point = sym_info.point if sym_info else 0.01
                                fixed_sl = float(strat.get("fixed_sl_points", 500)) * point
                                fixed_tp = float(strat.get("fixed_tp_points", 1000)) * point
                                if action == "BUY":
                                    decision["sl"] = round(ref_price - fixed_sl, 2)
                                    decision["tp"] = round(ref_price + fixed_tp, 2)
                                else:
                                    decision["sl"] = round(ref_price + fixed_sl, 2)
                                    decision["tp"] = round(ref_price - fixed_tp, 2)
                                logging.info(f"📐 [Custom Agent] คำนวณ SL/TP (Fixed Points Mode): SL={decision['sl']:.2f} | TP={decision['tp']:.2f}")
                            
                            # จัดการจับชนและสลับออเดอร์เก่าฝั่งตรงข้าม (Part 4)
                            # เช็คออเดอร์ค้างของ Magic นี้
                            open_pos_custom = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
                            if open_pos_custom:
                                existing_pos = open_pos_custom[0]
                                existing_dir = existing_pos["direction"]
                                if existing_dir == action:
                                    logging.info(f"⚖️ [Custom Agent] ทิศทางออเดอร์ใหม่ ({action}) ตรงกับออเดอร์ที่ถืออยู่ ({existing_dir}) -> ถือออเดอร์เดิมต่อ")
                                    decision["action"] = "HOLD"
                                else:
                                    logging.info(f"⚖️ [Custom Agent] ทิศทางใหม่ ({action}) สวนทางออเดอร์เดิม ({existing_dir}) -> สั่งปิดออเดอร์เก่า Ticket #{existing_pos['id']} ทันที")
                                    self.mt5_bridge.close_position(existing_pos["id"], symbol=self.symbol, comment="Custom Agent Flip Close")
                            
                    elif action == "HOLD":
                        # สัญญาณเป็น HOLD -> สั่งปิดออเดอร์ค้างที่มีทั้งหมดของ Magic นี้
                        open_pos_custom = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
                        if open_pos_custom:
                            for pos in open_pos_custom:
                                logging.info(f"⚖️ [Custom Agent] สัญญาณ AI สั่ง HOLD -> ปิดออเดอร์ค้าง Ticket #{pos['id']}")
                                self.mt5_bridge.close_position(pos["id"], symbol=self.symbol, comment="Custom Agent HOLD Close")
                
            if decision:
                if strategy_name not in ["groq_gen2", "custom_agent"] and quantum_time and quantum_time > last_trig_time:
                    state["last_triggered_signal_time"][strategy_name] = quantum_time
                    self.save_bot_state(state)
                self.execute_decision(strategy_name, decision, magic_number, pending_orders, strat)


    def manage_trailing_stop(self, strategy_name, open_positions, strat):
        """จัดการการเลื่อน trailing stop, breakeven และเป้ารวบล็อกกำไร"""
        # 1. เช็คเป้ารวบล็อกกำไร (Quick Profit Close) ทุกๆ 10 วินาที
        quick_close = float(strat.get("quick_close_profit", 0.0) or 0.0)
        if quick_close > 0.0 and strat.get("quick_close_enabled", True):
            total_float_pnl = sum(float(pos.get("pnl", 0.0)) for pos in open_positions)
            if total_float_pnl >= quick_close:
                logging.info(f"💰 [{strategy_name.upper()}] กำไรรวมของออเดอร์ลอยตัว (${total_float_pnl:.2f}) ถึงเป้า Quick Close (${quick_close:.2f}) -> สั่งปิดทุกไม้ทันที!")
                for pos in open_positions:
                    self.mt5_bridge.close_position(pos["id"], symbol=self.symbol, comment=f"{strategy_name.upper()} Quick Profit Close")
                return

        # 2. จัดการ Breakeven (กันทุน)
        if strat.get("breakeven_enabled", False):
            tf = strat.get("trailing_atr_tf", "5m")
            df_hist = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe=tf, num_candles=50)
            if not df_hist.empty:
                df_pa = self.agents._analyze_price_action(df_hist)
                atr = float(df_pa['atr_14'].iloc[-1])
                be_mult = float(strat.get("breakeven_atr_mult", 1.0))
                be_dist = atr * be_mult
                
                for pos in open_positions:
                    pos_id = pos["id"]
                    direction = pos["direction"]
                    entry = pos["entry_price"]
                    current_sl = pos.get("sl", 0.0)
                    floating_profit = float(pos.get("pnl", 0.0))
                    
                    price_info = self.mt5_bridge.get_current_price(self.symbol)
                    if price_info:
                        curr_price = price_info["price"]
                        
                        # เช็คจุดเพื่อขยับกันทุน
                        if direction == "BUY":
                            # กำไรบวกเกินระยะเบรกอีเวน และ SL ยังไม่ได้เลื่อนมาที่จุดเข้า
                            if (curr_price - entry >= be_dist) and (current_sl < entry):
                                self.mt5_bridge.modify_position(pos_id, new_sl=entry, new_tp=pos.get("tp"))
                                logging.info(f"🛡️ [{strategy_name.upper()}] ขยับราคา SL มาจุดบังทุน (Breakeven) สำเร็จที่ราคา {entry:.2f}")
                        else: # SELL
                            if (entry - curr_price >= be_dist) and (current_sl == 0.0 or current_sl > entry):
                                self.mt5_bridge.modify_position(pos_id, new_sl=entry, new_tp=pos.get("tp"))
                                logging.info(f"🛡️ [{strategy_name.upper()}] ขยับราคา SL มาจุดบังทุน (Breakeven) สำเร็จที่ราคา {entry:.2f}")

        # 3. จัดการ Trailing Stop
        if strat.get("trailing_enabled", True):
            logging.info(f"⚡ Live กลยุทธ์ {strategy_name}: พบออเดอร์ค้าง {len(open_positions)} ไม้ -> รัน ATR Trailing Stop (0 Tokens)")
            tf = strat.get("trailing_atr_tf", "5m")
            df_hist = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe=tf, num_candles=100)
            
            if not df_hist.empty:
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
            
            price_info = self.mt5_bridge.get_current_price(self.symbol) or {"price": 0.0, "bid": 0.0, "ask": 0.0}
            
            for pos in open_positions:
                pos_id = pos['id']
                direction = pos['direction']
                entry_price = float(pos['entry_price'])
                current_sl = float(pos.get('sl', 0.0) or 0.0)
                
                # ดึงราคารายฝั่งจริงในการปิดตำแหน่ง (Bid สำหรับ Buy, Ask สำหรับ Sell)
                if direction == 'BUY':
                    current_price = price_info.get("bid", price_info.get("price", 0.0))
                else:
                    current_price = price_info.get("ask", price_info.get("price", 0.0))
                
                trail_updated = False
                new_sl = None
                
                if direction == 'BUY':
                    if current_price - entry_price >= activation_dist:
                        target_sl = current_price - trail_dist
                        if current_sl == 0.0 or target_sl > current_sl:
                            if current_sl == 0.0 or (target_sl - current_sl) >= trail_step:
                                new_sl = target_sl
                                trail_updated = True
                elif direction == 'SELL':
                    if entry_price - current_price >= activation_dist:
                        target_sl = current_price + trail_dist
                        if current_sl == 0.0 or target_sl < current_sl:
                            if current_sl == 0.0 or (current_sl - target_sl) >= trail_step:
                                new_sl = target_sl
                                trail_updated = True
                                
                if trail_updated:
                    import MetaTrader5 as mt5
                    sym_info = mt5.symbol_info(self.mt5_bridge.resolve_symbol(self.symbol))
                    if sym_info:
                        new_sl = round(round(new_sl / sym_info.trade_tick_size) * sym_info.trade_tick_size, sym_info.digits)
                        
                    # เรียก modify_position ซึ่งเป็นชื่อฟังก์ชันที่ถูกต้องใน mt5_integration.py
                    self.mt5_bridge.modify_position(pos_id, new_sl=new_sl, new_tp=pos.get('tp'))
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
    def execute_decision(self, strat_name, decision, magic_number, pending_orders, strat_cfg):
        """ดำเนินการจัดการและเปิดออเดอร์คำสั่งซื้อขายตามการตัดสินใจ"""
        action = decision.get("action")
        reason = decision.get("reasoning")
        ticket = decision.get("ticket")
        logging.info(f"Live ผลลัพธ์กลยุทธ์ {strat_name} (Magic: {magic_number}): {action} | เหตุผล: {reason}")
        
        # กรองและจำกัดเวลาการพักคำสั่งซื้อขาย (Hold Minutes) ให้สอดคล้องตามกลยุทธ์ย่อยอย่างแม่นยำ
        hold_min_raw = decision.get("hold_minutes")
        try:
            hold_min_val = int(hold_min_raw) if hold_min_raw is not None else None
        except Exception:
            hold_min_val = None

        if strat_name in self.scalping_next_run:
            valid_holds = [5, 10, 15, 30]
            if hold_min_val not in valid_holds:
                hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 5
            else:
                hold_min = hold_min_val
            # ตั้งเวลา hold สำหรับกลยุทธ์ย่อยนี้
            self.scalping_next_run[strat_name] = time.time() + (hold_min * 60)
        else:
            if strat_name == "daytrading":
                valid_holds = [30, 60, 240]
                if hold_min_val not in valid_holds:
                    hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 30
                else:
                    hold_min = hold_min_val
            elif strat_name == "swingtrading":
                valid_holds = [240, 480, 720]
                if hold_min_val not in valid_holds:
                    hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 240
                else:
                    hold_min = hold_min_val
            else:
                hold_min = int(hold_min_val or 60)
            
            if strat_name == "groq_gen2":
                hold_min = int(hold_min_val or 15)
                # คำนวณหาเวลาเปิดแท่ง M15 ถัดไปที่ตรงรอบนาที 0, 15, 30, 45 ของชั่วโมง
                import datetime
                now_ts = time.time()
                now_dt = datetime.datetime.fromtimestamp(now_ts)
                minute = now_dt.minute
                current_m15_minute = (minute // 15) * 15
                base_dt = now_dt.replace(minute=current_m15_minute, second=0, microsecond=0)
                next_dt = base_dt + datetime.timedelta(minutes=hold_min)
                if next_dt.timestamp() <= now_ts:
                    next_dt += datetime.timedelta(minutes=15)
                strat_cfg["next_run_time"] = next_dt.timestamp()
                logging.info(f"⏰ [Groq Gen2] กำหนดรอบการวิเคราะห์แท่งถัดไปที่เวลาลงตัว: {next_dt.strftime('%H:%M:%S')}")
            else:
                strat_cfg["next_run_time"] = time.time() + (hold_min * 60)

        if action == "HOLD":
            logging.info(f"Live พักกลยุทธ์ {strat_name} เป็นเวลา {hold_min} นาที")
            msg = (
                f"🟡 **[MT5 Live - Strategy HOLD]**\n"
                f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol}\n"
                f"**Action:** HOLD | **Hold Duration:** พัก {hold_min} นาที\n"
                f"**Reason:** {reason}"
            )
            self.send_discord_message(msg)
            
        elif action == "CANCEL":
            if ticket:
                res = self.mt5_bridge.cancel_pending_order(ticket)
                if res.get("status") == "SUCCESS":
                    msg = (
                        f"🔴 **[MT5 Live - Cancel Pending]**\n"
                        f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol}\n"
                        f"**Action:** Cancel Pending Order #{ticket}\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
            
        elif action == "MODIFY":
            if ticket:
                entry = decision.get("entry")
                sl = decision.get("sl")
                tp = decision.get("tp")
                if entry:
                    res = self.mt5_bridge.modify_pending_order(ticket, price=entry, sl=sl, tp=tp)
                    if res.get("status") == "SUCCESS":
                        msg = (
                            f"🔵 **[MT5 Live - Modify Pending]**\n"
                            f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol}\n"
                            f"**Action:** Modify Pending Order #{ticket}\n"
                            f"**New Target:** Entry: {entry} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                            f"**Reason:** {reason}"
                        )
                        self.send_discord_message(msg)
            
        elif action == "CANCEL_AND_NEW" or action in ["BUY", "SELL"]:
            if ticket or action == "CANCEL_AND_NEW":
                old_ticket = ticket or (pending_orders[0]["id"] if pending_orders else None)
                if old_ticket:
                    self.mt5_bridge.cancel_pending_order(old_ticket)
                    logging.info(f"ยกเลิกคำสั่งล่วงหน้าเดิม #{old_ticket} ก่อนตั้งคำสั่งใหม่")
            
            direction = decision.get("new_direction") or decision.get("direction") or ("BUY" if action == "BUY" else "SELL")
            if direction not in ["BUY", "SELL"]:
                direction = "BUY"
                
            lot = decision.get("lot", 0.01)
            entry = decision.get("entry")
            sl = decision.get("sl")
            tp = decision.get("tp")
            
            max_allowed_lot = float(strat_cfg.get("max_lot", 0.01))
            if lot > max_allowed_lot:
                lot = max_allowed_lot
                
            force_market = False
            if strat_name == "groq_gen2":
                force_market = (decision.get("entry_type", "MARKET") == "MARKET")
                
            res = self.mt5_bridge.open_position(
                symbol=self.symbol,
                direction=direction,
                lot=lot,
                entry=entry,
                sl=sl,
                tp=tp,
                magic=magic_number,
                force_market=force_market,
                comment=f"{strat_name.upper()} Agent"
            )
            
            if res.get("status") == "SUCCESS":
                deal_id = res.get("ticket")
                is_pending = res.get("is_pending", False)
                
                if is_pending:
                    msg = (
                        f"🟠 **[MT5 Live - New Pending Order]**\n"
                        f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol} (Magic: {magic_number})\n"
                        f"**Order ID:** #{deal_id} | **Action:** {direction} (Pending)\n"
                        f"**Target:** Entry: {entry} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                else:
                    msg = (
                        f"🟢 **[MT5 Live - New Position Opened]**\n"
                        f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol} (Magic: {magic_number})\n"
                        f"**Position ID:** #{deal_id} | **Action:** {direction} (Market Price)\n"
                        f"**Details:** Lot: {lot} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                self.send_discord_message(msg)