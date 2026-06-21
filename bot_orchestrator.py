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
        # ปิดวันศุกส์ (4) หลัง 21:00 UTC (ประมาณตี 4 วันเสาร์เวลาไทย)
        if day == 4 and hour >= 21:
            return False
        # ปิดวันจันทร์ (0) ก่อน 00:00 UTC
        if day == 0 and hour < 0:
            return False
        return True

    def _prepare_market_summary(self, df_5m, df_15m, df_1h, current_price):
        """แปลงข้อมูลราคาจาก 3 กรอบเวลา (5m, 15m, 1h) ให้เป็นข้อความสรุปวิเคราะห์เชิงลึก"""
        import pandas as pd
        
        summary = f"=== ข้อมูลราคาและอินดิเคเตอร์ Multi-Timeframe สำหรับ {self.symbol} ===\n"
        summary += f"ราคาตลาดล่าสุด: {current_price:.2f} USD\n\n"
        
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
            logging.info("สถานะพอร์ต: ไม่มีออเดอร์ค้าง ดึงราคาเพื่อเริ่มวิเคราะห์แบบ Multi-Timeframe (5m, 15m, 1h)...")
            
            # ดึงประวัติย้อนหลัง 3 กรอบเวลา
            df_5m = self.data_feed.get_historical_data(interval="5m", period="1d")
            df_15m = self.data_feed.get_historical_data(interval="15m", period="2d")
            df_1h = self.data_feed.get_historical_data(interval="1h", period="5d")
            
            market_summary = self._prepare_market_summary(df_5m, df_15m, df_1h, current_price)
            
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
            reason = decision.get("reasoning")
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
                
                # ส่งแจ้งเตือน Discord
                status_text = "เปิดออเดอร์ใหม่สำเร็จ" if res.get("status") == "SUCCESS" else f"ล้มเหลว ({res.get('message', '')})"
                msg = (
                    f"🟢 **[Sim Mode - New Position]**\n"
                    f"**Asset:** {self.symbol} | **Action:** {action}\n"
                    f"**Lot Size:** {lot:.2f} | **Entry Price:** {current_price:.2f}\n"
                    f"**Target:** SL: {sl or '-'} | TP: {tp or '-'}\n"
                    f"**Result:** {status_text}\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
            else:
                logging.info("AI ตัดสินใจให้รอดูสถานการณ์ไปก่อน (HOLD)")
                # ส่งแจ้งเตือน Discord สำหรับ HOLD
                msg = (
                    f"🟡 **[Sim Mode - Analyst Alert]**\n"
                    f"**Asset:** {self.symbol} | **Action:** HOLD (รอดูสัญญาณ)\n"
                    f"**Reason:** {reason}"
                )
                self.send_discord_message(msg)
                
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
                    msg = (
                        f"🔴 **[Sim Mode - Close Trade]**\n"
                        f"**Order ID:** #{pos_id} | **Asset:** {self.symbol}\n"
                        f"**Action:** CLOSE POSITION (สั่งปิดออเดอร์)\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
                elif action == "BREAK_EVEN":
                    self.exchange.modify_sl_tp(pos_id, new_sl=pos['entry_price'])
                    msg = (
                        f"🛡️ **[Sim Mode - Break Even]**\n"
                        f"**Order ID:** #{pos_id} | **Asset:** {self.symbol}\n"
                        f"**Action:** Move SL to Entry ({pos['entry_price']:.2f})\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
                elif action == "TRAILING_STOP":
                    new_sl = decision.get("new_sl")
                    new_tp = decision.get("new_tp")
                    self.exchange.modify_sl_tp(pos_id, new_sl=new_sl, new_tp=new_tp)
                    msg = (
                        f"📈 **[Sim Mode - Trailing Stop]**\n"
                        f"**Order ID:** #{pos_id} | **Asset:** {self.symbol}\n"
                        f"**Action:** Move SL -> {new_sl or '-'} | TP -> {new_tp or '-'}\n"
                        f"**Reason:** {reason}"
                    )
                    self.send_discord_message(msg)
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
