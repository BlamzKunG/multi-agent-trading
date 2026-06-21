import os
import logging
import json
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request

# นำเข้าตัวควบคุมพอร์ตจำลองและพอร์ตจริง
from bot_orchestrator import TradingBotOrchestrator
from bot_orchestrator_mt5 import MT5TradingBotOrchestrator

# ----------------------------------------------------
# 📌 1. ตั้งค่าระบบ Logging ในหน่วยความจำเพื่อส่งไปแสดงบนหน้าเว็บ
# ----------------------------------------------------
class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = []
        
    def emit(self, record):
        log_entry = self.format(record)
        self.logs.append(log_entry)
        # เก็บประวัติการล็อกย้อนหลังสูงสุด 150 บรรทัด
        if len(self.logs) > 150:
            self.logs.pop(0)

# สร้างและผูกระบบ log handler
log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# ----------------------------------------------------
# 📌 2. เริ่มต้นระบบ Flask Web Server
# ----------------------------------------------------
app = Flask(__name__, template_folder='templates')

# ดึง API Key
api_key = os.environ.get("MAXPLUS_API_KEY", "DEMO_KEY")
if api_key == "DEMO_KEY":
    logging.warning("เตือน: ไม่พบ MAXPLUS_API_KEY ในระบบกรุณาตั้งค่าเพื่อใช้งานโมเดลวิเคราะห์จริง")

# การตั้งค่าเริ่มต้นของ Dashboard
dashboard_config = {
    "mode": "sim",            # "sim" หรือ "mt5"
    "max_lot": 0.01,
    "auto_pilot": False,      # โหมดรันอัตโนมัติ
    "interval_minutes": 5     # ทุกกี่นาที
}

# สร้างอินสแตนซ์ของบอทสำหรับทั้ง 2 โหมด
bot_sim = TradingBotOrchestrator(api_key=api_key)
bot_mt5 = MT5TradingBotOrchestrator(api_key=api_key)

CONFIG_FILE = "dashboard_config.json"
EQUITY_HISTORY_FILE = "equity_history.json"

def load_config():
    global dashboard_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                dashboard_config.update(loaded)
            # ซิงค์ค่าล็อตสูงสุดให้บอท
            bot_sim.max_lot = float(dashboard_config.get("max_lot", 0.01))
            bot_mt5.max_lot = float(dashboard_config.get("max_lot", 0.01))
        except Exception as e:
            logging.error(f"โหลดไฟล์ตั้งค่าล้มเหลว: {e}")

def save_config_file():
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(dashboard_config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"บันทึกไฟล์ตั้งค่าล้มเหลว: {e}")

# โหลดค่าตั้งค่าเริ่มต้น
load_config()

