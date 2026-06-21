import os
import sys
import json
import logging
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# นำเข้าตัวควบคุมพอร์ตจำลองและพอร์ตจริง
from bot_orchestrator import TradingBotOrchestrator
from bot_orchestrator_mt5 import MT5TradingBotOrchestrator

# ----------------------------------------------------
# 📌 1. โหลดข้อมูล API Key เริ่มต้น
# ----------------------------------------------------
DEFAULT_API_KEY = os.environ.get("MAXPLUS_API_KEY", "")

# สร้างบอทเริ่มต้น (เดี๋ยวคีย์จะถูกอัปเดตจากช่องกรอกใน GUI)
bot_sim = TradingBotOrchestrator(api_key=DEFAULT_API_KEY)
bot_mt5 = MT5TradingBotOrchestrator(api_key=DEFAULT_API_KEY)

# ----------------------------------------------------
# 📌 2. การเชื่อมการ Logging เข้าสู่หน้าจอ GUI Terminal
# ----------------------------------------------------
class TextHandler(logging.Handler):
    """ส่งต่อบันทึก Log ของระบบไปแสดงใน Widget ScrolledText ของ GUI"""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        
    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            if "ERROR" in msg:
                self.text_widget.insert('end', msg + '\n', 'error')
            elif "WARNING" in msg:
                self.text_widget.insert('end', msg + '\n', 'warning')
            elif "สำเร็จ" in msg or "SUCCESS" in msg or "เปิดออเดอร์ใหม่สำเร็จ" in msg:
                self.text_widget.insert('end', msg + '\n', 'success')
            else:
                self.text_widget.insert('end', msg + '\n', 'info')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview('end')
        
        # ป้องกันปัญหาเธรดขัดแย้ง (Thread Safety) ด้วย after
        try:
            self.text_widget.after(0, append)
        except Exception:
            pass

# ----------------------------------------------------
# 📌 3. คลาสควบคุมรอบเวลาเบื้องหลัง (Background Scheduler)
# ----------------------------------------------------
class BotScheduler(threading.Thread):
    def __init__(self, run_cycle_func, check_active_func):
        super().__init__(daemon=True)
        self.run_cycle_func = run_cycle_func
        self.check_active_func = check_active_func
        self.last_run_time = 0
        
    def run(self):
        while True:
            try:
                active, interval_min = self.check_active_func()
                if active:
                    now = time.time()
                    interval_sec = interval_min * 60
                    if now - self.last_run_time >= interval_sec:
                        self.last_run_time = now
                        logging.info(f"⏰ [Auto-Pilot] ถึงเวลาตามรอบทำงาน ({interval_min} นาที) - กำลังเริ่มรอบงาน...")
                        # รันผ่าน thread ย่อยเพื่อป้องกัน GUI ค้าง
                        t = threading.Thread(target=self.run_cycle_func, daemon=True)
                        t.start()
            except Exception as e:
                logging.error(f"เกิดข้อผิดพลาดใน scheduler loop: {e}")
            time.sleep(1)

