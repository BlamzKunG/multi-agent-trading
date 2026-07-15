import requests
import json
import logging
import time
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TradingAgents:
    """
    ระบบตัวแทนอัจฉริยะ (Multi-Agent Trading System)
    ทำหน้าที่วิเคราะห์กราฟและบริหารความเสี่ยงด้วยโมเดลภาษาผ่าน MaxPlus AI API
    """
    def __init__(self, api_key, base_url="https://api.maxplus-ai.cc/v1", analysis_model="claude-haiku-4-5", management_model="claude-haiku-4-5"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.analysis_model = analysis_model
        self.management_model = management_model
        
        # รายการโมเดลที่ใช้งานได้ เรียงลำดับจากราคาถูกสุดไปแพงสุด (ตาม API Key ของผู้ใช้ที่รองรับเฉพาะตระกูล Claude)
        self.analysis_models_catalog = [
            "claude-haiku-4-5-20251001",
            "claude-haiku-4-5",
            "claude-sonnet-4-6",
            "claude-sonnet-5",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8"
        ]
        
        self.management_models_catalog = [
            "claude-haiku-4-5-20251001",
            "claude-haiku-4-5",
            "claude-sonnet-4-5"
        ]
        
        # บันทึกโมเดลที่เปิดใช้งานได้สำเร็จล่าสุดแบบ Global และเวลาบันทึก
        self.last_successful_model = None
        self.last_success_time = 0.0

    def _get_models_to_try(self, model, category):
        # รีเซ็ตแคชโมเดลสำเร็จล่าสุดทุกๆ 15 นาที เพื่อให้ระบบมีโอกาสกลับมาลองใช้รุ่นที่ถูกที่สุดใหม่
        if self.last_successful_model and (time.time() - self.last_success_time > 15 * 60):
            logging.info("⏰ ครบ 15 นาทีแล้ว: รีเซ็ตโมเดลสำเร็จล่าสุดเพื่อกลับไปทดสอบใช้รุ่นที่ถูกที่สุดใหม่")
            self.last_successful_model = None
            self.last_success_time = 0.0

        if category == "analysis":
            catalog = list(self.analysis_models_catalog)
        elif category == "management":
            catalog = list(self.management_models_catalog)
        else:
            is_management = any(m in str(model).lower() for m in ["flash", "haiku", "mini"])
            if is_management:
                catalog = list(self.management_models_catalog)
                category = "management"
            else:
                catalog = list(self.analysis_models_catalog)
                category = "analysis"
                
        models_to_try = []
        
        # 1. ลองใช้โมเดลสำเร็จล่าสุดแบบ Global ก่อนเป็นอันดับแรก
        if self.last_successful_model:
            models_to_try.append(self.last_successful_model)
            
        # 2. ตามด้วยลำดับโมเดลในแค็ตตาล็อกตามลำดับราคาถูกสุดไปแพงสุด
        for m in catalog:
            if m not in models_to_try:
                models_to_try.append(m)
                
        # ป้องกันกรณีระบุโมเดลอื่นนอกเหนือจากที่มีในแค็ตตาล็อก ให้ใส่ต่อท้าย
        if model and model not in models_to_try:
            models_to_try.append(model)
            
        return models_to_try, category

    def _call_llm(self, model, messages, json_response=True, fallbacks=None, category=None):
        """ส่งคำขอไปยัง MaxPlus AI API พร้อมรองรับทั้ง Anthropic Protocol และ OpenAI Protocol อัตโนมัติ"""
        if category:
            models_to_try, resolved_category = self._get_models_to_try(model, category)
        else:
            if fallbacks is None:
                fallbacks = []
            models_to_try = [model] + fallbacks
            resolved_category = None
            
        for idx, current_model in enumerate(models_to_try):
            # ตรวจสอบชื่อแบรนด์โมเดล (รวมคำคีย์เวิร์ดของ Claude: claude, haiku, sonnet, opus)
            is_claude = any(keyword in current_model.lower() for keyword in ["claude", "haiku", "sonnet", "opus"])
            
            if is_claude:
                url = f"{self.base_url}/messages"
                headers = {
                    **self.headers,
                    "anthropic-version": "2023-06-01"
                }
                
                system_text = None
                user_messages = []
                for msg in messages:
                    if msg["role"] == "system":
                        system_text = msg["content"]
                    else:
                        user_messages.append({
                            "role": msg["role"],
                            "content": msg["content"]
                        })
                        
                payload = {
                    "model": current_model,
                    "messages": user_messages,
                    "temperature": 0.2,
                    "max_tokens": 4096
                }
                if system_text:
                    payload["system"] = system_text
            else:
                url = f"{self.base_url}/chat/completions"
                headers = self.headers
                payload = {
                    "model": current_model,
                    "messages": messages,
                    "temperature": 0.2
                }
                if json_response:
                    payload["response_format"] = {"type": "json_object"}
            
            max_retries = 3
            backoff_factor = 2
            
            for attempt in range(max_retries):
                try:
                    response = requests.post(url, headers=headers, json=payload, timeout=90)
                    
                    if response.status_code in [429, 500, 502, 503, 504]:
                        logging.warning(f"เรียกใช้ LLM ({current_model}) ล้มเหลวด้วยรหัส HTTP {response.status_code}. กำลังลองใหม่รอบที่ {attempt + 1}/{max_retries}...")
                        time.sleep(backoff_factor ** attempt)
                        continue
                        
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    result = response.json()
                    
                    if is_claude:
                        content = result['content'][0]['text']
                    else:
                        content = result['choices'][0]['message']['content']
                    
                    # หากเรียกสำเร็จ ให้เซฟเป็นโมเดลที่ใช้งานได้สำเร็จล่าสุดแบบ Global พร้อมเวลาบันทึก
                    self.last_successful_model = current_model
                    self.last_success_time = time.time()
                    logging.info(f"💾 บันทึกโมเดลสำเร็จล่าสุดแบบ Global: {current_model}")
                        
                    if json_response:
                        try:
                            return json.loads(content)
                        except Exception as json_err:
                            cleaned_content = content.strip()
                            if cleaned_content.startswith("```json"):
                                cleaned_content = cleaned_content[7:]
                            elif cleaned_content.startswith("```"):
                                cleaned_content = cleaned_content[3:]
                            if cleaned_content.endswith("```"):
                                cleaned_content = cleaned_content[:-3]
                            cleaned_content = cleaned_content.strip()
                            try:
                                return json.loads(cleaned_content)
                            except Exception:
                                raise json_err
                    return content
                    
                except Exception as e:
                    logging.warning(f"เกิดข้อผิดพลาดในการเชื่อมต่อ {current_model} (รอบที่ {attempt + 1}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_factor ** attempt)
                    else:
                        logging.error(f"พยายามใช้โมเดล {current_model} ครบ {max_retries} ครั้งแล้วแต่ล้มเหลว")
            
            if idx < len(models_to_try) - 1:
                logging.warning(f"สลับเปลี่ยนไปเรียกใช้โมเดลสำรองลำดับถัดไป: {models_to_try[idx+1]}")
                
        return None

    def _get_fallbacks(self, model_name):
        if "deepseek" in model_name.lower() or "glm" in model_name.lower() or "kimi" in model_name.lower():
            return ["deepseek-v4-flash"]
        elif "claude" in model_name.lower() or "sonnet" in model_name.lower() or "haiku" in model_name.lower() or "opus" in model_name.lower():
            if "5" in model_name.lower():
                return ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
            else:
                return ["claude-sonnet-5", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"]
        else:
            return ["claude-sonnet-5", "claude-sonnet-4-6"]

    def _analyze_price_action(self, df, swing_window=3):
        """
        วิเคราะห์โครงสร้างพฤติกรรมราคา (Price Action) และหาแนวรับแนวต้านสวิงไฮ/โลว์
        """
        if df.empty:
            return df
            
        df = df.copy()
        
        # 1. คำนวณลักษณะแท่งเทียนพื้นฐาน (Candlestick Attributes)
        df['body_size'] = (df['close'] - df['open']).abs()
        df['upper_shadow'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_shadow'] = df[['close', 'open']].min(axis=1) - df['low']
        df['range'] = df['high'] - df['low']
        df['body_percent'] = np.where(df['range'] > 0, df['body_size'] / df['range'], 0.0)
        
        # ประเภทของแท่งเทียน
        df['candle_type'] = np.where(df['close'] > df['open'], 'BULLISH', 
                             np.where(df['close'] < df['open'], 'BEARISH', 'DOJI'))
        
        # 2. คำนวณอินดิเคเตอร์แบบ Lag ต่ำ / ค่าเฉลี่ยประคองภาพรวม
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # คำนวณ ATR (14) เพื่อวัดความผันผวน
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(14).mean()
        df['atr_14'] = df['atr_14'].ffill().bfill()
        
        # 3. คำนวณจุด Swing High / Swing Low
        df['swing_high'] = False
        df['swing_low'] = False
        
        for i in range(swing_window, len(df) - swing_window):
            val = df.loc[i, 'high']
            is_high = True
            for j in range(1, swing_window + 1):
                if val < df.loc[i - j, 'high'] or val < df.loc[i + j, 'high']:
                    is_high = False
                    break
            if is_high:
                df.loc[i, 'swing_high'] = True
                
            val = df.loc[i, 'low']
            is_low = True
            for j in range(1, swing_window + 1):
                if val > df.loc[i - j, 'low'] or val > df.loc[i + j, 'low']:
                    is_low = False
                    break
            if is_low:
                df.loc[i, 'swing_low'] = True
                
        return df

    def analyze_market(self, df_5m, df_15m, df_1h, balance, symbol="XAUUSD", leverage=100.0, spread=0.0):
        """
        ระบบวิเคราะห์ร่วมกัน (Multi-Agent M5 Price Action Scalper):
        1. Trend & Structure Agent (LLM) - วิเคราะห์เทรนและแนวรับต้านใน M15/H1
        2. Price Action Agent (LLM) - วิเคราะห์พฤติกรรมราคาและแท่งเทียนกลับตัวใน M5
        3. Volatility & Spread Guard (Python) - ตัวกรองความคุ้มค่าและช่วงผันผวนรุนแรง
        4. Risk Manager (Python) - คำนวณล็อตที่เสี่ยงไม้ละ 1% และตั้งระยะ SL/TP ตาม ATR M5
        5. Scalp Master / CIO (LLM) - ตัดสินใจร่วมเป็นเอกฉันท์ออกออเดอร์ในรูปแบบ JSON
        """
        # วิเคราะห์ Price Action บนดาต้าเฟรมที่ส่งเข้ามาก่อน
        df_5m_pa = self._analyze_price_action(df_5m)
        df_15m_pa = self._analyze_price_action(df_15m)
        df_1h_pa = self._analyze_price_action(df_1h)
        
        # --- ด่านที่ 3: Volatility & Spread Guard (Python-based) ---
        current_price = float(df_5m_pa['close'].iloc[-1])
        atr_5m = float(df_5m_pa['atr_14'].iloc[-1])
        
        # กรองสเปรดและปริมาณความผันผวน
        spread_ok = True
        spread_reason = "Spread is normal."
        if spread > 0:
            max_spread_points = 35.0 if "XAU" in symbol.upper() else 50.0
            if spread > max_spread_points:
                spread_ok = False
                spread_reason = f"Spread too wide: {spread} points (limit {max_spread_points})"
                
        atr_ok = True
        atr_reason = "Volatility is suitable."
        min_atr = 0.50 if "XAU" in symbol.upper() else 10.0
        if atr_5m < min_atr:
            atr_ok = False
            atr_reason = f"Volatility too low: ATR is {atr_5m:.2f} (min {min_atr})"

        # --- ด่านที่ 4: Risk & Capital Manager (Python-based Math) ---
        risk_percent = 0.01
        risk_amount_usd = balance * risk_percent
        
        # คำนวณระยะ SL เริ่มต้นจาก 1.5 * ATR 5m (ขั้นต่ำ 1.50 USD สำหรับความปลอดภัย)
        sl_distance_usd = max(1.5 * atr_5m, 1.50 if "XAU" in symbol.upper() else 15.0)
        contract_size = 100.0 if "XAU" in symbol.upper() else 1.0
        calculated_lot = risk_amount_usd / (sl_distance_usd * contract_size)
        calculated_lot = round(max(0.01, calculated_lot), 2)
        
        max_allowed_lot = getattr(self, 'max_lot', 0.05)
        final_lot = min(calculated_lot, max_allowed_lot)
        
        # จัดรูปแบบสรุปแท่งเทียนและสวิงส่งต่อให้ LLM
        def format_candles(df, num_candles=10):
            summary = ""
            for _, row in df.tail(num_candles).iterrows():
                time_str = row['timestamp'].strftime('%H:%M')
                summary += f"- แท่ง {time_str}: Close={row['close']:.2f}, High={row['high']:.2f}, Low={row['low']:.2f}, Open={row['open']:.2f} | ประเภท={row['candle_type']} | ขนาดตัว={row['body_size']:.2f} ({row['body_percent']*100:.0f}%) | ไส้บน={row['upper_shadow']:.2f}, ไส้ล่าง={row['lower_shadow']:.2f}\n"
            return summary

        def format_swings(df):
            swings_high = df[df['swing_high']].tail(4)
            swings_low = df[df['swing_low']].tail(4)
            summary = "แนวต้านย่อย (Swing Highs):\n"
            for _, row in swings_high.iterrows():
                summary += f"- ราคา {row['high']:.2f} (เวลา {row['timestamp'].strftime('%H:%M')})\n"
            summary += "\nแนวรับย่อย (Swing Lows):\n"
            for _, row in swings_low.iterrows():
                summary += f"- ราคา {row['low']:.2f} (เวลา {row['timestamp'].strftime('%H:%M')})\n"
            return summary

        summary_5m = format_candles(df_5m_pa, 10)
        summary_15m = format_candles(df_15m_pa, 5)
        swings_5m = format_swings(df_5m_pa)
        swings_15m = format_swings(df_15m_pa)
        
        current_ema50 = df_5m_pa['ema_50'].iloc[-1]
        current_ema200 = df_5m_pa['ema_200'].iloc[-1]

        # --- Agent 1: Trend & Structure Agent (LLM) ---
        trend_model = self.management_model
        trend_system = f"""คุณคือ Trend & Market Structure Analyst หน้าที่ของคุณคือวิเคราะห์ทิศทางและโครงสร้างแนวโน้มใหญ่ของ {symbol}
วิเคราะห์ข้อมูลแท่งเทียนย่อย M15 และ H1 เพื่อประเมิน:
1. แนวโน้มระยะยาว (Bullish / Bearish / Sideways) โดยเทียบราคากับเส้นค่าเฉลี่ยและสวิงไฮ/โลว์
2. โซนแนวรับแนวต้านเชิงโครงสร้างหลักที่แข็งแกร่งที่สุด

โปรดวิเคราะห์อย่างกระชับ (ไม่เกิน 3-4 บรรทัด) โดยสรุปฝั่งที่ได้เปรียบ: BUY ONLY, SELL ONLY หรือ HOLD (ตลาดแกว่งกว้างไม่มีทิศทาง)"""
        
        trend_user = f"""ราคาปัจจุบัน: {current_price:.2f}
เส้นประคองเทรน M5: EMA 50 = {current_ema50:.2f}, EMA 200 = {current_ema200:.2f}

ประวัติแท่งเทียน M15 ล่าสุด:
{summary_15m}

จุดสวิงไฮ/โลว์แนวต้านรับ M15:
{swings_15m}

จงวิเคราะห์ทิศทางเทรนและแนวรับแนวต้านหลักส่งต่อให้ทีมงานเทรดสั้น:"""

        logging.info("กำลังเรียกใช้ Trend & Structure Agent...")
        trend_report = self._call_llm(trend_model, [
            {"role": "system", "content": trend_system},
            {"role": "user", "content": trend_user}
        ], json_response=False, category="management")
        logging.info(f"รายงานเทรนหลัก: {trend_report}")

        # --- Agent 2: Price Action Analyst Agent (LLM) ---
        pa_model = self.analysis_model
        pa_system = f"""คุณคือ Price Action Specialist หน้าที่ของคุณคือการจับจังหวะสไนเปอร์เข้าซื้อขาย {symbol} บนกรอบ M5
วิเคราะห์พฤทีกรรมราคาดิบและแท่งเทียน (Candlestick Patterns) ย้อนหลัง 10 แท่งล่าสุด รวมถึงการตอบสนองของราคาเมื่อวิ่งเข้าทดสอบแนวรับแนวต้าน หรือเส้น EMA 50/200
มองหาลักษณะแท่งเทียนกลับตัวที่มีสัญญาณ Rejection หรือ Breakout ชัดเจน เช่น Pin Bar, Engulfing หรือ Inside Bar

เป้าหมายของคุณคือเสนอกลยุทธ์เข้าสเกลปิ้งสั้นๆ:
- สัญญาณเข้า: BUY, SELL หรือ HOLD (ไม่มีสัญญาณชัดเจน)
- ราคาเข้าเป้าหมาย (Entry)
- จุดตัดขาดทุน SL ทางโครงสร้างราคา (Structural SL) เช่น ใต้ไส้เทียนกลับตัว หรือขอบสวิงไฮ/โลว์ล่าสุด
โปรดรายงานข้อเท็จจริงพร้อมเหตุผลวิเคราะห์อย่างรัดกุมที่สุด"""

        pa_user = f"""ราคาปัจจุบัน: {current_price:.2f}
EMA 50 = {current_ema50:.2f}, EMA 200 = {current_ema200:.2f}

รายงานแนวโน้มใหญ่จาก Trend Agent:
{trend_report}

ประวัติแท่งเทียน M5 ล่าสุด (กราฟเปล่า):
{summary_5m}

จุดสวิงแนวต้านรับ M5:
{swings_5m}

จงประเมินจังหวะแท่งเทียนและวิเคราะห์แผนเข้าออเดอร์ส่งต่อให้ประธานกองทุน:"""

        logging.info("กำลังเรียกใช้ Price Action Analyst Agent...")
        pa_report = self._call_llm(pa_model, [
            {"role": "system", "content": pa_system},
            {"role": "user", "content": pa_user}
        ], json_response=False, category="analysis")
        logging.info(f"รายงานพฤติกรรมราคา PA: {pa_report}")

        # --- Agent 5: Scalp Master / CIO Consensus (LLM) ---
        cio_model = self.analysis_model
        cio_system = f"""คุณคือ CIO / Scalp Master หน้าที่ของคุณคือสรุปการตัดสินใจในรอบนี้เป็นเอกฉันท์และตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "hold_minutes": 5 | 10 | 15 | 30, // หาก action เป็น HOLD ให้เลือกช่วงเวลาที่จะพักวิเคราะห์รอบต่อไปเป็นจำนวนนาที (ใส่เป็นตัวเลข 5, 10, 15 หรือ 30) เพื่อช่วยประหยัด Token หาก action เป็น BUY หรือ SELL ให้ระบุเป็น null
  "lot": float,
  "entry": float,
  "sl": float,
  "tp": float,
  "reasoning": "ประโยคสรุปมติเห็นพ้องของกองทุนและเหตุผลพฤติกรรมราคา"
}}

กติกาบังคับตัดสินใจสเกลปิ้ง (Hard Scalping Rules):
1. หาก Volatility Guard หรือ Spread Guard รายงานสถานะ FAIL ให้ปฏิเสธและสรุปตอบเป็น HOLD ทันที (ตั้งค่า lot, entry, sl, tp เป็น 0.0, และเลือก hold_minutes เป็น 15 หรือ 30)
2. หากข้อเสนอของ Trend Agent และ Price Action Agent ขัดแย้งกัน หรือไม่มีสัญญาณกลับตัวชัดเจนบนแท่ง M5 ให้ตอบเป็น HOLD ทันที (เลือก hold_minutes เป็น 5, 10, 15 หรือ 30 ขึ้นกับความปั่นป่วนของตลาด)
3. ขนาดล็อตและเป้าหมาย SL ให้ยึดค่าที่ Risk Manager คำนวณมาเป็นหลักเพื่อควบคุมความเสี่ยงไม่เกิน 1% ของพอร์ต
4. จุด TP ตั้งห่างประมาณ 1.5 - 2 เท่าของระยะ SL เริ่มต้น หรืออ้างอิงระดับสวิงถัดไปตามข้อมูลที่นักวิเคราะห์เสนอ
5. หากเป็น HOLD ให้ตั้ง lot, entry, sl, tp ทั้งหมดเป็น 0.0 หรือ null
6. ระบบ hold_minutes ในกรณี HOLD จะพักการเรียกใช้ LLM รอบถัดไปชั่วคราวเพื่อประหยัด Token (มีตัวเลือกคือ 5, 10, 15, 30 นาที)"""

        cio_user = f"""สถานะบัญชีและปัจจัยควบคุมความเสี่ยง:
- บาลานซ์: ${balance:.2f} USD
- ราคา {symbol} ปัจจุบัน: {current_price:.2f}

1. รายงานของฝ่ายเทรด:
   - ผู้คุมแนวโน้มใหญ่ (Trend Agent): {trend_report}
   - นักสืบแท่งเทียน (Price Action Agent): {pa_report}

2. รายงานฝ่ายสเปรดและความเสี่ยง (Safety & Risk Guards):
   - สเปรดโบรกเกอร์ล่าสุด: {spread_reason} (Spread Status: {"PASS" if spread_ok else "FAIL"})
   - ความเหมาะสมของสภาวะตลาด: {atr_reason} (Volatility Status: {"PASS" if atr_ok else "FAIL"})
   - ขนาดล็อตสูงสุดที่อนุญาต (Max Lot): {max_allowed_lot}
   - ล็อตที่คำนวณมา (Risk 1%): {final_lot}
   - ระยะตัดขาดทุนแนะนำ (SL Distance): {sl_distance_usd:.2f} USD (แนะนำจุด SL เริ่มต้นที่ประมาณ: {current_price - sl_distance_usd:.2f} สำหรับ BUY หรือ {current_price + sl_distance_usd:.2f} สำหรับ SELL)

จงสรุปคำสั่งตัดสินใจสุดท้ายในรูปแบบ JSON:"""

        logging.info("กำลังเรียกใช้ Scalp Master Agent เพื่อหาข้อสรุปการยิงออเดอร์...")
        final_decision = self._call_llm(cio_model, [
            {"role": "system", "content": cio_system},
            {"role": "user", "content": cio_user}
        ], json_response=True, category="analysis")
        
        logging.info(f"มติการตัดสินใจสุดท้ายของ Scalp Master: {final_decision}")
        return final_decision

    def manage_position(self, position_details, current_price, balance, symbol="XAUUSD"):
        """
        Agent ตัวที่ 2: Manager Agent (วิเคราะห์และควบคุมความเสี่ยงของออเดอร์ที่ค้างอยู่)
        """
        model = self.management_model
        
        system_prompt = f"""คุณคือ Risk Manager หน้าที่ของคุณคือควบคุมความเสี่ยงของออเดอร์ {symbol} ที่เปิดอยู่
วิเคราะห์ระดับราคาปัจจุบันเทียบกับออเดอร์ที่คุณถืออยู่ เพื่อตัดสินใจว่าจะทำอย่างไรกับออเดอร์นี้

ทางเลือกการตัดสินใจของคุณ:
- "HOLD": ถือออเดอร์ต่อไปตามแผนเดิม
- "TRAILING_STOP": เลื่อนจุด Stop Loss (และ/หรือ Take Profit) เพื่อล็อคกำไรที่วิ่งถูกทาง โดยระยะห่างและระดับราคาใหม่ (new_sl, new_tp) ให้กำหนดตามดุลยพินิจของคุณเองตามโครงสร้างราคาล่าสุดและความผันผวน
- "CLOSE": ปิดออเดอร์ทันทีที่ราคาตลาดปัจจุบัน เพื่อล็อคกำไรหรือเพื่อตัดขาดทุนก่อนชน SL หากประเมินว่าเทรนด์ได้เปลี่ยนไปแล้ว

คุณต้องตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "HOLD" | "TRAILING_STOP" | "CLOSE",
  "new_sl": float_ราคาใหม่_หรือ_null,
  "new_tp": float_ราคาใหม่_หรือ_null,
  "reasoning": "อธิบายเหตุผลของการจัดการออเดอร์สั้นๆ (ในประโยคเดียว)"
}}"""

        user_content = f"""สถานะบัญชีและออเดอร์ในปัจจุบัน:
- ยอดเงินบาลานซ์: ${balance:.2f} USD
- ราคา {symbol} ล่าสุด: {current_price}
- รายละเอียดออเดอร์ที่ถืออยู่:
{json.dumps(position_details, indent=2)}

กรุณาวิเคราะห์สภาวะความเสี่ยงและตัดสินใจจัดการออเดอร์นี้:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        logging.info(f"ส่งสถานะออเดอร์ {position_details['id']} ให้ Manager Agent จัดการ {symbol} ด้วยโมเดล {model}...")
        return self._call_llm(model, messages, json_response=True, category="management")

    def analyze_market_regime(self, df_fast, df_slow, df_macro, symbol="XAUUSD", num_fast=5, num_slow=3):
        """
        Market Regime Agent (วิเคราะห์จำแนกสภาวะตลาดหลัก)
        """
        model = self.analysis_model
        
        df_fast_pa = self._analyze_price_action(df_fast)
        df_slow_pa = self._analyze_price_action(df_slow)
        
        current_price = float(df_fast_pa['close'].iloc[-1])
        atr_fast = float(df_fast_pa['atr_14'].iloc[-1])
        
        system_prompt = f"""คุณคือ Market Regime Agent หน้าที่ของคุณคือจำแนกสภาวะตลาดปัจจุบันของ {symbol}
วิเคราะห์ความผันผวน ปริมาณแท่งเทียน และโครงสร้างการเคลื่อนที่ของราคาล่าสุด
เป้าหมายคือระบุสภาวะตลาดเป็นค่าใดค่าหนึ่งในกลุ่มเหล่านี้เท่านั้น:
- "Trend Strong" (แนวโน้มเด่นและทิศทางชัดเจน)
- "Trend Weak" (เริ่มมีเทรนแต่ยังไม่มีกำลังส่งเพียงพอ)
- "Sideway" (แกว่งตัวออกข้างในกรอบแคบ/กว้าง)
- "High Volatility" (ผันผวนรุนแรงผิดปกติ เช่น ช่วงข่าวนอกตารางหรือแรงซื้อขายกระชาก)
- "Low Volatility" (ราคานิ่งเกินไป ไม่คุ้มค่าสเปรด)
- "News" (ใกล้หรืออยู่ในช่วงเวลาประกาศข่าวเศรษฐกิจสำคัญ)
- "Uncertain" (ตลาดก้ำกึ่ง โครงสร้างราคาขัดแย้งกันอย่างรุนแรง)

คุณต้องตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "regime": "Trend Strong" | "Trend Weak" | "Sideway" | "High Volatility" | "Low Volatility" | "News" | "Uncertain",
  "direction": "BULLISH" | "BEARISH" | "NEUTRAL",
  "reason": "ประโยคอธิบายสั้นๆ เกี่ยวกับปัจจัยเชิงปริมาณและสถิติเทคนิคที่สังเกตได้"
}}"""

        def format_candles(df, num_candles):
            summary = ""
            for _, row in df.tail(num_candles).iterrows():
                summary += f"- Time={row['timestamp'].strftime('%d/%m %H:%M') if 'timestamp' in row else ''} Close={row['close']:.2f}, High={row['high']:.2f}, Low={row['low']:.2f} | ประเภท={row['candle_type']} | ขนาด={row['body_size']:.2f}\n"
            return summary

        user_content = f"""ราคาปัจจุบัน: {current_price:.2f}
ข้อมูลความผันผวนล่าสุด: ATR = {atr_fast:.2f}
โครงสร้างราคาแท่งเทียนกรอบเวลาเร็ว (Fast Frame) ย้อนหลัง {num_fast} แท่ง:
{format_candles(df_fast_pa, num_fast)}
โครงสร้างราคาแท่งเทียนกรอบเวลาช้า (Slow Frame) ย้อนหลัง {num_slow} แท่ง:
{format_candles(df_slow_pa, num_slow)}

กรุณาวิเคราะห์สภาวะตลาด (Market Regime) ล่าสุดออกมาเป็น JSON:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        logging.info("กำลังเรียกใช้ Market Regime Agent...")
        return self._call_llm(model, messages, json_response=True, category="analysis")

    def review_order(self, proposed_order, regime, trend_report, pa_report, symbol="XAUUSD"):
        """
        Reviewer Agent (ผู้ตรวจทานออเดอร์ก่อนส่งคำสั่งไปยังโบรกเกอร์)
        """
        model = self.management_model
        
        system_prompt = f"""คุณคือ Reviewer Agent หน้าที่ของคุณคือการทำ Double-Check และรีวิวออเดอร์ของ {symbol} ที่นักวิเคราะห์เสนอมา
ตรวจสอบความสมเหตุสมผลและความขัดแย้งของแผนการเทรด:
1. หากพฤติกรรมในภาพรวมไม่สอดคล้องกับกลยุทธ์ เช่น ทิศทางเข้าสวนภาพใหญ่โดยไม่มีสัญญาณยืนยัน
2. หากสภาวะตลาดเป็น High Volatility หรือ Low Volatility หรือ Uncertain หรือ News คุณต้องประเมินว่าคุ้มค่าที่จะเปิดออเดอร์หรือไม่
3. หากพบความขัดแย้งหรือสุ่มเสี่ยงสูง ให้ปรับ action เป็น "HOLD" และแจ้งเหตุผล
4. ห้ามขยับราคา entry, sl, tp ยกเว้นพบว่า SL แคบเกินไปและเสี่ยงโดนเคลียร์ง่ายเกินราคา ATR

คุณต้องตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "lot": float,
  "entry": float_หรือ_null,
  "sl": float_หรือ_null,
  "tp": float_หรือ_null,
  "reasoning": "อธิบายสั้นๆ เกี่ยวกับการตัดสินใจรีวิว (เห็นด้วย / เปลี่ยนเป็น HOLD เนื่องจาก...)"
}}"""

        user_content = f"""ข้อเสนอออเดอร์ดั้งเดิม:
{json.dumps(proposed_order, indent=2)}

รายงานประเมินสภาวะตลาด (Market Regime):
{json.dumps(regime, indent=2)}

รายงานนักวิเคราะห์เทรน (Trend Agent):
{trend_report}

รายงานนักวิเคราะห์พฤติกรรมราคา (Price Action Agent):
{pa_report}

จงรีวิวออเดอร์นี้และส่งผลการรีวิวในรูปแบบ JSON:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        logging.info("กำลังเรียกใช้ Reviewer Agent เพื่อตรวจทานออเดอร์สุดท้าย...")
        return self._call_llm(model, messages, json_response=True, category="management")

    def _format_reflection(self, performance_stats, trade_history):
        reflection_context = ""
        if performance_stats:
            reflection_context += "\n--- ผลงานสถิติในอดีตเฉพาะของคุณ (Performance Stats) ---\n"
            reflection_context += f"- Win Rate: {performance_stats.get('win_rate', 0.0)}%\n"
            reflection_context += f"- Profit Factor: {performance_stats.get('profit_factor', 1.0)}\n"
            reflection_context += f"- Expectancy: {performance_stats.get('expectancy', 0.0)}\n"
            reflection_context += f"- Average Hold Time: {performance_stats.get('avg_hold_time_mins', 0.0)} mins\n"
            reflection_context += f"- Average R: {performance_stats.get('avg_r', 0.0)}\n"
            reflection_context += f"- Max Drawdown: ${performance_stats.get('max_drawdown_usd', 0.0)} USD\n"
            
        if trade_history:
            reflection_context += "\n--- ประวัติไม้ที่ปิดล่าสุดของคุณ (Trade History for Reflection) ---\n"
            # แสดงล่าสุด 5 ไม้
            for t in trade_history[:5]:
                reflection_context += f"- เวลาปิด: {t.get('close_time')} | {t.get('direction')} {t.get('lot')} Lot | Entry: {t.get('entry_price')} -> Close: {t.get('close_price')} | PnL: ${t.get('pnl')} ({t.get('close_reason')})\n"
                
        if reflection_context:
            reflection_context = (
                "\n=========================================\n"
                "📌 การวิเคราะห์อ้างอิงสถิติพอร์ต (PORTFOLIO STATISTICS REFERENCE):\n"
                "ข้อมูลด้านล่างคือสถิติผลการทำงานย้อนหลังของคุณเพื่อใช้เป็นข้อมูลประกอบการประเมินบริหารความเสี่ยงเท่านั้น "
                "ห้ามนำผลการชนะ/แพ้ในอดีตมาเป็นอคติในการวิเคราะห์ทิศทางกราฟปัจจุบัน (หลีกเลี่ยง Recency Bias) "
                "หรือเกิดความลังเลที่จะเปิดออเดอร์เมื่อเห็นกราฟเกิด Setup ที่สวยงาม "
                "จงมุ่งเน้นการตัดสินใจโดยอิงจากโครงสร้างราคาปัจจุบัน (Current Market Structure), Price Action และ Technical Setup ณ ขณะนี้เป็นหลัก"
                "\n=========================================\n"
            ) + reflection_context
            
        return reflection_context

    def _format_candles_brief(self, df, num_candles=5):
        summary = ""
        for _, row in df.tail(num_candles).iterrows():
            summary += f"- {row['timestamp'].strftime('%H:%M')} Close={row['close']:.2f}, High={row['high']:.2f}, Low={row['low']:.2f} | {row['candle_type']} | ATR={row.get('atr_14', 0.0):.2f}\n"
        return summary

    def analyze_scalping(self, df_1m, df_5m, df_15m, df_30m, balance, symbol="XAUUSD", leverage=100.0, spread=0.0, performance_stats=None, trade_history=None, regime_report=None, pending_orders=None, strats_to_analyze=None):
        """
        1) Scalping Agent: Parallel analysis where each active sub-strategy acts as an independent agent (using its own magic number & pending orders).
        """
        model = self.analysis_model
        
        df_1m_pa = self._analyze_price_action(df_1m)
        df_5m_pa = self._analyze_price_action(df_5m)
        df_15m_pa = self._analyze_price_action(df_15m)
        
        current_price = float(df_5m_pa['close'].iloc[-1])
        atr_5m = float(df_5m_pa['atr_14'].iloc[-1])
        
        # Risk Manager calculations
        sl_distance_usd = max(1.5 * atr_5m, 1.50 if "XAU" in symbol.upper() else 15.0)
        contract_size = 100.0 if "XAU" in symbol.upper() else 1.0
        risk_amount_usd = balance * 0.01
        calculated_lot = risk_amount_usd / (sl_distance_usd * contract_size)
        calculated_lot = round(max(0.01, calculated_lot), 2)
        max_allowed_lot = getattr(self, 'max_lot', 0.05)
        final_lot = min(calculated_lot, max_allowed_lot)
        
        reflection_context = self._format_reflection(performance_stats, trade_history)
        
        # --- ขั้นตอนที่ 1: เลือกกลยุทธ์ย่อยสเกลปิ้งที่เหมาะสม (Scalping Strategy Selector) ---
        selector_system = f"""คุณคือ Scalping Strategy Selector ของกองทุนเทรดสั้นทองคำ ({symbol})
หน้าที่ของคุณคือคัดกรองและเลือกกลยุทธ์การเทรดสั้นที่เหมาะสมกับสภาวะราคาในปัจจุบันจาก 5 กลยุทธ์นี้เท่านั้น:
1. "TREND_PULLBACK" (เข้าซื้อขายเมื่อราคาย่อตัวหาเส้นเฉลี่ยตามแนวโน้มหลัก)
2. "BREAKOUT" (เข้าซื้อขายเมื่อราคาทะลุขอบแนวรับแนวต้านสวิงหลัก)
3. "MEAN_REVERSION" (เข้าซื้อขายดักสวนทิศทางกลับเข้าหาค่าเฉลี่ยกลางเมื่อราคายืดตัวเกินตัวเลขความผันผวนปกติ)
4. "LIQUIDITY_SWEEP" (เข้าซื้อขายดักสวนทิศทางหลังราคาแล่นไปเก็บ Stop Loss แนวต้านรับสำคัญแล้วมีการดึงกลับทันที)
5. "MOMENTUM_CONTINUATION" (เข้าซื้อขายตามทิศทางความชันและแรงเหวี่ยงตลาดปัจจุบันโดยไม่รอราคาย่อตัว)

คุณสามารถเลือกวิเคราะห์กลยุทธ์ย่อยได้มากกว่า 1 กลยุทธ์พร้อมกัน (ส่งกลับเป็นลิสต์ใน selected_strategies) หากมีโอกาสเทรดหลายแนวทาง เช่น จังหวะนี้มองได้ทั้ง BREAKOUT และ TREND_PULLBACK
ตอบกลับในรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "selected_strategies": ["TREND_PULLBACK" | "BREAKOUT" | "MEAN_REVERSION" | "LIQUIDITY_SWEEP" | "MOMENTUM_CONTINUATION", ...], // เลือกได้ 1 ถึง 3 กลยุทธ์
  "reason": "อธิบายสั้นๆ ทำไมกลยุทธ์เหล่านี้จึงเหมาะสมที่สุด"
}}"""

        selector_user = f"""ราคาปัจจุบัน: {current_price:.2f}