# ----------------------------------------------------
# 📌 3. ระบบบันทึกประวัติพอร์ต (Equity Logger)
# ----------------------------------------------------
def log_equity(mode, balance, equity):
    history_data = {}
    if os.path.exists(EQUITY_HISTORY_FILE):
        try:
            with open(EQUITY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except Exception:
            pass
            
    if mode not in history_data:
        history_data[mode] = []
        
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    history_data[mode].append({
        "timestamp": timestamp,
        "balance": float(balance),
        "equity": float(equity)
    })
    
    if len(history_data[mode]) > 100:
        history_data[mode].pop(0)
        
    try:
        with open(EQUITY_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"บันทึกประวัติ Equity ล้มเหลว: {e}")

def run_cycle_and_log(mode):
    """รันรอบบอทพร้อมบันทึกประวัติพอร์ต"""
    if mode == "sim":
        bot_sim.run_cycle()
        status = bot_sim.exchange.get_status()
        log_equity("sim", status["balance"], status["equity"])
    else:
        bot_mt5.run_cycle()
        if bot_mt5.mt5_bridge.connect():
            acc_status = bot_mt5.mt5_bridge.get_account_status()
            if acc_status:
                log_equity("mt5", acc_status["balance"], acc_status["equity"])

# ----------------------------------------------------
# 📌 4. ระบบ Scheduler (Auto-Pilot Background Loop)
# ----------------------------------------------------
scheduler_running = True

def scheduler_loop():
    global scheduler_running
    last_run_time = {} # mode -> timestamp
    
    while scheduler_running:
        try:
            auto_pilot = dashboard_config.get("auto_pilot", False)
            interval_min = int(dashboard_config.get("interval_minutes", 5))
            mode = dashboard_config.get("mode", "sim")
            
            if auto_pilot:
                now = time.time()
                last_run = last_run_time.get(mode, 0)
                interval_sec = interval_min * 60
                
                if now - last_run >= interval_sec:
                    logging.info(f"⏰ [Auto-Pilot] ถึงรอบรันอัตโนมัติ ({interval_min} นาที) ในโหมด {mode.upper()}")
                    last_run_time[mode] = now
                    run_cycle_and_log(mode)
        except Exception as e:
            logging.error(f"เกิดข้อผิดพลาดใน scheduler loop: {e}")
            
        time.sleep(1)

# สตาร์ทเทรดควบคุม
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

# ----------------------------------------------------
# 📌 5. REST APIs & Routes
# ----------------------------------------------------
@app.route('/')
def home():
    """เสิร์ฟหน้า Dashboard หลัก"""
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    """ดึงข้อมูลสถานะพอร์ตและราคาปัจจุบัน ส่งกลับไปที่หน้าเว็บ"""
    mode = dashboard_config["mode"]
    
    try:
        if mode == "sim":
            is_gold_open = bot_sim.is_gold_market_open()
            if is_gold_open:
                bot_sim.symbol = "XAUUSD"
                bot_sim.data_feed.symbol = "GC=F"
                bot_sim.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
                bot_sim.exchange.contract_size = 100.0
            else:
                bot_sim.symbol = "BTCUSD"
                bot_sim.data_feed.symbol = "BTC-USD"
                bot_sim.data_feed.url = "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD"
                bot_sim.exchange.contract_size = 1.0
                
            current_price = bot_sim.data_feed.get_current_price() or 0.0
            bot_sim.exchange.update_price(current_price)
            status = bot_sim.exchange.get_status()
            
            return jsonify({
                "status": "SUCCESS",
                "mode": "sim",
                "symbol": bot_sim.symbol,
                "current_price": current_price,
                "balance": status["balance"],
                "equity": status["equity"],
                "floating_pnl": status["floating_pnl"],
                "open_positions": status["open_positions"],
                "pending_orders": [], 
                "max_lot": dashboard_config["max_lot"],
                "auto_pilot": dashboard_config["auto_pilot"],
                "interval_minutes": dashboard_config["interval_minutes"]
            })
            
        else:
            is_gold_open = bot_mt5.is_gold_market_open()
            if is_gold_open:
                bot_mt5.symbol = "XAUUSD"
            else:
                bot_mt5.symbol = "BTCUSD"
                
            connected = bot_mt5.mt5_bridge.connect()
            if not connected:
                return jsonify({
                    "status": "ERROR",
                    "mode": "live",
                    "symbol": bot_mt5.symbol,
                    "current_price": 0.0,
                    "balance": 0.0,
                    "equity": 0.0,
                    "floating_pnl": 0.0,
                    "open_positions": [],
                    "pending_orders": [],
                    "max_lot": dashboard_config["max_lot"],
                    "auto_pilot": dashboard_config["auto_pilot"],
                    "interval_minutes": dashboard_config["interval_minutes"],
                    "message": "ไม่สามารถเชื่อมต่อโปรแกรม MT5 Terminal ได้"
                })
                
            price_info = bot_mt5.mt5_bridge.get_current_price(bot_mt5.symbol) or {"price": 0.0}
            acc_status = bot_mt5.mt5_bridge.get_account_status() or {"balance": 0.0, "equity": 0.0, "floating_pnl": 0.0}
            open_positions = bot_mt5.mt5_bridge.get_open_positions(bot_mt5.symbol)
            pending_orders = bot_mt5.mt5_bridge.get_pending_orders(bot_mt5.symbol)
            
            return jsonify({
                "status": "SUCCESS",
                "mode": "live",
                "symbol": bot_mt5.symbol,
                "current_price": price_info["price"],
                "balance": acc_status["balance"],
                "equity": acc_status["equity"],
                "floating_pnl": acc_status["floating_pnl"],
                "open_positions": open_positions,
                "pending_orders": pending_orders,
                "max_lot": dashboard_config["max_lot"],
                "auto_pilot": dashboard_config["auto_pilot"],
                "interval_minutes": dashboard_config["interval_minutes"]
            })
            
    except Exception as e:
        return jsonify({
            "status": "ERROR",
            "message": f"เกิดข้อผิดพลาดในการดึงสถานะ: {str(e)}"
        })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """ส่งรายการ log ทั้งหมดกลับไปที่หน้าเว็บแบบเรียลไทม์"""
    return jsonify({
        "logs": log_handler.logs
    })

@app.route('/api/run', methods=['POST'])
def run_sync_cycle():
    """สั่งรันวงจรรอบตัดสินใจของบอททันที 1 รอบ"""
    mode = dashboard_config["mode"]
    
    try:
        logging.info(f"--- สั่งรันวิเคราะห์รอบ ({mode.upper()}) ด้วยมือผ่าน Dashboard Web UI ---")
        run_cycle_and_log(mode)
        return jsonify({"status": "SUCCESS"})
    except Exception as e:
        logging.error(f"การรันวงจรรอบตัดสินใจล้มเหลว: {str(e)}")
        return jsonify({"status": "ERROR", "message": str(e)})

@app.route('/api/close', methods=['POST'])
def close_trade():
    """สั่งปิดออเดอร์ค้างทันทีผ่านแผงหน้าเว็บ"""
    mode = dashboard_config["mode"]
    req_data = request.get_json()
    pos_id = req_data.get("id")
    
    try:
        if mode == "sim":
            res = bot_sim.exchange.close_position(pos_id)
            if res["status"] == "SUCCESS":
                logging.info(f"สั่งปิดออเดอร์จำลอง #{pos_id} สำเร็จผ่านหน้าเว็บ UI")
                return jsonify({"status": "SUCCESS"})
            return jsonify({"status": "ERROR", "message": res.get("message")})
        else:
            res = bot_mt5.mt5_bridge.close_position(ticket=int(pos_id), symbol=bot_mt5.symbol)
            if res["status"] == "SUCCESS":
                logging.info(f"สั่งปิดออเดอร์ MT5 #{pos_id} สำเร็จผ่านหน้าเว็บ UI")
                return jsonify({"status": "SUCCESS"})
            return jsonify({"status": "ERROR", "message": res.get("message")})
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)})

