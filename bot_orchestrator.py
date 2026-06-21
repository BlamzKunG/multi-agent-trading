import os
import time
import logging
from exchange_sim import MockExchange
from data_feed import GoldDataFeed
from trading_agents import TradingAgents

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TradingBotOrchestrator:
    """
    ตัวประสานระบบเทรดอัจฉริยะ (Stateless Trading Bot Orchestrator)
    รวบรวมข้อมูลตลาด -> ส่งวิเคราะห์ผ่าน Agent -> รันคำสั่งจำลองและคุมความเสี่ยง
    """
    def __init__(self, api_key, initial_balance=30.0, leverage=100.0):
        # 1. โหลดโมดูลจำลองโบรกเกอร์
        self.exchange = MockExchange(initial_balance=initial_balance, leverage=leverage)
        # 2. โหลดโมดูลดึงข้อมูลตลาดจริง
        self.data_feed = GoldDataFeed()
        # 3. โหลดโมดูล Agent
        self.agents = TradingAgents(api_key=api_key)
        
    def _prepare_market_summary(self, df):
        """แปลงตารางข้อมูลราคาและอินดิเคเตอร์ให้เป็นข้อความสรุปเพื่อให้ AI เข้าใจง่าย"""
        if df.empty:
            return "ไม่สามารถโหลดข้อมูลราคาล่าสุดได้"
            
        last_row = df.iloc[-1]
        summary = f"ราคาทองล่าสุด (XAUUSD close proxy): {last_row['close']:.2f} USD\n"
        summary += f"จุดสูงสุด (High): {last_row['high']:.2f} | จุดต่ำสุด (Low): {last_row['low']:.2f}\n"
        
        # คำนวณ Simple Moving Averages สั้นๆ เพื่อป้อนเพิ่มให้ AI (เช่น SMA 10 และ SMA 30)
        if len(df) >= 30:
            df_sma10 = df['close'].rolling(10).mean()
            df_sma30 = df['close'].rolling(30).mean()
            
            last_sma10 = df_sma10.iloc[-1]
            last_sma30 = df_sma30.iloc[-1]
            
            trend = "ขาขึ้น (SMA10 > SMA30)" if last_sma10 > last_sma30 else "ขาลง (SMA10 < SMA30)"
            summary += f"เส้นค่าเฉลี่ยระยะสั้น (SMA 10): {last_sma10:.2f}\n"
            summary += f"เส้นค่าเฉลี่ยระยะกลาง (SMA 30): {last_sma30:.2f}\n"
            summary += f"เทรนด์ระยะสั้นในกราฟ: {trend}\n"
            
        # ประวัติราคา 5 แท่งเทียนล่าสุด
        summary += "\nราคาปิด 5 แท่งเทียนล่าสุด:\n"
        for idx, row in df.tail(5).iterrows():
            summary += f"- เวลา {row['timestamp']}: {row['close']:.2f} USD (Vol: {row['volume']})\n"
            
        return summary

    def run_cycle(self):
        """
        รันขั้นตอนการตัดสินใจแบบ Stateless 1 รอบ
        """
        logging.info("=== เริ่มต้นรอบการทำงาน (New Trading Cycle) ===")
        
        # 1. ดึงราคาทองตลาดจริงล่าสุด
        current_price = self.data_feed.get_current_price()
        if not current_price:
            logging.error("ไม่สามารถตรวจสอบราคาตลาดปัจจุบันได้ ข้ามรอบการทำงานนี้")
            return
            
        self.exchange.update_price(current_price)
        status = self.exchange.get_status()
        
        logging.info(f"ราคาตลาดปัจจุบัน: {current_price} USD | Equity: ${status['equity']:.2f} | Balance: ${status['balance']:.2f}")
        
        # 2. ตรวจสอบสถานะพอร์ต
        open_positions = status['open_positions']
        
        if not open_positions:
            # ----------------------------------------------------
            # 📌 สาขา A: ไม่มีออเดอร์ว่าง -> วิเคราะห์หาจุดเปิดออเดอร์
            # ----------------------------------------------------
            logging.info("สถานะพอร์ต: ไม่มีออเดอร์ค้าง ดึงราคาเพื่อเริ่มวิเคราะห์...")
            
            # ดึงประวัติแท่งเทียน 15 นาที ย้อนหลัง 2 วัน เพื่อทำเป็น Technical Summary
            df = self.data_feed.get_historical_data(interval="15m", period="2d")
            market_summary = self._prepare_market_summary(df)
            
            # ส่งให้ Analyst Agent วิเคราะห์
            decision = self.agents.analyze_market(
                market_data_str=market_summary,
                balance=self.exchange.balance,
                leverage=self.exchange.leverage
            )
            
            if not decision:
                logging.error("ไม่ได้รับข้อมูลการตัดสินใจจาก Analyst Agent")
                return
                
            logging.info(f"คำตัดสินใจของ AI: {decision.get('action')} | เหตุผล: {decision.get('reasoning')}")
            
            # ดำเนินการยิงออเดอร์ตามที่ AI ตัดสินใจ
            action = decision.get("action")
            if action in ["BUY", "SELL"]:
                lot = decision.get("lot", 0.01)
                sl = decision.get("sl")
                tp = decision.get("tp")
                
                # Double Verification (ระบบความปลอดภัยตรวจสอบขนาดล็อต)
                if self.exchange.balance < 100.0 and lot > 0.01:
                    logging.warning(f"เตือน: พอร์ตมีตรรกะเสี่ยงเกินขอบเขต ปรับล็อตลดลงเหลือ 0.01 เพื่อความปลอดภัย (เดิมขอ {lot})")
                    lot = 0.01
                    
                res = self.exchange.open_position(direction=action, lot=lot, sl=sl, tp=tp)
                logging.info(f"ผลลัพธ์การดำเนินการ: {res}")
            else:
                logging.info("AI ตัดสินใจให้รอดูสถานการณ์ไปก่อน (HOLD)")
                
        else:
            # ----------------------------------------------------
            # 📌 สาขา B: มีออเดอร์ค้างอยู่ -> ส่งให้ Manager Agent จัดการหน้าไม้
            # ----------------------------------------------------
            logging.info(f"สถานะพอร์ต: มีออเดอร์ค้างอยู่ {len(open_positions)} ไม้")
            
            for pos in open_positions:
                pos_id = pos['id']
                decision = self.agents.manage_position(
                    position_details=pos,
                    current_price=current_price,
                    balance=self.exchange.balance
                )
                
                if not decision:
                    logging.error(f"ไม่ได้รับการตอบกลับจาก Manager Agent สำหรับออเดอร์ {pos_id}")
                    continue
                    
                action = decision.get("action")
                reason = decision.get("reasoning")
                logging.info(f"คำสั่งคุมความเสี่ยงของออเดอร์ {pos_id}: {action} | เหตุผล: {reason}")
                
                if action == "CLOSE":
                    self.exchange.close_position(pos_id)
                elif action == "BREAK_EVEN":
                    # ตั้งจุด SL เท่ากับราคาเปิดออเดอร์
                    self.exchange.modify_sl_tp(pos_id, new_sl=pos['entry_price'])
                elif action == "TRAILING_STOP":
                    new_sl = decision.get("new_sl")
                    new_tp = decision.get("new_tp")
                    self.exchange.modify_sl_tp(pos_id, new_sl=new_sl, new_tp=new_tp)
                else:
                    logging.info(f"ถือออเดอร์ {pos_id} ต่อไปตามเงื่อนไขเดิม (HOLD)")
                    
        logging.info("=== จบรอบการทำงาน ===\n")

# จุดรันโปรแกรมทดสอบ
if __name__ == "__main__":
    # ตรวจสอบ API Key
    api_key = os.environ.get("MAXPLUS_API_KEY")
    if not api_key:
        print("กรุณาตั้งค่าสภาพแวดล้อมระบบด้วยการรันคำสั่ง: export MAXPLUS_API_KEY='คีย์ของคุณ'")
    else:
        # เริ่มรันบอทเทรดจำลอง
        bot = TradingBotOrchestrator(api_key=api_key)
        bot.run_cycle()
