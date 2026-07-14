import os
import time
import logging
from datetime import datetime, timezone
from exchange_sim import MockExchange
from data_feed import GoldDataFeed
from trading_agents import TradingAgents
from performance_tracker import PerformanceTracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TradingBotOrchestrator:
    """
    ตัวประสานระบบเทรดอัจฉริยะแบบแยกกลยุทธ์ (Multi-Strategy Simulation Bot Orchestrator)
    """
    def __init__(self, api_key, initial_balance=30.0, leverage=100.0):
        self.exchange = MockExchange(initial_balance=initial_balance, leverage=leverage)
        self.data_feed = GoldDataFeed()
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
        รันวงจรการเทรดเฉพาะของแต่ละกลยุทธ์ เพื่อป้องกันการซ้อนกัน
        """
        if strategy_name not in self.strategies:
            logging.error(f"ไม่พบข้อมูลกลยุทธ์ {strategy_name}")
            return
            
        strat = self.strategies[strategy_name]
        if not strat.get("enabled", True):
            logging.info(f"🚫 กลยุทธ์ {strategy_name} ถูกปิดใช้งาน ข้ามรอบ")
            return
            
        magic_number = int(strat.get("magic", 123456))
        
        logging.info(f"⏰ === เริ่มรอบการทำงานของกลยุทธ์: {strategy_name.upper()} (Magic: {magic_number}) ===")
        
        # 1. ตรวจสอบสถานะตลาดทองคำ
        if self.is_gold_market_open():
            self.symbol = "XAUUSD"
            self.data_feed.symbol = "GC=F"
            self.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
            self.exchange.contract_size = 100.0
        else:
            self.symbol = "BTCUSD"
            self.data_feed.symbol = "BTC-USD"
            self.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
            self.exchange.contract_size = 1.0
            
        # 2. ดึงราคาปัจจุบัน
        current_price = self.data_feed.get_current_price()
        if not current_price:
            logging.error(f"ไม่สามารถตรวจสอบราคาตลาดสำหรับ {self.symbol} ได้ ข้ามรอบ")
            return
            
        self.exchange.update_price(current_price)
        
        # ดึงสถานะคัดกรองตาม Magic Number
        status = self.exchange.get_status(magic=magic_number)
        open_positions = status['open_positions']
        
        # 3. จัดการ ATR Trailing Stop (Python-only)
        if open_positions:
            if strat.get("trailing_enabled", True):
                logging.info(f"⚡ กลยุทธ์ {strategy_name}: พบออเดอร์ค้าง {len(open_positions)} ไม้ -> รัน ATR Trailing Stop (0 Tokens)")
                
                tf = strat.get("trailing_atr_tf", "5m")
                period_map = {"1m": "1d", "5m": "1d", "15m": "2d", "30m": "2d", "1h": "5d"}
                period = period_map.get(tf, "1d")
                
                df_hist = self.data_feed.get_historical_data(interval=tf, period=period)
                df_hist_anal = self.data_feed.analyze_price_action(df_hist)
                
                if not df_hist_anal.empty and 'atr_14' in df_hist_anal.columns:
                    atr = float(df_hist_anal['atr_14'].iloc[-1])
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
                            if current_sl is None or target_sl > float(current_sl):
                                if current_sl is None or (target_sl - float(current_sl)) >= trail_step:
                                    new_sl = target_sl
                                    trail_updated = True
                    elif direction == 'SELL':
                        if entry_price - current_price >= activation_dist:
                            target_sl = current_price + trail_dist
                            if current_sl is None or target_sl < float(current_sl):
                                if current_sl is None or (float(current_sl) - target_sl) >= trail_step:
                                    new_sl = target_sl
                                    trail_updated = True
                                    
                    if trail_updated:
                        self.exchange.modify_sl_tp(pos_id, new_sl=new_sl)
                        logging.info(f"📈 [ATR Trailing Stop] เลื่อน SL ของออเดอร์ {pos_id} ไปที่ {new_sl:.2f}")
                        msg = (
                            f"📈 **[Sim Mode - ATR Trailing Stop]**\n"
                            f"**Order ID:** #{pos_id} | **Asset:** {self.symbol} | **Strategy:** {strategy_name.upper()}\n"
                            f"**Action:** Move SL -> {new_sl:.2f}\n"
                            f"**Reason:** Price moved in favor with ATR-based activation ({activation_dist:.2f} USD)"
                        )
                        self.send_discord_message(msg)
                        pos['sl'] = new_sl
            else:
                logging.info(f"ถือออเดอร์ {len(open_positions)} ไม้ของกลยุทธ์ {strategy_name} ต่อไปโดยไม่มี Trailing Stop")
            return
            
        # 4. ตรวจสอบระยะเวลาพักวิเคราะห์ (Hold) เพื่อประหยัด Token
        now = time.time()
        if now < strat.get("next_run_time", 0):
            remaining_sec = strat["next_run_time"] - now
            logging.info(f"⏳ [Hold Active] กลยุทธ์ {strategy_name}: อยู่ในช่วงพักวิเคราะห์ เหลือเวลา {int(remaining_sec/60)} นาที {int(remaining_sec%60)} วินาที...")
            return
            
        logging.info(f"กลยุทธ์ {strategy_name}: ไม่มีออเดอร์ค้าง รันระบบวิเคราะห์ด้วย Agent...")
        
        # 5. ดึงคำสั่งซื้อขายล่วงหน้า (Pending Orders) และประวัติย้อนหลังของกลยุทธ์นี้
        pending_orders = []
        if strategy_name in ["daytrading", "swingtrading"]:
            pending_orders = self.exchange.get_pending_orders(symbol=self.symbol, magic=magic_number)
            
        closed_trades = status.get('history', [])
        perf_stats = PerformanceTracker.calculate_metrics(closed_trades)
        
        # 6. เรียกใช้กลยุทธ์ย่อย
        decision = None
        if strategy_name == "scalping":
            df_1m = self.data_feed.get_historical_data(interval="1m", period="1d")
            df_5m = self.data_feed.get_historical_data(interval="5m", period="1d")
            df_15m = self.data_feed.get_historical_data(interval="15m", period="2d")
            df_30m = self.data_feed.get_historical_data(interval="30m", period="2d")
            
            regime = self.agents.analyze_market_regime(df_5m, df_15m, df_30m, symbol=self.symbol)
            decision = self.agents.analyze_scalping(
                df_1m=df_1m, df_5m=df_5m, df_15m=df_15m, df_30m=df_30m,
                balance=self.exchange.balance, symbol=self.symbol,
                leverage=self.exchange.leverage, spread=0.0,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime
            )
            
        elif strategy_name == "daytrading":
            df_15m = self.data_feed.get_historical_data(interval="15m", period="2d")
            df_1h = self.data_feed.get_historical_data(interval="1h", period="7d")
            
            def resample_h4(df):
                if df.empty: return df
                d = df.copy()
                d.set_index('timestamp', inplace=True)
                d = d.resample('4H').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
                d.reset_index(inplace=True)
                return d
            df_4h = resample_h4(df_1h)
            
            regime = self.agents.analyze_market_regime(df_15m, df_1h, df_4h, symbol=self.symbol)
            decision = self.agents.analyze_daytrading(
                df_15m=df_15m, df_1h=df_1h, df_4h=df_4h,
                balance=self.exchange.balance, symbol=self.symbol,
                leverage=self.exchange.leverage, spread=0.0,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime,
                pending_orders=pending_orders
            )
            
        elif strategy_name == "swingtrading":
            df_1h = self.data_feed.get_historical_data(interval="1h", period="30d")
            def resample_h4(df):
                if df.empty: return df
                d = df.copy()
                d.set_index('timestamp', inplace=True)
                d = d.resample('4H').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna()
                d.reset_index(inplace=True)
                return d
            df_4h = resample_h4(df_1h)
            df_1d = self.data_feed.get_historical_data(interval="1d", period="3mo")
            df_1w = self.data_feed.get_historical_data(interval="1wk", period="1y")
            
            regime = self.agents.analyze_market_regime(df_4h, df_1d, df_1w, symbol=self.symbol)
            decision = self.agents.analyze_swingtrading(
                df_4h=df_4h, df_1d=df_1d, df_1w=df_1w,
                balance=self.exchange.balance, symbol=self.symbol,
                leverage=self.exchange.leverage, spread=0.0,
                performance_stats=perf_stats, trade_history=closed_trades,
                regime_report=regime,
                pending_orders=pending_orders
            )
            
        if not decision:
            logging.error(f"ไม่ได้รับผลวิเคราะห์สัญญาลักษณ์กลยุทธ์ {strategy_name}")
            return
            
        action = decision.get("action")
        reason = decision.get("reasoning")
        ticket = decision.get("ticket")
        logging.info(f"ผลวิเคราะห์ {strategy_name}: {action} | Reasoning: {reason}")
        
        # 7. ดำเนินการจัดการออเดอร์ตามผลการวิเคราะห์
        # กรองและจำกัดเวลาการพักคำสั่งซื้อขาย (Hold Minutes) ให้สอดคล้องตามกลยุทธ์ย่อยอย่างแม่นยำ
        hold_min_raw = decision.get("hold_minutes")
        try:
            hold_min_val = int(hold_min_raw) if hold_min_raw is not None else None
        except Exception:
            hold_min_val = None

        if strategy_name == "scalping":
            valid_holds = [5, 10, 15, 30]
            if hold_min_val not in valid_holds:
                hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 5
            else:
                hold_min = hold_min_val
        elif strategy_name == "daytrading":
            valid_holds = [30, 60, 240]
            if hold_min_val not in valid_holds:
                hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 30
            else:
                hold_min = hold_min_val
        elif strategy_name == "swingtrading":
            valid_holds = [240, 480, 720]
            if hold_min_val not in valid_holds:
                hold_min = min(valid_holds, key=lambda x: abs(x - hold_min_val)) if hold_min_val is not None else 240
            else:
                hold_min = hold_min_val
        else:
            hold_min = int(hold_min_val or 60)

        if action == "HOLD":
            strat["next_run_time"] = time.time() + (hold_min * 60)
            logging.info(f"พักกลยุทธ์ {strategy_name} เป็นเวลา {hold_min} นาที")
            msg = (
                f"🟡 **[Sim Mode - Strategy HOLD]**\n"
                f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                f"**Action:** HOLD | **Hold Duration:** พัก {hold_min} นาที\n"
                f"**Reason:** {reason}"
            )
            self.send_discord_message(msg)
            
        elif action == "CANCEL":
            if ticket:
                res = self.exchange.cancel_pending_order(ticket)
                if res.get("status") == "SUCCESS":
                    msg = (
                        f"🔴 **[Sim Mode - Cancel Pending]**\n"
                        f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                        f"**Action:** Cancel Pending Order #{ticket}\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
            strat["next_run_time"] = time.time() + (hold_min * 60)
            
        elif action == "MODIFY":
            if ticket:
                entry = decision.get("entry")
                sl = decision.get("sl")
                tp = decision.get("tp")
                if entry:
                    res = self.exchange.modify_pending_order(ticket, price=entry, sl=sl, tp=tp)
                    if res.get("status") == "SUCCESS":
                        msg = (
                            f"🔵 **[Sim Mode - Modify Pending]**\n"
                            f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                            f"**Action:** Modify Pending Order #{ticket}\n"
                            f"**New Target:** Entry: {entry} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                            f"**Reason:** {reason}"
                        )
                        self.send_discord_message(msg)
            strat["next_run_time"] = time.time() + (hold_min * 60)
            
        elif action == "CANCEL_AND_NEW" or action in ["BUY", "SELL"]:
            # ถ้ามี ticket หรือเป็น CANCEL_AND_NEW ให้ยกเลิกคำสั่งเดิมก่อน
            if ticket or action == "CANCEL_AND_NEW":
                old_ticket = ticket or (pending_orders[0]["id"] if pending_orders else None)
                if old_ticket:
                    self.exchange.cancel_pending_order(old_ticket)
                    logging.info(f"ยกเลิกคำสั่งล่วงหน้าเดิม #{old_ticket} ก่อนตั้งคำสั่งใหม่")
            
            direction = decision.get("new_direction") or decision.get("direction") or ("BUY" if action == "BUY" else "SELL")
            if direction not in ["BUY", "SELL"]:
                direction = "BUY"  # Fallback
                
            lot = decision.get("lot", 0.01)
            entry = decision.get("entry")
            sl = decision.get("sl")
            tp = decision.get("tp")
            
            max_allowed_lot = float(strat.get("max_lot", 0.01))
            if lot > max_allowed_lot:
                lot = max_allowed_lot
                
            res = self.exchange.open_position(direction=direction, lot=lot, sl=sl, tp=tp, entry=entry, magic=magic_number)
            
            if res.get("status") == "SUCCESS":
                strat["next_run_time"] = 0
                is_pending = res.get("is_pending", False)
                order_text = "Pending Order" if is_pending else "Market Position"
                icon = "🟡" if is_pending else "🟢"
                msg = (
                    f"{icon} **[Sim Mode - New {order_text}]**\n"
                    f"**Strategy:** {strategy_name.upper()} | **Asset:** {self.symbol}\n"
                    f"**Action:** {direction} | **Lot Size:** {lot:.2f}\n"
                    f"**Price:** {entry or 'Market'}\n"
                    f"**Target:** SL: {sl or '-'} | TP: {tp or '-'}\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
            else:
                logging.error(f"ไม่สามารถทำรายการเปิดออเดอร์ในระบบจำลองได้: {res.get('message')}")
        
        logging.info(f"=== จบรอบกลยุทธ์: {strategy_name.upper()} ===\n")

