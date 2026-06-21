import os
import time
import logging
from mt5_integration import MT5Integration
from trading_agents import TradingAgents

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MT5TradingBotOrchestrator:
    """
    ตัวควบคุมการเทรดจริงบน MT5 (MetaTrader 5 Live Bot Orchestrator)
    ดึงราคาและแท่งเทียนจริงจาก MT5 -> ส่งวิเคราะห์ผ่าน Agent -> ส่งคำสั่งเทรดเข้าโบรกเกอร์จริง
    """
    def __init__(self, api_key, login=None, password=None, server=None, symbol="XAUUSD"):
        self.symbol = symbol
        # 1. โหลดโมดูลเชื่อมต่อ MT5
        self.mt5_bridge = MT5Integration(login=login, password=password, server=server)
        # 2. โหลดโมดูล Agent
        self.agents = TradingAgents(api_key=api_key)
        
    def _prepare_market_summary(self, df, current_price):
        """แปลงข้อมูลแท่งเทียนและราคาจาก MT5 ให้เป็น Text Summary ป้อนให้ AI"""
        if df.empty:
            return "ไม่สามารถดึงข้อมูลประวัติราคาย้อนหลังจาก MT5 ได้"
            
        last_row = df.iloc[-1]
        summary = f"ราคาทองคำ XAUUSD ล่าสุดจากโบรกเกอร์: {current_price:.2f} USD\n"
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
        
        # 1. เชื่อมต่อ MT5
        if not self.mt5_bridge.connect():
            logging.error("ไม่สามารถเชื่อมต่อโปรแกรม MT5 Terminal ได้ ข้ามรอบนี้")
            return
            
        # 2. ดึงราคาและข้อมูลบัญชีล่าสุด
        price_info = self.mt5_bridge.get_current_price(self.symbol)
        acc_status = self.mt5_bridge.get_account_status()
        
        if not price_info or not acc_status:
            logging.error("ดึงข้อมูลราคาหรือข้อมูลพอร์ตจาก MT5 ล้มเหลว")
            return
            
        current_price = price_info["price"]
        balance = acc_status["balance"]
        equity = acc_status["equity"]
        
        logging.info(f"บัญชีเงินจริง: Balance ${balance:.2f} | Equity ${equity:.2f} | ราคาทองตลาด: {current_price} USD")
        
        # 3. ดึงรายการออเดอร์ XAUUSD ที่ค้างอยู่
        open_positions = self.mt5_bridge.get_open_positions(self.symbol)
        
        if not open_positions:
            # ----------------------------------------------------
            # 📌 สาขา A: ไม่มีออเดอร์ค้าง -> วิเคราะห์หาจุดเปิดออเดอร์ใหม่
            # ----------------------------------------------------
            logging.info("พอร์ตว่าง ไม่มีออเดอร์ค้าง ดึงประวัติแท่งเทียนย้อนหลัง...")
            
            # ดึงแท่งเทียน 15m ย้อนหลัง 100 แท่ง
            df = self.mt5_bridge.get_historical_data(self.symbol, timeframe="15m", num_candles=100)
            market_summary = self._prepare_market_summary(df, current_price)
            
            # ส่งข้อมูลให้ AI วิเคราะห์การเทรด
            decision = self.agents.analyze_market(
                market_data_str=market_summary,
                balance=balance,
                leverage=100.0  # สามารถเปลี่ยนให้ดึงอัตโนมัติจาก MT5 ได้
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
                
                # Double Verification (กฎเหล็กความปลอดภัยตรวจสอบขนาดล็อต)
                if balance < 100.0 and lot > 0.01:
                    logging.warning(f"เตือน: ขนาดล็อตใหญ่เกินไปสำหรับทุนจริง ปรับลดลงเหลือ 0.01 (เดิมขอ {lot})")
                    lot = 0.01
                    
                logging.info(f"กำลังส่งคำสั่งเทรดจริง: {action} ขนาด {lot} Lot...")
                res = self.mt5_bridge.open_position(direction=action, lot=lot, sl=sl, tp=tp, symbol=self.symbol)
                logging.info(f"ผลการทำรายการบนโบรกเกอร์: {res}")
            else:
                logging.info("AI ประเมินว่ายังไม่ควรกระทำการใดๆ ให้รอดูสัญญาณต่อไป (HOLD)")
                
        else:
            # ----------------------------------------------------
            # 📌 สาขา B: มีออเดอร์ค้างอยู่ -> ส่งให้ AI จัดการบริหารหน้าไม้เพื่อกันความเสี่ยง
            # ----------------------------------------------------
            logging.info(f"มีออเดอร์ค้างอยู่ใน MT5 ทั้งหมด {len(open_positions)} ไม้")
            
            for pos in open_positions:
                ticket_id = pos['id']
                
                # ส่งสถานะออเดอร์ให้ AI ประเมินการขยับจุดทำกำไร/ขาดทุน
                decision = self.agents.manage_position(
                    position_details=pos,
                    current_price=current_price,
                    balance=balance
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
