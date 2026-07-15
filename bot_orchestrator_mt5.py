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

    def run_cycle(self):
        """
        รันทุกกลยุทธ์ย่อยทีละตัวตามลำดับ (หากไม่มีคิวภายนอกควบคุม)
        """
        for strat_name in ["scalping", "daytrading", "swingtrading"]:
            if self.strategies[strat_name]["enabled"]:
                self.run_strategy_cycle(strat_name)

    def run_strategy_cycle(self, strategy_name):
        """
        รันวงจรการเทรดของแต่ละกลยุทธ์ โดยกลยุทธ์ Scalping จะแบ่งย่อยเป็น 5 กลยุทธ์ย่อยที่มี Magic Number และคำสั่งล่วงหน้าแยกของตนเอง
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
        
        # 4. จัดการตามประเภทกลยุทธ์
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
            
            # ตรวจสอบ Trailing Stop และกำหนดกลยุทธ์ย่อยที่ต้องวิเคราะห์ในลูปนี้
            for sub_name, m_num in scalping_info.items():
                # ตรวจสอบออเดอร์ค้าง (Open Positions) ของกลยุทธ์ย่อยนี้
                sub_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=m_num)
                if sub_positions:
                    # มีออเดอร์ค้าง -> รัน Trailing Stop และไม่อ่านวิเคราะห์เพื่อเปิดเพิ่มในรอบนี้
                    self.manage_trailing_stop(sub_name, sub_positions, strat)
                else:
                    # เช็คว่าหมดช่วง Hold หรือยัง
                    if time.time() >= self.scalping_next_run.get(sub_name, 0.0):
                        strats_to_analyze.append(sub_name)
                
                # ดึงคำสั่งซื้อขายล่วงหน้า (Pending Orders) ของกลยุทธ์ย่อยนี้
                sub_pendings = self.mt5_bridge.get_pending_orders(self.symbol, magic=m_num)
                pending_orders_dict[sub_name] = sub_pendings
                
                # หากมี Pending Order ค้างอยู่ จำเป็นต้องวิเคราะห์เพื่อจัดการ (ลบ/แก้ไข) ถึงแม้จะอยู่ในช่วง Hold
                if sub_pendings and sub_name not in strats_to_analyze and not sub_positions:
                    strats_to_analyze.append(sub_name)
            
            if not strats_to_analyze:
                logging.info("⚡ Live [Autopilot] Scalping: ไม่มีกลยุทธ์ย่อยใดต้องวิเคราะห์ในรอบนี้ (อยู่ในช่วง Hold หรือมีออเดอร์ค้าง)")
                return
                
            logging.info(f"⏰ Live === เริ่มประมวลผลกลยุทธ์ Scalping ประจำรอบ (กลยุทธ์ที่วิเคราะห์: {', '.join(strats_to_analyze)}) ===")
            
            # ดึงประวัติรวมสะสมเพื่อส่งคำนวณสถิติ
            all_scalp_trades = []
            for m_num in [strat["magic"]] + list(scalping_info.values()):
                all_scalp_trades.extend(self.mt5_bridge.get_trade_history(symbol=self.symbol, days=15, magic=m_num))
            perf_stats = PerformanceTracker.calculate_metrics(all_scalp_trades)
            
            # เรียกใช้ตัวประเมิน Regime ตลาดรวม
            df_5m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="5m", num_candles=100)
            df_15m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="15m", num_candles=100)
            df_30m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="30m", num_candles=100)
            regime = self.agents.analyze_market_regime(df_5m, df_15m, df_30m, symbol=self.symbol, num_fast=50, num_slow=30)
            
            # รันการวิเคราะห์รายกลยุทธ์แบบขนานและดึงผลลัพธ์การตัดสินใจ
            df_1m = self.mt5_bridge.get_historical_data(symbol=self.symbol, timeframe="1m", num_candles=100)
            decisions = self.agents.analyze_scalping(
                df_1m=df_1m, df_5m=df_5m, df_15m=df_15m, df_30m=df_30m,
                balance=balance, symbol=self.symbol,
                leverage=100.0, spread=spread,
                performance_stats=perf_stats, trade_history=all_scalp_trades,
                regime_report=regime,
                pending_orders=pending_orders_dict,
                strats_to_analyze=strats_to_analyze
            )
            
            # สั่งการตัดสินใจสำหรับแต่ละกลยุทธ์ย่อยที่ส่งเข้ามา
            for sub_name, decision in decisions.items():
                m_num = scalping_info[sub_name]
                self.execute_decision(sub_name, decision, m_num, pending_orders_dict[sub_name], strat)
                
        else:
            # สำหรับ Day Trading และ Swing Trading
            magic_number = int(strat.get("magic", 123456))
            logging.info(f"⏰ Live === เริ่มรอบการทำงานของกลยุทธ์: {strategy_name.upper()} (Magic: {magic_number}) ===")
            
            open_positions = self.mt5_bridge.get_open_positions(self.symbol, magic=magic_number)
            if open_positions:
                self.manage_trailing_stop(strategy_name, open_positions, strat)
                return
                
            # ตรวจสอบระยะเวลาพักวิเคราะห์ (Hold) เพื่อประหยัด Token
            now = time.time()
            if now < strat.get("next_run_time", 0):
                remaining_sec = strat["next_run_time"] - now
                logging.info(f"⏳ Live [Hold Active] กลยุทธ์ {strategy_name}: อยู่ในช่วงพักวิเคราะห์ เหลือเวลา {int(remaining_sec/60)} นาที {int(remaining_sec%60)} วินาที...")
                return
                
            pending_orders = self.mt5_bridge.get_pending_orders(self.symbol, magic=magic_number)
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
                    pending_orders=pending_orders
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
                    pending_orders=pending_orders
                )
                
            if decision:
                self.execute_decision(strategy_name, decision, magic_number, pending_orders, strat)

    def manage_trailing_stop(self, strategy_name, open_positions, strat):
        """จัดการการเลื่อน trailing stop ตามข้อมูล ATR สำหรับพอร์ตจริง"""
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
            
            price_info = self.mt5_bridge.get_current_price(self.symbol) or {"price": 0.0}
            current_price = price_info.get("price", 0.0)
            
            for pos in open_positions:
                pos_id = pos['id']
                direction = pos['direction']
                entry_price = float(pos['entry_price'])
                current_sl = pos.get('sl', 0.0)
                
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
                
            res = self.mt5_bridge.open_position(
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