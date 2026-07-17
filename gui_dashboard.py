import os
import sys
import json
import logging
import threading
import time
import queue
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# นำเข้าตัวควบคุมพอร์ตจำลองและพอร์ตจริง
from bot_orchestrator import TradingBotOrchestrator
from bot_orchestrator_mt5 import MT5TradingBotOrchestrator
from performance_tracker import PerformanceTracker

# ----------------------------------------------------
# 📌 1. โหลดข้อมูล API Key เริ่มต้น
# ----------------------------------------------------
DEFAULT_API_KEY = os.environ.get("MAXPLUS_API_KEY", "")

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
        
        try:
            self.text_widget.after(0, append)
        except Exception:
            pass

# ----------------------------------------------------
# 📌 3. ระบบคิวเรียงลำดับการทำงาน (Sequential Queue Manager)
# ----------------------------------------------------
class StrategyQueueManager:
    def __init__(self, run_strategy_func):
        self.task_queue = queue.Queue()
        self.run_strategy_func = run_strategy_func
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        
    def add_task(self, strategy_name):
        current_queue = list(self.task_queue.queue)
        if strategy_name not in current_queue:
            logging.info(f"📥 [Queue] เพิ่มกลยุทธ์ {strategy_name.upper()} เข้าสู่คิวเรียงลำดับ...")
            self.task_queue.put(strategy_name)
        else:
            logging.info(f"⏳ [Queue] กลยุทธ์ {strategy_name.upper()} อยู่ในคิวรอแล้ว ข้ามการใส่ซ้ำ")
            
    def _worker_loop(self):
        while True:
            try:
                strategy_name = self.task_queue.get()
                logging.info(f"🚀 [Queue Manager] เริ่มประมวลผลกลยุทธ์: {strategy_name.upper()}")
                self.run_strategy_func(strategy_name)
                logging.info(f"✅ [Queue Manager] เสร็จสิ้นกลยุทธ์: {strategy_name.upper()}")
                self.task_queue.task_done()
            except Exception as e:
                logging.error(f"เกิดข้อผิดพลาดใน Queue Manager worker loop: {e}")
            time.sleep(1)

# ----------------------------------------------------
# 📌 4. คลาสควบคุมรอบเวลาเบื้องหลัง (Background Scheduler)
# ----------------------------------------------------
class BotScheduler(threading.Thread):
    def __init__(self, check_and_enqueue_func):
        super().__init__(daemon=True)
        self.check_and_enqueue_func = check_and_enqueue_func
        
    def run(self):
        while True:
            try:
                self.check_and_enqueue_func()
            except Exception as e:
                logging.error(f"เกิดข้อผิดพลาดใน scheduler loop: {e}")
            time.sleep(5) # เช็คสถานะเวลาทุก 5 วินาที