สภาวะตลาดหลัก (Market Regime): {json.dumps(regime_report, indent=2)}
ประวัติแท่งเทียน M5 ล่าสุด:
{self._format_candles_brief(df_5m_pa, 50)}

จงวิเคราะห์และระบุลิสต์กลยุทธ์สเกลปิ้งที่เหมาะสมเพื่อส่งไปวิเคราะห์เชิงลึก:"""

        logging.info("Scalping Selector: กำลังวิเคราะห์เลือกกลยุทธ์สเกลปิ้งย่อย...")
        strategy_decision = self._call_llm(self.management_model, [
            {"role": "system", "content": selector_system},
            {"role": "user", "content": selector_user}
        ], json_response=True, category="management")
        
        selected_strats = strategy_decision.get("selected_strategies", ["TREND_PULLBACK"])
        if not isinstance(selected_strats, list) or len(selected_strats) == 0:
            selected_strats = [strategy_decision.get("selected_strategy", "TREND_PULLBACK")]
            
        strat_reason = strategy_decision.get("reason", "Default strategy selection")
        logging.info(f"🎯 Scalping Strategies ที่เลือกวิเคราะห์: {', '.join(selected_strats)} ({strat_reason})")
        
        # กรองเฉพาะกลยุทธ์ที่บอทกำหนดให้ต้องวิเคราะห์ในรอบนี้
        if strats_to_analyze is None:
            strats_to_analyze = ["TREND_PULLBACK", "BREAKOUT", "MEAN_REVERSION", "LIQUIDITY_SWEEP", "MOMENTUM_CONTINUATION"]
            
        active_strats = [s for s in selected_strats if s in strats_to_analyze]
        
        # เพิ่มกลยุทธ์ใดๆ ที่มี pending order ค้างอยู่และระบบขอให้สแกน (เพื่อจัดการ ลบ/แก้ไข)
        if pending_orders:
            for s_name, p_list in pending_orders.items():
                if p_list and s_name in strats_to_analyze and s_name not in active_strats:
                    active_strats.append(s_name)
                    
        if not active_strats:
            logging.info("⚡ ไม่มีกลยุทธ์ย่อยของ Scalping ใดที่พร้อมหรือต้องทำการประมวลผลวิเคราะห์ในลูปนี้")
            return {}
            
        # --- ขั้นตอนที่ 2: เรียกใช้ Micro Trend Analyst (ข้อมูลอิงร่วม) ---
        trend_system = f"""คุณคือ Micro Trend Analyst ทำหน้าที่ประเมินความเอียงของเทรนสั้นของ {symbol}
