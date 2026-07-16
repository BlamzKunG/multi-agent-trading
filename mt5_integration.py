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
        term_info = mt5.terminal_info()
        if account_info and term_info:
            logging.info(f"เชื่อมต่อสำเร็จ! บัญชี: {account_info.login} | โบรกเกอร์: {account_info.company} | ยอดเงินคงเหลือ: ${account_info.balance:.2f}")
            logging.info(f"📍 เส้นทาง MT5 Terminal: {term_info.path}")
            logging.info(f"📂 โฟลเดอร์ข้อมูล MT5 Data: {term_info.data_path}")
        return True

    def disconnect(self):
        """ปิดการเชื่อมต่อ"""
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
            logging.info("ปิดการเชื่อมต่อ MetaTrader 5 สำเร็จ")

    def resolve_symbol(self, symbol):
        """ค้นหาและแปลงชื่อคู่เงินให้รองรับชื่อพิเศษของโบรกเกอร์ (เช่น XAUUSD-ECN, XAUUSDm)"""
        if not hasattr(self, 'symbol_cache'):
            self.symbol_cache = {}
            
        if symbol in self.symbol_cache:
            return self.symbol_cache[symbol]
            
        if not self.connect():
            return symbol
            
        # ลูปสูงสุด 5 ครั้ง พร้อมมีดีเลย์ เพื่อรองรับกรณีโบรกเกอร์เพิ่งล็อกอินและกำลัง Sync รายชื่อคู่เงิน (Sync Lag)
        for attempt in range(5):
            # 1. ลองค้นหาแบบตรงตัว
            sym_info = mt5.symbol_info(symbol)
            if sym_info is not None:
                self.symbol_cache[symbol] = symbol
                mt5.symbol_select(symbol, True)
                return symbol
                
            # 2. ลองสแกนหารายการชื่อสัญลักษณ์ยอดนิยมโดยตรง (รวมสกุลต่อท้ายของเกือบทุกโบรกเกอร์)
            common_suffixes = [
                "", "m", "-ECN", ".i", "_", ".m", ".ecn", "micro", "-pro", ".pro", "pro", 
                ".cfd", ".vt", "+", ".x", "g", ".g", ".raw", "raw", ".std", "std", "mini", ".mini"
            ]
            search_key = "XAUUSD" if "XAU" in symbol.upper() else "BTCUSD" if "BTC" in symbol.upper() else None
            
            if search_key:
                candidates = []
                if search_key == "XAUUSD":
                    candidates.append("GOLD")
                    candidates.append("GOLD.m")
                    candidates.append("GOLD.pro")
                    candidates.append("GOLD.cfd")
                for suffix in common_suffixes:
                    candidates.append(f"{search_key}{suffix}")
                    
                for candidate in candidates:
                    if mt5.symbol_select(candidate, True):
                        logging.info(f"🔍 [Auto-Discovery/Suffix] พบและเลือกสัญลักษณ์สำเร็จ (รอบที่ {attempt+1}): {candidate}")
                        self.symbol_cache[symbol] = candidate
                        return candidate
                        
            # 3. หากยังไม่พบ ลองค้นหาผ่านรายชื่อคู่เงินทั้งหมดจากโบรกเกอร์ (Fallback)
            search_key_short = "XAU" if "XAU" in symbol.upper() else "BTC" if "BTC" in symbol.upper() else None
            if search_key_short:
                symbols = mt5.symbols_get(group=f"*{search_key_short}*")
                if not symbols and search_key_short == "XAU":
                    symbols = mt5.symbols_get(group="*GOLD*")
                if not symbols and search_key_short == "BTC":
                    symbols = mt5.symbols_get(group="*BITCOIN*")
                    
                if symbols:
                    for sym in symbols:
                        name = sym.name.upper()
                        if (search_key_short in name and "USD" in name) or (name == "GOLD"):
                            logging.info(f"🔍 [Auto-Discovery/FullSearch] พบและเลือกสัญลักษณ์สำเร็จ (รอบที่ {attempt+1}): {sym.name}")
                            self.symbol_cache[symbol] = sym.name
                            mt5.symbol_select(sym.name, True)
                            return sym.name
            
            # หากยังไม่พบในรอบนี้ แสดงว่าโปรแกรมกำลังล็อกอินและ Sync ข้อมูล ให้รอ 1.5 วินาทีแล้วลองใหม่
            logging.warning(f"⚠️ ไม่พบสัญลักษณ์ {symbol} ในระบบ กำลังรอซิงค์ข้อมูลสัญลักษณ์จากโบรกเกอร์ (รอบที่ {attempt+1}/5)...")
            time.sleep(1.5)
            
        # หากครบ 5 รอบแล้วยังไม่พบ ให้พิมพ์ข้อมูลสำหรับตรวจวินิจฉัยปัญหา (Diagnostic Logs)
        all_symbols = mt5.symbols_get()
        if all_symbols:
            gold_matches = [sym.name for sym in all_symbols if "XAU" in sym.name.upper() or "GOLD" in sym.name.upper()]
            btc_matches = [sym.name for sym in all_symbols if "BTC" in sym.name.upper() or "BITCOIN" in sym.name.upper()]
            logging.error(f"❌ [Diagnostic] สแกนพบสัญลักษณ์ทองคำทั้งหมดบนโบรกเกอร์: {gold_matches}")
            logging.error(f"❌ [Diagnostic] สแกนพบสัญลักษณ์บิทคอยน์ทั้งหมดบนโบรกเกอร์: {btc_matches}")
            logging.error(f"จำนวนคู่เงินทั้งหมดบนโบรกเกอร์: {len(all_symbols)} คู่เงิน")
        else:
            # ลองใช้ mt5.symbols_get(group="*") เผื่อ symbols_get() เปล่าๆ คืนค่า None
            all_symbols_wildcard = mt5.symbols_get(group="*")
            if all_symbols_wildcard:
                gold_matches = [sym.name for sym in all_symbols_wildcard if "XAU" in sym.name.upper() or "GOLD" in sym.name.upper()]
                logging.error(f"❌ [Diagnostic-Wildcard] สแกนพบสัญลักษณ์ทองคำทั้งหมด: {gold_matches}")
            else:
                logging.error("❌ [Diagnostic] ไม่สามารถดึงรายชื่อคู่เงินใดๆ จาก MT5 ได้เลย (symbols_get() คืนค่า None) รหัสข้อผิดพลาด: " + str(mt5.last_error()))
            
        self.symbol_cache[symbol] = symbol
        return symbol

    def get_current_price(self, symbol="XAUUSD"):
        """ดึงราคา Tick ล่าสุด (Bid/Ask) จาก Broker"""
        symbol = self.resolve_symbol(symbol)
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
            
        sym_info = mt5.symbol_info(symbol)
        spread = sym_info.spread if sym_info else 0.0
            
        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "price": (tick.bid + tick.ask) / 2.0,  # ราคาเฉลี่ยกลาง
            "spread": float(spread)
        }

    def get_historical_data(self, symbol="XAUUSD", timeframe="15m", num_candles=100):
        """
        ดึงข้อมูลแท่งเทียนประวัติศาสตร์จาก Broker
        - timeframe: '1m', '5m', '15m', '1h', '1d'
        - num_candles: จำนวนแท่งเทียนที่ต้องการย้อนหลัง
        """
        symbol = self.resolve_symbol(symbol)
        if not self.connect():
            return pd.DataFrame()
            
        # แปลงข้อความเป็นค่า Timeframe ของ MT5
        tf_map = {
            "1m": mt5.TIMEFRAME_M1,
            "5m": mt5.TIMEFRAME_M5,
            "15m": mt5.TIMEFRAME_M15,
            "30m": mt5.TIMEFRAME_M30,
            "1h": mt5.TIMEFRAME_H1,
            "4h": mt5.TIMEFRAME_H4,
            "1d": mt5.TIMEFRAME_D1,
            "1w": mt5.TIMEFRAME_W1,
            "1wk": mt5.TIMEFRAME_W1
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

    def get_open_positions(self, symbol="XAUUSD", magic=None):
        """ดึงรายการออเดอร์ที่เปิดอยู่ ณ ปัจจุบัน"""
        symbol = self.resolve_symbol(symbol)
        if not self.connect():
            return []
            
        positions = mt5.positions_get(symbol=symbol)
        if positions is None:
            logging.error(f"ไม่สามารถตรวจสอบออเดอร์ค้างได้: {mt5.last_error()}")
            return []
            
        positions_list = []
        for pos in positions:
            if magic is not None and pos.magic != int(magic):
                continue
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
                "margin": 0.0,            # คำนวณฝั่ง MT5 อัตโนมัติอยู่แล้ว
                "magic": pos.magic
            })
        return positions_list

    def open_position(self, direction, lot, sl=None, tp=None, entry=None, symbol="XAUUSD", magic=123456):
        """
        ส่งคำสั่งซื้อขายล่วงหน้า (Pending Order) เท่านั้น - ปิดการใช้ Market Order เพื่อป้องกันราคาเสียเปรียบ
        - direction: 'BUY' หรือ 'SELL'
        - lot: ขนาดสัญญา
        - sl: จุดตัดขาดทุน
        - tp: จุดทำกำไร
        - entry: ราคาตั้งซื้อขายล่วงหน้า (หากเป็น None จะตั้ง Pending ราคาเบี่ยงเบนห่างราคาตลาดเล็กน้อย)
        - magic: หมายเลข Magic Number ของ Agent
        """
        symbol = self.resolve_symbol(symbol)
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
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
        market_compare_price = ask_price if direction == "BUY" else bid_price
        
        # บังคับใช้คำสั่งล่วงหน้า (Pending Order) เสมอ
        is_pending = True
        
        if entry is None:
            # Fallback หากโมเดลลืมราคาเข้า ให้ตั้งราคา Pending ห่างจากตลาดในระยะที่มีนัยสำคัญเชิงเทคนิค
            min_dist = 3.50 if "XAU" in symbol.upper() else (80.0 if "BTC" in symbol.upper() else 10.0)
            if direction == "BUY":
                entry_val = ask_price - min_dist
            else:
                entry_val = bid_price + min_dist
        else:
            entry_val = float(entry)
            
        target_price = round(round(entry_val / tick_size) * tick_size, digits)
        
        # ปรับแต่งระดับราคาให้พ้นระยะ Stops Level ขั้นต่ำเพื่อป้องกัน Broker Reject
        min_stop_distance = stops_level * point
        if abs(target_price - market_compare_price) < min_stop_distance:
            if direction == "BUY":
                if target_price < market_compare_price:
                    target_price = market_compare_price - min_stop_distance
                else:
                    target_price = market_compare_price + min_stop_distance
            else: # SELL
                if target_price > market_compare_price:
                    target_price = market_compare_price + min_stop_distance
                else:
                    target_price = market_compare_price - min_stop_distance
            target_price = round(round(target_price / tick_size) * tick_size, digits)
            
        # ปรับทศนิยมตัวแปร SL และ TP ให้สอดคล้องกับโบรกเกอร์
        final_sl = round(round(float(sl) / tick_size) * tick_size, digits) if sl else 0.0
        final_tp = round(round(float(tp) / tick_size) * tick_size, digits) if tp else 0.0
        
        # ตรวจสอบและแก้ไข SL/TP ในกรณีตั้งกลับทิศทาง (Auto-correct reversed SL/TP)
        if direction == "BUY":
            if final_sl > 0.0 and final_sl >= target_price:
                if final_tp > 0.0 and final_tp <= target_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = 0.0
            if final_tp > 0.0 and final_tp <= target_price:
                final_tp = 0.0
        else: # SELL
            if final_sl > 0.0 and final_sl <= target_price:
                if final_tp > 0.0 and final_tp >= target_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = 0.0
            if final_tp > 0.0 and final_tp >= target_price:
                final_tp = 0.0
                
        # กำหนดประเภทคำสั่งซื้อขายล่วงหน้าตามระดับราคาเทียบกับตลาดปัจจุบัน
        if direction == "BUY":
            if target_price < ask_price:
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
                logging.info(f"ราคาเสนอซื้อ ({target_price}) ต่ำกว่าราคาตลาด Ask ({ask_price}): เลือกใช้ BUY LIMIT")
            else:
                order_type = mt5.ORDER_TYPE_BUY_STOP
                logging.info(f"ราคาเสนอซื้อ ({target_price}) สูงกว่าราคาตลาด Ask ({ask_price}): เลือกใช้ BUY STOP")
        else: # SELL
            if target_price > bid_price:
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
                logging.info(f"ราคาเสนอขาย ({target_price}) สูงกว่าราคาตลาด Bid ({bid_price}): เลือกใช้ SELL LIMIT")
            else:
                order_type = mt5.ORDER_TYPE_SELL_STOP
                logging.info(f"ราคาเสนอขาย ({target_price}) ต่ำกว่าราคาตลาด Bid ({bid_price}): เลือกใช้ SELL STOP")
                
        request = {
            "symbol": symbol,
            "volume": float(lot),
            "type": order_type,
            "price": target_price,
            "sl": final_sl,
            "tp": final_tp,
            "deviation": 20,
            "magic": int(magic),
            "comment": "LLM Auto Trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "action": mt5.TRADE_ACTION_PENDING
        }
        
        # ส่งคำสั่งไปยังโบรกเกอร์
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            err_msg = f"ส่งคำสั่ง {direction} ล้มเหลว: {result.comment} (code: {result.retcode})"
            logging.error(err_msg)
            return {"status": "FAILED", "message": err_msg}
            
        logging.info(f"ส่ง Pending Order สำเร็จผ่าน MT5! Ticket: {result.order} ที่ราคา {target_price}")
        return {"status": "SUCCESS", "order_id": result.order, "is_pending": True}
    def close_position(self, ticket, symbol="XAUUSD"):
        """ปิดออเดอร์ที่ระบุด้วยตั๋ว Ticket ID"""
        symbol = self.resolve_symbol(symbol)
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
            "magic": pos.magic,
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
        """แก้ไขจุด SL / TP ของออเดอร์ที่มีอยู่ พร้อมตรวจสอบความปลอดภัยทิศทางและ Stops Level"""
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"status": "ERROR", "message": "ไม่พบออเดอร์ในระบบ"}
            
        pos = positions[0]
        symbol = pos.symbol
        sym_info = mt5.symbol_info(symbol)
        
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"status": "ERROR", "message": "ไม่สามารถดึงข้อมูลราคาล่าสุดได้"}
            
        # หาขอบเขตความกว้างขั้นต่ำของโบรกเกอร์ (Stops Level)
        point = sym_info.point if sym_info else 0.00001
        stops_level_points = sym_info.trade_stops_level if sym_info else 30
        # บางโบรกเกอร์ส่งค่า trade_stops_level มาเป็น 0 แต่จริง ๆ มีการจำกัด ให้กันเหนียวไว้ที่อย่างน้อย 30 points
        if stops_level_points == 0:
            stops_level_points = 30
        stops_limit = stops_level_points * point
        
        final_sl = pos.sl
        final_tp = pos.tp
        
        # ตรวจสอบทิศทางและระยะห่างของ SL/TP
        if pos.type == mt5.POSITION_TYPE_BUY:
            # สำหรับ BUY: SL ต้องอยู่ต่ำกว่าราคาปัจจุบัน (Bid) และ TP ต้องอยู่สูงกว่าราคาปัจจุบัน
            current_price = tick.bid
            
            if new_sl is not None:
                requested_sl = float(new_sl)
                max_valid_sl = current_price - stops_limit
                if requested_sl > max_valid_sl:
                    logging.warning(f"⚠️ [Self-Healing] SL ที่ AI ขอมา ({requested_sl}) สูงกว่าขีดจำกัดสูงสุดสำหรับ BUY ({max_valid_sl}) - ปรับลงเป็น {max_valid_sl}")
                    final_sl = max_valid_sl
                else:
                    final_sl = requested_sl
                    
            if new_tp is not None:
                requested_tp = float(new_tp)
                min_valid_tp = current_price + stops_limit
                if requested_tp < min_valid_tp:
                    logging.warning(f"⚠️ [Self-Healing] TP ที่ AI ขอมา ({requested_tp}) ต่ำกว่าขีดจำกัดต่ำสุดสำหรับ BUY ({min_valid_tp}) - ปรับขึ้นเป็น {min_valid_tp}")
                    final_tp = min_valid_tp
                else:
                    final_tp = requested_tp
                    
        elif pos.type == mt5.POSITION_TYPE_SELL:
            # สำหรับ SELL: SL ต้องอยู่สูงกว่าราคาปัจจุบัน (Ask) และ TP ต้องอยู่ต่ำกว่าราคาปัจจุบัน
            current_price = tick.ask
            
            if new_sl is not None:
                requested_sl = float(new_sl)
                min_valid_sl = current_price + stops_limit
                if requested_sl < min_valid_sl:
                    logging.warning(f"⚠️ [Self-Healing] SL ที่ AI ขอมา ({requested_sl}) ต่ำกว่าขีดจำกัดต่ำสุดสำหรับ SELL ({min_valid_sl}) - ปรับขึ้นเป็น {min_valid_sl}")
                    final_sl = min_valid_sl
                else:
                    final_sl = requested_sl
                    
            if new_tp is not None:
                requested_tp = float(new_tp)
                max_valid_tp = current_price - stops_limit
                if requested_tp > max_valid_tp:
                    logging.warning(f"⚠️ [Self-Healing] TP ที่ AI ขอมา ({requested_tp}) สูงกว่าขีดจำกัดสูงสุดสำหรับ SELL ({max_valid_tp}) - ปรับลงเป็น {max_valid_tp}")
                    final_tp = max_valid_tp
                else:
                    final_tp = requested_tp

        # ทำการปัดเศษราคาให้ตรงกับ Tick Size และจำนวนทศนิยมของสัญลักษณ์
        if sym_info:
            digits = sym_info.digits
            tick_size = sym_info.trade_tick_size
            if final_sl > 0:
                final_sl = round(round(final_sl / tick_size) * tick_size, digits)
            if final_tp > 0:
                final_tp = round(round(final_tp / tick_size) * tick_size, digits)
                
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
        return {"status": "SUCCESS", "final_sl": final_sl, "final_tp": final_tp}

    def get_pending_orders(self, symbol="XAUUSD", magic=None):
        """ดึงคำสั่งซื้อขายล่วงหน้า (Pending Orders) ที่ยังไม่ถูกจับคู่"""
        symbol = self.resolve_symbol(symbol)
        if not self.connect():
            return []
            
        orders = mt5.orders_get(symbol=symbol)
        if orders is None:
            logging.error(f"ไม่สามารถดึงข้อมูล Pending Orders ได้: {mt5.last_error()}")
            return []
            
        orders_list = []
        for ord in orders:
            if magic is not None and ord.magic != int(magic):
                continue
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

    def modify_pending_order(self, ticket, price, sl=None, tp=None):
        """แก้ไขราคาเข้า จุด SL หรือ TP ของคำสั่งซื้อขายล่วงหน้า (Pending Order) พร้อมแปลงประเภทอัตโนมัติหากราคาพ้นราคาตลาด"""
        if not self.connect():
            return {"status": "ERROR", "message": "ไม่ได้เชื่อมต่อ MT5"}
            
        ord_info = mt5.orders_get(ticket=int(ticket))
        if ord_info is None or len(ord_info) == 0:
            return {"status": "ERROR", "message": f"ไม่พบคำสั่งซื้อขายล่วงหน้า #{ticket}"}
            
        ord = ord_info[0]
        symbol = ord.symbol
        sym_info = mt5.symbol_info(symbol)
        if not sym_info:
            return {"status": "ERROR", "message": f"ไม่พบข้อมูลคู่เงิน {symbol}"}
            
        digits = sym_info.digits
        tick_size = sym_info.trade_tick_size
        
        price_info = self.get_current_price(symbol)
        if not price_info:
            return {"status": "ERROR", "message": "ไม่สามารถอ่านราคาปัจจุบันได้"}
            
        bid_price = price_info["bid"]
        ask_price = price_info["ask"]
        
        # ตรวจสอบทิศทางจากของเดิม
        is_buy = ord.type in [mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP]
        direction = "BUY" if is_buy else "SELL"
        
        new_price = float(price)
        final_price = round(round(new_price / tick_size) * tick_size, digits)
        
        # ตรวจสอบประเภทคำสั่งซื้อขายล่วงหน้าที่ต้องใช้จริงตามราคาใหม่
        if is_buy:
            required_type = mt5.ORDER_TYPE_BUY_LIMIT if final_price < ask_price else mt5.ORDER_TYPE_BUY_STOP
        else:
            required_type = mt5.ORDER_TYPE_SELL_LIMIT if final_price > bid_price else mt5.ORDER_TYPE_SELL_STOP
            
        # ตรวจสอบและแก้ไข SL/TP ในกรณีตั้งกลับทิศทาง (Auto-correct reversed SL/TP)
        final_sl = float(sl) if sl else 0.0
        final_tp = float(tp) if tp else 0.0
        
        if is_buy:
            if final_sl > 0.0 and final_sl >= final_price:
                if final_tp > 0.0 and final_tp <= final_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = 0.0
            if final_tp > 0.0 and final_tp <= final_price:
                final_tp = 0.0
        else: # SELL
            if final_sl > 0.0 and final_sl <= final_price:
                if final_tp > 0.0 and final_tp >= final_price:
                    final_sl, final_tp = final_tp, final_sl
                else:
                    final_sl = 0.0
            if final_tp > 0.0 and final_tp >= final_price:
                final_tp = 0.0
                
        # ปรับทศนิยมตามโบรกเกอร์
        final_sl = round(round(final_sl / tick_size) * tick_size, digits) if final_sl > 0.0 else 0.0
        final_tp = round(round(final_tp / tick_size) * tick_size, digits) if final_tp > 0.0 else 0.0
        
        # หากจำเป็นต้องสลับประเภทคำสั่ง (เช่นจาก LIMIT เป็น STOP) เนื่องจากราคาตลาดวิ่งข้ามจุด
        # ให้สลับลบออเดอร์เดิมและสั่งตั้งคำสั่งอันใหม่ของกลยุทธ์โดยทันทีเพื่อกันข้อผิดพลาด Invalid Price
        if required_type != ord.type:
            logging.info(f"ราคาใหม่ {final_price} ต้องการประเภทออเดอร์ {required_type} ซึ่งต่างจากเดิม {ord.type}: สั่งลบตั๋ว #{ticket} และตั้งใหม่")
            cancel_res = self.cancel_pending_order(ticket)
            if cancel_res.get("status") == "SUCCESS":
                new_order_res = self.open_position(
                    direction=direction,
                    lot=ord.volume_current,
                    sl=final_sl if final_sl > 0.0 else None,
                    tp=final_tp if final_tp > 0.0 else None,
                    entry=final_price,
                    symbol=symbol,
                    magic=ord.magic
                )
                return new_order_res
            else:
                return cancel_res
                
        # หากประเภทออเดอร์ยังสอดคล้อง ดำเนินการปรับปรุงตามเดิม
        request = {
            "action": mt5.TRADE_ACTION_MODIFY,
            "order": int(ticket),
            "price": final_price,
            "sl": final_sl,
            "tp": final_tp,
            "type_time": mt5.ORDER_TIME_GTC
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"ไม่สามารถแก้ไขคำสั่งล่วงหน้า #{ticket} ได้: {result.comment}")
            return {"status": "FAILED", "message": result.comment}
            
        logging.info(f"แก้ไขคำสั่งล่วงหน้า #{ticket} สำเร็จผ่าน MT5! ราคา: {final_price} | SL: {final_sl} | TP: {final_tp}")
        return {"status": "SUCCESS", "order_id": ticket}

    def get_trade_history(self, symbol="XAUUSD", days=7, magic=None):
        """ดึงประวัติการเทรดที่ปิดแล้วย้อนหลังสำหรับสินทรัพย์ที่กำหนด"""
        symbol = self.resolve_symbol(symbol)
        if not self.connect():
            return []
            
        from datetime import datetime, timedelta, timezone
        
        # ค้นหาสัญญาจำลองตามจริงเพื่อคำนวณราคาเปิดย้อนหลังกรณีจำเป็น
        sym_info = mt5.symbol_info(symbol)
        contract_size = sym_info.trade_contract_size if sym_info else (100.0 if "XAU" in symbol else 1.0)
        
        # ดึงประวัติย้อนหลังตั้งแต่ n วันก่อน
        now = datetime.now()
        from_date = now - timedelta(days=days)
        to_date = now + timedelta(days=1)
        
        deals = mt5.history_deals_get(from_date, to_date)
        if deals is None:
            logging.error(f"ไม่สามารถดึงข้อมูลประวัติการเทรดได้: {mt5.last_error()}")
            return []
            
        # จัดกลุ่มดีลตาม position_id
        position_deals = {}
        for deal in deals:
            # กรองดีลเฉพาะเกี่ยวกับสินทรัพย์ที่สนใจ
            if not deal.symbol or symbol not in deal.symbol:
                continue
            pos_id = deal.position_id
            if pos_id not in position_deals:
                position_deals[pos_id] = []
            position_deals[pos_id].append(deal)
            
        history_list = []
        for pos_id, p_deals in position_deals.items():
            # กรองเฉพาะดีลที่ปิดสมบูรณ์แล้ว (มี DEAL_ENTRY_OUT)
            has_out = any(d.entry == mt5.DEAL_ENTRY_OUT for d in p_deals)
            if not has_out:
                continue
                
            open_deal = None
            close_deal = None
            total_pnl = 0.0
            total_lot = 0.0
            
            for d in p_deals:
                if d.entry == mt5.DEAL_ENTRY_IN:
                    open_deal = d
                    total_lot = d.volume
                elif d.entry == mt5.DEAL_ENTRY_OUT:
                    close_deal = d
                total_pnl += d.profit + d.commission + d.swap
                
            if not open_deal or not close_deal:
                continue
                
            if magic is not None and open_deal.magic != int(magic):
                continue
                
            direction = "BUY" if open_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
            
            # เวลาเปิด/ปิด (เวลา Server MT5)
            open_time_str = datetime.fromtimestamp(open_deal.time).strftime('%Y-%m-%d %H:%M:%S')
            close_time_str = datetime.fromtimestamp(close_deal.time).strftime('%Y-%m-%d %H:%M:%S')
            
            # เหตุผลปิดออเดอร์
            close_reason = "MARKET_CLOSE"
            if close_deal.reason == 3:
                close_reason = "SL"
            elif close_deal.reason == 4:
                close_reason = "TP"
            elif close_deal.reason == 5:
                close_reason = "STOP_OUT"
            elif close_deal.reason == 1:
                close_reason = "BOT_CLOSE"
                
            history_list.append({
                "id": str(pos_id),
                "direction": direction,
                "lot": total_lot,
                "entry_price": open_deal.price,
                "close_price": close_deal.price,
                "sl": open_deal.sl if hasattr(open_deal, 'sl') and open_deal.sl > 0 else None,
                "tp": open_deal.tp if hasattr(open_deal, 'tp') and open_deal.tp > 0 else None,
                "pnl": round(total_pnl, 2),
                "open_time": open_time_str,
                "close_time": close_time_str,
                "close_reason": close_reason,
                "magic": open_deal.magic
            })
            
        history_list.sort(key=lambda x: x["close_time"], reverse=True)
        return history_list

    def get_global_variable(self, name):
        """ดึงค่าตัวแปร Global จาก MT5 Terminal"""
        if not self.connect():
            return None
        import MetaTrader5 as mt5
        try:
            return mt5.global_variable_get(name)
        except Exception:
            return None