# ----------------------------------------------------
# 📌 5. ตัวออกแบบและสร้างหน้าจอ GUI (Main Application)
# ----------------------------------------------------
class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MaxPlus AI Agent Hub - Trading Terminal")
        self.root.geometry("1300x850")
        self.root.configure(bg="#0f172a") # Dark Slate Theme
        
        self.scheduler = None
        self.is_running_strategy = False
        
        # ตั้งค่า Fonts & Styles
        self.font_title = ("Outfit", 11, "bold")
        self.font_label = ("Outfit", 9)
        self.font_metric_num = ("Outfit", 18, "bold")
        self.font_metric_lbl = ("Outfit", 8, "bold")
        
        # คิวตัวแปรเก็บรอบการทำงานล่าสุดเพื่อคุม scheduler
        self.last_run_times = {
            "scalping": 0,
            "daytrading": 0,
            "swingtrading": 0,
            "groq_gen2": 0,
            "custom_agent": 0
        }
        
        # กำหนดตัวแปรกราฟิก
        self.var_mode = tk.StringVar(value="Simulation")
        self.var_auto_pilot = tk.BooleanVar(value=False)
        self.var_analysis_model = tk.StringVar(value="claude-haiku-4-5 (Native: $0.25/1M)")
        self.var_management_model = tk.StringVar(value="claude-haiku-4-5 (Native: $0.25/1M)")
        
        # ตัวแปรแยกกลยุทธ์
        self.strat_vars = {
            "scalping": {
                "enabled": tk.BooleanVar(value=True),
                "magic": tk.StringVar(value="111111"),
                "max_lot": tk.StringVar(value="0.05"),
                "interval": tk.StringVar(value="5"),
                "trailing_enabled": tk.BooleanVar(value=True),
                "trailing_atr_tf": tk.StringVar(value="5m"),
                "trailing_activation_mult": tk.StringVar(value="1.5"),
                "trailing_distance_mult": tk.StringVar(value="1.5"),
                "trailing_step_mult": tk.StringVar(value="0.3")
            },
            "daytrading": {
                "enabled": tk.BooleanVar(value=True),
                "magic": tk.StringVar(value="222222"),
                "max_lot": tk.StringVar(value="0.05"),
                "interval": tk.StringVar(value="30"),
                "trailing_enabled": tk.BooleanVar(value=True),
                "trailing_atr_tf": tk.StringVar(value="15m"),
                "trailing_activation_mult": tk.StringVar(value="1.5"),
                "trailing_distance_mult": tk.StringVar(value="1.5"),
                "trailing_step_mult": tk.StringVar(value="0.3")
            },
            "swingtrading": {
                "enabled": tk.BooleanVar(value=True),
                "magic": tk.StringVar(value="333333"),
                "max_lot": tk.StringVar(value="0.05"),
                "interval": tk.StringVar(value="240"),
                "trailing_enabled": tk.BooleanVar(value=False),
                "trailing_atr_tf": tk.StringVar(value="1h"),
                "trailing_activation_mult": tk.StringVar(value="1.5"),
                "trailing_distance_mult": tk.StringVar(value="1.5"),
                "trailing_step_mult": tk.StringVar(value="0.3")
            },
            "groq_gen2": {
                "enabled": tk.BooleanVar(value=True),
                "magic": tk.StringVar(value="444444"),
                "max_lot": tk.StringVar(value="0.05"),
                "interval": tk.StringVar(value="1"),
                "trailing_enabled": tk.BooleanVar(value=False),
                "trailing_atr_tf": tk.StringVar(value="15m"),
                "trailing_activation_mult": tk.StringVar(value="1.5"),
                "trailing_distance_mult": tk.StringVar(value="1.5"),
                "trailing_step_mult": tk.StringVar(value="0.3")
            },
            "custom_agent": {
                "enabled": tk.BooleanVar(value=True),
                "magic": tk.StringVar(value="555555"),
                "max_lot": tk.StringVar(value="0.05"),
                "lot_size": tk.StringVar(value="0.01"),
                "interval": tk.StringVar(value="5"),
                "trailing_enabled": tk.BooleanVar(value=True),
                "trailing_atr_tf": tk.StringVar(value="5m"),
                "trailing_activation_mult": tk.StringVar(value="1.5"),
                "trailing_distance_mult": tk.StringVar(value="1.0"),
                "trailing_step_mult": tk.StringVar(value="0.3"),
                "breakeven_enabled": tk.BooleanVar(value=True),
                "breakeven_atr_mult": tk.StringVar(value="1.0"),
                "quick_close_profit": tk.StringVar(value="9.0"),
                "daily_profit_target": tk.StringVar(value="100.0"),
                "daily_loss_limit": tk.StringVar(value="30.0"),
                "daily_quota_enabled": tk.BooleanVar(value=True),
                "quick_close_enabled": tk.BooleanVar(value=True),
                "reverse_mode": tk.BooleanVar(value=False),
                "hold_mode_enabled": tk.BooleanVar(value=False),
                "risk_mode": tk.StringVar(value="ATR"),
                "fixed_sl_points": tk.StringVar(value="500"),
                "fixed_tp_points": tk.StringVar(value="1000")
            }
        }
        
        self.setup_ui()
        self.setup_logging()
        
        # โหลดคิวและเริ่มทำงาน
        self.queue_manager = StrategyQueueManager(self.run_strategy_cycle_safe)
        self.load_config()
        self.start_scheduler()
        
        self.update_portfolio_loop()
        
    def setup_ui(self):
        # ออกแบบ Layout สองคอลัมน์หลัก
        self.left_panel = tk.Frame(self.root, bg="#1e293b", width=420, padx=12, pady=12)
        self.left_panel.pack(side="left", fill="y", padx=(10, 5), pady=10)
        self.left_panel.pack_propagate(False)
        
        self.right_panel = tk.Frame(self.root, bg="#0f172a", padx=5, pady=10)
        self.right_panel.pack(side="right", expand=True, fill="both", padx=(5, 10))
        
        # ----------------------------------------------------
        # 🅰️ ออกแบบเมนูด้านซ้าย: คอนฟิกแยกหลาย Page (Notebook)
        # ----------------------------------------------------
        lbl_head = tk.Label(self.left_panel, text="⚙️ Multi-Agent Dashboard Config", font=("Outfit", 12, "bold"), bg="#1e293b", fg="#f8fafc")
        lbl_head.pack(anchor="w", pady=(0, 10))
        
        # สวิตช์และปุ่มควบคุมระบบออโต้/แมนนวล ด้านล่างของ Left Panel (แพ็กลงด้านล่างก่อนเพื่อให้คงอยู่เสมอ)
        control_frame = tk.LabelFrame(self.left_panel, text="🚦 Control Room", bg="#1e293b", fg="#fbbf24", font=self.font_label, padx=10, pady=5)
        control_frame.pack(side="bottom", fill="x", pady=5)

        # สร้าง Notebook ในฝั่งซ้ายเพื่อแยกหน้าการตั้งค่า (แพ็กส่วนบนหลังจากนั้นเพื่อเติมช่องว่างที่เหลือ)
        self.config_tabs = ttk.Notebook(self.left_panel)
        self.config_tabs.pack(side="top", fill="both", expand=True, pady=(0, 10))
        
        # 1. แท็บตั้งค่าระบบส่วนกลาง (Global Setup)
        self.tab_global = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_global, text=" Global Setup ")
        self.setup_global_tab()
        
        # 2. แท็บ Scalping Agent
        self.tab_scalp = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_scalp, text=" ⚡ Scalping ")
        self.setup_strategy_tab(self.tab_scalp, "scalping")
        
        # 3. แท็บ Day Trading Agent
        self.tab_day = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_day, text=" 📅 Day Trading ")
        self.setup_strategy_tab(self.tab_day, "daytrading")
        
        # 4. แท็บ Swing Trading Agent
        self.tab_swing = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_swing, text=" 📈 Swing ")
        self.setup_strategy_tab(self.tab_swing, "swingtrading")
        
        # 5. แท็บ Groq Gen2 Agent
        self.tab_groq = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_groq, text=" 🤖 Groq Gen2 ")
        self.setup_strategy_tab(self.tab_groq, "groq_gen2")
        
        # 6. แท็บ Custom Agent (AI Flex)
        self.tab_custom = tk.Frame(self.config_tabs, bg="#1e293b", padx=10, pady=10)
        self.config_tabs.add(self.tab_custom, text=" 🧠 Custom Agent ")
        self.setup_custom_agent_tab(self.tab_custom)
        
        self.chk_auto = tk.Checkbutton(control_frame, text="🟢 เปิดระบบ Auto-Pilot รันรอบอัตโนมัติ", variable=self.var_auto_pilot, font=self.font_label, bg="#1e293b", fg="#818cf8", selectcolor="#0f172a", command=self.on_auto_pilot_toggle)
        self.chk_auto.pack(anchor="w", pady=3)
        
        btn_save = tk.Button(control_frame, text="💾 Save Configuration", font=self.font_label, bg="#818cf8", fg="#0f172a", activebackground="#a5b4fc", relief="flat", height=1, command=self.save_config)
        btn_save.pack(fill="x", pady=3)
        
        # ปุ่มแยกแมนนวลในการรันแต่ละกลยุทธ์
        manual_btn_frame = tk.Frame(control_frame, bg="#1e293b")
        manual_btn_frame.pack(fill="x", pady=3)
        
        btn_scalp = tk.Button(manual_btn_frame, text="Run Scalping", font=("Outfit", 8, "bold"), bg="#10b981", fg="white", relief="flat", command=lambda: self.trigger_manual_strategy("scalping"))
        btn_scalp.pack(side="left", expand=True, fill="x", padx=1)
        
        btn_day = tk.Button(manual_btn_frame, text="Run DayTrade", font=("Outfit", 8, "bold"), bg="#f59e0b", fg="white", relief="flat", command=lambda: self.trigger_manual_strategy("daytrading"))
        btn_day.pack(side="left", expand=True, fill="x", padx=1)
        
        btn_swing = tk.Button(manual_btn_frame, text="Run Swing", font=("Outfit", 8, "bold"), bg="#3b82f6", fg="white", relief="flat", command=lambda: self.trigger_manual_strategy("swingtrading"))
        btn_swing.pack(side="left", expand=True, fill="x", padx=1)
        
        btn_groq = tk.Button(manual_btn_frame, text="Run GroqGen2", font=("Outfit", 8, "bold"), bg="#a855f7", fg="white", relief="flat", command=lambda: self.trigger_manual_strategy("groq_gen2"))
        btn_groq.pack(side="left", expand=True, fill="x", padx=1)
        
        btn_custom = tk.Button(manual_btn_frame, text="Run Custom", font=("Outfit", 8, "bold"), bg="#ec4899", fg="white", relief="flat", command=lambda: self.trigger_manual_strategy("custom_agent"))
        btn_custom.pack(side="left", expand=True, fill="x", padx=1)
        
        self.lbl_sched_status = tk.Label(control_frame, text="สถานะ: หยุดการทำงานออโต้", font=self.font_label, bg="#1e293b", fg="#ef4444")
        self.lbl_sched_status.pack(pady=3)

        # ----------------------------------------------------
        # 🅱️ ออกแบบเมนูด้านขวา: Metrics, Tables, Performance, Logs
        # ----------------------------------------------------
        self.metrics_frame = tk.Frame(self.right_panel, bg="#0f172a")
        self.metrics_frame.pack(fill="x", pady=(0, 10))
        
        self.card_balance = self.create_metric_card(self.metrics_frame, "BALANCE", "$0.00", "#f8fafc")
        self.card_balance.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        
        self.card_equity = self.create_metric_card(self.metrics_frame, "EQUITY", "$0.00", "#f8fafc")
        self.card_equity.grid(row=0, column=1, sticky="nsew", padx=5)
        
        self.card_pnl = self.create_metric_card(self.metrics_frame, "FLOATING P&L", "$0.00", "#10b981")
        self.card_pnl.grid(row=0, column=2, sticky="nsew", padx=5)
        
        self.card_price = self.create_metric_card(self.metrics_frame, "CURRENT PRICE", "0.00 (Offline)", "#fbbf24")
        self.card_price.grid(row=0, column=3, sticky="nsew", padx=(5, 0))
        
        self.metrics_frame.columnconfigure((0, 1, 2, 3), weight=1)
        
        self.tabs = ttk.Notebook(self.right_panel)
        self.tabs.pack(fill="both", expand=True, pady=(0, 10))
        
        # แท็บที่ 1: Active Positions
        self.tab_active = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_active, text=" Active Positions ")
        self.setup_positions_table()
        
        # แท็บที่ 2: Trade History
        self.tab_history = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_history, text=" Trade History ")
        self.setup_history_table()
        
        # แท็บที่ 3: Performance Statistics
        self.tab_perf = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_perf, text=" 📊 Performance Statistics ")
        self.setup_performance_tab()
        
        # แท็บที่ 4: Equity Curve
        self.tab_equity = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_equity, text=" 📈 Equity Curve ")
        self.setup_equity_tab()
        
        # แท็บที่ 5: Indicator Monitor
        self.tab_indicator = tk.Frame(self.tabs, bg="#1e293b")
        self.tabs.add(self.tab_indicator, text=" 🔍 Indicator Monitor ")
        self.setup_indicator_tab()
        
        # กล่องแสดงบันทึก LOG ด้านล่าง
        self.log_frame = tk.Frame(self.right_panel, bg="#1e293b", padx=10, pady=8)
        self.log_frame.pack(fill="x", side="bottom")
        
        lbl_log_title = tk.Label(self.log_frame, text="💻 AI Multi-Agent Logging Terminal", font=self.font_title, bg="#1e293b", fg="#f8fafc")
        lbl_log_title.pack(anchor="w", pady=(0, 3))
        
        self.log_text = scrolledtext.ScrolledText(self.log_frame, height=9, bg="#020617", fg="#f8fafc", insertbackground="white", font=("JetBrains Mono", 8))
        self.log_text.pack(fill="x", expand=True)
        self.log_text.tag_config('error', foreground="#ef4444")
        self.log_text.tag_config('warning', foreground="#fbbf24")
        self.log_text.tag_config('success', foreground="#10b981")
        self.log_text.tag_config('info', foreground="#f8fafc")
        self.log_text.configure(state='disabled')
        
    def create_scrollable_container(self, parent_frame):
        # สร้าง Canvas และ Scrollbar เพื่อรองรับการสกรอลล์แนวดิ่ง
        canvas = tk.Canvas(parent_frame, bg="#1e293b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#1e293b")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )
        
        window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # ปรับความกว้างของ scrollable_frame ให้เต็มขนาด canvas เสมอเพื่อความสมมาตร
        canvas.bind('<Configure>', lambda event: canvas.itemconfig(window_id, width=event.width))
        
        # ผูกระบบเลื่อนลูกกลิ้งเมาส์ (Mousewheel) ให้รองรับระบบ Linux (X11) และ Windows/macOS
        def _on_mousewheel(event):
            if event.num == 4:
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                canvas.yview_scroll(1, "units")
            else:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                
        def _bind_mouse(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
            canvas.bind_all("<Button-4>", _on_mousewheel)
            canvas.bind_all("<Button-5>", _on_mousewheel)
            
        def _unbind_mouse(event):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
            
        canvas.bind("<Enter>", _bind_mouse)
        canvas.bind("<Leave>", _unbind_mouse)
        
        return scrollable_frame

    def setup_global_tab(self):
        # สร้างคอนเทนเนอร์สกรอลล์เพื่อรองรับหน้าจอกว้าง-ต่ำ
        scrollable_frame = self.create_scrollable_container(self.tab_global)

        # 1. ปรับโหมดการทำงาน
        tk.Label(scrollable_frame, text="Trading Mode (โหมดเทรด)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w", pady=(5, 2))
        self.cb_mode = ttk.Combobox(scrollable_frame, textvariable=self.var_mode, values=["Simulation", "MT5 Live"], state="readonly")
        self.cb_mode.pack(fill="x", pady=(0, 10))
        self.cb_mode.bind("<<ComboboxSelected>>", self.on_mode_change)
        
        # 2. ช่องใส่ API Key
        tk.Label(scrollable_frame, text="MaxPlus API Key", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w", pady=(5, 2))
        self.ent_api_key = tk.Entry(scrollable_frame, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=3)
        self.ent_api_key.pack(fill="x", pady=(0, 10))
        
        # 3. รายละเอียด MT5
        self.frame_mt5 = tk.LabelFrame(scrollable_frame, text="⚙️ ตั้งค่า MetaTrader 5 Login", font=self.font_label, bg="#1e293b", fg="#fbbf24", padx=10, pady=5, relief="solid", bd=1)
        self.frame_mt5.pack(fill="x", pady=(0, 10))
        
        tk.Label(self.frame_mt5, text="Login ID (หมายเลขบัญชี)", font=("Outfit", 8), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_login = tk.Entry(self.frame_mt5, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        self.ent_mt5_login.pack(fill="x", pady=(1, 5))
        
        tk.Label(self.frame_mt5, text="Password (รหัสผ่าน)", font=("Outfit", 8), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_pass = tk.Entry(self.frame_mt5, show="*", bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        self.ent_mt5_pass.pack(fill="x", pady=(1, 5))
        
        tk.Label(self.frame_mt5, text="Server (เซิร์ฟเวอร์โบรกเกอร์)", font=("Outfit", 8), bg="#1e293b", fg="#94a3b8").pack(anchor="w")
        self.ent_mt5_server = tk.Entry(self.frame_mt5, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        self.ent_mt5_server.pack(fill="x", pady=(1, 5))
        
        # 4. เลือกโมเดลสำหรับ Analyst และ Manager
        tk.Label(scrollable_frame, text="Analyst Model (โมเดลวิเคราะห์ตลาด)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w", pady=(5, 2))
        self.cb_analysis_model = ttk.Combobox(scrollable_frame, textvariable=self.var_analysis_model, values=[
            "claude-haiku-4-5-20251001 (Native: $0.25/1M)",
            "claude-haiku-4-5 (Native: $0.25/1M)",
            "claude-sonnet-4-6 (Native: $3.00/1M)",
            "claude-sonnet-5 (Native: $3.00/1M)",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8 (Native: $15.00/1M)"
        ], state="readonly")
        self.cb_analysis_model.pack(fill="x", pady=(0, 10))
        
        tk.Label(scrollable_frame, text="Manager Model (โมเดลควบคุมพอร์ต)", font=self.font_label, bg="#1e293b", fg="#94a3b8").pack(anchor="w", pady=(5, 2))
        self.cb_management_model = ttk.Combobox(scrollable_frame, textvariable=self.var_management_model, values=[
            "claude-haiku-4-5-20251001 (Native: $0.25/1M)",
            "claude-haiku-4-5",
            "claude-sonnet-4-5"
        ], state="readonly")
        self.cb_management_model.pack(fill="x", pady=(0, 10))

    def setup_custom_agent_tab(self, parent_frame):
        scrollable_frame = self.create_scrollable_container(parent_frame)
        vars_dict = self.strat_vars["custom_agent"]
        
        # 1. General Config Group
        f_gen = tk.LabelFrame(scrollable_frame, text="⚙️ General Configuration", bg="#1e293b", fg="#f8fafc", font=("Outfit", 9, "bold"), padx=8, pady=5)
        f_gen.pack(fill="x", pady=5, padx=5)
        
        chk_enable = tk.Checkbutton(f_gen, text="เปิดใช้งาน Custom Agent", variable=vars_dict["enabled"], font=("Outfit", 9, "bold"), bg="#1e293b", fg="#10b981", selectcolor="#0f172a")
        chk_enable.pack(anchor="w", pady=3)
        
        def add_row(parent, label_text, var):
            row = tk.Frame(parent, bg="#1e293b")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, font=self.font_label, bg="#1e293b", fg="#94a3b8", width=18, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var, bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2).pack(side="right", fill="x", expand=True)
            
        add_row(f_gen, "Magic Number", vars_dict["magic"])
        add_row(f_gen, "Lot Size คงที่", vars_dict["lot_size"])
        add_row(f_gen, "Run Interval (นาที)", vars_dict["interval"])
        
        # 2. Risk Management Group
        f_risk = tk.LabelFrame(scrollable_frame, text="🛡️ Risk & Target Setup", bg="#1e293b", fg="#f8fafc", font=("Outfit", 9, "bold"), padx=8, pady=5)
        f_risk.pack(fill="x", pady=5, padx=5)
        
        row_rm = tk.Frame(f_risk, bg="#1e293b")
        row_rm.pack(fill="x", pady=2)
        tk.Label(row_rm, text="Risk Mode (SL/TP)", font=self.font_label, bg="#1e293b", fg="#94a3b8", width=18, anchor="w").pack(side="left")
        cb_rm = ttk.Combobox(row_rm, textvariable=vars_dict["risk_mode"], values=["ATR", "Fixed"], state="readonly")
        cb_rm.pack(side="right", fill="x", expand=True)
        
        add_row(f_risk, "Fixed SL (Points)", vars_dict["fixed_sl_points"])
        add_row(f_risk, "Fixed TP (Points)", vars_dict["fixed_tp_points"])
        
        # 3. Targets Quotas
        f_target = tk.LabelFrame(scrollable_frame, text="💰 Daily Quota Targets", bg="#1e293b", fg="#f8fafc", font=("Outfit", 9, "bold"), padx=8, pady=5)
        f_target.pack(fill="x", pady=5, padx=5)
        chk_dq = tk.Checkbutton(f_target, text="เปิดใช้การคุมวงเงินรายวัน (Daily Quota)", variable=vars_dict["daily_quota_enabled"], font=self.font_label, bg="#1e293b", fg="#10b981", selectcolor="#0f172a")
        chk_dq.pack(anchor="w", pady=2)
        add_row(f_target, "Daily Profit Target ($)", vars_dict["daily_profit_target"])
        add_row(f_target, "Daily Loss Limit ($)", vars_dict["daily_loss_limit"])
        
        # 4. Trailing & Breakeven Auto controls
        f_auto = tk.LabelFrame(scrollable_frame, text="🚦 Autopilot Controls", bg="#1e293b", fg="#f8fafc", font=("Outfit", 9, "bold"), padx=8, pady=5)
        f_auto.pack(fill="x", pady=5, padx=5)
        
        chk_be = tk.Checkbutton(f_auto, text="เปิดใช้ Breakeven (กันทุน)", variable=vars_dict["breakeven_enabled"], font=self.font_label, bg="#1e293b", fg="#3b82f6", selectcolor="#0f172a")
        chk_be.pack(anchor="w", pady=2)
        add_row(f_auto, "Breakeven ATR Mult", vars_dict["breakeven_atr_mult"])
        
        chk_qc = tk.Checkbutton(f_auto, text="เปิดใช้การรวบล็อกกำไรด่วน (Quick Close)", variable=vars_dict["quick_close_enabled"], font=self.font_label, bg="#1e293b", fg="#10b981", selectcolor="#0f172a")
        chk_qc.pack(anchor="w", pady=2)
        add_row(f_auto, "Quick Close Profit ($)", vars_dict["quick_close_profit"])
        
        chk_tr = tk.Checkbutton(f_auto, text="เปิดใช้ ATR Trailing Stop", variable=vars_dict["trailing_enabled"], font=self.font_label, bg="#1e293b", fg="#fbbf24", selectcolor="#0f172a")
        chk_tr.pack(anchor="w", pady=2)
        
        row_tf = tk.Frame(f_auto, bg="#1e293b")
        row_tf.pack(fill="x", pady=2)
        tk.Label(row_tf, text="Trailing ATR TF", font=self.font_label, bg="#1e293b", fg="#94a3b8", width=18, anchor="w").pack(side="left")
        cb_tf = ttk.Combobox(row_tf, textvariable=vars_dict["trailing_atr_tf"], values=["1m", "5m", "15m", "1h"], state="readonly")
        cb_tf.pack(side="right", fill="x", expand=True)
        
        add_row(f_auto, "Activation Mult", vars_dict["trailing_activation_mult"])
        add_row(f_auto, "Distance Mult", vars_dict["trailing_distance_mult"])
        add_row(f_auto, "Step Mult", vars_dict["trailing_step_mult"])
        
        # 5. AI Settings
        f_ai = tk.LabelFrame(scrollable_frame, text="🤖 AI Model Flags", bg="#1e293b", fg="#f8fafc", font=("Outfit", 9, "bold"), padx=8, pady=5)
        f_ai.pack(fill="x", pady=5, padx=5)
        
        chk_nh = tk.Checkbutton(f_ai, text="เปิดใช้งาน Hold Mode (เปิด = ยอมให้ AI ตอบ HOLD | ปิด = บังคับยิง BUY/SELL เท่านั้น)", variable=vars_dict["hold_mode_enabled"], font=self.font_label, bg="#1e293b", fg="#a855f7", selectcolor="#0f172a")
        chk_nh.pack(anchor="w", pady=2)
        chk_rv = tk.Checkbutton(f_ai, text="เปิด Reverse Mode (สลับฝั่งสัญญาณ)", variable=vars_dict["reverse_mode"], font=self.font_label, bg="#1e293b", fg="#ec4899", selectcolor="#0f172a")
        chk_rv.pack(anchor="w", pady=2)

    def setup_strategy_tab(self, parent_frame, strat_name):
        scrollable_frame = self.create_scrollable_container(parent_frame)
        vars_dict = self.strat_vars[strat_name]
        
        # บังคับจัดกริดบน scrollable_frame
        scrollable_frame.columnconfigure(0, weight=1)
        scrollable_frame.columnconfigure(1, weight=1)
        
        # Row 0: Enabled/Disabled Strategy
        chk_enable = tk.Checkbutton(scrollable_frame, text="เปิดใช้งานกลยุทธ์นี้", variable=vars_dict["enabled"], font=("Outfit", 9, "bold"), bg="#1e293b", fg="#10b981", selectcolor="#0f172a")
        chk_enable.grid(row=0, column=0, columnspan=2, sticky="w", pady=(5, 10))
        
        # Row 1: Magic Number
        tk.Label(scrollable_frame, text="Magic Number", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=1, column=0, sticky="w", pady=3)
        ent_magic = tk.Entry(scrollable_frame, textvariable=vars_dict["magic"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_magic.grid(row=1, column=1, sticky="ew", pady=3)
        
        # Row 2: Max Lot
        tk.Label(scrollable_frame, text="Max Lot Size", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=2, column=0, sticky="w", pady=3)
        ent_max_lot = tk.Entry(scrollable_frame, textvariable=vars_dict["max_lot"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_max_lot.grid(row=2, column=1, sticky="ew", pady=3)
        
        # Row 3: Run Cycle Interval (Minutes)
        tk.Label(scrollable_frame, text="Run Interval (นาที)", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=3, column=0, sticky="w", pady=3)
        ent_interval = tk.Entry(scrollable_frame, textvariable=vars_dict["interval"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_interval.grid(row=3, column=1, sticky="ew", pady=3)
        
        # แผงหัวข้อย่อย Trailing Config
        lbl_trailing_sec = tk.Label(scrollable_frame, text="🛡️ การตั้งค่า Trailing Stop", font=("Outfit", 9, "bold"), bg="#1e293b", fg="#fbbf24")
        lbl_trailing_sec.grid(row=4, column=0, columnspan=2, sticky="w", pady=(15, 5))
        
        # Row 5: Trailing Enabled
        chk_trail = tk.Checkbutton(scrollable_frame, text="เปิดใช้ ATR Trailing Stop", variable=vars_dict["trailing_enabled"], font=self.font_label, bg="#1e293b", fg="#fbbf24", selectcolor="#0f172a")
        chk_trail.grid(row=5, column=0, columnspan=2, sticky="w", pady=3)
        
        # Row 6: ATR Timeframe
        tk.Label(scrollable_frame, text="ATR Timeframe", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=6, column=0, sticky="w", pady=3)
        cb_atr_tf = ttk.Combobox(scrollable_frame, textvariable=vars_dict["trailing_atr_tf"], values=["1m", "5m", "15m", "1h"], state="readonly")
        cb_atr_tf.grid(row=6, column=1, sticky="ew", pady=3)
        
        # Row 7: Activation Mult
        tk.Label(scrollable_frame, text="Activation Mult", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=7, column=0, sticky="w", pady=3)
        ent_act_mult = tk.Entry(scrollable_frame, textvariable=vars_dict["trailing_activation_mult"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_act_mult.grid(row=7, column=1, sticky="ew", pady=3)
        
        # Row 8: Distance Mult
        tk.Label(scrollable_frame, text="Distance Mult", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=8, column=0, sticky="w", pady=3)
        ent_dist_mult = tk.Entry(scrollable_frame, textvariable=vars_dict["trailing_distance_mult"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_dist_mult.grid(row=8, column=1, sticky="ew", pady=3)
        
        # Row 9: Step Mult
        tk.Label(scrollable_frame, text="Step Mult", font=self.font_label, bg="#1e293b", fg="#94a3b8").grid(row=9, column=0, sticky="w", pady=3)
        ent_step_mult = tk.Entry(scrollable_frame, textvariable=vars_dict["trailing_step_mult"], bg="#0f172a", fg="#f8fafc", insertbackground="white", relief="flat", bd=2)
        ent_step_mult.grid(row=9, column=1, sticky="ew", pady=3)

    def create_metric_card(self, parent, title, initial_value, num_color):
        card = tk.Frame(parent, bg="#1e293b", padx=12, pady=12, relief="flat")
        lbl_title = tk.Label(card, text=title, font=self.font_metric_lbl, bg="#1e293b", fg="#94a3b8")
        lbl_title.pack(anchor="w")
        lbl_val = tk.Label(card, text=initial_value, font=self.font_metric_num, bg="#1e293b", fg=num_color)
        lbl_val.pack(anchor="w", pady=(4, 0))
        card.lbl_val = lbl_val
        return card
        
    def setup_positions_table(self):
        tbl_frame = tk.Frame(self.tab_active, bg="#1e293b", padx=5, pady=5)
        tbl_frame.pack(fill="both", expand=True)
        
        # เพิ่มคอลัมน์ "Strategy" เพื่อระบุว่าออเดอร์เปิดจาก Agent ใด
        columns = ("ticket", "strategy", "dir", "lot", "entry", "sl", "tp", "pnl")
        self.tree_positions = ttk.Treeview(tbl_frame, columns=columns, show="headings", height=5)
        self.tree_positions.pack(side="left", fill="both", expand=True)
        
        self.tree_positions.heading("ticket", text="Ticket ID")
        self.tree_positions.heading("strategy", text="Strategy Agent")
        self.tree_positions.heading("dir", text="Direction")
        self.tree_positions.heading("lot", text="Lot Size")
        self.tree_positions.heading("entry", text="Entry Price")
        self.tree_positions.heading("sl", text="Stop Loss")
        self.tree_positions.heading("tp", text="Take Profit")
        self.tree_positions.heading("pnl", text="Floating P&L")
        
        for col in columns:
            self.tree_positions.column(col, width=90, anchor="center")
            
        scrollbar = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree_positions.yview)
        self.tree_positions.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        btn_frame = tk.Frame(self.tab_active, bg="#1e293b", pady=5)
        btn_frame.pack(fill="x")
        btn_close = tk.Button(btn_frame, text="🛑 Close Selected Position", font=self.font_label, bg="#ef4444", fg="white", relief="flat", command=self.close_selected_position)
        btn_close.pack(side="right", padx=10)
        
    def setup_history_table(self):
        tbl_frame = tk.Frame(self.tab_history, bg="#1e293b", padx=5, pady=5)
        tbl_frame.pack(fill="both", expand=True)
        
        # เพิ่มคอลัมน์ "Strategy" ในประวัติการปิดออเดอร์เช่นกัน
        columns = ("ticket", "strategy", "dir", "lot", "entry", "close", "pnl", "open_time", "close_time", "reason")
        self.tree_history = ttk.Treeview(tbl_frame, columns=columns, show="headings", height=5)
        self.tree_history.pack(side="left", fill="both", expand=True)
        
        self.tree_history.heading("ticket", text="Ticket ID")
        self.tree_history.heading("strategy", text="Strategy Agent")
        self.tree_history.heading("dir", text="Direction")
        self.tree_history.heading("lot", text="Lot Size")
        self.tree_history.heading("entry", text="Entry Price")
        self.tree_history.heading("close", text="Close Price")
        self.tree_history.heading("pnl", text="PnL ($)")
        self.tree_history.heading("open_time", text="Open Time")
        self.tree_history.heading("close_time", text="Close Time")
        self.tree_history.heading("reason", text="Reason")
        
        for col in columns:
            self.tree_history.column(col, width=80, anchor="center")
            
        scrollbar = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.tree_history.yview)
        self.tree_history.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def setup_performance_tab(self):
        # หน้าต่างเปรียบเทียบสถิติของทั้ง 3 Strategies
        perf_frame = tk.Frame(self.tab_perf, bg="#1e293b", padx=15, pady=15)
        perf_frame.pack(fill="both", expand=True)
        
        # ออกแบบตาราง Grid เปรียบเทียบ
        # หัวคอลัมน์: Metric | Scalping | Day Trading | Swing Trading
        headers = ["📊 PERFORMANCE METRIC", "⚡ SCALPING AGENT", "📅 DAY TRADING AGENT", "📈 SWING TRADING AGENT"]
        for idx, h in enumerate(headers):
            lbl = tk.Label(perf_frame, text=h, font=("Outfit", 10, "bold"), bg="#1e293b", fg="#fbbf24" if idx > 0 else "#94a3b8")
            lbl.grid(row=0, column=idx, sticky="ew", padx=10, pady=8)
            perf_frame.columnconfigure(idx, weight=1)
            
        metrics_rows = [
            ("total_trades", "Total Trades (จำนวนไม้รวม)"),
            ("win_rate", "Win Rate (อัตราการชนะ %)"),
            ("profit_factor", "Profit Factor (ปัจจัยกำไร)"),
            ("expectancy", "Expectancy (คาดหวังรายไม้ $)"),
            ("avg_hold_time_mins", "Avg Hold Time (ถือครองเฉลี่ย นาที)"),
            ("avg_r", "Average R-Reward Ratio"),
            ("max_drawdown_usd", "Max Drawdown (ติดลบสูงสุด $)")
        ]
        
        self.perf_labels = {} # สำหรับเก็บ Label Widget เพื่อนำไปเปลี่ยนค่า
        
        for row_idx, (key, text) in enumerate(metrics_rows, start=1):
            # คอลัมน์ 0: ข้อความ
            lbl_metric = tk.Label(perf_frame, text=text, font=("Outfit", 9, "bold"), bg="#1e293b", fg="#cbd5e1", anchor="w")
            lbl_metric.grid(row=row_idx, column=0, sticky="w", padx=10, pady=6)
            
            self.perf_labels[key] = {}
            for col_idx, strat_name in enumerate(["scalping", "daytrading", "swingtrading"], start=1):
                val_lbl = tk.Label(perf_frame, text="-", font=("Outfit", 10), bg="#1e293b", fg="#f8fafc")
                val_lbl.grid(row=row_idx, column=col_idx, padx=10, pady=6)
                self.perf_labels[key][strat_name] = val_lbl

    def setup_logging(self):
        log_handler = TextHandler(self.log_text)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        log_handler.setFormatter(formatter)
        logging.getLogger().addHandler(log_handler)
        
    def load_config(self):
        if os.path.exists("gui_config.json"):
            try:
                with open("gui_config.json", "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    
                self.var_mode.set(cfg.get("mode", "Simulation"))
                self.ent_api_key.delete(0, 'end')
                self.ent_api_key.insert(0, cfg.get("api_key", DEFAULT_API_KEY))
                self.var_auto_pilot.set(cfg.get("auto_pilot", False))
                self.ent_mt5_login.delete(0, 'end')
                self.ent_mt5_login.insert(0, str(cfg.get("mt5_login", "")))
                self.ent_mt5_pass.delete(0, 'end')
                self.ent_mt5_pass.insert(0, str(cfg.get("mt5_pass", "")))
                self.ent_mt5_server.delete(0, 'end')
                self.ent_mt5_server.insert(0, str(cfg.get("mt5_server", "")))
                
                self.var_analysis_model.set(cfg.get("analysis_model", "gpt-5.5 (Native: $3.00/1M)"))
                self.var_management_model.set(cfg.get("management_model", "gpt-5.4-mini (Native: $2.25/1M)"))
                
                # โหลดค่าแต่ละกลยุทธ์แบบไดนามิก (รองรับทุกตัวแปร)
                for name, s_dict in self.strat_vars.items():
                    s_cfg = cfg.get(name, {})
                    if s_cfg:
                        for key, var in s_dict.items():
                            if key in s_cfg:
                                val = s_cfg[key]
                                if isinstance(var, tk.BooleanVar):
                                    var.set(bool(val))
                                elif isinstance(var, tk.StringVar):
                                    var.set(str(val))
                        
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
                "auto_pilot": self.var_auto_pilot.get(),
                "analysis_model": self.var_analysis_model.get(),
                "management_model": self.var_management_model.get(),
                "mt5_login": self.ent_mt5_login.get(),
                "mt5_pass": self.ent_mt5_pass.get(),
                "mt5_server": self.ent_mt5_server.get()
            }
            
            # เก็บค่ารายกลยุทธ์แบบไดนามิก (รองรับทุกตัวแปรอัตโนมัติ)
            for name, s_dict in self.strat_vars.items():
                cfg[name] = {}
                for key, var in s_dict.items():
                    val = var.get()
                    if isinstance(var, tk.BooleanVar):
                        cfg[name][key] = bool(val)
                    else:
                        val_str = str(val)
                        if val_str.lower() in ["true", "false"]:
                            cfg[name][key] = (val_str.lower() == "true")
                        elif val_str.isdigit():
                            cfg[name][key] = int(val_str)
                        else:
                            try:
                                cfg[name][key] = float(val_str)
                            except ValueError:
                                cfg[name][key] = val_str
                
            with open("gui_config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
                
            self.apply_config_to_bots(cfg)
            logging.info("💾 บันทึกการตั้งค่าลงไฟล์ gui_config.json สำเร็จ!")
            messagebox.showinfo("สำเร็จ", "บันทึกการตั้งค่าและซิงค์ตัวแปรของกลยุทธ์ทั้งหมดเข้าสู่ระบบสำเร็จ!")
        except Exception as e:
            logging.error(f"ไม่สามารถบันทึกค่าลงไฟล์ได้: {e}")
            messagebox.showerror("ผิดพลาด", f"ไม่สามารถบันทึกการตั้งค่าได้: {e}")

    def apply_config_to_bots(self, cfg):
        key = cfg.get("api_key", "")
        if key:
            bot_sim.agents.api_key = key
            bot_sim.agents.headers["Authorization"] = f"Bearer {key}"
            bot_mt5.agents.api_key = key
            bot_mt5.agents.headers["Authorization"] = f"Bearer {key}"
            
        analysis_model = cfg.get("analysis_model", "gpt-5.5").split()[0]
        management_model = cfg.get("management_model", "gpt-5.4-mini").split()[0]
        bot_sim.agents.analysis_model = analysis_model
        bot_mt5.agents.analysis_model = analysis_model
        bot_sim.agents.management_model = management_model
        bot_mt5.agents.management_model = management_model
        
        login = cfg.get("mt5_login", "")
        pwd = cfg.get("mt5_pass", "")
        srv = cfg.get("mt5_server", "")
        if login:
            bot_mt5.mt5_bridge.login = int(login)
        if pwd:
            bot_mt5.mt5_bridge.password = pwd
        if srv:
            bot_mt5.mt5_bridge.server = srv
            
        # สมัครโครงสร้างกลยุทธ์ทั้งหมดเข้าสู่บอทประมวลผล
        for name in ["scalping", "daytrading", "swingtrading", "groq_gen2", "custom_agent"]:
            s_cfg = cfg.get(name, {})
            if s_cfg:
                for bot in [bot_sim, bot_mt5]:
                    bot.strategies[name]["enabled"] = s_cfg.get("enabled", True)
                    bot.strategies[name]["magic"] = s_cfg.get("magic", 123456)
                    bot.strategies[name]["max_lot"] = s_cfg.get("max_lot", 0.01)
                    bot.strategies[name]["trailing_enabled"] = s_cfg.get("trailing_enabled", True)
                    bot.strategies[name]["trailing_atr_tf"] = s_cfg.get("trailing_atr_tf", "5m")
                    bot.strategies[name]["trailing_activation_mult"] = s_cfg.get("trailing_activation_mult", 1.5)
                    bot.strategies[name]["trailing_distance_mult"] = s_cfg.get("trailing_distance_mult", 1.5)
                    bot.strategies[name]["trailing_step_mult"] = s_cfg.get("trailing_step_mult", 0.3)

    def on_mode_change(self, event=None):
        mode = self.var_mode.get()
        if mode == "Simulation":
            self.frame_mt5.pack_forget()
        else:
            self.frame_mt5.pack(fill="x", after=self.ent_api_key, pady=(0, 10))

    def on_auto_pilot_toggle(self):
        active = self.var_auto_pilot.get()
        if active:
            # ดึงเวลาแต่ละตัวมาแจ้งเตือน
            t_sc = self.strat_vars["scalping"]["interval"].get()
            t_dt = self.strat_vars["daytrading"]["interval"].get()
            t_sw = self.strat_vars["swingtrading"]["interval"].get()
            t_gq = self.strat_vars["groq_gen2"]["interval"].get()
            t_ct = self.strat_vars["custom_agent"]["interval"].get()
            self.lbl_sched_status.config(
                text=f"สถานะ: Auto-Pilot ทำงาน (Scalp:{t_sc}m | Day:{t_dt}m | Swing:{t_sw}m | Groq:{t_gq}m | Custom:{t_ct}m)", 
                fg="#10b981"
            )
        else:
            self.lbl_sched_status.config(text="สถานะ: หยุดการทำงานออโต้", fg="#ef4444")

    def start_scheduler(self):
        def check_and_enqueue():
            if not self.var_auto_pilot.get():
                return
                
            now = time.time()
            for name, s_dict in self.strat_vars.items():
                if not s_dict["enabled"].get():
                    continue
                    
                interval_min = int(s_dict["interval"].get() or 5)
                interval_sec = interval_min * 60
                
                # ตรวจเช็คเวลาที่ผ่านมาเทียบรอบการรันล่าสุด
                if now - self.last_run_times[name] >= interval_sec:
                    # อัปเดตเวลารันล่าสุด (กันไม่ให้เรียกซ้อนขณะต่อคิว)
                    self.last_run_times[name] = now
                    logging.info(f"⏰ [Auto-Pilot] ถึงรอบรันกลยุทธ์ {name.upper()} (รอบ {interval_min} นาที)")
                    self.queue_manager.add_task(name)
                    
        self.scheduler = BotScheduler(check_and_enqueue)
        self.scheduler.start()

    def trigger_manual_strategy(self, strategy_name):
        logging.info(f"⚡ [Manual] สั่งประมวลผลกลยุทธ์ {strategy_name.upper()} ทันที...")
        self.queue_manager.add_task(strategy_name)

    def run_strategy_cycle_safe(self, strategy_name):
        """
        ทำงานแยกกลยุทธ์ เรียงคิวกันตามลำดับจากคิวส่วนกลาง
        """
        self.is_running_strategy = True
        try:
            # ซิงค์ข้อมูลล่าสุดจาก UI
            self.save_config_silent()
            mode = self.var_mode.get()
            
            if mode == "Simulation":
                bot_sim.run_strategy_cycle(strategy_name)
            else:
                bot_mt5.run_strategy_cycle(strategy_name)
        except Exception as e:
            logging.error(f"การรันกลยุทธ์ {strategy_name} เกิดข้อผิดพลาด: {e}")
        finally:
            self.is_running_strategy = False

    def save_config_silent(self):
        try:
            cfg = {
                "mode": self.var_mode.get(),
                "api_key": self.ent_api_key.get(),
                "auto_pilot": self.var_auto_pilot.get(),
                "analysis_model": self.var_analysis_model.get(),
                "management_model": self.var_management_model.get(),
                "mt5_login": self.ent_mt5_login.get(),
                "mt5_pass": self.ent_mt5_pass.get(),
                "mt5_server": self.ent_mt5_server.get()
            }
            for name, s_dict in self.strat_vars.items():
                cfg[name] = {}
                for key, var in s_dict.items():
                    val = var.get()
                    if isinstance(var, tk.BooleanVar):
                        cfg[name][key] = bool(val)
                    else:
                        val_str = str(val)
                        if val_str.lower() in ["true", "false"]:
                            cfg[name][key] = (val_str.lower() == "true")
                        elif val_str.isdigit():
                            cfg[name][key] = int(val_str)
                        else:
                            try:
                                cfg[name][key] = float(val_str)
                            except ValueError:
                                cfg[name][key] = val_str
            with open("gui_config.json", "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
            self.apply_config_to_bots(cfg)
        except Exception:
            pass

    def update_portfolio_loop(self):
        def do_update():
            mode = self.var_mode.get()
            try:
                # แมพป้ายชื่อเพื่อแสดงผลกลยุทธ์ให้ถูกต้อง
                magic_map = {
                    1001: "SCALP_PULLBACK",
                    1002: "SCALP_BREAKOUT",
                    1003: "SCALP_MEAN_REVERSION",
                    1004: "SCALP_LIQUIDITY_SWEEP",
                    1005: "SCALP_MOMENTUM"
                }
                for name, s_dict in self.strat_vars.items():
                    try:
                        magic_map[int(s_dict["magic"].get())] = name.upper()
                    except ValueError:
                        pass
                
                if mode == "Simulation":
                    is_gold_open = bot_sim.is_gold_market_open()
                    bot_sim.symbol = "XAUUSD" if is_gold_open else "BTCUSD"
                    
                    price = bot_sim.data_feed.get_current_price() or 0.0
                    bot_sim.exchange.update_price(price)
                    
                    # ในโหมดจำลอง ดึงประวัติทั้งหมดเพื่อแสดง
                    status = bot_sim.exchange.get_status()
                    
                    bal = status["balance"]
                    eq = status["equity"]
                    pnl = status["floating_pnl"]
                    symbol = bot_sim.symbol
                    open_pos = status["open_positions"]
                    pending_orders = status.get("pending_orders", [])
                    history = status.get("history", [])
                    
                    # คำนวณ Performance สถิติรายตัว
                    for name in ["scalping", "daytrading", "swingtrading", "groq_gen2", "custom_agent"]:
                        try:
                            mag = int(self.strat_vars[name]["magic"].get())
                            if name == "scalping":
                                strat_hist = [t for t in history if t.get("magic") in [mag, 1001, 1002, 1003, 1004, 1005]]
                            else:
                                strat_hist = [t for t in history if t.get("magic") == mag]
                            metrics = PerformanceTracker.calculate_metrics(strat_hist)
                            self.root.after(0, lambda n=name, m=metrics: self.refresh_performance_metrics(n, m))
                        except Exception:
                            pass
                    
                    self.root.after(0, lambda: self.refresh_metrics(bal, eq, pnl, price, symbol))
                    self.root.after(0, lambda: self.refresh_positions_tree(open_pos, pending_orders, magic_map))
                    self.root.after(0, lambda: self.refresh_history_tree(history, magic_map))
                    
                    # อัพเดทข้อมูลแท็บใหม่ (Equity Curve & Sim Indicator Monitor)
                    self.current_balance = bal
                    self.current_history = history
                    self.root.after(0, self.draw_equity_curve)
                    self.root.after(0, self.show_sim_indicator_monitor)
                    
                else:
                    is_gold_open = bot_mt5.is_gold_market_open()
                    bot_mt5.symbol = "XAUUSD" if is_gold_open else "BTCUSD"
                    
                    connected = bot_mt5.mt5_bridge.connect()
                    if connected:
                        price_info = bot_mt5.mt5_bridge.get_current_price(bot_mt5.symbol) or {"price": 0.0}
                        acc_status = bot_mt5.mt5_bridge.get_account_status() or {"balance": 0.0, "equity": 0.0, "floating_pnl": 0.0}
                        
                        # ใน GUI รวมประวัติพอร์ตทั้งหมดจาก MT5 แล้วเอามาฟิลเตอร์แสดงบน Performance
                        open_pos = bot_mt5.mt5_bridge.get_open_positions(bot_mt5.symbol)
                        pending_orders = bot_mt5.mt5_bridge.get_pending_orders(bot_mt5.symbol)
                        history = bot_mt5.mt5_bridge.get_trade_history(bot_mt5.symbol, days=30)
                        
                        bal = acc_status["balance"]
                        eq = acc_status["equity"]
                        pnl = acc_status["floating_pnl"]
                        price = price_info["price"]
                        symbol = bot_mt5.symbol
                        
                        # คำนวณ Performance
                        for name in ["scalping", "daytrading", "swingtrading", "groq_gen2", "custom_agent"]:
                            try:
                                mag = int(self.strat_vars[name]["magic"].get())
                                if name == "scalping":
                                    strat_hist = [t for t in history if t.get("magic") in [mag, 1001, 1002, 1003, 1004, 1005]]
                                else:
                                    strat_hist = [t for t in history if t.get("magic") == mag]
                                metrics = PerformanceTracker.calculate_metrics(strat_hist)
                                self.root.after(0, lambda n=name, m=metrics: self.refresh_performance_metrics(n, m))
                            except Exception:
                                pass
                                
                        # ดึงสัญญาณทิศทางจาก MT5
                        dir_m1 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M1_DIR")
                        time_m1 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M1_TIME")
                        price_m1 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M1_PRICE")
                        
                        dir_m5 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M5_DIR")
                        time_m5 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M5_TIME")
                        price_m5 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M5_PRICE")
                        
                        dir_m15 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M15_DIR")
                        time_m15 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M15_TIME")
                        price_m15 = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_M15_PRICE")
                        
                        update_time = bot_mt5.mt5_bridge.get_global_variable("QUANTUM_UPDATE_TIME")

                        self.root.after(0, lambda: self.refresh_metrics(bal, eq, pnl, price, symbol))
                        self.root.after(0, lambda: self.refresh_positions_tree(open_pos, pending_orders, magic_map))
                        self.root.after(0, lambda: self.refresh_history_tree(history, magic_map))
                        
                        # อัพเดทข้อมูลแท็บใหม่ (Equity Curve & Indicator Monitor)
                        self.current_balance = bal
                        self.current_history = history
                        self.root.after(0, self.draw_equity_curve)
                        self.root.after(0, lambda: self.refresh_indicator_monitor(
                            dir_m1, time_m1, price_m1,
                            dir_m5, time_m5, price_m5,
                            dir_m15, time_m15, price_m15,
                            update_time, price
                        ))
                    else:
                        self.root.after(0, self.refresh_offline)
                        self.root.after(0, self.show_sim_indicator_monitor)
            except Exception as e:
                pass
                
        t = threading.Thread(target=do_update, daemon=True)
        t.start()
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
        
    def refresh_positions_tree(self, open_pos, pending_orders, magic_map):
        self.tree_positions.delete(*self.tree_positions.get_children())
        # 1. Display Open Positions
        for pos in open_pos:
            magic = pos.get("magic", 0)
            strat_label = magic_map.get(magic, f"MANUAL / OTHER ({magic})")
            
            self.tree_positions.insert("", "end", values=(
                pos["id"],
                strat_label,
                pos["direction"],
                f"{pos['lot']:.2f}",
                f"{pos['entry_price']:.2f}",
                f"{pos['sl']:.2f}" if pos.get('sl') else "-",
                f"{pos['tp']:.2f}" if pos.get('tp') else "-",
                f"${pos['pnl']:.2f}"
            ))
        # 2. Display Pending Orders
        for ord in pending_orders:
            magic = ord.get("magic", 0)
            strat_label = magic_map.get(magic, f"MANUAL / OTHER ({magic})")
            ord_type = ord.get("type", "PENDING")
            
            self.tree_positions.insert("", "end", values=(
                ord["id"],
                strat_label,
                ord_type,
                f"{ord['lot']:.2f}",
                f"{ord['entry_price']:.2f}",
                f"{ord['sl']:.2f}" if ord.get('sl') else "-",
                f"{ord['tp']:.2f}" if ord.get('tp') else "-",
                "PENDING"
            ))
            
    def refresh_history_tree(self, history, magic_map):
        self.tree_history.delete(*self.tree_history.get_children())
        for item in history[:50]:
            magic = item.get("magic", 0)
            strat_label = magic_map.get(magic, f"MANUAL / OTHER ({magic})")
            
            self.tree_history.insert("", "end", values=(
                item["id"],
                strat_label,
                item["direction"],
                f"{item['lot']:.2f}",
                f"{item['entry_price']:.2f}",
                f"{item['close_price']:.2f}",
                f"${item['pnl']:.2f}",
                item.get("open_time", "-"),
                item.get("close_time", "-"),
                item.get("close_reason", "MARKET")
            ))

    def refresh_performance_metrics(self, strat_name, metrics):
        # อัปเดต Label สถิติของกลยุทธ์ที่ตรงตัว
        for key, value in metrics.items():
            if key in self.perf_labels:
                lbl = self.perf_labels[key].get(strat_name)
                if lbl:
                    if key == "win_rate":
                        lbl.config(text=f"{value}%")
                    elif key == "max_drawdown_usd" or key == "expectancy":
                        lbl.config(text=f"${value:,.2f}")
                    else:
                        lbl.config(text=str(value))

    def setup_equity_tab(self):
        # สร้างคอนโทรลบาร์ด้านบนสำหรับกรองบอท
        filter_frame = tk.Frame(self.tab_equity, bg="#0f172a", pady=5)
        filter_frame.pack(fill="x", padx=10, pady=(5, 0))
        
        tk.Label(filter_frame, text="🔍 เลือกกราฟบอทที่ต้องการดู:", font=("Outfit", 9, "bold"), bg="#0f172a", fg="#f8fafc").pack(side="left", padx=5)
        
        self.var_equity_filter = tk.StringVar(value="ALL")
        options = ["ALL", "SCALPING", "DAYTRADING", "SWINGTRADING", "GROQ_GEN2"]
        
        cb_filter = ttk.Combobox(filter_frame, textvariable=self.var_equity_filter, values=options, state="readonly", width=15)
        cb_filter.pack(side="left", padx=5)
        cb_filter.bind("<<ComboboxSelected>>", lambda e: self.draw_equity_curve())
        
        # สร้าง Canvas สำหรับวาดกราฟเส้น Equity
        self.equity_canvas = tk.Canvas(self.tab_equity, bg="#020617", highlightthickness=0)
        self.equity_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.equity_canvas.bind("<Configure>", lambda e: self.draw_equity_curve())

    def draw_equity_curve(self):
        if not hasattr(self, "equity_canvas") or not self.equity_canvas.winfo_exists():
            return
        
        self.equity_canvas.delete("all")
        w = self.equity_canvas.winfo_width()
        h = self.equity_canvas.winfo_height()
        if w < 100 or h < 100:
            return

        bal = getattr(self, "current_balance", 10000.0)
        raw_history = getattr(self, "current_history", [])
        
        filter_val = self.var_equity_filter.get() if hasattr(self, "var_equity_filter") else "ALL"
        
        # คัดกรองประวัติตาม Magic Number ของ Agent
        history = raw_history
        if filter_val != "ALL":
            try:
                if filter_val == "SCALPING":
                    magics = [111111, 1001, 1002, 1003, 1004, 1005]
                    history = [t for t in history if t.get("magic") in magics]
                elif filter_val == "DAYTRADING":
                    history = [t for t in history if t.get("magic") == 222222]
                elif filter_val == "SWINGTRADING":
                    history = [t for t in history if t.get("magic") == 333333]
                elif filter_val == "GROQ_GEN2":
                    history = [t for t in history if t.get("magic") == 444444]
            except Exception:
                pass
                
        # คัดกรองและจัดเรียงประวัติการปิดออเดอร์ตามวันเวลา
        sorted_history = sorted(history, key=lambda x: x.get("close_time", ""))
        pnl_list = [float(t.get("pnl", 0.0)) for t in sorted_history]
        total_pnl = sum(pnl_list)
        starting_balance = bal - total_pnl
        
        points = [starting_balance]
        curr = starting_balance
        for pnl in pnl_list:
            curr += pnl
            points.append(curr)
            
        pad_x = 60
        pad_y = 45
        
        # วาดพื้นหลัง/กรอบ
        self.equity_canvas.create_rectangle(pad_x, pad_y, w - pad_x, h - pad_y, outline="#334155", width=1)
        
        # ข้อความหัวกราฟ
        title_text = f"Equity Curve: {filter_val} (Initial: ${starting_balance:,.2f} -> Current: ${bal:,.2f} | Trades: {len(points)-1})"
        self.equity_canvas.create_text(w // 2, 20, text=title_text, fill="#f8fafc", font=("Outfit", 11, "bold"))

        if len(points) < 2:
            self.equity_canvas.create_text(w // 2, h // 2, text="No trade history available yet to draw equity curve.", fill="#64748b", font=("Outfit", 10))
            return
            
        y_min = min(points)
        y_max = max(points)
        y_range = y_max - y_min
        if y_range == 0:
            y_min -= 100
            y_max += 100
            y_range = 200
        else:
            # ขยายกรอบขอบบนล่าง 10% เพื่อความสวยงาม
            y_min -= y_range * 0.1
            y_max += y_range * 0.1
            y_range = y_max - y_min
            
        # วาดเส้นกริดแนวนอน (Horizontal Grid Lines & Price Labels)
        grid_count = 5
        for i in range(grid_count):
            val = y_min + i * (y_range / (grid_count - 1))
            y_coord = h - pad_y - (val - y_min) * (h - 2 * pad_y) / y_range
            self.equity_canvas.create_line(pad_x, y_coord, w - pad_x, y_coord, fill="#1e293b", dash=(3, 3))
            self.equity_canvas.create_text(pad_x - 10, y_coord, text=f"${val:,.0f}", fill="#94a3b8", anchor="e", font=("Outfit", 8))
            
        # พล็อตจุดพิกัดเส้น
        coords = []
        n_points = len(points)
        for i, val in enumerate(points):
            cx = pad_x + i * (w - 2 * pad_x) / (n_points - 1)
            cy = h - pad_y - (val - y_min) * (h - 2 * pad_y) / y_range
            coords.append((cx, cy))
            
        # วาดพื้นที่แรเงาใต้เส้นกราฟ (Polygon)
        poly_coords = [coords[0][0], h - pad_y]
        for pt in coords:
            poly_coords.extend([pt[0], pt[1]])
        poly_coords.extend([coords[-1][0], h - pad_y])
        self.equity_canvas.create_polygon(poly_coords, fill="#022c22", outline="") # สีเขียวมืดแรเงา
        
        # วาดเส้นกราฟหลัก (Main Line)
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i+1]
            self.equity_canvas.create_line(x1, y1, x2, y2, fill="#10b981", width=2.5, smooth=True)
            # พล็อตจุดวงกลมเล็กๆ บนเส้น
            self.equity_canvas.create_oval(x1 - 2, y1 - 2, x1 + 2, y1 + 2, fill="#34d399", outline="#059669")
        # จุดสุดท้าย
        self.equity_canvas.create_oval(coords[-1][0] - 3, coords[-1][1] - 3, coords[-1][0] + 3, coords[-1][1] + 3, fill="#34d399", outline="#059669")

    def setup_indicator_tab(self):
        # หน้าจอตรวจสอบค่า Indicator
        container = tk.Frame(self.tab_indicator, bg="#1e293b", padx=15, pady=15)
        container.pack(fill="both", expand=True)
        
        # Title
        tk.Label(container, text="Quantum TrendPulse MT5 Indicator Monitor", font=("Outfit", 12, "bold"), bg="#1e293b", fg="#f8fafc").pack(anchor="w", pady=(0, 15))
        
        # Grid Frame
        grid_frame = tk.Frame(container, bg="#1e293b")
        grid_frame.pack(fill="both", expand=True)
        
        # Columns configure
        grid_frame.columnconfigure((0, 1, 2), weight=1)
        
        # สร้าง Card สำหรับแต่ละ Timeframe
        self.card_m1 = self.create_ind_card(grid_frame, "M1 Chart Signal", 0)
        self.card_m5 = self.create_ind_card(grid_frame, "M5 Chart Signal", 1)
        self.card_m15 = self.create_ind_card(grid_frame, "M15 (Main) Signal", 2)
        
        # สรุป Alignment และ Confirmation
        summary_frame = tk.LabelFrame(container, text=" 📊 Alignment & Confirmation Summary ", bg="#1e293b", fg="#94a3b8", font=("Outfit", 9, "bold"), padx=15, pady=10)
        summary_frame.pack(fill="x", pady=(15, 0))
        
        summary_frame.columnconfigure((0, 1), weight=1)
        
        # 1. Consensus / Alignment Status
        align_label_lbl = tk.Label(summary_frame, text="Indicator Consensus (3 Timeframes):", font=("Outfit", 10), bg="#1e293b", fg="#94a3b8")
        align_label_lbl.grid(row=0, column=0, sticky="w", pady=5)
        self.lbl_ind_align = tk.Label(summary_frame, text="WAITING FOR CONNECTION", font=("Outfit", 10, "bold"), bg="#1e293b", fg="#fbbf24")
        self.lbl_ind_align.grid(row=0, column=1, sticky="w", pady=5)
        
        # 2. Trigger Confirmation Status
        confirm_label_lbl = tk.Label(summary_frame, text="M1 Trigger Confirmation:", font=("Outfit", 10), bg="#1e293b", fg="#94a3b8")
        confirm_label_lbl.grid(row=1, column=0, sticky="w", pady=5)
        self.lbl_ind_confirm = tk.Label(summary_frame, text="WAITING FOR SIGNAL", font=("Outfit", 10, "bold"), bg="#1e293b", fg="#fbbf24")
        self.lbl_ind_confirm.grid(row=1, column=1, sticky="w", pady=5)
        
        # 3. Update status info
        self.lbl_ind_update = tk.Label(container, text="Last Update: -", font=("Outfit", 8), bg="#1e293b", fg="#64748b")
        self.lbl_ind_update.pack(anchor="e", pady=(8, 0))

    def create_ind_card(self, parent, title, col):
        card = tk.LabelFrame(parent, text=f" {title} ", bg="#0f172a", fg="#94a3b8", font=("Outfit", 9, "bold"), padx=12, pady=10, relief="solid", bd=1)
        card.grid(row=0, column=col, sticky="nsew", padx=5, pady=5)
        card.grid_propagate(True)
        
        # Direction
        tk.Label(card, text="Direction:", font=("Outfit", 9), bg="#0f172a", fg="#64748b").grid(row=0, column=0, sticky="w", pady=3)
        lbl_dir = tk.Label(card, text="NONE", font=("Outfit", 11, "bold"), bg="#0f172a", fg="#94a3b8")
        lbl_dir.grid(row=0, column=1, sticky="w", pady=3)
        
        # Signal Price
        tk.Label(card, text="Signal Price:", font=("Outfit", 9), bg="#0f172a", fg="#64748b").grid(row=1, column=0, sticky="w", pady=3)
        lbl_price = tk.Label(card, text="0.00", font=("Outfit", 10, "bold"), bg="#0f172a", fg="#f8fafc")
        lbl_price.grid(row=1, column=1, sticky="w", pady=3)
        
        # Signal Time
        tk.Label(card, text="Signal Time:", font=("Outfit", 9), bg="#0f172a", fg="#64748b").grid(row=2, column=0, sticky="w", pady=3)
        lbl_time = tk.Label(card, text="-", font=("Outfit", 9), bg="#0f172a", fg="#94a3b8")
        lbl_time.grid(row=2, column=1, sticky="w", pady=3)
        
        card.columnconfigure(1, weight=1)
        return {"dir": lbl_dir, "price": lbl_price, "time": lbl_time, "frame": card}

    def refresh_indicator_monitor(self, d_m1, t_m1, p_m1, d_m5, t_m5, p_m5, d_m15, t_m15, p_m15, upd_time, current_price):
        if not hasattr(self, "lbl_ind_align"):
            return
            
        import datetime
        
        # Helper to update card label
        def update_card(card, d, t, p):
            if d == 1.0:
                card["dir"].config(text="BUY", fg="#10b981")
            elif d == -1.0:
                card["dir"].config(text="SELL", fg="#ef4444")
            else:
                card["dir"].config(text="NONE / HOLD", fg="#94a3b8")
                
            card["price"].config(text=f"{p:,.2f}" if p and p > 0 else "0.00")
            
            if t and t > 0:
                dt_str = datetime.datetime.fromtimestamp(t).strftime('%H:%M:%S')
                card["time"].config(text=dt_str)
            else:
                card["time"].config(text="-")

        update_card(self.card_m1, d_m1, t_m1, p_m1)
        update_card(self.card_m5, d_m5, t_m5, p_m5)
        update_card(self.card_m15, d_m15, t_m15, p_m15)
        
        # Consensus/Alignment checking
        is_aligned = (d_m1 == d_m5 == d_m15 and d_m1 != 0.0 and d_m1 is not None)
        if is_aligned:
            align_txt = f"ALIGNED ({'BUY' if d_m1 == 1.0 else 'SELL'})"
            align_color = "#10b981"
        else:
            align_txt = "NOT ALIGNED (ทิศทางไม่ตรงกัน)"
            align_color = "#ef4444"
        self.lbl_ind_align.config(text=align_txt, fg=align_color)
        
        # Confirmation checking
        if is_aligned and p_m15 and p_m15 > 0:
            if d_m15 == 1.0:
                is_confirmed = (current_price > p_m15)
                conf_txt = f"{'CONFIRMED' if is_confirmed else 'WAITING'} (M1 Close: {current_price:.2f} > M15 Ref: {p_m15:.2f})"
            else:
                is_confirmed = (current_price < p_m15)
                conf_txt = f"{'CONFIRMED' if is_confirmed else 'WAITING'} (M1 Close: {current_price:.2f} < M15 Ref: {p_m15:.2f})"
                
            conf_color = "#10b981" if is_confirmed else "#fbbf24"
        else:
            conf_txt = "WAITING FOR THREE-TIMEFRAME CONSENSUS"
            conf_color = "#64748b"
        self.lbl_ind_confirm.config(text=conf_txt, fg=conf_color)
        
        if upd_time and upd_time > 0:
            upd_str = datetime.datetime.fromtimestamp(upd_time).strftime('%Y-%m-%d %H:%M:%S')
            self.lbl_ind_update.config(text=f"Last EA Terminal Update: {upd_str}")
        else:
            self.lbl_ind_update.config(text="Last Update: N/A")

    def show_sim_indicator_monitor(self):
        if not hasattr(self, "lbl_ind_align"):
            return
        self.lbl_ind_align.config(text="OFFLINE (ACTIVE IN MT5 LIVE MODE ONLY)", fg="#64748b")
        self.lbl_ind_confirm.config(text="OFFLINE (ACTIVE IN MT5 LIVE MODE ONLY)", fg="#64748b")
        self.lbl_ind_update.config(text="Last Update: N/A")

    def close_selected_position(self):
        selected = self.tree_positions.selection()
        if not selected:
            messagebox.showwarning("คำเตือน", "กรุณาเลือกตั๋วออเดอร์ในตารางที่ต้องการปิด")
            return
            
        values = self.tree_positions.item(selected[0])['values']
        ticket_id = values[0]
        
        if messagebox.askyesno("ยืนยันการปิดออเดอร์", f"คุณต้องการปิดออเดอร์ Ticket #{ticket_id} ทันทีหรือไม่?"):
            def do_close():
                mode = self.var_mode.get()
                logging.info(f"🛑 สั่ง CLOSE ออเดอร์ #{ticket_id}...")
                try:
                    if mode == "Simulation":
                        res = bot_sim.exchange.close_position(str(ticket_id))
                    else:
                        res = bot_mt5.mt5_bridge.close_position(int(ticket_id), symbol=bot_mt5.symbol)
                        
                    if res.get("status") == "SUCCESS":
                        logging.info(f"ปิดออเดอร์ #{ticket_id} สำเร็จ!")
                    else:
                        logging.error(f"ปิดออเดอร์ #{ticket_id} ล้มเหลว: {res.get('message')}")
                except Exception as e:
                    logging.error(f"ระบบปิดออเดอร์ขัดข้อง: {e}")
                    
            t = threading.Thread(target=do_close, daemon=True)
            t.start()

# ----------------------------------------------------
# 📌 6. ฟังก์ชันเริ่มรัน GUI Dashboard
# ----------------------------------------------------
if __name__ == "__main__":
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
        
    root = tk.Tk()
    
    style = ttk.Style()
    style.theme_use("clam")
    
    style.configure("TCombobox", fieldbackground="#0f172a", background="#1e293b", foreground="#f8fafc", relief="flat")
    style.configure("TNotebook", background="#1e293b", borderwidth=0)
    style.configure("TNotebook.Tab", background="#0f172a", foreground="#94a3b8", borderwidth=0, padding=[10, 4])
    style.map("TNotebook.Tab", background=[('selected', '#1e293b')], foreground=[('selected', '#f8fafc')])
    
    style.configure("Treeview", background="#1e293b", fieldbackground="#1e293b", foreground="#f8fafc", rowheight=26, font=("Outfit", 9))
    style.map("Treeview", background=[('selected', '#818cf8')], foreground=[('selected', '#0f172a')])
    style.configure("Treeview.Heading", background="#0f172a", foreground="#94a3b8", borderwidth=0, font=("Outfit", 9, "bold"))
    
    app = TradingBotGUI(root)
    root.mainloop()