วิเคราะห์กราฟแท่งเทียน M15/M30 เพื่อหาทิศทางของค่าเฉลี่ย EMA 50/200 และความชัน (Slope)
ส่งรายงานสรุปสั้นๆ (ไม่เกิน 3 บรรทัด) ว่าทิศทางใดได้เปรียบ: BUY ONLY, SELL ONLY หรือ HOLD"""
        
        trend_user = f"""ราคาปัจจุบัน: {current_price:.2f}
ประวัติแท่งเทียน M15 ย้อนหลัง:
{self._format_candles_brief(df_15m_pa, 30)}
กรุณาวิเคราะห์แนวโน้มสั้น:"""
        
        logging.info("Scalping Sub-agent 1: เรียกใช้ Micro Trend Analyst...")
        trend_report = self._call_llm(self.management_model, [
            {"role": "system", "content": trend_system},
            {"role": "user", "content": trend_user}
        ], json_response=False, category="management")
        
        # --- ขั้นตอนที่ 3: วิเคราะห์ทีละกลยุทธ์อิสระ (Strategy-by-Strategy Analysts) ---
        decisions_dict = {}
        
        for strat in active_strats:
            if strat == "TREND_PULLBACK":
                agent_name = "Trend Pullback Agent"
                agent_system = f"""คุณคือ Trend Pullback Agent ของ {symbol}
