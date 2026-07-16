import uuid
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MockExchange:
    """
    ระบบจำลองตลาดและโบรกเกอร์ (Mock Exchange/Broker Simulator)
    ใช้สำหรับจำลองการเปิดออเดอร์ XAUUSD, คำนวณ Margin, กำไร/ขาดทุน, SL/TP และ Pending Orders
    """
    def __init__(self, initial_balance=30.0, leverage=100.0):
        self.balance = float(initial_balance)
        self.leverage = float(leverage)
        self.positions = {}  # เก็บออเดอร์ที่เปิดอยู่ {position_id: position_details}
        self.pending_orders = {}  # เก็บออเดอร์ล่วงหน้า {order_id: order_details}
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
        อัปเดตราคาล่าสุด ตรวจเช็คว่าออเดอร์เปิดชน SL/TP หรือยัง และแปลง Pending Orders ที่ราคาวิ่งมาถึงให้เป็น Active Positions
        """
        self.current_price = float(new_price)
        
        # 1. ตรวจสอบและแปลง Pending Orders ที่เข้าเงื่อนไขราคา
        filled_order_ids = []
        for ord_id, ord in list(self.pending_orders.items()):
            entry = ord["entry_price"]
            direction = ord["direction"]
            ord_type = ord["type"]
            
            trigger = False
            if ord_type == "BUY_LIMIT" and self.current_price <= entry:
                trigger = True
            elif ord_type == "BUY_STOP" and self.current_price >= entry:
                trigger = True
            elif ord_type == "SELL_LIMIT" and self.current_price >= entry:
                trigger = True
            elif ord_type == "SELL_STOP" and self.current_price <= entry:
                trigger = True
                
            if trigger:
                filled_order_ids.append(ord_id)
                
        for ord_id in filled_order_ids:
            ord = self.pending_orders.pop(ord_id)
            # พยายามเปิดออเดอร์จริงจากการจับคู่ราคา
            required_margin = (self.contract_size * ord["lot"] * ord["entry_price"]) / self.leverage
            total_used_margin = sum((self.contract_size * pos['lot'] * pos['entry_price']) / self.leverage for pos in self.positions.values())
            free_margin = self.equity - total_used_margin - required_margin
            
            if free_margin >= 0:
                pos_id = ord_id  # ใช้รหัสตั๋วเดิม
                position = {
                    "id": pos_id,
                    "direction": ord["direction"],
                    "lot": ord["lot"],
                    "entry_price": ord["entry_price"],
                    "sl": ord["sl"],
                    "tp": ord["tp"],
                    "pnl": 0.0,
                    "margin": required_margin,
                    "open_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "magic": ord["magic"]
                }
                self.positions[pos_id] = position
                logging.info(f"🔔 [Pending Order Filled] ออเดอร์ล่วงหน้า #{pos_id} ถูกเปิดการทำงานที่ราคา {ord['entry_price']} | SL: {ord['sl']}, TP: {ord['tp']} | Magic: {ord['magic']}")
            else:
                logging.warning(f"❌ [Pending Order Cancelled] ออเดอร์ล่วงหน้า #{ord_id} ถูกยกเลิกอัตโนมัติ เนื่องจาก Margin ไม่พอตอนเปิดใช้งาน")

        # 2. ตรวจสอบเงื่อนไข SL / TP ของออเดอร์ที่ค้างอยู่
        closed_ids = []
        for pos_id, pos in self.positions.items():
            if pos['direction'] == 'BUY':
                pos['pnl'] = (self.current_price - pos['entry_price']) * self.contract_size * pos['lot']
            else:
                pos['pnl'] = (pos['entry_price'] - self.current_price) * self.contract_size * pos['lot']
                
            sl = pos['sl']
            tp = pos['tp']
            
            # เช็ค Stop Loss
            if sl is not None:
                if (pos['direction'] == 'BUY' and self.current_price <= sl) or \
                   (pos['direction'] == 'SELL' and self.current_price >= sl):
                    logging.info(f"ออเดอร์ {pos_id} ชน Stop Loss ที่ราคา {self.current_price}")
                    closed_ids.append((pos_id, sl, 'SL'))
                    continue
                    
            # เช็ค Take Profit
            if tp is not None:
                if (pos['direction'] == 'BUY' and self.current_price >= tp) or \
                   (pos['direction'] == 'SELL' and self.current_price <= tp):
                    logging.info(f"ออเดอร์ {pos_id} ชน Take Profit ที่ราคา {self.current_price}")
                    closed_ids.append((pos_id, tp, 'TP'))
                    continue

        # ทำการปิดออเดอร์ที่ชน SL/TP
        for pos_id, execution_price, reason in closed_ids:
            self._close_position_internal(pos_id, execution_price, reason)

    def open_position(self, direction, lot, sl=None, tp=None, entry=None, magic=123456, symbol="XAUUSD", force_market=False):
        """
        เปิดออเดอร์ล่วงหน้า (Pending Order) หรือ Market Order (เมื่อระบุ force_market=True)
        """
        if direction not in ['BUY', 'SELL']:
            return {"status": "ERROR", "message": "ทิศทางออเดอร์ไม่ถูกต้อง (ต้องเป็น BUY หรือ SELL)"}
            
        if self.current_price <= 0:
            return {"status": "ERROR", "message": "ราคาตลาดปัจจุบันไม่ถูกต้อง (ต้องมากกว่า 0)"}
            
        # ตรวจสอบและแก้ไข SL/TP ในกรณีตั้งกลับทิศทาง (Auto-correct reversed SL/TP)
        final_sl = float(sl) if sl is not None else None
        final_tp = float(tp) if tp is not None else None
        
        if force_market:
            is_pending = False
            target_price = self.current_price
            
            if direction == "BUY":
                if final_sl is not None and final_sl >= target_price:
                    if final_tp is not None and final_tp <= target_price:
                        final_sl, final_tp = final_tp, final_sl
                    else:
                        final_sl = None
                if final_tp is not None and final_tp <= target_price:
                    final_tp = None
            else: # SELL
                if final_sl is not None and final_sl <= target_price:
                    if final_tp is not None and final_tp >= target_price:
                        final_sl, final_tp = final_tp, final_sl
                    else:
                        final_sl = None
                if final_tp is not None and final_tp >= target_price:
                    final_tp = None
                    
            pos_id = str(uuid.uuid4())[:8]
            new_pos = {
                "id": pos_id,
                "direction": direction,
                "lot": float(lot),
                "entry_price": float(target_price),
                "sl": final_sl,
                "tp": final_tp,
                "magic": int(magic),
                "open_time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self.open_positions[pos_id] = new_pos
            logging.info(f"เปิดตำแหน่ง (Market Order) สำเร็จ: {direction} {lot} Lot ที่ราคา {target_price} | SL: {final_sl}, TP: {final_tp} | Magic: {magic}")
            return {"status": "SUCCESS", "order_id": pos_id, "is_pending": False}
            
        is_pending = True
        
        if entry is None:
            # Fallback ตั้งห่างราคาตลาดปัจจุบันในระยะที่มีนัยสำคัญจริง
            min_dist = 3.50 if "XAU" in symbol.upper() else (80.0 if "BTC" in symbol.upper() else 10.0)
            if direction == "BUY":
                entry_val = self.current_price - min_dist
            else:
                entry_val = self.current_price + min_dist
        else:
            entry_val = float(entry)
            
        target_price = entry_val
        
        if direction == "BUY":
            if final_sl is not None and final_sl >= target_price:
                if final_tp is not None and final_tp <= target_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = None
            if final_tp is not None and final_tp <= target_price:
                final_tp = None
        else: # SELL
            if final_sl is not None and final_sl <= target_price:
                if final_tp is not None and final_tp >= target_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = None
            if final_tp is not None and final_tp >= target_price:
                final_tp = None
                
        if direction == "BUY":
            ord_type = "BUY_LIMIT" if target_price < self.current_price else "BUY_STOP"
        else:
            ord_type = "SELL_LIMIT" if target_price > self.current_price else "SELL_STOP"

        ord_id = str(uuid.uuid4())[:8]
        pending_order = {
            "id": ord_id,
            "direction": direction,
            "type": ord_type,
            "lot": float(lot),
            "entry_price": float(target_price),
            "sl": final_sl,
            "tp": final_tp,
            "magic": int(magic)
        }
        self.pending_orders[ord_id] = pending_order
        logging.info(f"ตั้งออเดอร์ล่วงหน้าสำเร็จ: {ord_type} {lot} Lot ที่ราคา {target_price} | SL: {final_sl}, TP: {final_tp} | Magic: {magic}")
        return {"status": "SUCCESS", "order_id": ord_id, "is_pending": True}
    def get_pending_orders(self, symbol="XAUUSD", magic=None):
        """ดึงคำสั่งซื้อขายล่วงหน้า (Pending Orders) ที่ยังไม่ถูกจับคู่"""
        orders_list = list(self.pending_orders.values())
        if magic is not None:
            orders_list = [ord for ord in orders_list if ord["magic"] == int(magic)]
        return orders_list

    def cancel_pending_order(self, ticket):
        """ยกเลิกคำสั่งซื้อขายล่วงหน้า (Pending Order)"""
        ticket_str = str(ticket)
        if ticket_str in self.pending_orders:
            self.pending_orders.pop(ticket_str)
            logging.info(f"ยกเลิกคำสั่งซื้อขายล่วงหน้า Ticket #{ticket} สำเร็จ")
            return {"status": "SUCCESS"}
        return {"status": "ERROR", "message": f"ไม่พบคำสั่งล่วงหน้า #{ticket}"}

    def modify_pending_order(self, ticket, price, sl=None, tp=None):
        """แก้ไขราคาเข้า หรือ SL/TP ของออเดอร์ล่วงหน้าในระบบจำลองพอร์ต"""
        ticket_str = str(ticket)
        if ticket_str in self.pending_orders:
            ord = self.pending_orders[ticket_str]
            new_price = float(price)
            ord["entry_price"] = new_price
            
            # ตรวจสอบและแก้ไข SL/TP ในกรณีตั้งกลับทิศทาง (Auto-correct reversed SL/TP)
            final_sl = float(sl) if sl is not None else None
            final_tp = float(tp) if tp is not None else None
            
            if ord["direction"] == "BUY":
                if final_sl is not None and final_sl >= new_price:
                    if final_tp is not None and final_tp <= new_price:
                        final_sl, final_tp = final_tp, final_sl
                    else:
                        final_sl = None
                if final_tp is not None and final_tp <= new_price:
                    final_tp = None
            else: # SELL
                if final_sl is not None and final_sl <= new_price:
                    if final_tp is not None and final_tp >= new_price:
                        final_sl, final_tp = final_tp, final_sl
                    else:
                        final_sl = None
                if final_tp is not None and final_tp >= new_price:
                    final_tp = None
                    
            # สลับแปลงประเภทออเดอร์ (Limit <-> Stop) อัตโนมัติหากราคาพ้นราคาตลาดจำลอง
            if ord["direction"] == "BUY":
                ord["type"] = "BUY_LIMIT" if new_price < self.current_price else "BUY_STOP"
            else:
                ord["type"] = "SELL_LIMIT" if new_price > self.current_price else "SELL_STOP"
                
            ord["sl"] = final_sl
            ord["tp"] = final_tp
            logging.info(f"แก้ไขคำสั่งซื้อขายล่วงหน้า #{ticket} สำเร็จ | ราคาเข้าใหม่: {new_price} ({ord['type']}), SL: {final_sl}, TP: {final_tp}")
            return {"status": "SUCCESS"}
        return {"status": "ERROR", "message": f"ไม่พบคำสั่งล่วงหน้า #{ticket}"}
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

    def get_status(self, magic=None):
        """ดึงสรุปสถานะพอร์ตปัจจุบัน"""
        open_positions = list(self.positions.values())
        pending_orders = list(self.pending_orders.values())
        history = self.history
        
        if magic is not None:
            open_positions = [pos for pos in open_positions if pos.get("magic") == int(magic)]
            pending_orders = [ord for ord in pending_orders if ord.get("magic") == int(magic)]
            history = [pos for pos in history if pos.get("magic") == int(magic)]
            
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "floating_pnl": round(sum(pos['pnl'] for pos in open_positions), 2),
            "open_positions": open_positions,
            "pending_orders": pending_orders,
            "history": history
        }