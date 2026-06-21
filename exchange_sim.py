import uuid
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MockExchange:
    """
    ระบบจำลองตลาดและโบรกเกอร์ (Mock Exchange/Broker Simulator)
    ใช้สำหรับจำลองการเปิดออเดอร์ XAUUSD, คำนวณ Margin, กำไร/ขาดทุน และ SL/TP 
    """
    def __init__(self, initial_balance=30.0, leverage=100.0):
        self.balance = float(initial_balance)
        self.leverage = float(leverage)
        self.positions = {}  # เก็บออเดอร์ที่เปิดอยู่ {position_id: position_details}
        self.history = []    # เก็บประวัติออเดอร์ที่ปิดแล้ว
        self.contract_size = 100.0  # สำหรับทองคำ XAUUSD (1 Lot = 100 Ounces)
        self.current_price = 0.0
        
    @property
    def equity(self):
        """คำนวณ Equity (ยอดเงินคงเหลือ + กำไร/ขาดทุนที่ยังไม่ปิด)"""
        return self.balance + self.get_total_floating_pnl()

    def get_total_floating_pnl(self):
        """คำนวณกำไร/ขาดทุนรวมของออเดอร์ที่เปิดอยู่"""
        return sum(pos['pnl'] for pos in self.positions.values())

    def update_price(self, new_price):
        """
        อัปเดตราคาล่าสุด และตรวจเช็คออเดอร์ว่าชน SL หรือ TP หรือยัง
        """
        self.current_price = float(new_price)
        closed_ids = []
        
        for pos_id, pos in self.positions.items():
            # 1. คำนวณ P&L ปัจจุบัน
            # สำหรับ Buy: P&L = (Current Price - Entry Price) * Contract Size * Lot
            # สำหรับ Sell: P&L = (Entry Price - Current Price) * Contract Size * Lot
            if pos['direction'] == 'BUY':
                pos['pnl'] = (self.current_price - pos['entry_price']) * self.contract_size * pos['lot']
            else:
                pos['pnl'] = (pos['entry_price'] - self.current_price) * self.contract_size * pos['lot']
                
            # 2. ตรวจสอบเงื่อนไข SL / TP
            sl = pos['sl']
            tp = pos['tp']
            
            # เช็คกรณีชน Stop Loss
            if sl is not None:
                if (pos['direction'] == 'BUY' and self.current_price <= sl) or \
                   (pos['direction'] == 'SELL' and self.current_price >= sl):
                    logging.info(f"ออเดอร์ {pos_id} ชน Stop Loss ที่ราคา {self.current_price}")
                    closed_ids.append((pos_id, sl, 'SL'))
                    continue
                    
            # เช็คกรณีชน Take Profit
            if tp is not None:
                if (pos['direction'] == 'BUY' and self.current_price >= tp) or \
                   (pos['direction'] == 'SELL' and self.current_price <= tp):
                    logging.info(f"ออเดอร์ {pos_id} ชน Take Profit ที่ราคา {self.current_price}")
                    closed_ids.append((pos_id, tp, 'TP'))
                    continue

        # ทำการปิดออเดอร์ที่ชน SL/TP
        for pos_id, execution_price, reason in closed_ids:
            self._close_position_internal(pos_id, execution_price, reason)

    def open_position(self, direction, lot, sl=None, tp=None):
        """
        เปิดออเดอร์ใหม่ (Market Order)
        - direction: 'BUY' หรือ 'SELL'
        - lot: ขนาดสัญญา (ต่ำสุด 0.01)
        - sl: ระดับจุดตัดขาดทุน (ราคา)
        - tp: ระดับจุดทำกำไร (ราคา)
        """
        if direction not in ['BUY', 'SELL']:
            return {"status": "ERROR", "message": "ทิศทางออเดอร์ไม่ถูกต้อง (ต้องเป็น BUY หรือ SELL)"}
            
        if self.current_price <= 0:
            return {"status": "ERROR", "message": "ราคาตลาดปัจจุบันไม่ถูกต้อง (ต้องมากกว่า 0)"}
            
        # 1. คำนวณ Margin ที่ต้องการ
        # Margin = (Contract Size * Lot * Current Price) / Leverage
        required_margin = (self.contract_size * lot * self.current_price) / self.leverage
        
        # 2. เช็คว่าเงินในพอร์ตพอกับหลักประกันไหม
        # เพื่อความปลอดภัยในการเทรดจริง Free Margin = Equity - Margin
        total_used_margin = sum((self.contract_size * pos['lot'] * pos['entry_price']) / self.leverage for pos in self.positions.values())
        free_margin = self.equity - total_used_margin - required_margin
        
        if free_margin < 0:
            return {
                "status": "REJECTED", 
                "message": f"Margin ไม่พอ! ต้องการ ${required_margin:.2f} แต่คงเหลือเพียง ${self.equity - total_used_margin:.2f}"
            }
            
        # 3. บันทึกข้อมูลออเดอร์
        pos_id = str(uuid.uuid4())[:8]  # สุ่ม ID ออเดอร์สั้นๆ
        position = {
            "id": pos_id,
            "direction": direction,
            "lot": float(lot),
            "entry_price": self.current_price,
            "sl": float(sl) if sl is not None else None,
            "tp": float(tp) if tp is not None else None,
            "pnl": 0.0,
            "margin": required_margin,
            "open_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        self.positions[pos_id] = position
        logging.info(f"เปิดออเดอร์ใหม่สำเร็จ: {direction} {lot} Lot ที่ราคา {self.current_price} | SL: {sl}, TP: {tp}")
        return {"status": "SUCCESS", "position": position}

    def close_position(self, pos_id):
        """ปิดออเดอร์ที่ระบุด้วยราคาตลาดปัจจุบัน"""
        if pos_id not in self.positions:
            return {"status": "ERROR", "message": "ไม่พบออเดอร์ที่ระบุ"}
        return self._close_position_internal(pos_id, self.current_price, "MARKET_CLOSE")

    def _close_position_internal(self, pos_id, execution_price, reason):
        """กระบวนการปิดออเดอร์และบันทึกประวัติการทำรายการ"""
        pos = self.positions.pop(pos_id)
        
        # คำนวณกำไร/ขาดทุนสุดท้ายที่เกิดขึ้นจริง (Realized P&L)
        if pos['direction'] == 'BUY':
            final_pnl = (execution_price - pos['entry_price']) * self.contract_size * pos['lot']
        else:
            final_pnl = (pos['entry_price'] - execution_price) * self.contract_size * pos['lot']
            
        self.balance += final_pnl
        pos['pnl'] = final_pnl
        pos['close_price'] = execution_price
        pos['close_reason'] = reason
        pos['close_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        self.history.append(pos)
        logging.info(f"ปิดออเดอร์ {pos_id} สำเร็จ ({reason}) ที่ราคา {execution_price} | ได้กำไร/ขาดทุน: ${final_pnl:.2f} | บาลานซ์คงเหลือ: ${self.balance:.2f}")
        return {"status": "SUCCESS", "closed_position": pos}

    def modify_sl_tp(self, pos_id, new_sl=None, new_tp=None):
        """แก้ไขจุด SL และ TP ของออเดอร์ที่ถืออยู่"""
        if pos_id not in self.positions:
            return {"status": "ERROR", "message": "ไม่พบออเดอร์ที่ระบุ"}
            
        pos = self.positions[pos_id]
        if new_sl is not None:
            pos['sl'] = float(new_sl)
        if new_tp is not None:
            pos['tp'] = float(new_tp)
            
        logging.info(f"แก้ไขออเดอร์ {pos_id} สำเร็จ | ตั้ง SL ใหม่: {pos['sl']}, TP ใหม่: {pos['tp']}")
        return {"status": "SUCCESS", "position": pos}

    def get_status(self):
        """ดึงสรุปสถานะพอร์ตปัจจุบัน"""
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "floating_pnl": round(self.get_total_floating_pnl(), 2),
            "open_positions": list(self.positions.values()),
            "history": self.history
        }