หน้าที่ของคุณคือจับจังหวะราคย่อตัวมาทดสอบเส้น EMA 50/200 ในกรอบ M5/M15/M30
ตรวจสอบสัญญาณ Rejection หรือดึงกลับฝั่งเดียวกันกับแนวโน้มหลัก
ส่งรายงาน (ไม่เกิน 3 บรรทัด) แนะนำราคาจุดตั้ง Limit Order ที่ได้เปรียบ และระดับ SL ใต้เส้น EMA หรือใต้สวิงโลว์หลัก"""
            elif strat == "BREAKOUT":
                agent_name = "Breakout Agent"
                agent_system = f"""คุณคือ Breakout Agent ของ {symbol}
หน้าที่ของคุณคือตรวจจับราคาปิดหลุดขอบเขต Swing High/Low ในอดีตของกรอบ M5/M15 พร้อมกับการขยายตัวของความผันผวน
ส่งรายงาน (ไม่เกิน 3 บรรทัด) แนะนำราคาจุดตั้ง Stop Order เมื่อราคาเบรคทะลุ และระดับ SL บริเวณกึ่งกลางกรอบสวิงหรือระดับราคาเบรคเอาต์เดิม"""
            elif strat == "MEAN_REVERSION":
                agent_name = "Mean Reversion Agent"
                agent_system = f"""คุณคือ Mean Reversion Agent ของ {symbol}
