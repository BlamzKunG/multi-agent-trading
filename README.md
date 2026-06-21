# 🤖 XAUUSD Stateless LLM Trading Bot

ระบบบอทเทรดทองคำ (XAUUSD) อัจฉริยะ ทำงานแบบ Stateless Loop ขับเคลื่อนด้วย Multi-Agent LLMs ผ่าน MaxPlus AI API 

---

## 📌 โครงสร้างระบบ (Architecture)

1. **`exchange_sim.py`**: ระบบจำลองโบรกเกอร์ (Mock Broker) คำนวณ Margin, Leverage และ P&L แบบเรียลไทม์พร้อมปุ่มความปลอดภัย (Guardrails) ป้องกันพอร์ตเสียหาย
2. **`data_feed.py`**: ตัวเชื่อมต่อดึงข้อมูลราคาทองคำจริง (GC=F) จาก Yahoo Finance API ทั้งราคาแบบปัจจุบันและแท่งเทียนย้อนหลัง
3. **`trading_agents.py`**: Agent 2 ตัวประมวลผลผ่านโมเดลภาษา:
   * **Analyst Agent** (`claude-sonnet-4-6` / `gpt-5.5`): วิเคราะห์โอกาสเข้าเทรดและส่งสัญญาณ
   * **Manager Agent** (`claude-haiku-4-5` / `gpt-5.4-mini`): บริหารความเสี่ยงของออเดอร์ (เลื่อน SL กันหน้าทุน / ปิดออเดอร์)
4. **`bot_orchestrator.py`**: ตัวคุมระบบหลักรันลูปกระบวนการตัดสินใจทั้งหมด
5. **`test_exchange.py`**: สคริปต์สั้นสำหรับทดสอบฟังก์ชันโบรกเกอร์จำลอง

---

## 🚀 วิธีเริ่มต้นใช้งานบนคอมพิวเตอร์ (PC Setup)

### 1. โคลนโปรเจกต์ลงเครื่อง
```bash
git clone https://github.com/BlamzKunG/multi-agent-trading.git
cd multi-agent-trading
```

### 2. ติดตั้งไลบรารีที่จำเป็น
```bash
pip install pandas requests
```

### 3. ตั้งค่า API Key ของ MaxPlus AI
ระบุ Key ใน Environment Variable ของระบบคุณก่อนรันบอท:

* **บน Windows (Command Prompt):**
  ```cmd
  set MAXPLUS_API_KEY="ccsk-คีย์ของคุณ"
  ```
* **บน macOS / Linux:**
  ```bash
  export MAXPLUS_API_KEY="ccsk-คีย์ของคุณ"
  ```

### 4. การทดสอบรัน (เลือกวิธีรัน)

#### 🅰️ แบบที่ 1: รันบนระบบจำลอง (Simulation Mode - ไม่จำเป็นต้องใช้ MT5)
เหมาะสำหรับทดสอบตรรกะบอทและความเสี่ยงโดยไม่ใช้เงินจริง:
```bash
# ทดสอบระบบจำลองโบรกเกอร์
python test_exchange.py

# รันบอทเทรดวิเคราะห์ข้อมูลตลาดจริงในระบบจำลอง 1 รอบ
python bot_orchestrator.py
```

#### 🅱️ แบบที่ 2: รันเชื่อมต่อกับบัญชีจริงบน MetaTrader 5 (MT5 Live Mode)
*ความต้องการพิเศษ: ต้องรันบน PC Windows ที่มีโปรแกรม MT5 ติดตั้งอยู่*

1. ติดตั้งไลบรารี MetaTrader 5 เพิ่มเติม:
   ```bash
   pip install MetaTrader5
   ```
2. เปิดโปรแกรม MT5 Terminal และล็อกอินเข้าพอร์ตของคุณ (เดโมหรือบัญชีจริง)
3. รันตัวควบคุมหลักสำหรับ MT5:
   ```bash
   python bot_orchestrator_mt5.py
   ```
   *(บอทจะเชื่อมต่อเข้ากับโปรแกรม MT5 และส่งคำสั่งเทรด XAUUSD ไปที่โบรกเกอร์จริงของคุณแบบอัตโนมัติ)*