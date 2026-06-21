import requests
import json
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TradingAgents:
    """
    ระบบตัวแทนอัจฉริยะ (Multi-Agent Trading System)
    ทำหน้าที่วิเคราะห์กราฟและบริหารความเสี่ยงด้วยโมเดลภาษาผ่าน MaxPlus AI API
    """
    def __init__(self, api_key, base_url="https://api.maxplus-ai.cc/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
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
                    response = requests.post(url, headers=headers, json=payload, timeout=30)
                    
                    if response.status_code in [429, 500, 502, 503, 504]:
                        logging.warning(f"เรียกใช้ LLM ({current_model}) ล้มเหลวด้วยรหัส HTTP {response.status_code}. กำลังลองใหม่รอบที่ {attempt + 1}/{max_retries}...")
                        time.sleep(backoff_factor ** attempt)
                        continue
                        
                    response.raise_for_status()
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

    def analyze_market(self, market_data_str, balance, symbol="XAUUSD", leverage=100.0):
        """
        Agent ตัวที่ 1: Analyst Agent (วิเคราะห์ตลาดและเสนอแผนเข้าออเดอร์)
        - model: sonnet-4-5 (หรือ gpt-5.5)
        """
        model = "sonnet-4-5" 
        
        system_prompt = f"""คุณคือ AI Technical Analyst & Risk Manager ผู้เชี่ยวชาญการเทรด {symbol} ด้วยกลยุทธ์ Multi-Timeframe Analysis
หน้าที่ของคุณคือวิเคราะห์โครงสร้างตลาดและทิศทางราคาจากหลายกรอบเวลา (1h, 15m, 5m) เพื่อหาจุดเข้าเปิดสัญญาที่ได้เปรียบสูงและมีระดับความเสี่ยงต่ำ

หลักการเทรดแบบ Multi-Timeframe ที่คุณต้องปฏิบัติตามอย่างเคร่งครัด:
1. เทรดตามแนวโน้มกรอบใหญ่ (Trend Filter 1h): มองหาโอกาสเปิด BUY เฉพาะเมื่อเทรนด์ 1h เป็นขาขึ้น และมองหาโอกาสเปิด SELL เฉพาะเมื่อเทรนด์ 1h เป็นขาลง ยกเว้นมีสัญญาณกลับตัวรุนแรงที่บริเวณแนวรับแนวต้านหลัก
2. วิเคราะห์กรอบเวลากลาง (15m) สำหรับช่วงราคาและระดับ SL: ใช้ค่า ATR (Average True Range) ในกราฟ 15m เพื่อกำหนดความกว้างของ Stop Loss (SL) แนะนำให้ SL ห่างจากจุดเข้าประมาณ 1.5 - 2 เท่าของ ATR เพื่อไม่ให้โดนชนง่ายเกินไป
3. วิเคราะห์โมเมนตัมกรอบเล็ก (5m) เพื่อยืนยันและ Timing จุดเข้า: ใช้โครงสร้างราคาใน 5m เป็นจุดยืนยันว่าราคาเริ่มกลับตัวหรือวิ่งไปในทางเดียวกันแล้ว (เช่น ถ้ารายการ 1h และ 15m เป็นขาขึ้น รอให้ 5m เป็นขาขึ้นร่วมด้วยแล้วจึงยิง BUY)
4. ปรับราคารอเข้า (Entry Price): หากต้องการจุดเข้าที่ได้เปรียบกว่า สามารถกำหนดราคา Limit Pending Order หรือหากราคาปัจจุบันน่าสนใจ สามารถยิงเป็น Market Order ได้ (โดยกำหนด entry ให้ใกล้เคียงราคาล่าสุด)

กฎเหล็กด้านการเงิน (Risk Rules):
- บัญชีของคุณมียอดบาลานซ์คงเหลือปัจจุบัน: ${balance:.2f} USD
- เลิฟเวอเรจบัญชี: 1:{leverage}
- หากยอดเงินคงเหลือต่ำกว่า $100 ห้ามใช้ล็อตเกิน 0.01 Lot เด็ดขาด (ห้ามตอบค่าล็อตอื่น)!
- ระยะ Stop Loss ต้องมีความสมเหตุสมผลเชิงเทคนิคและมีความปลอดภัย ไม่กว้างจนมาร์จิ้นไม่พอ

คุณต้องวิเคราะห์ข้อมูลและตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "lot": 0.01,
  "entry": float,
  "sl": float,
  "tp": float,
  "reasoning": "อธิบายเหตุผลเชิงเทคนิคที่สอดคล้องกับแนวคิดกรอบเวลาใหญ่และย่อยสั้นๆ (ในประโยคเดียว)"
}}

*หมายเหตุ: หากเลือก "action": "HOLD" (ยังไม่มีสัญญาณเทรด) ให้ตั้งค่า lot, entry, sl, tp เป็น null หรือ 0.0*"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"วิเคราะห์ข้อมูลตลาด {symbol} ล่าสุดด้านล่างนี้:\n{market_data_str}"}
        ]
        
        logging.info(f"ส่งข้อมูลให้ Analyst Agent วิเคราะห์โอกาสเข้าเทรด {symbol}...")
        return self._call_llm(model, messages, json_response=True, fallbacks=["gpt-5.5", "haiku"])

    def manage_position(self, position_details, current_price, balance, symbol="XAUUSD"):
        """
        Agent ตัวที่ 2: Manager Agent (วิเคราะห์และควบคุมความเสี่ยงของออเดอร์ที่ค้างอยู่)
        - model: haiku (หรือ gpt-5.4-mini) เพื่อความรวดเร็วและประหยัด
        """
        model = "haiku"
        
        system_prompt = f"""คุณคือ Risk Manager หน้าที่ของคุณคือควบคุมความเสี่ยงของออเดอร์ {symbol} ที่เปิดอยู่
วิเคราะห์ระดับราคาปัจจุบันเทียบกับออเดอร์ที่คุณถืออยู่ เพื่อตัดสินใจว่าจะทำอย่างไรกับออเดอร์นี้

ทางเลือกการตัดสินใจของคุณ:
- "HOLD": ถือออเดอร์ต่อไปตามแผนเดิม
- "BREAK_EVEN": เลื่อนจุด Stop Loss (SL) มาตั้งไว้ที่ราคาเปิด (Entry Price) ของออเดอร์ เพื่อให้ไม่มีความเสี่ยงขาดทุนอีกต่อไป (ใช้เมื่อราคาวิ่งถูกทางไปพอสมควรแล้ว)
- "TRAILING_STOP": เลื่อนจุด Stop Loss ตามราคาปัจจุบันเพื่อล็อคกำไรที่วิ่งถูกทาง
- "CLOSE": ปิดออเดอร์ทันทีที่ราคาตลาดปัจจุบัน เพื่อล็อคกำไรหรือเพื่อตัดขาดทุนก่อนชน SL หากประเมินว่าเทรนด์ได้เปลี่ยนไปแล้ว

คุณต้องตอบกลับเป็นรูปแบบ JSON โครงสร้างนี้เท่านั้น:
{{
  "action": "HOLD" | "BREAK_EVEN" | "TRAILING_STOP" | "CLOSE",
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
        
        logging.info(f"ส่งสถานะออเดอร์ {position_details['id']} ให้ Manager Agent จัดการ {symbol}...")
        return self._call_llm(model, messages, json_response=True, fallbacks=["gpt-5.4-mini", "sonnet-4-5"])