หน้าที่ของคุณคือตรวจสอบหาราคาที่เหยียดตัวออกจากเส้นค่าเฉลี่ย EMA 200 มากเกินไปในกรอบ M5/M15 ร่วมกับสัญญาณแท่งเทียนกลับตัวฝั่งตรงข้าม
ส่งรายงาน (ไม่เกิน 3 บรรทัด) ชี้ราคาจุดตั้ง Limit Order สวนกลับ และจุด SL เหนือปลายไส้เทียนของแท่งกลับตัวล่าสุด"""
            elif strat == "LIQUIDITY_SWEEP":
                agent_name = "Liquidity Sweep Agent"
                agent_system = f"""คุณคือ Liquidity Sweep Agent ของ {symbol}
หน้าที่ของคุณคือเฝ้าระวังจังหวะที่ราคากวาดผ่านแนวต้าน/รับสวิงหลัก (Stop Hunt) แล้วดึงกลับมาปิดในกรอบเดิมทิ้งไส้เทียนยาว Rejection wick
ส่งรายงาน (ไม่เกิน 3 บรรทัด) แนะนำราคาจุดตั้ง Limit Order ดักกลับหัวหลังจากการกวาดสภาพคล่อง และ SL เหนือ/ใต้ปลายไส้เทียนที่กวาดไป"""
            else: # MOMENTUM_CONTINUATION
                agent_name = "Momentum Continuation Agent"
                agent_system = f"""คุณคือ Momentum Continuation Agent ของ {symbol}
