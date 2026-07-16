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
        รันวงจรการเทรดของแต่ละกลยุทธ์ (โหมดจำลองตลาด)
        """
        if strategy_name not in self.strategies:
            logging.error(f"ไม่พบข้อมูลกลยุทธ์ {strategy_name}")
            return
            
        strat = self.strategies[strategy_name]
        if not strat.get("enabled", True):
            logging.info(f"🚫 กลยุทธ์ {strategy_name} ถูกปิดใช้งาน ข้ามรอบ")
            return
            
        # 1. ตรวจสอบสถานะตลาดทองคำ
        if self.is_gold_market_open():
            self.symbol = "XAUUSD"
        else:
            self.symbol = "BTCUSD"
            
        # 2. ดึงราคาพอร์ตจำลอง
        price = self.data_feed.get_current_price() or 0.0
        self.exchange.update_price(price)
        
        status = self.exchange.get_status()
        balance = status["balance"]
        
        # 3. จัดการตามประเภทกลยุทธ์
        if strategy_name == "scalping":
            scalping_info = {
                "TREND_PULLBACK": 1001,
                "BREAKOUT": 1002,
                "MEAN_REVERSION": 1003,
                "LIQUIDITY_SWEEP": 1004,
                "MOMENTUM_CONTINUATION": 1005
            }
            
            strats_to_analyze = []
            pending_orders_dict = {}
            
            # ตรวจสอบ Trailing Stop และหาตัวที่สามารถวิเคราะห์ใหม่ได้
            for sub_name, m_num in scalping_info.items():
                sub_positions = self.exchange.get_open_positions(self.symbol, magic=m_num)
                if sub_positions:
                    self.manage_trailing_stop(sub_name, sub_positions, strat)
                else:
                    if time.time() >= self.scalping_next_run.get(sub_name, 0.0):
                        strats_to_analyze.append(sub_name)
                        
                sub_pendings = self.exchange.get_pending_orders(self.symbol, magic=m_num)
                pending_orders_dict[sub_name] = sub_pendings
                
                if sub_pendings and sub_name not in strats_to_analyze and not sub_positions:
                    strats_to_analyze.append(sub_name)
                    
            if not strats_to_analyze:
                logging.info("⚡ [Sim Mode] Scalping: ไม่มีกลยุทธ์ย่อยใดต้องวิเคราะห์ในรอบนี้ (อยู่ในช่วง Hold หรือมีออเดอร์ค้าง)")
                return
                
            logging.info(f"⏰ [Sim Mode] === เริ่มประมวลผลกลยุทธ์ Scalping ประจำรอบ (กลยุทธ์ที่วิเคราะห์: {', '.join(strats_to_analyze)}) ===")
            
            # ดึงประวัติสะสมเพื่อส่งคำนวณสถิติ
            all_scalp_trades = []
            for m_num in [strat["magic"]] + list(scalping_info.values()):
                all_scalp_trades.extend([t for t in status.get("history", []) if t.get("magic") == m_num])
            perf_stats = PerformanceTracker.calculate_metrics(all_scalp_trades)
            
            # เรียกใช้ตัวประเมิน Regime ตลาดรวม
            df_5m = self.data_feed.get_historical_data(interval="5m", period="1d")
            df_15m = self.data_feed.get_historical_data(interval="15m", period="2d")
            df_30m = self.data_feed.get_historical_data(interval="30m", period="2d")
            regime = self.agents.analyze_market_regime(df_5m, df_15m, df_30m, symbol=self.symbol, num_fast=50, num_slow=30)
            
            # รันการวิเคราะห์รายกลยุทธ์แบบขนาน
            df_1m = self.data_feed.get_historical_data(interval="1m", period="1d")
            decisions = self.agents.analyze_scalping(
                df_1m=df_1m, df_5m=df_5m, df_15m=df_15m, df_30m=df_30m,
                balance=balance, symbol=self.symbol,
                leverage=self.exchange.leverage, spread=0.0,
                performance_stats=perf_stats, trade_history=all_scalp_trades,
                regime_report=regime,
                pending_orders=pending_orders_dict,
                strats_to_analyze=strats_to_analyze, quantum_direction=None
            )
            
            # ดำเนินการตามผลการวิเคราะห์
            for sub_name, decision in decisions.items():
                m_num = scalping_info[sub_name]
                self.execute_decision(sub_name, decision, m_num, pending_orders_dict[sub_name], strat)
                
        else:
            magic_number = int(strat.get("magic", 123456))
            logging.info(f"⏰ [Sim Mode] === เริ่มรอบการทำงานของกลยุทธ์: {strategy_name.upper()} (Magic: {magic_number}) ===")
            
            open_positions = self.exchange.get_open_positions(self.symbol, magic=magic_number)
            if open_positions:
                self.manage_trailing_stop(strategy_name, open_positions, strat)
                return
                
            # ตรวจสอบระยะเวลาพักวิเคราะห์
            now = time.time()
            if now < strat.get("next_run_time", 0):
                remaining_sec = strat["next_run_time"] - now
                logging.info(f"⏳ [Hold Active] กลยุทธ์ {strategy_name}: อยู่ในช่วงพักวิเคราะห์ เหลือเวลา {int(remaining_sec/60)} นาที {int(remaining_sec%60)} วินาที...")
                return
                
            pending_orders = self.exchange.get_pending_orders(self.symbol, magic=magic_number)
            closed_trades = [t for t in status.get("history", []) if t.get("magic") == magic_number]
            perf_stats = PerformanceTracker.calculate_metrics(closed_trades)
            
            decision = None
            if strategy_name == "daytrading":
                df_15m = self.data_feed.get_historical_data(interval="15m", period="2d")
                df_1h = self.data_feed.get_historical_data(interval="1h", period="7d")
                df_4h = self.resample_h4(df_1h)
                regime = self.agents.analyze_market_regime(df_15m, df_1h, df_4h, symbol=self.symbol, num_fast=50, num_slow=48)
                decision = self.agents.analyze_daytrading(
                    df_15m=df_15m, df_1h=df_1h, df_4h=df_4h,
                    balance=balance, symbol=self.symbol,
                    leverage=self.exchange.leverage, spread=0.0,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    regime_report=regime,
                    pending_orders=pending_orders, quantum_direction=None
                )
            elif strategy_name == "swingtrading":
                df_1h_30d = self.data_feed.get_historical_data(interval="1h", period="30d")
                df_4h = self.resample_h4(df_1h_30d)
                df_1d = self.data_feed.get_historical_data(interval="1d", period="3mo")
                df_1w = self.data_feed.get_historical_data(interval="1wk", period="1y")
                regime = self.agents.analyze_market_regime(df_4h, df_1d, df_1w, symbol=self.symbol, num_fast=48, num_slow=30)
                decision = self.agents.analyze_swingtrading(
                    df_4h=df_4h, df_1d=df_1d, df_1w=df_1w,
                    balance=balance, symbol=self.symbol,
                    leverage=self.exchange.leverage, spread=0.0,
                    performance_stats=perf_stats, trade_history=closed_trades,
                    regime_report=regime,
                    pending_orders=pending_orders, quantum_direction=None
                )
                
            if decision:
                self.execute_decision(strategy_name, decision, magic_number, pending_orders, strat)

    def manage_trailing_stop(self, strategy_name, open_positions, strat):
        """จัดการการเลื่อน trailing stop ตามข้อมูล ATR สำหรับพอร์ตจำลอง"""
        if strat.get("trailing_enabled", True):
            logging.info(f"⚡ [Sim Mode] กลยุทธ์ {strategy_name}: พบออเดอร์ค้าง {len(open_positions)} ไม้ -> รัน ATR Trailing Stop")
            tf = strat.get("trailing_atr_tf", "5m")
            df_hist = self.data_feed.get_historical_data(interval=tf, period="1d")
            
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
            
            current_price = float(self.data_feed.get_current_price() or 0.0)
            
            for pos in open_positions:
                pos_id = pos['id']
                direction = pos['direction']
                entry_price = float(pos['entry_price'])
                current_sl = float(pos.get('sl', 0.0) or 0.0)
                
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
                    # เรียก modify_sl_tp ซึ่งเป็นชื่อฟังก์ชันที่ถูกต้องใน exchange_sim.py
                    self.exchange.modify_sl_tp(pos_id, new_sl=new_sl, new_tp=pos.get('tp'))
                    logging.info(f"📈 [Sim Mode ATR Trailing Stop] เลื่อน SL ออเดอร์ #{pos_id} ไปที่ {new_sl:.2f}")
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
    def execute_decision(self, strat_name, decision, magic_number, pending_orders, strat_cfg):
        """ดำเนินการจัดการและเปิดออเดอร์คำสั่งซื้อขายในพอร์ตจำลอง"""
        action = decision.get("action")
        reason = decision.get("reasoning")
        ticket = decision.get("ticket")
        logging.info(f"ผลลัพธ์กลยุทธ์ {strat_name} (Magic: {magic_number}): {action} | เหตุผล: {reason}")
        
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
            strat_cfg["next_run_time"] = time.time() + (hold_min * 60)

        if action == "HOLD":
            logging.info(f"พักกลยุทธ์ {strat_name} เป็นเวลา {hold_min} นาที")
            msg = (
                f"🟡 **[Sim Mode - Strategy HOLD]**\n"
                f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol}\n"
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
                    res = self.exchange.modify_pending_order(ticket, price=entry, sl=sl, tp=tp)
                    if res.get("status") == "SUCCESS":
                        msg = (
                            f"🔵 **[Sim Mode - Modify Pending]**\n"
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
                    self.exchange.cancel_pending_order(old_ticket)
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
                
            res = self.exchange.open_position(
                symbol=self.symbol,
                direction=direction,
                lot=lot,
                entry=entry,
                sl=sl,
                tp=tp,
                magic=magic_number
            )
            
            if res.get("status") == "SUCCESS":
                deal_id = res.get("ticket")
                is_pending = res.get("is_pending", False)
                
                if is_pending:
                    msg = (
                        f"🟠 **[Sim Mode - New Pending Order]**\n"
                        f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol} (Magic: {magic_number})\n"
                        f"**Order ID:** #{deal_id} | **Action:** {direction} (Pending)\n"
                        f"**Target:** Entry: {entry} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                else:
                    msg = (
                        f"🟢 **[Sim Mode - New Position Opened]**\n"
                        f"**Strategy:** {strat_name.upper()} | **Asset:** {self.symbol} (Magic: {magic_number})\n"
                        f"**Position ID:** #{deal_id} | **Action:** {direction} (Market Price)\n"
                        f"**Details:** Lot: {lot} | SL: {sl or '-'} | TP: {tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                self.send_discord_message(msg)