@app.route('/api/cancel', methods=['POST'])
def cancel_order():
    """ยกเลิกออเดอร์ล่วงหน้า (Pending Order)"""
    mode = dashboard_config["mode"]
    req_data = request.get_json()
    order_id = req_data.get("id")
    
    try:
        if mode == "sim":
            return jsonify({"status": "ERROR", "message": "โหมดจำลองไม่รองรับออเดอร์ล่วงหน้า"})
        else:
            res = bot_mt5.mt5_bridge.cancel_pending_order(ticket=int(order_id))
            if res["status"] == "SUCCESS":
                logging.info(f"ยกเลิกคำสั่งล่วงหน้า #{order_id} สำเร็จผ่านหน้าเว็บ UI")
                return jsonify({"status": "SUCCESS"})
            return jsonify({"status": "ERROR", "message": res.get("message")})
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)})

@app.route('/api/config', methods=['POST'])
def update_config():
    """ปรับแต่งการตั้งค่าโหมดการรันและขนาดล็อตสูงสุด"""
    req_data = request.get_json()
    mode = req_data.get("mode")
    max_lot = float(req_data.get("max_lot", 0.01))
    auto_pilot = bool(req_data.get("auto_pilot", False))
    interval_minutes = int(req_data.get("interval_minutes", 5))
    
    dashboard_config["mode"] = mode
    dashboard_config["max_lot"] = max_lot
    dashboard_config["auto_pilot"] = auto_pilot
    dashboard_config["interval_minutes"] = interval_minutes
    
    # อัปเดตล็อตบอท
    bot_sim.max_lot = max_lot
    bot_mt5.max_lot = max_lot
    
    save_config_file()
    
    logging.info(f"💾 บันทึกการตั้งค่าบอท: โหมด={mode.upper()} | ล็อตสูงสุด={max_lot} | Auto-Pilot={auto_pilot} | รอบ={interval_minutes} นาที")
    return jsonify({"status": "SUCCESS"})

@app.route('/api/history', methods=['GET'])
def get_history():
    """ดึงประวัติการปิดออเดอร์ย้อนหลัง"""
    mode = dashboard_config["mode"]
    try:
        if mode == "sim":
            history = bot_sim.exchange.history
            return jsonify({
                "status": "SUCCESS",
                "history": history
            })
        else:
            connected = bot_mt5.mt5_bridge.connect()
            if not connected:
                return jsonify({
                    "status": "ERROR",
                    "history": [],
                    "message": "ไม่ได้เชื่อมต่อ MT5"
                })
            history = bot_mt5.mt5_bridge.get_trade_history(bot_mt5.symbol)
            return jsonify({
                "status": "SUCCESS",
                "history": history
            })
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)})

@app.route('/api/equity_chart', methods=['GET'])
def get_equity_chart():
    """ดึงข้อมูลประวัติ Balance/Equity เพื่อนำไปพล็อตกราฟ"""
    mode = dashboard_config["mode"]
    history_data = {}
    if os.path.exists(EQUITY_HISTORY_FILE):
        try:
            with open(EQUITY_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
        except Exception:
            pass
            
    points = history_data.get(mode, [])
    return jsonify({
        "status": "SUCCESS",
        "points": points
    })

if __name__ == '__main__':
    logging.info("เริ่มต้นเปิดใช้งานระบบ Web Dashboard บนพอร์ต 5000...")
    logging.info("คุณสามารถเข้าใช้งานได้ทาง: http://127.0.0.1:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)