หน้าที่ของคุณคือวิเคราะห์ความลาดชันและการเรียงตัวของเนื้อแท่งเทียนปิดเต็ม (Marubozu) ที่ไร้การย่อตัว เพื่อเกาะแนวราคาตามกระแสเงินไหล
ส่งรายงาน (ไม่เกิน 3 บรรทัด) แนะนำราคาจุดตั้ง Pending Order ตามน้ำทันที และระดับ SL ที่ปลายฐานแท่งเทียนล่าสุด"""

            agent_user = f"""ราคาปัจจุบัน: {current_price:.2f}
แท่งเทียน M5 ล่าสุด:
{self._format_candles_brief(df_5m_pa, 50)}
แท่งเทียน M1 ล่าสุด:
{self._format_candles_brief(df_1m_pa, 30)}
กรุณาวิเคราะห์พฤติกรรมราคาสำหรับ {agent_name} ตามกลยุทธ์ {strat}:"""
            
            logging.info(f"Scalping Sub-agent 2: เรียกใช้ {agent_name}...")
            report = self._call_llm(model, [
                {"role": "system", "content": agent_system},
                {"role": "user", "content": agent_user}
            ], json_response=False, category="analysis")
            
            # --- ขั้นตอนที่ 4: รันบอท CIO ตัดสินใจวิเคราะห์หาผลสรุปของกลยุทธ์ย่อยตัวนี้ (เดี่ยวๆ) ---
            cio_system = f"""คุณคือ Scalp Master / CIO Consensus ของกองทุนเทรดสั้น
หน้าที่ของคุณคือประเมินแผนการเทรดของกลยุทธ์ย่อย {strat} และสังเคราะห์การตัดสินใจจัดการพอร์ตและคำสั่งซื้อขายแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD" | "MODIFY" | "CANCEL" | "CANCEL_AND_NEW",
  "ticket": int_หรือ_string_หรือ_null, // ใส่ Ticket ID ของคำสั่งล่วงหน้า (Pending Order) ที่ต้องการจัดการ (หากไม่มีให้ใส่ null)
  "hold_minutes": 5 | 10 | 15 | 30, // ในโหมด Scalping หากตอบ HOLD หรือข้ามรอบ ให้เลือกเวลาพักวิเคราะห์ 5, 10, 15 หรือ 30 นาที
  "lot": float,
  "entry": float_หรือ_null, // เพื่อป้องกันการได้จุดเข้าตลาดที่แย่ (Bad entry):
                            // ให้กำหนดระดับตั้ง Pending Order (Limit/Stop) ที่เหมาะสม
                            // เช่น หากวางช้อนซื้อแนวรับของ Pullback/Reversion ให้ใช้แบบ Limit (BUY ต่ำกว่าตลาด)
                            // หากวางดักทะลุกรอบเบรคเอาต์ ให้ใช้แบบ Stop (BUY สูงกว่าตลาด)
                            // ระบุราคาดังกล่าวลงในช่อง entry (หรือระบุ null หากต้องการใช้ Market Price ซึ่งไม่แนะนำ)
  "sl": float_หรือ_null,
  "tp": float_หรือ_null,
  "reasoning": "ประโยคอธิบายสั้นๆ เกี่ยวกับการตัดสินใจ"
}}

กติกา:
1. ปฏิบัติตามมติของ Market Regime เสมอ (Regime ปัจจุบัน: {regime_report.get('regime') if regime_report else 'Uncertain'})
2. หากมีคำสั่งล่วงหน้า (Pending Order) เปิดค้างอยู่ของกลยุทธ์นี้ (ข้อมูลด้านล่าง) คุณสามารถเลือก action เป็น HOLD, MODIFY, CANCEL, CANCEL_AND_NEW
3. ล็อตสูงสุดจำกัดที่ {max_allowed_lot} ล็อตที่คำนวณมาตามความเสี่ยง 1% คือ {final_lot}
4. ระยะ TP แนะนำห่าง 1.5 - 2 เท่าของระยะ SL แนะนำ (SL แนะนำห่างประมาณ: {sl_distance_usd:.2f} USD)"""

            sub_pendings = pending_orders.get(strat, []) if pending_orders else []
            pending_str = json.dumps(sub_pendings, indent=2) if sub_pendings else "ไม่มีคำสั่งล่วงหน้าของกลยุทธ์นี้ค้างอยู่"
            
            cio_user = f"""สถิติบัญชี: บาลานซ์ ${balance:.2f} USD | ราคา {symbol}: {current_price:.2f}
