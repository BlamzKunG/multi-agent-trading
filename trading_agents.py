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
    def __init__(self, api_key, base_url="https://api.maxplus-ai.cc/v1", analysis_model="claude-sonnet-5", management_model="claude-sonnet-4-6"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.analysis_model = analysis_model
        self.management_model = management_model
        
    def _call_llm(self, model, messages, json_response=True, fallbacks=None):
        """ส่งคำขอไปยัง MaxPlus AI API พร้อมรองรับทั้ง Anthropic Protocol และ OpenAI Protocol อัตโนมัติ"""
        if fallbacks is None:
            fallbacks = []
            
        models_to_try = [model] + fallbacks
        
        for idx, current_model in enumerate(models_to_try):
            # ตรวจสอบชื่อแบรนด์โมเดล (รวมคำคีย์เวิร์ดของ Claude: claude, haiku, sonnet, opus)
            is_claude = any(keyword in current_model.lower() for keyword in ["claude", "haiku", "sonnet", "opus"])
            
            if is_claude:
                # 📌 ใช้ Anthropic Messages API (/v1/messages)
                url = f"{self.base_url}/messages"
                headers = {
                    **self.headers,
                    "anthropic-version": "2023-06-01"
                }
                
                # แยก System Prompt ออกตามมาตรฐานของ Anthropic
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
                    "max_tokens": 4096  # จำเป็นสำหรับ Anthropic
                }
                if system_text:
                    payload["system"] = system_text
            else:
                # 📌 ใช้ OpenAI Chat Completions API (/v1/chat/completions)
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
                    
                    if json_response:
                        try:
                            return json.loads(content)
                        except Exception as json_err:
                            # ป้องกันกรณี LLM ตอบกลับมาเป็น markdown code block ครอบ JSON
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
            
            # ถ้าโมเดลหลักขัดข้อง และยังมีโมเดลสำรองในลิสต์ ให้สลับไปใช้
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
        ], json_response=False, fallbacks=self._get_fallbacks(trend_model))
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
        ], json_response=False, fallbacks=self._get_fallbacks(pa_model))
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
        
        # เลือก fallback อัตโนมัติตามพูลโมเดลเพื่อป้องกันข้อผิดพลาด 409 (ข้ามพูล)
        fallbacks = self._get_fallbacks(cio_model)
            
        final_decision = self._call_llm(cio_model, [
            {"role": "system", "content": cio_system},
            {"role": "user", "content": cio_user}
        ], json_response=True, fallbacks=fallbacks)
        
        logging.info(f"มติการตัดสินใจสุดท้ายของ Scalp Master: {final_decision}")
        return final_decision

    def manage_position(self, position_details, current_price, balance, symbol="XAUUSD"):
        """
        Agent ตัวที่ 2: Manager Agent (วิเคราะห์และควบคุมความเสี่ยงของออเดอร์ที่ค้างอยู่)
        """
        model = self.management_model
        
        # เลือก fallback อัตโนมัติตามพูลโมเดลเพื่อป้องกันข้อผิดพลาด 409 (ข้ามพูล)
        fallbacks = self._get_fallbacks(model)
        
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
        return self._call_llm(model, messages, json_response=True, fallbacks=fallbacks)