# ----------------------------------------------------
# 📌 4. ตัวออกแบบและสร้างหน้าจอ GUI (Main Application)
# ----------------------------------------------------
class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MaxPlus AI Agent Hub - Trading Terminal")
        self.root.geometry("1200x750")
        self.root.configure(bg="#0f172a") # Dark Slate Theme
        
        self.scheduler = None
        self.is_running_cycle = False
        
        # ตั้งค่า Fonts & Styles
        self.font_title = ("Outfit", 12, "bold")
        self.font_label = ("Outfit", 10)
        self.font_metric_num = ("Outfit", 20, "bold")
        self.font_metric_lbl = ("Outfit", 8, "bold")
        
        # สร้างตัวแปรเก็บค่าต่างๆ ของระบบควบคุม
        self.var_mode = tk.StringVar(value="Simulation")
        self.var_auto_pilot = tk.BooleanVar(value=False)
        
        self.setup_ui()
        self.setup_logging()
        self.load_config()
        self.start_scheduler()
        
        # เริ่มต้นลูปอัปเดตราคาพอร์ตและตารางออเดอร์
        self.update_portfolio_loop()
        
    def setup_ui(self):
        # ออกแบบ Layout สองคอลัมน์หลัก (ซ้าย: ตั้งค่า / ขวา: แสดงสถานะและล็อก)
        self.left_panel = tk.Frame(self.root, bg="#1e293b", width=350, padx=15, pady=15)
        self.left_panel.pack(side="left", fill="y", padx=(10, 5), pady=10)
        self.left_panel.pack_propagate(False)
        
        self.right_panel = tk.Frame(self.root, bg="#0f172a", padx=5, pady=10)
        self.right_panel.pack(side="right", expand=True, fill="both", padx=(5, 10))
        
        # ----------------------------------------------------
        # 🅰️ ออกแบบเมนูด้านซ้าย: คอนฟิกและปุ่มควบคุม
        # ----------------------------------------------------
        
        # 1. หัวข้อระบบบอท
        lbl_head = tk.Label(self.left_panel, text="🤖 บัญชีและการตั้งค่าบอท", font=self.font_title, bg="#1e293b", fg="#f8fafc")
        lbl_head.pack(anchor="w", pady=(0, 15))
        
        # 2. ปรับโหมดการทำงาน
        tk.Label(self.left_panel, text="Trading Mode (โหมดเทรด)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.cb_mode = ttk.Combobox(self.left_panel, textvariable=self.var_mode, values=["Simulation", "MT5 Live"], state="readonly")
        self.cb_mode.pack(fill="x", pady=(2, 10))
        self.cb_mode.bind("<<ComboboxSelected>>", self.on_mode_change)
        
        # 3. ช่องใส่ API Key
        tk.Label(self.left_panel, text="MaxPlus API Key", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_api_key = tk.Entry(self.left_panel, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=5)
        self.ent_api_key.pack(fill="x", pady=(2, 10))
        
        # 4. รายละเอียด MT5 (แสดงเฉพาะเมื่อใช้งาน MT5 Live)
        self.frame_mt5 = tk.LabelFrame(self.left_panel, text="⚙️ ตั้งค่า MetaTrader 5 Login", font=self.font_label, bg="#1e293b", fg="#fbbf24", padx=10, pady=10, relief="solid", bd=1)
        self.frame_mt5.pack(fill="x", pady=(0, 15))
        
        tk.Label(self.frame_mt5, text="Login ID (หมายเลขบัญชี)", font=("Outfit", 9), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_login = tk.Entry(self.frame_mt5, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=3)
        self.ent_mt5_login.pack(fill="x", pady=(1, 5))
        
        tk.Label(self.frame_mt5, text="Password (รหัสผ่าน)", font=("Outfit", 9), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_pass = tk.Entry(self.frame_mt5, show="*", bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=3)
        self.ent_mt5_pass.pack(fill="x", pady=(1, 5))
        
        tk.Label(self.frame_mt5, text="Server (เซิร์ฟเวอร์โบรกเกอร์)", font=("Outfit", 9), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_server = tk.Entry(self.frame_mt5, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=3)
        self.ent_mt5_server.pack(fill="x", pady=(1, 5))
        
        # 5. จำกัดความเสี่ยง
        tk.Label(self.left_panel, text="Max Allowed Lot size (ล็อตสูงสุด)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_max_lot = tk.Entry(self.left_panel, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=5)
        self.ent_max_lot.pack(fill="x", pady=(2, 10))
        self.ent_max_lot.insert(0, "0.01")
        
        # 6. ตั้งค่าช่วงเวลารันบอท (Timer)
        tk.Label(self.left_panel, text="Interval Cycle (รอบการรันบอทกี่นาที)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_interval = tk.Entry(self.left_panel, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=5)
        self.ent_interval.pack(fill="x", pady=(2, 10))
        self.ent_interval.insert(0, "5")
        
        # 7. ปรับสวิตช์ Auto-Pilot
        self.chk_auto = tk.Checkbutton(self.left_panel, text="⚙️ เปิดใช้ระบบ Auto-Pilot (รันออโต้)", variable=self.var_auto_pilot, font=self.font_label, bg="#1e293b", fg="#818cf8", selectcolor="#0f172a", activebackground="#1e293b", activeforeground="#818cf8", command=self.on_auto_pilot_toggle)
        self.chk_auto.pack(anchor="w", pady=(5, 15))
        
        # 8. ปุ่มหลักในการเซฟการตั้งค่าและยิงระบบแมนนวล
        btn_save = tk.Button(self.left_panel, text="💾 Save Configuration", font=self.font_label, bg="#818cf8", fg="#0f172a", activebackground="#f472b6", relief="flat", height=2, command=self.save_config)
        btn_save.pack(fill="x", pady=(0, 10))
        
        self.btn_run = tk.Button(self.left_panel, text="⚡ Run Sync Cycle Now", font=self.font_label, bg="#10b981", fg="#f8fafc", activebackground="#34d399", relief="flat", height=2, command=self.trigger_manual_cycle)
        self.btn_run.pack(fill="x", pady=(0, 10))
        
        self.lbl_sched_status = tk.Label(self.left_panel, text="สถานะ: หยุดการทำงานออโต้", font=self.font_label, bg="#1e293b", fg="#ef4444")
        self.lbl_sched_status.pack(pady=5)
        
        # ----------------------------------------------------
        # 🅱️ ออกแบบเมนูด้านขวา: Metrics, Tables, Logs Terminal
        # ----------------------------------------------------
        
        # 1. แผงแสดงยอดเงิน (Metrics Cards Panel)
        self.metrics_frame = tk.Frame(self.right_panel, bg="#0f172a")
        self.metrics_frame.pack(fill="x", pady=(0, 15))
        
        self.card_balance = self.create_metric_card(self.metrics_frame, "BALANCE", "$0.00", "#f8fafc")
        self.card_balance.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        self.card_equity = self.create_metric_card(self.metrics_frame, "EQUITY", "$0.00", "#f8fafc")
        self.card_equity.grid(row=0, column=1, sticky="nsew", padx=10)
        
        self.card_pnl = self.create_metric_card(self.metrics_frame, "FLOATING P&L", "$0.00", "#10b981")
        self.card_pnl.grid(row=0, column=2, sticky="nsew", padx=10)
        
        self.card_price = self.create_metric_card(self.metrics_frame, "CURRENT PRICE", "0.00 (Offline)", "#fbbf24")
        self.card_price.grid(row=0, column=3, sticky="nsew", padx=(10, 0))
        
        self.metrics_frame.columnconfigure((0, 1, 2, 3), weight=1)
        
        # 2. แผงตารางการเทรด (Active Positions & Closed Trades History)
        self.tabs = ttk.Notebook(self.right_panel)
        self.tabs.pack(fill="both", expand=True, pady=(0, 15))
        
        # แท็บที่ 1: ออเดอร์ถือค้างอยู่
        self.tab_active = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_active, text=" Active Positions ")
        self.setup_positions_table()
        
        # แท็บที่ 2: ประวัติการเทรดที่ปิดแล้ว
        self.tab_history = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_history, text=" Trade History ")
        self.setup_history_table()
        
        # 3. แผงควบคุมระบบ Log Terminal
        self.log_frame = tk.Frame(self.right_panel, bg="#1e293b", padx=10, pady=10)
        self.log_frame.pack(fill="x", side="bottom")
        
        lbl_log_title = tk.Label(self.log_frame, text="💻 AI Trading Logging Terminal", font=self.font_title, bg="#1e293b", fg="#f8fafc")
        lbl_log_title.pack(anchor="w", pady=(0, 5))
        
        # ตัวกล่องข้อความ Log เลื่อนดูได้
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=10, bg="#020617", fg="#f8fafc", insertbackground="white", font=("JetBrains Mono", 8))
        self.log_text.pack(fill="x", expand=True)
        
        # แท็กทำสีบันทึก
        self.log_text.tag_config('error', foreground="#ef4444")
        self.log_text.tag_config('warning', foreground="#fbbf24")
        self.log_text.tag_config('success', foreground="#10b981")
        self.log_text.tag_config('info', foreground="#f8fafc")
        self.log_text.configure(state='disabled')
        
    def create_metric_card(self, parent, title, initial_value, num_color):
        card = tk.Frame(parent, bg="#1e293b", padx=15, pady=15, relief="flat")
        
        lbl_title = tk.Label(card, text=title, font=self.font_metric_lbl, bg="#1e293b", fg="#94a3b8")
        lbl_title.pack(anchor="w")
        
        lbl_val = tk.Label(card, text=initial_value, font=self.font_metric_num, bg="#1e293b", fg=num_color)
        lbl_val.pack(anchor="w", pady=(5, 0))
        
        # บันทึก label ค่าไว้ใช้อัปเดต
        card.lbl_val = lbl_val
        return card
        
    def setup_positions_table(self):
        # เฟรมตารางออเดอร์ค้าง + ปุ่มสั่งปิด
        tbl_frame = tk.Frame(self.tab_active, bg="#1e293b", padx=5, pady=5)
        tbl_frame.pack(fill="both", expand=True)
        
        columns = ("ticket", "dir", "lot", "entry", "sl", "tp", "pnl")
        self.tree_positions = ttk.Treeview(tbl_frame, columns=columns, show="headings", height=5)
        self.tree_positions.pack(side="left", fill="both", expand=True)
        
        # ตั้งชื่อคอลัมน์ภาษาไทย/อังกฤษ
        self.tree_positions.heading("ticket", text="Ticket ID")
        self.tree_positions.heading("dir", text="Direction")
        self.tree_positions.heading("lot", text="Lot Size")
        self.tree_positions.heading("entry", text="Entry Price")
        self.tree_positions.heading("sl", text="Stop Loss")
        self.tree_positions.heading("tp", text="Take Profit")
        self.tree_positions.heading("pnl", text="Floating P&L")
        
        # กำหนดขนาดคอลัมน์
        for col in columns:
            self.tree_positions.column(col, width=100, anchor="center")
            
        scrollbar = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree_positions.yview)
        self.tree_positions.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # เพิ่มปุ่มปิดไม้
        btn_frame = tk.Frame(self.tab_active, bg="#1e293b", pady=5)
        btn_frame.pack(fill="x")
        btn_close = tk.Button(btn_frame, text="🛑 Close Selected Position (สั่งปิดไม้ที่เลือก)", font=self.font_label, bg="#ef4444", fg="white", activebackground="#dc2626", command=self.close_selected_position)
        btn_close.pack(side="right", padx=10)
        
    def setup_history_table(self):
        tbl_frame = tk.Frame(self.tab_history, bg="#1e293b", padx=5, pady=5)
        tbl_frame.pack(fill="both", expand=True)
        
        columns = ("ticket", "dir", "lot", "entry", "close", "pnl", "open_time", "close_time", "reason")
        self.tree_history = ttk.Treeview(tbl_frame, columns=columns, show="headings", height=5)
        self.tree_history.pack(side="left", fill="both", expand=True)
        
        self.tree_history.heading("ticket", text="Ticket ID")
        self.tree_history.heading("dir", text="Direction")
        self.tree_history.heading("lot", text="Lot Size")
        self.tree_history.heading("entry", text="Entry Price")
        self.tree_history.heading("close", text="Close Price")
        self.tree_history.heading("pnl", text="PnL ($)")
        self.tree_history.heading("open_time", text="Open Time")
        self.tree_history.heading("close_time", text="Close Time")
        self.tree_history.heading("reason", text="Reason")
        
        for col in columns:
            self.tree_history.column(col, width=90, anchor="center")
            
        scrollbar = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree_history.yview)
        self.tree_history.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
    def setup_logging(self):
        # เชื่อม Log บันทึกของโปรเจ็กต์เข้ามาแสดงใน ScrolledText
        self.handler = TextHandler(self.log_text)
        self.handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger = logging.getLogger()
        logger.addHandler(self.handler)
        logging.info("เริ่มต้น GUI Dashboard สำเร็จ! ข้อมูล Log ระบบจะมาแสดงในช่องนี้...")
        
    # ----------------------------------------------------
    # 📌 5. ฟังก์ชันการจัดการบันทึก/โหลด Configuration JSON
    # ----------------------------------------------------
    def load_config(self):
        config_path = "gui_config.json"
        
        # ดึง API Key ปัจจุบัน
        self.ent_api_key.insert(0, DEFAULT_API_KEY)
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    
                self.var_mode.set(cfg.get("mode", "Simulation"))
                
                self.ent_api_key.delete(0, 'end')
                self.ent_api_key.insert(0, cfg.get("api_key", DEFAULT_API_KEY))
                
                self.ent_max_lot.delete(0, 'end')
                self.ent_max_lot.insert(0, str(cfg.get("max_lot", 0.01)))
                
                self.ent_interval.delete(0, 'end')
                self.ent_interval.insert(0, str(cfg.get("interval_minutes", 5)))
                
                self.var_auto_pilot.set(cfg.get("auto_pilot", False))
                
                self.ent_mt5_login.delete(0, 'end')
                self.ent_mt5_login.insert(0, str(cfg.get("mt5_login", "")))
                self.ent_mt5_pass.delete(0, 'end')
                self.ent_mt5_pass.insert(0, str(cfg.get("mt5_pass", "")))
                self.ent_mt5_server.delete(0, 'end')
                self.ent_mt5_server.insert(0, str(cfg.get("mt5_server", "")))
                
                # บังคับซิงค์ค่าไปยังบอท
                self.apply_config_to_bots(cfg)
                
            except Exception as e:
                logging.error(f"โหลดไฟล์ตั้งค่าล้มเหลว: {e}")
                
        self.on_mode_change()
        self.on_auto_pilot_toggle()
        
    def save_config(self):
        try:
            cfg = {
                "mode": self.var_mode.get(),
                "api_key": self.ent_api_key.get(),
                "max_lot": float(self.ent_max_lot.get() or 0.01),
                "interval_minutes": int(self.ent_interval.get() or 5),
                "auto_pilot": self.var_auto_pilot.get(),
                "mt5_login": self.ent_mt5_login.get(),
                "mt5_pass": self.ent_mt5_pass.get(),
                "mt5_server": self.ent_mt5_server.get()
            }
            
            with open("gui_config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
                
            self.apply_config_to_bots(cfg)
            logging.info("💾 บันทึกการตั้งค่าลงไฟล์ gui_config.json สำเร็จ!")
            messagebox.showinfo("สำเร็จ", "บันทึกการตั้งค่าและซิงค์ตัวแปรเข้าสู่ระบบสำเร็จ!")
        except Exception as e:
            logging.error(f"ไม่สามารถบันทึกค่าลงไฟล์ได้: {e}")
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถบันทึกการตั้งค่าได้: {e}")
            
    def apply_config_to_bots(self, cfg):
        # อัปเดต API Key
        key = cfg.get("api_key", "")
        if key:
            bot_sim.agents.api_key = key
            bot_sim.agents.headers["Authorization"] = f"Bearer {key}"
            bot_mt5.agents.api_key = key
            bot_mt5.agents.headers["Authorization"] = f"Bearer {key}"
            
        # อัปเดตล็อตสูงสุด
        max_lot = float(cfg.get("max_lot", 0.01))
        bot_sim.max_lot = max_lot
        bot_mt5.max_lot = max_lot
        
        # อัปเดตบัญชี MT5
        login = cfg.get("mt5_login", "")
        pwd = cfg.get("mt5_pass", "")
        srv = cfg.get("mt5_server", "")
        if login:
            bot_mt5.mt5_bridge.login = int(login)
        if pwd:
            bot_mt5.mt5_bridge.password = pwd
        if srv:
            bot_mt5.mt5_bridge.server = srv

    def on_mode_change(self, event=None):
        mode = self.var_mode.get()
        if mode == "Simulation":
            self.frame_mt5.pack_forget() # ซ่อนกล่องล็อกอิน MT5
        else:
            # ดึงกล่องตั้งค่า MT5 ขึ้นมาแสดงใต้กล่อง API Key
            self.frame_mt5.pack(fill="x", after=self.ent_api_key, pady=(0, 15))

    def on_auto_pilot_toggle(self):
        active = self.var_auto_pilot.get()
        if active:
            interval = self.ent_interval.get()
            self.lbl_sched_status.config(text=f"สถานะ: Auto-Pilot ทำงาน (ทุก {interval} นาที)", fg="#10b981")
        else:
            self.lbl_sched_status.config(text="สถานะ: หยุดการทำงานออโต้", fg="#ef4444")
            
    # ----------------------------------------------------
    # 📌 6. การเริ่มระบบ Background Scheduler
    # ----------------------------------------------------
    def start_scheduler(self):
        # สร้างฟังก์ชันให้ดึงสถานะตั้งค่าเพื่อตรวจสอบการรันในเธรดหลังบ้าน
        def check_active():
            return self.var_auto_pilot.get(), int(self.ent_interval.get() or 5)
            
        def run_cycle_safe():
            # รันผ่านระบบ sync ความปลอดภัยป้องกันการรันซ้อน
            if self.is_running_cycle:
                return
            self.is_running_cycle = True
            self.btn_run.configure(state='disabled', text="🔄 Running Cycle...")
            
            try:
                # ซิงค์ค่าล่าสุดจากหน้าจอ UI ก่อนรันรอบงาน
                cfg = {
                    "mode": self.var_mode.get(),
                    "api_key": self.ent_api_key.get(),
                    "max_lot": float(self.ent_max_lot.get() or 0.01),
                    "interval_minutes": int(self.ent_interval.get() or 5),
                    "auto_pilot": self.var_auto_pilot.get(),
                    "mt5_login": self.ent_mt5_login.get(),
                    "mt5_pass": self.ent_mt5_pass.get(),
                    "mt5_server": self.ent_mt5_server.get()
                }
                self.apply_config_to_bots(cfg)
                
                mode = cfg["mode"]
                if mode == "Simulation":
                    bot_sim.run_cycle()
                else:
                    bot_mt5.run_cycle()
            except Exception as e:
                logging.error(f"การรันวงจรประเมินผิดพลาด: {e}")
            finally:
                self.is_running_cycle = False
                self.btn_run.configure(state='normal', text="⚡ Run Sync Cycle Now")
                
        self.run_cycle_safe_func = run_cycle_safe
        self.scheduler = BotScheduler(run_cycle_safe, check_active)
        self.scheduler.start()
        
    def trigger_manual_cycle(self):
        if self.is_running_cycle:
            messagebox.showwarning("คำเตือน", "บอทกำลังรันประมวลผลรอบปัจจุบันอยู่ กรุณารอสักครู่")
            return
            
        logging.info("⚡ สั่งรันวิเคราะห์รอบตลาดทันที (Manual Trigger)...")
        # รันใน Thread เพื่อไม่ให้หน้าจอค้าง
        t = threading.Thread(target=self.run_cycle_safe_func, daemon=True)
        t.start()

    # ----------------------------------------------------
    # 📌 7. ลูปอัปเดตข้อมูลพอร์ตและตารางธุรกรรม (3 วินาทีครั้ง)
    # ----------------------------------------------------
    def update_portfolio_loop(self):
        # ทำงานแบบ Non-blocking แยกเธรดเพื่อไม่ให้ UI กระตุกขณะดึงราคา
        def do_update():
            mode = self.var_mode.get()
            try:
                if mode == "Simulation":
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
                    
                    # บัญชีจำลอง
                    bal = status["balance"]
                    eq = status["equity"]
                    pnl = status["floating_pnl"]
                    symbol = bot_sim.symbol
                    open_pos = status["open_positions"]
                    history = status.get("history", [])
                    
                    self.root.after(0, lambda: self.refresh_metrics(bal, eq, pnl, current_price, symbol))
                    self.root.after(0, lambda: self.refresh_positions_tree(open_pos))
                    self.root.after(0, lambda: self.refresh_history_tree(history))
                    
                else:
                    # โหมดเชื่อมต่อ MT5
                    is_gold_open = bot_mt5.is_gold_market_open()
                    bot_mt5.symbol = "XAUUSD" if is_gold_open else "BTCUSD"
                    
                    connected = bot_mt5.mt5_bridge.connect()
                    if connected:
                        price_info = bot_mt5.mt5_bridge.get_current_price(bot_mt5.symbol) or {"price": 0.0}
                        acc_status = bot_mt5.mt5_bridge.get_account_status() or {"balance": 0.0, "equity": 0.0, "floating_pnl": 0.0}
                        open_pos = bot_mt5.mt5_bridge.get_open_positions(bot_mt5.symbol)
                        history = bot_mt5.mt5_bridge.get_trade_history(bot_mt5.symbol)
                        
                        bal = acc_status["balance"]
                        eq = acc_status["equity"]
                        pnl = acc_status["floating_pnl"]
                        price = price_info["price"]
                        symbol = bot_mt5.symbol
                        
                        self.root.after(0, lambda: self.refresh_metrics(bal, eq, pnl, price, symbol))
                        self.root.after(0, lambda: self.refresh_positions_tree(open_pos))
                        self.root.after(0, lambda: self.refresh_history_tree(history))
                    else:
                        self.root.after(0, self.refresh_offline)
            except Exception as e:
                pass
                
        t = threading.Thread(target=do_update, daemon=True)
        t.start()
        # รันรอบหน้าในอีก 3 วินาที
        self.root.after(3000, self.update_portfolio_loop)

    def refresh_metrics(self, balance, equity, pnl, price, symbol):
        self.card_balance.lbl_val.config(text=f"${balance:,.2f}")
        self.card_equity.lbl_val.config(text=f"${equity:,.2f}")
        
        pnl_text = f"{'+' if pnl >= 0 else ''}${pnl:,.2f}"
        pnl_color = "#10b981" if pnl >= 0 else "#ef4444"
        self.card_pnl.lbl_val.config(text=pnl_text, fg=pnl_color)
        
        self.card_price.lbl_val.config(text=f"{price:,.2f} USD ({symbol})")
        
    def refresh_offline(self):
        self.card_balance.lbl_val.config(text="Offline", fg="#ef4444")
        self.card_equity.lbl_val.config(text="Offline", fg="#ef4444")
        self.card_pnl.lbl_val.config(text="$0.00", fg="#94a3b8")
        self.card_price.lbl_val.config(text="MT5 Terminal Disconnected", fg="#ef4444")
        
    def refresh_positions_tree(self, open_pos):
        # ล้างข้อมูลเดิมและเติมรายการปัจจุบัน
        self.tree_positions.delete(*self.tree_positions.get_children())
        for pos in open_pos:
            self.tree_positions.insert("", "end", values=(
                pos["id"],
                pos["direction"],
                f"{pos['lot']:.2f}",
                f"{pos['entry_price']:.2f}",
                f"{pos['sl']:.2f}" if pos.get('sl') else "-",
                f"{pos['tp']:.2f}" if pos.get('tp') else "-",
                f"${pos['pnl']:.2f}"
            ))
            
    def refresh_history_tree(self, history):
        # ล้างข้อมูลเดิมและเติมรายการปิดแล้ว
        self.tree_history.delete(*self.tree_history.get_children())
        for item in history[:50]: # แสดงรายการล่าสุด 50 ไม้พอเพื่อประสิทธิภาพ
            self.tree_history.insert("", "end", values=(
                item["id"],
                item["direction"],
                f"{item['lot']:.2f}",
                f"{item['entry_price']:.2f}",
                f"{item['close_price']:.2f}",
                f"${item['pnl']:.2f}",
                item.get("open_time", "-"),
                item.get("close_time", "-"),
                item.get("close_reason", "MARKET")
            ))

    def close_selected_position(self):
        selected = self.tree_positions.selection()
        if not selected:
            messagebox.showwarning("คำเตือน", "กรุณาเลือกตั๋วออเดอร์ในตารางที่ต้องการปิด")
            return
            
        values = self.tree_positions.item(selected[0])['values']
        ticket_id = values[0]
        
        if messagebox.askyesno("ยืนยันการยกเลิก", f"คุณต้องการส่งคำสั่งปิดออเดอร์ Ticket #{ticket_id} ทันทีหรือไม่?"):
            def do_close():
                mode = self.var_mode.get()
                logging.info(f"🛑 สั่ง CLOSE ออเดอร์ #{ticket_id} ผ่านหน้า Desktop GUI...")
                try:
                    if mode == "Simulation":
                        res = bot_sim.exchange.close_position(str(ticket_id))
                    else:
                        res = bot_mt5.mt5_bridge.close_position(int(ticket_id), symbol=bot_mt5.symbol)
                        
                    if res.get("status") == "SUCCESS":
                        logging.info(f"ปิดออเดอร์ #{ticket_id} สำเร็จ!")
                        self.root.after(0, lambda: messagebox.showinfo("สำเร็จ", f"ปิดออเดอร์ #{ticket_id} สำเร็จ!"))
                    else:
                        err = res.get('message', 'Unknown Error')
                        logging.error(f"ปิดออเดอร์ #{ticket_id} ล้มเหลว: {err}")
                        self.root.after(0, lambda: messagebox.showerror("ล้มเหลว", f"ไม่สามารถปิดออเดอร์ได้: {err}"))
                except Exception as e:
                    logging.error(f"ระบบปิดออเดอร์ขัดข้อง: {e}")
                    
            t = threading.Thread(target=do_close, daemon=True)
            t.start()

# ----------------------------------------------------
# 📌 8. ฟังก์ชันเริ่มรัน GUI Dashboard
# ----------------------------------------------------
if __name__ == "__main__":
    # บังคับใช้ระบบ DPI-awareness บน Windows เพื่อความชัดของหน้าจอคอมพิวเตอร์
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    root = tk.Tk()
    
    # กำหนดสไตล์ ttk เพิ่มความโมเดิร์น
    style = ttk.Style()
    style.theme_use("clam")
    
    # แต่งสีหัวตารางและกล่องเลือก
    style.configure("TCombobox", fieldbackground="#0f172a", background="#1e293b", foreground="#f8fafc", relief="flat")
    style.configure("Treeview", background="#1e293b", fieldbackground="#1e293b", foreground="#f8fafc", rowheight=26, font=("Outfit", 9))
    style.map("Treeview", background=[('selected', '#818cf8')], foreground=[('selected', '#0f172a')])
    style.configure("Treeview.Heading", background="#0f172a", foreground="#94a3b8", borderwidth=0, font=("Outfit", 9, "bold"))
    
    app = TradingBotGUI(root)
    root.mainloop()