รายงานสภาวะตลาดส่วนกลาง: {json.dumps(regime_report, indent=2)}
รายงานคำสั่งล่วงหน้า (Pending Orders) ของกลยุทธ์ {strat} ที่ยังไม่ทำงาน:
{pending_str}

รายงานสรุปแนวโน้ม Micro Trend Analyst: {trend_report}
รายงานวิเคราะห์จาก {agent_name}: {report}
{reflection_context}

จงตอบสรุปผลการเทรดแบบ Scalping (กลยุทธ์ {strat}) ในรูปแบบ JSON:"""

            logging.info(f"Scalping CIO ({strat}): สรุปผลลัพธ์มติการเทรด...")
            proposal = self._call_llm(model, [
                {"role": "system", "content": cio_system},
                {"role": "user", "content": cio_user}
            ], json_response=True, category="analysis")
            
            decisions_dict[strat] = proposal
            
        return decisions_dict
    def analyze_daytrading(self, df_15m, df_1h, df_4h, balance, symbol="XAUUSD", leverage=100.0, spread=0.0, performance_stats=None, trade_history=None, regime_report=None, pending_orders=None):
        """
        2) Day Trading Agent: Intraday trading, holds positions only within the day
        """
        model = self.analysis_model
        
        df_15m_pa = self._analyze_price_action(df_15m)
        df_1h_pa = self._analyze_price_action(df_1h)
        df_4h_pa = self._analyze_price_action(df_4h)
        
        current_price = float(df_15m_pa['close'].iloc[-1])
        atr_1h = float(df_1h_pa['atr_14'].iloc[-1])
        
        # Risk Manager calculations (Day Trade SL is typically 1.5 * ATR 1h to avoid intraday noise)
        sl_distance_usd = max(1.5 * atr_1h, 3.0 if "XAU" in symbol.upper() else 30.0)
        contract_size = 100.0 if "XAU" in symbol.upper() else 1.0
        risk_amount_usd = balance * 0.01
        calculated_lot = risk_amount_usd / (sl_distance_usd * contract_size)
        calculated_lot = round(max(0.01, calculated_lot), 2)
        max_allowed_lot = getattr(self, 'max_lot', 0.05)
        final_lot = min(calculated_lot, max_allowed_lot)
        
        reflection_context = self._format_reflection(performance_stats, trade_history)
        
        # Sub-agent 1: Intraday Trend Analyst
        trend_system = f"""คุณคือ Intraday Trend Analyst ทำหน้าที่ตรวจสอบกรอบราคา H1 และ H4 ของ {symbol}
หาแนวรับต้านหลักระดับวัน ค้นหาเส้นเฉลี่ย VWAP หรือ EMA และระบุทิศทางภาพใหญ่ในการเทรดระหว่างวัน
ส่งรายงานสรุปสั้นๆ (ไม่เกิน 3 บรรทัด) ว่าทิศทางใดได้เปรียบ: BULLISH, BEARISH หรือ RANGE-BOUND"""
        
        trend_user = f"""ราคาปัจจุบัน: {current_price:.2f}
ประวัติแท่ง H1 ย้อนหลัง:
{self._format_candles_brief(df_1h_pa, 48)}
ประวัติแท่ง H4 ย้อนหลัง:
{self._format_candles_brief(df_4h_pa, 12)}
กรุณาวิเคราะห์สภาวะแนวโน้มรายวัน:"""
        
        logging.info("Day Trading Sub-agent 1: เรียกใช้ Intraday Trend Analyst...")
        trend_report = self._call_llm(self.management_model, [
            {"role": "system", "content": trend_system},
            {"role": "user", "content": trend_user}
        ], json_response=False, category="management")
        
        # Sub-agent 2: Range Guard
        range_system = f"""คุณคือ Range Guard หน้าที่ของคุณคือตรวจสอบกรอบการสวิงของราคาวันนี้
คำนวณ Daily Range, Opening Range (M15), หาแนวรับต้านย่อย และประเมินจุด Overbought/Oversold ในการดีดตัวกลับ
ส่งรายงาน (ไม่เกิน 3 บรรทัด) แนะนำว่าราคาใกล้จุดตึงตัวหรือพร้อมกลับตัว (Mean Reversion) หรือทะลุกรอบแรง (Breakout)"""
        
        range_user = f"""ราคาปัจจุบัน: {current_price:.2f}
แท่ง M15 ล่าสุด:
{self._format_candles_brief(df_15m_pa, 30)}
ความผันผวนระดับ H1 (ATR): {atr_1h:.2f}
กรุณาวิเคราะห์กรอบสวิง:"""
        
        logging.info("Day Trading Sub-agent 2: เรียกใช้ Range Guard...")
        range_report = self._call_llm(model, [
            {"role": "system", "content": range_system},
            {"role": "user", "content": range_user}
        ], json_response=False, category="analysis")
        
        # CIO Day Trade Master
        cio_system = f"""คุณคือ Day Trade Master / CIO Consensus ของกองทุนเทรดรายวัน
หน้าที่ของคุณคือรับรายงานและสถิติด้านล่าง สังเคราะห์การตัดสินใจจัดการพอร์ตและคำสั่งซื้อขายแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD" | "MODIFY" | "CANCEL" | "CANCEL_AND_NEW",
  "ticket": int_หรือ_string_หรือ_null, // ใส่ Ticket ID ของคำสั่งล่วงหน้า (Pending Order) ที่ต้องการจัดการ (หากไม่มีให้ใส่ null)
  "hold_minutes": 30 | 60 | 240, // หากตอบ HOLD หรือข้ามรอบ ให้เลือกเวลาหน่วงพักวิเคราะห์รอบต่อไป
  "lot": float,
  "entry": float_หรือ_null, // หากต้องการตั้ง Pending Order ให้ระบุราคาที่ห่างจากราคาปัจจุบัน หรือระบุ null หากต้องการใช้ Market Price ทันที
  "sl": float_หรือ_null,
  "tp": float_หรือ_null,
  "reasoning": "ประโยคสรุปเหตุผลการตัดสินใจและการเข้าเทรดสไตล์ Day Trade"
}}

กติกา:
1. ปฏิบัติตามมติของ Market Regime เสมอ (Regime ปัจจุบัน: {regime_report.get('regime') if regime_report else 'Uncertain'})
2. หากมีคำสั่งล่วงหน้า (Pending Order) เปิดค้างอยู่ (ข้อมูลด้านล่าง) คุณสามารถเลือก action เป็น:
   - "HOLD": ถือคำสั่งล่วงหน้านี้ต่อตามเดิม
   - "MODIFY": แก้ไขราคาเข้า (entry), SL หรือ TP ของตั๋วใบนี้ (ระบุเลข ticket ให้ถูกต้อง)
   - "CANCEL": ยกเลิกคำสั่งล่วงหน้านี้ออกไปก่อนชั่วคราว
   - "CANCEL_AND_NEW": ยกเลิกคำสั่งเดิมแล้วต้องการยื่นตั้งคำสั่งล่วงหน้าอันใหม่ทันที
3. ล็อตสูงสุดจำกัดที่ {max_allowed_lot} ล็อตที่คำนวณตามความเสี่ยง 1% คือ {final_lot}
4. ระยะ TP แนะนำห่าง 1.5 - 2 เท่าของระยะ SL แนะนำ (SL แนะนำรายวันห่างประมาณ: {sl_distance_usd:.2f} USD)
5. ออเดอร์ทั้งหมดต้องไม่ถือครองข้ามคืน"""

        pending_str = json.dumps(pending_orders, indent=2) if pending_orders else "ไม่มีคำสั่งล่วงหน้าค้างอยู่"
        cio_user = f"""สถิติบัญชี: บาลานซ์ ${balance:.2f} USD | ราคา {symbol}: {current_price:.2f}
รายงานสภาวะตลาดส่วนกลาง: {json.dumps(regime_report, indent=2)}
รายงานคำสั่งล่วงหน้า (Pending Orders) ที่ยังไม่ทำงาน:
{pending_str}

รายงาน Intraday Trend Analyst: {trend_report}
รายงาน Range Guard: {range_report}
{reflection_context}

