import requests
import json
import logging

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
        
    def _call_llm(self, model, messages, json_response=True):
        """ส่งคำขอไปยัง MaxPlus AI API"""
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2  # ใช้ temp ต่ำเพื่อลดความเพ้อเจ้อ (Hallucinations)
        }
        
        # หากระบบปลายทางรองรับและบังคับใช้ JSON
        if json_response:
            payload["response_format"] = {"type": "json_object"}
            
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            if json_response:
                return json.loads(content)
            return content
            
        except Exception as e:
            logging.error(f"เกิดข้อผิดพลาดในการเรียกใช้ LLM ({model}): {e}")
            return None

    def analyze_market(self, market_data_str, balance, symbol="XAUUSD", leverage=100.0):
        """
        Agent ตัวที่ 1: Analyst Agent (วิเคราะห์ตลาดและเสนอแผนเข้าออเดอร์)
        - model: claude-sonnet-4-6 (หรือใช้ gpt-5.5 ตามต้องการ)
        """
        # ตั้งค่าโมเดลวิเคราะห์
        model = "claude-sonnet-4-6" 
        
        system_prompt = f"""คุณคือ AI Technical Analyst & Risk Manager ผู้เชี่ยวชาญการเทรด {symbol}
หน้าที่ของคุณคือวิเคราะห์ข้อมูลตลาดล่าสุด และเสนอการเปิดออเดอร์ที่มีความเสี่ยงต่ำ

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
  "reasoning": "อธิบายเหตุผลเชิงเทคนิคสั้นๆ (ในประโยคเดียว)"
}}

*หมายเหตุ: หากเลือก "action": "HOLD" (ยังไม่มีสัญญาณเทรด) ให้ตั้งค่า lot, entry, sl, tp เป็น null หรือ 0.0*"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"วิเคราะห์ข้อมูลตลาด {symbol} ล่าสุดด้านล่างนี้:\n{market_data_str}"}
        ]
        
        logging.info(f"ส่งข้อมูลให้ Analyst Agent วิเคราะห์โอกาสเข้าเทรด {symbol}...")
        return self._call_llm(model, messages, json_response=True)

    def manage_position(self, position_details, current_price, balance, symbol="XAUUSD"):
        """
        Agent ตัวที่ 2: Manager Agent (วิเคราะห์และควบคุมความเสี่ยงของออเดอร์ที่ค้างอยู่)
        - model: claude-haiku-4-5 (หรือใช้ gpt-5.4-mini) เพื่อความรวดเร็วและประหยัด
        """
        # ตั้งค่าโมเดลสปีดเร็ว
        model = "claude-haiku-4-5"
        
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
        return self._call_llm(model, messages, json_response=True)
