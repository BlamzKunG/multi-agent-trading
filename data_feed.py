import requests
import pandas as pd
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GoldDataFeed:
    """
    คลาสสำหรับดึงข้อมูลราคา XAUUSD (อ้างอิงราคาทองคำ Gold Futures GC=F จาก Yahoo Finance)
    ดึงทั้งราคารีลไทม์ และข้อมูลราคาย้อนหลังเป็น DataFrame เพื่อคำนวณสัญญาณเทคนิคอล
    """
    def __init__(self, symbol="GC=F"):
        self.symbol = symbol
        self.url = f"https://query1.finance.yahoo.com/v8/finance/chart/{self.symbol}"
        # ใช้ User-Agent เพื่อไม่ให้โดนบล็อกจาก Yahoo Finance API
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def get_current_price(self):
        """ดึงราคาปัจจุบันล่าสุดของ XAUUSD"""
        params = {"interval": "1m", "range": "1d"}
        try:
            response = requests.get(self.url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # ดึงราคาตลาดปัจจุบัน (regularMarketPrice)
            meta = data['chart']['result'][0]['meta']
            current_price = meta.get('regularMarketPrice')
            
            if current_price is None:
                # ดึงราคาสุดท้ายจากลิสต์ข้อมูลแท่งเทียน
                indicators = data['chart']['result'][0]['indicators']['quote'][0]
                close_prices = [p for p in indicators['close'] if p is not None]
                if close_prices:
                    current_price = close_prices[-1]
                    
            if current_price:
                return float(current_price)
            else:
                raise ValueError("ไม่พบข้อมูลราคาปัจจุบันใน API response")
                
        except Exception as e:
            logging.error(f"เกิดข้อผิดพลาดในการดึงราคา XAUUSD ปัจจุบัน: {e}")
            return None

    def get_historical_data(self, interval="15m", period="5d"):
        """
        ดึงข้อมูลแท่งเทียนย้อนหลัง
        - interval: กรอบเวลา (เช่น '1m', '5m', '15m', '1h', '1d')
        - period: ช่วงเวลาย้อนหลัง (เช่น '1d', '5d', '1mo', '3mo')
        คืนค่ากลับเป็น pandas DataFrame ที่มีคอลัมน์ [timestamp, open, high, low, close, volume]
        """
        params = {"interval": interval, "range": period}
        try:
            response = requests.get(self.url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            result = data['chart']['result'][0]
            timestamps = result.get('timestamp', [])
            quote = result['indicators']['quote'][0]
            
            # รวมข้อมูลราคา
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(timestamps, unit='s'),
                "open": quote.get('open', []),
                "high": quote.get('high', []),
                "low": quote.get('low', []),
                "close": quote.get('close', []),
                "volume": quote.get('volume', [])
            })
            
            # ลบแถวที่มีค่าว่าง (NaN) ออกเพื่อความถูกต้องในการคำนวณ Indicator
            df = df.dropna().reset_index(drop=True)
            return df
            
        except Exception as e:
            logging.error(f"เกิดข้อผิดพลาดในการดึงข้อมูลย้อนหลัง XAUUSD: {e}")
            return pd.DataFrame()

# ทดสอบดึงข้อมูล
if __name__ == "__main__":
    feed = GoldDataFeed()
    
    # 1. ทดสอบดึงราคาปัจจุบัน
    price = feed.get_current_price()
    print(f"=== ราคาทองคำ XAUUSD (GC=F) ปัจจุบัน ===")
    print(f"ราคา: {price} USD/oz\n")
    
    # 2. ทดสอบดึงแท่งเทียนย้อนหลัง 15 นาที ย้อนหลัง 2 วัน
    print(f"=== ดึงข้อมูลแท่งเทียนย้อนหลัง 15m ===")
    df = feed.get_historical_data(interval="15m", period="2d")
    if not df.empty:
        print(df.tail(5))  # แสดง 5 แถวล่าสุด
        print(f"จำนวนแท่งเทียนที่ได้: {len(df)} แท่ง")
    else:
        print("ไม่สามารถดึงข้อมูลย้อนหลังได้")