จงตอบสรุปการตัดสินใจในรูปแบบ JSON:"""

        logging.info("Day Trading CIO: สรุปผลลัพธ์มติการเทรดแบบ Day Trading...")
        proposal = self._call_llm(model, [
            {"role": "system", "content": cio_system},
            {"role": "user", "content": cio_user}
        ], json_response=True, category="analysis")
        
        return proposal

    def analyze_swingtrading(self, df_4h, df_1d, df_1w, balance, symbol="XAUUSD", leverage=100.0, spread=0.0, performance_stats=None, trade_history=None, regime_report=None, pending_orders=None):
        """
        3) Swing Trading Agent: Holds positions for days to weeks, capturing large structural moves
        """
        model = self.analysis_model
        
        df_4h_pa = self._analyze_price_action(df_4h)
        df_1d_pa = self._analyze_price_action(df_1d)
        df_1w_pa = self._analyze_price_action(df_1w)
        
        current_price = float(df_4h_pa['close'].iloc[-1])
        atr_1d = float(df_1d_pa['atr_14'].iloc[-1])
        
        # Risk Manager calculations (Swing Trade SL is typically 1.5 * Daily ATR to handle multi-day fluctuations)
        sl_distance_usd = max(1.5 * atr_1d, 8.0 if "XAU" in symbol.upper() else 80.0)
        contract_size = 100.0 if "XAU" in symbol.upper() else 1.0
        risk_amount_usd = balance * 0.01
        calculated_lot = risk_amount_usd / (sl_distance_usd * contract_size)
        calculated_lot = round(max(0.01, calculated_lot), 2)
        max_allowed_lot = getattr(self, 'max_lot', 0.05)
        final_lot = min(calculated_lot, max_allowed_lot)
        
        reflection_context = self._format_reflection(performance_stats, trade_history)
        
        # Sub-agent 1: Macro Structure Analyst
        trend_system = f"""คุณคือ Macro Structure Analyst หน้าที่ของคุณคือตรวจสอบสวิงใหญ่ระดับ D1 และ W1 ของ {symbol}
ค้นหาแนวรับต้านหนาเชิงพฤติกรรมหลัก (Major S/R) และระบุโครงสร้าง Market Structure (Higher Highs / Higher Lows)
ส่งรายงานสรุปสั้นๆ (ไม่เกิน 3 บรรทัด) ชี้ระดับแนวยุทธศาสตร์และแนวโน้มหลักระดับสัปดาห์"""
        
        trend_user = f"""ราคาปัจจุบัน: {current_price:.2f}
ประวัติแท่ง D1 ย้อนหลัง:
{self._format_candles_brief(df_1d_pa, 30)}
ประวัติแท่ง W1 ย้อนหลัง:
{self._format_candles_brief(df_1w_pa, 4)}
กรุณาวิเคราะห์แนวโน้มสวิงใหญ่:"""
        
        logging.info("Swing Trading Sub-agent 1: เรียกใช้ Macro Structure Analyst...")
        trend_report = self._call_llm(self.management_model, [
            {"role": "system", "content": trend_system},
            {"role": "user", "content": trend_user}
        ], json_response=False, category="management")
        
        # Sub-agent 2: Fundamental Catalyst Guard
        fundamental_system = f"""คุณคือ Fundamental Catalyst Guard ทำหน้าที่วิเคราะห์ข่าวใหญ่ระดับมหภาคและดอกเบี้ยนโยบาย
วิเคราะห์ความเสี่ยงข้ามสัปดาห์ เช่น Gap Risk, ค่า Swap (Carry cost), ปัจจัยนโยคารธนาคารกลางที่จะเกิดขึ้นในระยะยาว
ส่งรายงานแจ้งเตือน (ไม่เกิน 3 บรรทัด) เรื่องความเสี่ยงและฝั่งทิศทางที่มีแต้มต่อเชิงปัจจัยพื้นฐานร่วมกับเทรนยาว"""
        
        fundamental_user = f"""ราคาปัจจุบัน: {current_price:.2f}
แท่ง H4 ล่าสุด:
{self._format_candles_brief(df_4h_pa, 48)}
กรุณาวิเคราะห์สภาวะเชิงปัจจัยพื้นฐานและความเสี่ยงยาว:"""
        
        logging.info("Swing Trading Sub-agent 2: เรียกใช้ Fundamental Catalyst Guard...")
        fundamental_report = self._call_llm(model, [
            {"role": "system", "content": fundamental_system},
            {"role": "user", "content": fundamental_user}
        ], json_response=False, category="analysis")
        
        # CIO Swing Master
        cio_system = f"""คุณคือ Swing Master / CIO Consensus ของกองทุนเทรดสวิงระยะยาว
หน้าที่ของคุณคือรับรายงานและสถิติด้านล่าง สังเคราะห์การตัดสินใจจัดการพอร์ตและคำสั่งซื้อขายแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD" | "MODIFY" | "CANCEL" | "CANCEL_AND_NEW",
  "ticket": int_หรือ_string_หรือ_null, // ใส่ Ticket ID ของคำสั่งล่วงหน้า (Pending Order) ที่ต้องการจัดการ (หากไม่มีให้ใส่ null)
  "hold_minutes": 240 | 480 | 720, // ในโหมด Swing Trading หากตอบ HOLD ให้เลือกพักวิเคราะห์ 240 (4 ชม.), 480 (8 ชม.) หรือ 720 (12 ชม.) นาที
  "lot": float,
  "entry": float_หรือ_null, // หากต้องการตั้ง Pending Order ให้ระบุราคาที่ห่างจากราคาปัจจุบัน หรือระบุ null หากต้องการใช้ Market Price ทันที
  "sl": float_หรือ_null,
  "tp": float_หรือ_null,
  "reasoning": "ประโยคสรุปแผนการเทรดสวิงระยะยาวร่วมกับแนวคิดกลยุทธ์"
}}

กติกา:
1. ปฏิบัติตามมติของ Market Regime เสมอ (Regime ปัจจุบัน: {regime_report.get('regime') if regime_report else 'Uncertain'})
2. หากมีคำสั่งล่วงหน้า (Pending Order) เปิดค้างอยู่ (ข้อมูลด้านล่าง) คุณสามารถเลือก action เป็น:
   - "HOLD": ถือคำสั่งล่วงหน้านี้ต่อตามเดิม
   - "MODIFY": แก้ไขราคาเข้า (entry), SL หรือ TP ของตั๋วใบนี้ (ระบุเลข ticket ให้ถูกต้อง)
   - "CANCEL": ยกเลิกคำสั่งล่วงหน้านี้ออกไปก่อนชั่วคราว
   - "CANCEL_AND_NEW": ยกเลิกคำสั่งเดิมแล้วต้องการยื่นตั้งคำสั่งล่วงหน้าอันใหม่ทันที
3. ล็อตสูงสุดจำกัดที่ {max_allowed_lot} ล็อตที่คำนวณตามความเสี่ยง 1% คือ {final_lot}
4. ระยะ TP แนะนำห่าง 1.5 - 2 เท่าของระยะ SL แนะนำ (SL แนะนำสัปดาห์ห่างประมาณ: {sl_distance_usd:.2f} USD)
5. ยินดีถือออเดอร์ข้ามคืนได้หากสอดคล้องความเสี่ยงและแนวโน้มเชิงมหภาค"""

        pending_str = json.dumps(pending_orders, indent=2) if pending_orders else "ไม่มีคำสั่งล่วงหน้าค้างอยู่"
        cio_user = f"""สถิติบัญชี: บาลานซ์ ${balance:.2f} USD | ราคา {symbol}: {current_price:.2f}
รายงานสภาวะตลาดส่วนกลาง: {json.dumps(regime_report, indent=2)}
รายงานคำสั่งล่วงหน้า (Pending Orders) ที่ยังไม่ทำงาน:
{pending_str}

รายงาน Macro Structure Analyst: {trend_report}
รายงาน Fundamental Catalyst Guard: {fundamental_report}
{reflection_context}

จงตอบสรุปการตัดสินใจในรูปแบบ JSON:"""

        logging.info("Swing Trading CIO: สรุปผลลัพธ์มติการเทรดแบบ Swing Trading...")
        proposal = self._call_llm(model, [
            {"role": "system", "content": cio_system},
            {"role": "user", "content": cio_user}
        ], json_response=True, category="analysis")
        
        final_decision = self.review_order(proposal, regime_report, trend_report, fundamental_report, symbol)
        return final_decision
