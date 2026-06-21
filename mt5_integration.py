import MetaTrader5 as mt5
import pandas as pd
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MT5Integration:
    """
    โมดูลเชื่อมต่อตรงกับ MetaTrader 5 (MT5 Bridge)
    ใช้สำหรับดึงราคารอบตลาดจริง และยิงออเดอร์/คุมความเสี่ยงจริงผ่านบัญชี Broker ของผู้ใช้
    *หมายเหตุ: ไลบรารี MetaTrader5 จะทำงานได้เฉพาะบนเครื่อง PC Windows ที่ติดตั้งโปรแกรม MT5 Terminal เท่านั้น*
    """
    def __init__(self, login=None, password=None, server=None):
        self.login = login
        self.password = password
        self.server = server
        self.initialized = False

    def connect(self):
        """เชื่อมต่อกับโปรแกรม MT5 Terminal"""
        if self.initialized:
            return True
            
        logging.info("กำลังเชื่อมต่อเข้ากับโปรแกรม MetaTrader 5...")
        
        # กรณีมีการส่งค่าบัญชีเข้ามา ล็อกอินอัตโนมัติ
        if self.login and self.password and self.server:
            if not mt5.initialize(login=int(self.login), password=self.password, server=self.server):
                logging.error(f"ไม่สามารถเชื่อมต่อ MT5 ได้: {mt5.last_error()}")
                return False
        else:
            # ใช้การเชื่อมต่อผ่าน Terminal ที่เปิดทิ้งไว้ในเครื่อง PC ปัจจุบัน
            if not mt5.initialize():
                logging.error(f"ไม่สามารถเปิดการทำงาน MT5 ได้ (โปรดตรวจสอบว่าเปิดโปรแกรม MT5 ไว้ใน PC หรือไม่): {mt5.last_error()}")
                return False
                
        self.initialized = True
        account_info = mt5.account_info()
        if account_info:
            logging.info(f"เชื่อมต่อสำเร็จ! บัญชี: {account_info.login} | โบรกเกอร์: {account_info.company} | ยอดเงินคงเหลือ: ${account_info.balance:.2f}")
        return True

    def disconnect(self):
        """ปิดการเชื่อมต่อ"""
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
            logging.info("ปิดการเชื่อมต่อ MetaTrader 5 สำเร็จ")

    def get_current_price(self, symbol="XAUUSD"):
        """ดึงราคา Tick ล่าสุด (Bid/Ask) จาก Broker"""
        if not self.connect():
            return None
            
        # ตรวจสอบว่าเปิดข้อมูลคู่เงินใน Market Watch หรือยัง
        selected = mt5.symbol_select(symbol, True)
        if not selected:
            logging.error(f"ไม่สามารถเลือกคู่เงิน {symbol} ใน Market Watch ได้")
            return None
            
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            logging.error(f"ไม่สามารถดึงข้อมูลราคาของ {symbol} ได้")
            return None
            
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "price": (tick.bid + tick.ask) / 2.0  # ราคาเฉลี่ยกลาง
        }

    def get_historical_data(self, symbol="XAUUSD", timeframe="15m", num_candles=100):
        """
        ดึงข้อมูลแท่งเทียนประวัติศาสตร์จาก Broker
        - timeframe: '1m', '5m', '15m', '1h', '1d'
        - num_candles: จำนวนแท่งเทียนที่ต้องการย้อนหลัง
        """
        if not self.connect():
            return pd.DataFrame()
            
        # แปลงข้อความเป็นค่า Timeframe ของ MT5
        tf_map = {
            "1m": mt5.TIMEFRAME_M1,
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "1h": mt5.TIMEFRAME_H1,
            "1d": mt5.TIMEFRAME_D1
        }
        
        mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)
        
        # ดึงแท่งเทียนย้อนหลังนับจากแท่งปัจจุบัน (แท่งที่ 0 คือแท่งกำลังวิ่ง)
        rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, num_candles)
        if rates is None or len(rates) == 0:
            logging.error(f"ดึงข้อมูลกราฟย้อนหลังล้มเหลว: {mt5.last_error()}")
            return pd.DataFrame()
            
        # แปลงเป็น pandas DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # เปลี่ยนชื่อคอลัมน์ให้ล้อกับระบบจำลอง
        df = df.rename(columns={
            "time": "timestamp",
            "tick_volume": "volume"
        })
        return df[["timestamp", "open", "high", "low", "close", "volume"]]

    def get_account_status(self):
        """ดึงสถานะเงินทุนและพอร์ตปัจจุบัน"""
        if not self.connect():
            return None
            
        acc = mt5.account_info()
        if not acc:
            return None
            
        return {
            "balance": acc.balance,
            "equity": acc.equity,
            "margin": acc.margin,
            "free_margin": acc.margin_free,
            "floating_pnl": acc.profit
        }

    def get_open_positions(self, symbol="XAUUSD"):
        """ดึงรายการออเดอร์ที่เปิดอยู่ ณ ปัจจุบัน"""
        if not self.connect():
            return []
            
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            logging.error(f"ไม่สามารถตรวจสอบออเดอร์ค้างได้: {mt5.last_error()}")
            return []
            
        positions_list = []
        for pos in positions:
            # แปลงทิศทางออเดอร์
            direction = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
            positions_list.append({
                "id": pos.ticket,         # ใช้ Ticket ID ใน MT5
                "direction": direction,
                "lot": pos.volume,
                "entry_price": pos.price_open,
                "sl": pos.sl,
                "tp": pos.tp,
                "pnl": pos.profit,
                "margin": 0.0             # คำนวณฝั่ง MT5 อัตโนมัติอยู่แล้ว
            })
        return positions_list

    def open_position(self, direction, lot, sl=None, tp=None, entry=None, symbol="XAUUSD"):
        """
        ส่งคำสั่งเปิดออเดอร์ (Market Order) หรือ ตั้งคำสั่งรอดำเนินการ (Pending Order)
        - direction: 'BUY' หรือ 'SELL'
        - lot: ขนาดสัญญา
        - sl: จุดตัดขาดทุน
        - tp: จุดทำกำไร
        - entry: ราคาที่ต้องการเข้าเทรด (หากละเว้นไว้ จะเปิดออเดอร์ที่ราคาปัจจุบันทันที)
        """
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        # ดึงราคาและข้อมูลของโบรกเกอร์เกี่ยวกับสัญลักษณ์
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"status": "ERROR", "message": f"ไม่พบข้อมูลคู่เงิน {symbol} บน MT5"}
            
        digits = sym_info.digits
        tick_size = sym_info.trade_tick_size
        stops_level = sym_info.trade_stops_level
        point = sym_info.point
        
        price_info = self.get_current_price(symbol)
        if not price_info:
            return {"status": "ERROR", "message": "ไม่สามารถอ่านราคาปัจจุบันได้"}
            
        bid_price = price_info["bid"]
        ask_price = price_info["ask"]
        
        # ปรับทศนิยมตัวแปร SL และ TP ให้สอดคล้องกับโบรกเกอร์
        final_sl = round(round(float(sl) / tick_size) * tick_size, digits) if sl else 0.0
        final_tp = round(round(float(tp) / tick_size) * tick_size, digits) if tp else 0.0
        
        # คำนวณระยะห่างขั้นต่ำตาม Stops Level เพื่อความปลอดภัยในการตั้ง Pending Order
        min_stop_distance = stops_level * point
        
        # กำหนด Deviation Limit ตามประเภทสินทรัพย์ (Bitcoin ผันผวนสูงและราคาสูงกว่าทองมาก)
        if "BTC" in symbol.upper():
            deviation_limit = max(min_stop_distance * 1.5, 50.0)
        else:
            deviation_limit = max(min_stop_distance * 1.5, 1.50)
            
        is_pending = False
        order_type = None
        target_price = None
        
        if entry is not None:
            entry_val = float(entry)
            market_compare_price = ask_price if direction == "BUY" else bid_price
            
            # ถ้าราคาเข้าที่เสนอมา ห่างจากราคาตลาดปัจจุบันเกิน Deviation Limit ให้ตั้งเป็น Pending Order
            if abs(entry_val - market_compare_price) > deviation_limit:
                is_pending = True
                target_price = round(round(entry_val / tick_size) * tick_size, digits)
                
                if direction == "BUY":
                    if target_price < ask_price:
                        order_type = mt5.ORDER_TYPE_BUY_LIMIT  # ซื้อราคาต่ำกว่าตลาด
                        logging.info(f"ราคาเสนอซื้อ ({target_price}) ต่ำกว่าราคาตลาด Ask ({ask_price}): เลือกใช้ BUY LIMIT")
                    else:
                        order_type = mt5.ORDER_TYPE_BUY_STOP   # ซื้อราคาสูงกว่าตลาด (Breakout)
                        logging.info(f"ราคาเสนอซื้อ ({target_price}) สูงกว่าราคาตลาด Ask ({ask_price}): เลือกใช้ BUY STOP")
                else:  # SELL
                    if target_price > bid_price:
                        order_type = mt5.ORDER_TYPE_SELL_LIMIT # ขายราคาสูงกว่าตลาด
                        logging.info(f"ราคาเสนอขาย ({target_price}) สูงกว่าราคาตลาด Bid ({bid_price}): เลือกใช้ SELL LIMIT")
                    else:
                        order_type = mt5.ORDER_TYPE_SELL_STOP  # ขายราคาต่ำกว่าตลาด (Breakout)
                        logging.info(f"ราคาเสนอขาย ({target_price}) ต่ำกว่าราคาตลาด Bid ({bid_price}): เลือกใช้ SELL STOP")
            else:
                logging.info(f"ราคาเสนอเข้า ({entry_val}) ใกล้เคียงราคาตลาดปัจจุบัน (ห่างไม่เกิน {deviation_limit:.2f}): สลับมาเข้าตลาดทันที (Market Order)")
                
        if not is_pending:
            # เปิดออเดอร์ทันที (Market Order)
            order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
            target_price = ask_price if direction == "BUY" else bid_price
            target_price = round(round(target_price / tick_size) * tick_size, digits)
            
        request = {
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": target_price,
            "sl": final_sl,
            "tp": final_tp,
            "deviation": 20,
            "magic": 123456,
            "comment": "LLM Auto Trade",
            "type_time": mt5.ORDER_TIME_GTC
        }
        
        if is_pending:
            request["action"] = mt5.TRADE_ACTION_PENDING
        else:
            request["action"] = mt5.TRADE_ACTION_DEAL
            request["type_filling"] = mt5.ORDER_FILLING_IOC
            
        # ส่งคำสั่งไปยังโบรกเกอร์
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            err_msg = f"ส่งคำสั่ง {direction} ล้มเหลว: {result.comment} (code: {result.retcode})"
            logging.error(err_msg)
            return {"status": "FAILED", "message": err_msg}
            
        order_text = "Pending Order" if is_pending else "Market Order"
        logging.info(f"ส่ง {order_text} สำเร็จผ่าน MT5! Ticket: {result.order} ที่ราคา {result.price}")
        return {"status": "SUCCESS", "order_id": result.order, "is_pending": is_pending}

    def close_position(self, ticket, symbol="XAUUSD"):
        """ปิดออเดอร์ที่ระบุด้วยตั๋ว Ticket ID"""
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "ERROR", "message": "ไม่พบออเดอร์ค้างในระบบ (อาจจะถูกปิดไปแล้ว)"}
            
        pos = positions[0]
        direction = "SELL" if pos.type == mt5.POSITION_TYPE_BUY else "BUY"
        price_info = self.get_current_price(symbol)
        
        execution_price = price_info["bid"] if direction == "BUY" else price_info["ask"]
        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        
        # ปัดราคาปิดออเดอร์ให้ตรงทศนิยมของโบรกเกอร์
        sym_info = mt5.symbol_info(symbol)
        if sym_info:
            execution_price = round(round(execution_price / sym_info.trade_tick_size) * sym_info.trade_tick_size, sym_info.digits)
            
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": execution_price,
            "deviation": 20,
            "magic": 123456,
            "comment": "LLM Close Position",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"การปิดออเดอร์ {ticket} ล้มเหลว: {result.comment}")
            return {"status": "FAILED", "message": result.comment}
            
        logging.info(f"ปิดออเดอร์ Ticket {ticket} สำเร็จที่ราคา {result.price}")
        return {"status": "SUCCESS"}

    def modify_position(self, ticket, new_sl=None, new_tp=None):
        """แก้ไขจุด SL / TP ของออเดอร์ที่มีอยู่"""
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "ERROR", "message": "ไม่พบออเดอร์ในระบบ"}
            
        pos = positions[0]
        symbol = pos.symbol
        sym_info = mt5.symbol_info(symbol)
        
        final_sl = pos.sl
        final_tp = pos.tp
        
        if sym_info:
            digits = sym_info.digits
            tick_size = sym_info.trade_tick_size
            if new_sl is not None:
                final_sl = round(round(float(new_sl) / tick_size) * tick_size, digits)
            if new_tp is not None:
                final_tp = round(round(float(new_tp) / tick_size) * tick_size, digits)
        else:
            if new_sl is not None:
                final_sl = float(new_sl)
            if new_tp is not None:
                final_tp = float(new_tp)
                
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": final_sl,
            "tp": final_tp
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"การแก้ไข SL/TP ของออเดอร์ {ticket} ล้มเหลว: {result.comment}")
            return {"status": "FAILED", "message": result.comment}
            
        logging.info(f"แก้ไข SL/TP ออเดอร์ {ticket} สำเร็จ | SL ใหม่: {final_sl}, TP ใหม่: {final_tp}")
        return {"status": "SUCCESS"}

    def get_pending_orders(self, symbol="XAUUSD"):
        """ดึงคำสั่งซื้อขายล่วงหน้า (Pending Orders) ที่ยังไม่ถูกจับคู่"""
        if not self.connect():
            return []
            
        orders = mt5.orders_get(symbol=symbol)
        if orders is None:
            logging.error(f"ไม่สามารถดึงข้อมูล Pending Orders ได้: {mt5.last_error()}")
            return []
            
        orders_list = []
        for ord in orders:
            # ตรวจสอบประเภท Pending Order
            ord_type = ""
            if ord.type == mt5.ORDER_TYPE_BUY_LIMIT: ord_type = "BUY_LIMIT"
            elif ord.type == mt5.ORDER_TYPE_BUY_STOP: ord_type = "BUY_STOP"
            elif ord.type == mt5.ORDER_TYPE_SELL_LIMIT: ord_type = "SELL_LIMIT"
            elif ord.type == mt5.ORDER_TYPE_SELL_STOP: ord_type = "SELL_STOP"
            else: continue  # ข้ามหากไม่ใช่ประเภท Pending
            
            orders_list.append({
                "id": ord.ticket,
                "direction": "BUY" if "BUY" in ord_type else "SELL",
                "type": ord_type,
                "lot": ord.volume_current,
                "entry_price": ord.price_open,
                "sl": ord.sl,
                "tp": ord.tp
            })
        return orders_list

    def cancel_pending_order(self, ticket):
        """ยกเลิกคำสั่งซื้อขายล่วงหน้า (Pending Order)"""
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": int(ticket)
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"ไม่สามารถยกเลิกคำสั่งล่วงหน้า {ticket} ได้: {result.comment}")
            return {"status": "FAILED", "message": result.comment}
            
        logging.info(f"ยกเลิกคำสั่งซื้อขายล่วงหน้า Ticket {ticket} สำเร็จ")
        return {"status": "SUCCESS"}
