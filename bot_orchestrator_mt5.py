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
        
    def _prepare_market_summary(self, df, current_price):
        """แปลงข้อมูลแท่งเทียนและราคาจาก MT5 ให้เป็น Text Summary ป้อนให้ AI"""
        if df.empty:
            return f"ไม่สามารถดึงข้อมูลประวัติราคาย้อนหลังจาก MT5 สำหรับ {self.symbol} ได้"
            
        last_row = df.iloc[-1]
        summary = f"ราคา {self.symbol} ล่าสุดจากโบรกเกอร์: {current_price:.2f} USD\n"
        summary += f"ราคาปิดแท่งล่าสุด: {last_row['close']:.2f} | สูงสุด (High): {last_row['high']:.2f} | ต่ำสุด (Low): {last_row['low']:.2f}\n"
        
        # คำนวณ Simple Moving Averages เพื่อบอกเทรนด์
        if len(df) >= 30:
            df_sma10 = df['close'].rolling(10).mean()
            df_sma30 = df['close'].rolling(30).mean()
            
            last_sma10 = df_sma10.iloc[-1]
            last_sma30 = df_sma30.iloc[-1]
            
            trend = "ขาขึ้น (SMA10 > SMA30)" if last_sma10 > last_sma30 else "ขาลง (SMA10 < SMA30)"
            summary += f"เส้นค่าเฉลี่ยระยะสั้น (SMA 10): {last_sma10:.2f}\n"
            summary += f"เส้นค่าเฉลี่ยระยะกลาง (SMA 30): {last_sma30:.2f}\n"
            summary += f"เทรนด์ตลาดปัจจุบัน: {trend}\n"
            
        summary += "\nประวัติแท่งเทียน 5 แท่งล่าสุดจากกราฟจริง:\n"
        for idx, row in df.tail(5).iterrows():
            summary += f"- เวลา {row['timestamp']}: Close {row['close']:.2f} USD (Vol: {row['volume']})\n"
            
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
            logging.info(f"พอร์ตว่างสนิท ไม่มีออเดอร์และคำสั่งล่วงหน้า ดึงกราฟย้อนหลัง {self.symbol}...")
            
            # ดึงแท่งเทียน 15m ย้อนหลัง 100 แท่ง
            df = self.mt5_bridge.get_historical_data(self.symbol, timeframe="15m", num_candles=100)
            market_summary = self._prepare_market_summary(df, current_price)
            
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
                if balance < 100.0 and lot > 0.01:
                    logging.warning(f"เตือน: ขนาดล็อตใหญ่เกินไปสำหรับทุนจริง ปรับลดลงเหลือ 0.01 (เดิมขอ {lot})")
                    lot = 0.01
                    
                logging.info(f"กำลังส่งคำสั่งเทรด: {action} ขนาด {lot} Lot (เป้าหมายราคาเข้า: {entry})...")
                res = self.mt5_bridge.open_position(direction=action, lot=lot, sl=sl, tp=tp, entry=entry, symbol=self.symbol)
                logging.info(f"ผลการทำรายการบนโบรกเกอร์: {res}")
            else:
                logging.info("AI ประเมินว่ายังไม่ควรกระทำการใดๆ ให้รอดูสัญญาณต่อไป (HOLD)")
                
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
                elif action == "BREAK_EVEN":
                    logging.info(f"กำลังเลื่อน Stop Loss ออเดอร์ {ticket_id} กันหน้าทุนที่ {pos['entry_price']}...")
                    self.mt5_bridge.modify_position(ticket_id, new_sl=pos['entry_price'])
                elif action == "TRAILING_STOP":
                    new_sl = decision.get("new_sl")
                    new_tp = decision.get("new_tp")
                    logging.info(f"กำลังขยับจุดตามสัญญาณ Trailing: SL {new_sl} | TP {new_tp}...")
                    self.mt5_bridge.modify_position(ticket_id, new_sl=new_sl, new_tp=new_tp)
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
