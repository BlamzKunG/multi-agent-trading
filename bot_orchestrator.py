import os
import time
import logging
from datetime import datetime, timezone
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
        self.symbol = "XAUUSD"

    def is_gold_market_open(self):
        """ตรวจสอบว่าตลาดทองคำปิดทำการช่วงวันหยุดเสาร์-อาทิตย์หรือไม่ (อิงเวลา UTC)"""
        now_utc = datetime.now(timezone.utc)
        day = now_utc.weekday()  # 0 = Monday, ..., 6 = Sunday
        hour = now_utc.hour
        
        # ปิดวันเสาร์ (5) และวันอาทิตย์ (6) ทั้งวัน
        if day in [5, 6]:
            return False
        # ปิดวันศุกส์ (4) หลัง 21:00 UTC (ประมาณตี 4 วันเสาร์เวลาไทย)
        if day == 4 and hour >= 21:
            return False
        # ปิดวันจันทร์ (0) ก่อน 00:00 UTC
        if day == 0 and hour < 0:
            return False
        return True

    def _prepare_market_summary(self, df):
        """แปลงตารางข้อมูลราคาและอินดิเคเตอร์ให้เป็นข้อความสรุปเพื่อให้ AI เข้าใจง่าย"""
        if df.empty:
            return f"ไม่สามารถโหลดข้อมูลราคาล่าสุดสำหรับ {self.symbol} ได้"
            
        last_row = df.iloc[-1]
        summary = f"ราคาล่าสุดสำหรับ {self.symbol}: {last_row['close']:.2f} USD\n"
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
        
        # 1. ตรวจสอบสถานะตลาดทองคำ (XAUUSD) เพื่อปรับเปลี่ยนสินทรัพย์
        if self.is_gold_market_open():
            self.symbol = "XAUUSD"
            self.data_feed.symbol = "GC=F"
            self.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
            self.exchange.contract_size = 100.0  # ทองคำ 1 lot = 100 ounces
            logging.info("ตลาดทองคำเปิดทำการ เลือกเทรดสินทรัพย์หลัก: XAUUSD")
        else:
            self.symbol = "BTCUSD"
            self.data_feed.symbol = "BTC-USD"
            self.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
            self.exchange.contract_size = 1.0   # Bitcoin 1 lot = 1 BTC
            logging.info("ตลาดทองคำปิดทำการ (ช่วงวันหยุดเสาร์-อาทิตย์) สลับมาเทรดสินทรัพย์สำรอง: BTCUSD (Bitcoin)")

        # 2. ดึงราคาตลาดจริงล่าสุด
        current_price = self.data_feed.get_current_price()
        if not current_price:
            logging.error(f"ไม่สามารถตรวจสอบราคาตลาดปัจจุบันสำหรับ {self.symbol} ได้ ข้ามรอบการทำงานนี้")
            return
            
        self.exchange.update_price(current_price)
        status = self.exchange.get_status()
        
        logging.info(f"ราคาตลาดปัจจุบันสำหรับ {self.symbol}: {current_price} USD | Equity: ${status['equity']:.2f} | Balance: ${status['balance']:.2f}")
        
        # 3. ตรวจสอบสถานะพอร์ต
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
                symbol=self.symbol,
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
                max_allowed_lot = getattr(self, 'max_lot', 0.01)
                if lot > max_allowed_lot:
                    logging.warning(f"เตือน: ขนาดล็อตที่ขอมา ({lot}) เกินเพดานสูงสุดที่จำกัดไว้ ({max_allowed_lot}) ปรับล็อตเหลือ {max_allowed_lot}")
                    lot = max_allowed_lot
                elif self.exchange.balance < 100.0 and lot > 0.01:
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
                    balance=self.exchange.balance,
                    symbol=self.symbol
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
