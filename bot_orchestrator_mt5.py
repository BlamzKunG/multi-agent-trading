import os
import time
import logging
from datetime import datetime, timezone
from mt5_integration import MT5Integration
from trading_agents import TradingAgents

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MT5TradingBotOrchestrator:
    """
    ตัวควบคุมการเทรดจริงบน MT5 (MetaTrader 5 Live Bot Orchestrator)
    ดึงราคาและแท่งเทียนจริงจาก MT5 -> ส่งวิเคราะห์ผ่าน Agent -> ส่งคำสั่งเทรดเข้าโบรกเกอร์จริง
    """
    def __init__(self, api_key, login=None, password=None, server=None):
        # 1. โหลดโมดูลเชื่อมต่อ MT5
        self.mt5_bridge = MT5Integration(login=login, password=password, server=server)
        # 2. โหลดโมดูล Agent
        self.agents = TradingAgents(api_key=api_key)
        self.symbol = "XAUUSD"

    def send_discord_message(self, message):
        """ส่งข้อความแจ้งเตือนไปยัง Discord Webhook"""
        import requests
        webhook_url = os.environ.get(
            "DISCORD_WEBHOOK_URL",
            "https://discord.com/api/webhooks/1490619446287401121/-3q8Jfe1Hu49gXwL00ZKJkOHjO5CmMQKMe9ixm22YRmIwC0Czy9jV6EhI4muoFqn6JXC"
        )
        try:
            payload = {"content": message}
            response = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logging.error(f"ไม่สามารถส่งการแจ้งเตือนไปยัง Discord ได้: {e}")

    def is_gold_market_open(self):
        """ตรวจสอบว่าตลาดทองคำปิดทำการช่วงวันหยุดเสาร์-อาทิตย์หรือไม่ (อิงเวลา UTC)"""
        now_utc = datetime.now(timezone.utc)
        day = now_utc.weekday()  # 0 = Monday, ..., 6 = Sunday
        hour = now_utc.hour
        
        # ปิดวันเสาร์ (5) และวันอาทิตย์ (6) ทั้งวัน
        if day in [5, 6]:
            return False
        # ปิดวันศุกร์ (4) หลัง 21:00 UTC (ประมาณตี 4 วันเสาร์เวลาไทย)
        if day == 4 and hour >= 21:
            return False
        # ปิดวันจันทร์ (0) ก่อน 00:00 UTC
        if day == 0 and hour < 0:
            return False
        return True
        
    def _prepare_market_summary(self, df_5m, df_15m, df_1h, current_price):
        """แปลงข้อมูลราคาและอินดิเคเตอร์จาก 3 กรอบเวลา (5m, 15m, 1h) ให้เป็นข้อความสรุปเชิงเทคนิคสำหรับ AI"""
        import pandas as pd
        
        summary = f"=== ข้อมูลราคาและอินดิเคเตอร์ Multi-Timeframe สำหรับ {self.symbol} ===\n"
        summary += f"ราคาตลาดล่าสุดจากโบรกเกอร์: {current_price:.2f} USD\n\n"
        
        # 1. วิเคราะห์ กรอบเวลาใหญ่ (HTF) - 1h
        summary += "1. [กรอบเวลา 1 ชั่วโมง - เทรนด์หลักและแนวรับแนวต้านสำคัญ]\n"
        if not df_1h.empty:
            last_row_1h = df_1h.iloc[-1]
            summary += f"- ราคาปิดแท่งล่าสุด (1h): {last_row_1h['close']:.2f}\n"
            if len(df_1h) >= 30:
                df_sma10 = df_1h['close'].rolling(10).mean()
                df_sma30 = df_1h['close'].rolling(30).mean()
                last_sma10 = df_sma10.iloc[-1]
                last_sma30 = df_sma30.iloc[-1]
                trend_1h = "ขาขึ้น (SMA10 > SMA30)" if last_sma10 > last_sma30 else "ขาลง (SMA10 < SMA30)"
                summary += f"- เทรนด์หลัก (1h): {trend_1h} | SMA10: {last_sma10:.2f} | SMA30: {last_sma30:.2f}\n"
            
            # หาจุดสูงสุด/ต่ำสุดใน 20 แท่งล่าสุดเพื่อวิเคราะห์แนวรับแนวต้าน
            if len(df_1h) >= 20:
                recent_20 = df_1h.tail(20)
                highest_20 = recent_20['high'].max()
                lowest_20 = recent_20['low'].min()
                summary += f"- แนวต้านสำคัญช่วงนี้ (High 20h): {highest_20:.2f}\n"
                summary += f"- แนวรับสำคัญช่วงนี้ (Low 20h): {lowest_20:.2f}\n"
        else:
            summary += "- (ไม่สามารถดึงข้อมูล 1h ได้)\n"
            
        summary += "\n"
        
        # 2. วิเคราะห์ กรอบเวลากลาง (ITF) - 15m
        summary += "2. [กรอบเวลา 15 นาที - โครงสร้างราคาและระยะปลอดภัย]\n"
        if not df_15m.empty:
            last_row_15m = df_15m.iloc[-1]
            summary += f"- ราคาปิดแท่งล่าสุด (15m): {last_row_15m['close']:.2f}\n"
            if len(df_15m) >= 30:
                df_sma10 = df_15m['close'].rolling(10).mean()
                df_sma30 = df_15m['close'].rolling(30).mean()
                last_sma10 = df_sma10.iloc[-1]
                last_sma30 = df_sma30.iloc[-1]
                trend_15m = "ขาขึ้น (SMA10 > SMA30)" if last_sma10 > last_sma30 else "ขาลง (SMA10 < SMA30)"
                summary += f"- เทรนด์รอง (15m): {trend_15m} | SMA10: {last_sma10:.2f} | SMA30: {last_sma30:.2f}\n"
                
            # คำนวณ ATR เพื่อใช้วัดความผันผวนหาระยะ Stop Loss
            if len(df_15m) >= 14:
                high_low = df_15m['high'] - df_15m['low']
                high_cp = (df_15m['high'] - df_15m['close'].shift()).abs()
                low_cp = (df_15m['low'] - df_15m['close'].shift()).abs()
                tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                summary += f"- ค่าความผันผวน ATR (14): {atr:.2f} (แนะนำตั้ง SL ห่างอย่างน้อย 1.5 - 2 เท่าของ ATR)\n"
                
            # แสดงประวัติราคา 3 แท่งล่าสุด
            summary += "- ประวัติราคา 3 แท่งล่าสุด (15m):\n"
            for idx, row in df_15m.tail(3).iterrows():
                summary += f"  * เวลา {row['timestamp']}: Open {row['open']:.2f} | Close {row['close']:.2f} | Vol: {row['volume']}\n"
        else:
            summary += "- (ไม่สามารถดึงข้อมูล 15m ได้)\n"
            
        summary += "\n"
        
        # 3. วิเคราะห์ กรอบเวลาเล็ก (LTF) - 5m
        summary += "3. [กรอบเวลา 5 นาที - สัญญาณจุดเข้าซื้อขายปัจจุบัน]\n"
        if not df_5m.empty:
            last_row_5m = df_5m.iloc[-1]
            summary += f"- ราคาปิดแท่งล่าสุด (5m): {last_row_5m['close']:.2f}\n"
            if len(df_5m) >= 30:
                df_sma10 = df_5m['close'].rolling(10).mean()
                df_sma30 = df_5m['close'].rolling(30).mean()
                last_sma10 = df_sma10.iloc[-1]
                last_sma30 = df_sma30.iloc[-1]
                trend_5m = "ขาขึ้น (SMA10 > SMA30)" if last_sma10 > last_sma30 else "ขาลง (SMA10 < SMA30)"
                summary += f"- โมเมนตัมระยะสั้น (5m): {trend_5m}\n"
                
            # แสดงประวัติราคา 3 แท่งล่าสุด
            summary += "- ประวัติราคา 3 แท่งล่าสุด (5m):\n"
            for idx, row in df_5m.tail(3).iterrows():
                summary += f"  * เวลา {row['timestamp']}: Open {row['open']:.2f} | Close {row['close']:.2f} | Vol: {row['volume']}\n"
        else:
            summary += "- (ไม่สามารถดึงข้อมูล 5m ได้)\n"
            
        return summary

    def run_cycle(self):
        """
        รันวงจรการตัดสินใจซื้อขายจริง 1 รอบ
        """
        logging.info("=== เริ่มต้นรอบการทำงานจริงบน MT5 (New Live Cycle) ===")
        
        # 1. ตรวจสอบสถานะตลาดทองคำ (XAUUSD)
        if self.is_gold_market_open():
            self.symbol = "XAUUSD"
            logging.info("ตลาดทองคำเปิดทำการ เลือกเทรดสินทรัพย์หลัก: XAUUSD")
        else:
            self.symbol = "BTCUSD"  # หรือ "BTCUSDT" ตามที่ Broker รองรับ
            logging.info("ตลาดทองคำปิดทำการ (ช่วงวันหยุดเสาร์-อาทิตย์) สลับมาเทรดสินทรัพย์สำรอง: BTCUSD (Bitcoin)")
            
        # 2. เชื่อมต่อ MT5
        if not self.mt5_bridge.connect():
            logging.error("ไม่สามารถเชื่อมต่อโปรแกรม MT5 Terminal ได้ ข้ามรอบนี้")
            return
            
        # 3. ดึงราคาและข้อมูลบัญชีล่าสุด
        price_info = self.mt5_bridge.get_current_price(self.symbol)
        acc_status = self.mt5_bridge.get_account_status()
        
        if not price_info or not acc_status:
            logging.error("ดึงข้อมูลราคาหรือข้อมูลพอร์ตจาก MT5 ล้มเหลว")
            return
            
        current_price = price_info["price"]
        balance = acc_status["balance"]
        equity = acc_status["equity"]
        
        logging.info(f"บัญชีเงินจริง: Balance ${balance:.2f} | Equity ${equity:.2f} | ราคา {self.symbol} ล่าสุด: {current_price} USD")
        
        # 4. ดึงรายการออเดอร์ที่ค้างอยู่ (ทั้งเทรดจริงค้าง และคำสั่งล่วงหน้าที่ยังไม่จับคู่)
        open_positions = self.mt5_bridge.get_open_positions(self.symbol)
        pending_orders = self.mt5_bridge.get_pending_orders(self.symbol)
        
        if not open_positions and not pending_orders:
            # ----------------------------------------------------
            # 📌 สาขา A: พอร์ตว่างสนิท -> วิเคราะห์หาจุดเปิดออเดอร์ใหม่ (Market หรือ Pending)
            # ----------------------------------------------------
            logging.info(f"พอร์ตว่างสนิท ไม่มีออเดอร์และคำสั่งล่วงหน้า ดึงกราฟย้อนหลัง {self.symbol} แบบ Multi-Timeframe (5m, 15m, 1h)...")
            
            # ดึงแท่งเทียนย้อนหลัง 3 กรอบเวลา
            df_5m = self.mt5_bridge.get_historical_data(self.symbol, timeframe="5m", num_candles=100)
            df_15m = self.mt5_bridge.get_historical_data(self.symbol, timeframe="15m", num_candles=100)
            df_1h = self.mt5_bridge.get_historical_data(self.symbol, timeframe="1h", num_candles=100)
            
            market_summary = self._prepare_market_summary(df_5m, df_15m, df_1h, current_price)
            
            # ส่งข้อมูลให้ AI วิเคราะห์การเทรด
            decision = self.agents.analyze_market(
                market_data_str=market_summary,
                balance=balance,
                symbol=self.symbol,
                leverage=100.0
            )
            
            if not decision:
                logging.error("ไม่ได้รับข้อมูลวิเคราะห์จาก AI")
                return
                
            action = decision.get("action")
            reason = decision.get("reasoning")
            logging.info(f"การประเมินจาก AI: {action} | เหตุผล: {reason}")
            
            if action in ["BUY", "SELL"]:
                lot = decision.get("lot", 0.01)
                sl = decision.get("sl")
                tp = decision.get("tp")
                entry = decision.get("entry")
                
                # Double Verification (กฎเหล็กความปลอดภัยตรวจสอบขนาดล็อต)
                max_allowed_lot = getattr(self, 'max_lot', 0.01)
                if lot > max_allowed_lot:
                    logging.warning(f"เตือน: ขนาดล็อตที่ขอมา ({lot}) เกินเพดานสูงสุดที่จำกัดไว้ ({max_allowed_lot}) ปรับล็อตเหลือ {max_allowed_lot}")
                    lot = max_allowed_lot
                elif balance < 100.0 and lot > 0.01:
                    logging.warning(f"เตือน: ขนาดล็อตใหญ่เกินไปสำหรับทุนจริง ปรับลดลงเหลือ 0.01 (เดิมขอ {lot})")
                    lot = 0.01
                    
                logging.info(f"กำลังส่งคำสั่งเทรด: {action} ขนาด {lot} Lot (เป้าหมายราคาเข้า: {entry})...")
                res = self.mt5_bridge.open_position(direction=action, lot=lot, sl=sl, tp=tp, entry=entry, symbol=self.symbol)
                logging.info(f"ผลการทำรายการบนโบรกเกอร์: {res}")
                
                # ส่งแจ้งเตือน Discord
                status_text = "ยิงออเดอร์สำเร็จ" if res.get("status") == "SUCCESS" else f"ล้มเหลว ({res.get('message', '')})"
                msg = (
                    f"🟢 **[MT5 Live - New Position]**\n"
                    f"**Asset:** {self.symbol} | **Action:** {action}\n"
                    f"**Lot Size:** {lot:.2f} | **Target Entry:** {entry or 'Market'}\n"
                    f"**Current Price:** {current_price:.2f} USD\n"
                    f"**Target:** SL: {sl or '-'} | TP: {tp or '-'}\n"
                    f"**Broker Result:** {status_text}\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
            else:
                logging.info("AI ประเมินว่ายังไม่ควรกระทำการใดๆ ให้รอดูสัญญาณต่อไป (HOLD)")
                # ส่งแจ้งเตือน Discord สำหรับ HOLD
                msg = (
                    f"🟡 **[MT5 Live - Analyst Alert]**\n"
                    f"**Asset:** {self.symbol} | **Action:** HOLD (รอดูสัญญาณ)\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
                
        elif pending_orders and not open_positions:
            # ----------------------------------------------------
            # 📌 สาขา B1: มีคำสั่ง Pending Order ค้างอยู่ (ยังไม่จับคู่) -> ส่งให้ AI จัดการ/ยกเลิก
            # ----------------------------------------------------
            logging.info(f"มีคำสั่งล่วงหน้า (Pending Order) รอค้างในระบบ {len(pending_orders)} ไม้")
            
            for ord in pending_orders:
                order_ticket = ord['id']
                
                # จำลองโครงสร้างเพื่อให้ AI ตัวคุมความเสี่ยงเข้าใจได้ (เนื่องจากยังไม่มี P&L เกิดขึ้นจริง)
                ord['pnl'] = 0.0
                ord['entry_price'] = ord['entry_price']  # ราคาเป้าหมายที่รอเข้า
                
                decision = self.agents.manage_position(
                    position_details=ord,
                    current_price=current_price,
                    balance=balance,
                    symbol=self.symbol
                )
                
                if not decision:
                    logging.error(f"ไม่ได้รับแผนจัดการคำสั่งล่วงหน้า {order_ticket} จาก AI")
                    continue
                    
                action = decision.get("action")
                reason = decision.get("reasoning")
                logging.info(f"การจัดการของ AI สำหรับคำสั่งล่วงหน้า {order_ticket}: {action} | เหตุผล: {reason}")
                
                if action == "CLOSE":
                    logging.info(f"กำลังยกเลิกคำสั่งซื้อขายล่วงหน้า Ticket {order_ticket}...")
                    self.mt5_bridge.cancel_pending_order(order_ticket)
                    msg = (
                        f"❌ **[MT5 Live - Cancel Pending]**\n"
                        f"**Order ID:** #{order_ticket} | **Asset:** {self.symbol}\n"
                        f"**Action:** CANCEL PENDING ORDER\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
                else:
                    logging.info(f"คงคำสั่งล่วงหน้า Ticket {order_ticket} ไว้ตามเดิม (HOLD)")
                    
        else:
            # ----------------------------------------------------
            # 📌 สาขา B2: มีออเดอร์ค้างอยู่ (มีผลกำไรขาดทุนวิ่งอยู่) -> ส่งให้ AI คุมความเสี่ยงหน้าไม้
            # ----------------------------------------------------
            logging.info(f"มีออเดอร์ค้างอยู่ (Active Position) ทั้งหมด {len(open_positions)} ไม้")
            
            for pos in open_positions:
                ticket_id = pos['id']
                
                # ส่งสถานะออเดอร์ให้ AI ประเมินการขยับจุดทำกำไร/ขาดทุน
                decision = self.agents.manage_position(
                    position_details=pos,
                    current_price=current_price,
                    balance=balance,
                    symbol=self.symbol
                )
                
                if not decision:
                    logging.error(f"ไม่ได้รับแผนจัดการออเดอร์ {ticket_id} จาก AI")
                    continue
                    
                action = decision.get("action")
                reason = decision.get("reasoning")
                logging.info(f"การจัดการของ AI สำหรับตั๋ว {ticket_id}: {action} | เหตุผล: {reason}")
                
                if action == "CLOSE":
                    logging.info(f"กำลังส่งคำสั่งปิดออเดอร์ Ticket {ticket_id} ทันที...")
                    self.mt5_bridge.close_position(ticket_id, self.symbol)
                    msg = (
                        f"🔴 **[MT5 Live - Close Trade]**\n"
                        f"**Order ID:** #{ticket_id} | **Asset:** {self.symbol}\n"
                        f"**Action:** CLOSE POSITION (สั่งปิดออเดอร์)\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
                elif action == "TRAILING_STOP":
                    new_sl = decision.get("new_sl")
                    new_tp = decision.get("new_tp")
                    logging.info(f"กำลังขยับจุดตามสัญญาณ Trailing: SL {new_sl} | TP {new_tp}...")
                    self.mt5_bridge.modify_position(ticket_id, new_sl=new_sl, new_tp=new_tp)
                    msg = (
                        f"📈 **[MT5 Live - Trailing Stop]**\n"
                        f"**Order ID:** #{ticket_id} | **Asset:** {self.symbol}\n"
                        f"**Action:** Move SL -> {new_sl or '-'} | TP -> {new_tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
                else:
                    logging.info(f"ถือครองออเดอร์ {ticket_id} ต่อไปตามเงื่อนไขเดิม (HOLD)")
                    
        logging.info("=== จบรอบการทำงานจริงบน MT5 ===\n")

if __name__ == "__main__":
    # โหลดค่า API Key
    api_key = os.environ.get("MAXPLUS_API_KEY")
    if not api_key:
        print("กรุณาตั้งค่า: export MAXPLUS_API_KEY='คีย์ของคุณ'")
    else:
        # กำหนดบัญชี MT5 (หากต้องการให้ล็อกอินอัตโนมัติ ให้กรอกข้อมูลด้านล่างนี้)
        # ตัวอย่าง: bot = MT5TradingBotOrchestrator(api_key=api_key, login=123456, password="Password", server="Broker-Server")
        # หากไม่ใส่พารามิเตอร์ บอทจะเชื่อมต่อเข้ากับโปรแกรม MT5 ที่คุณเปิดล็อกอินทิ้งไว้ในเครื่องคอมพิวเตอร์อัตโนมัติ
        bot = MT5TradingBotOrchestrator(api_key=api_key)
        bot.run_cycle()
