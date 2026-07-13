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

    def analyze_price_action(self, df, swing_window=3):
        """
        วิเคราะห์โครงสร้างพฤติกรรมราคา (Price Action) และหาแนวรับแนวต้านสวิงไฮ/โลว์
        """
        import numpy as np
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
        
        # 3. คำนวณจุด Swing High / Swing Low (แนวรับแนวต้านทางโครงสร้างราคา)
        df['swing_high'] = False
        df['swing_low'] = False
        
        for i in range(swing_window, len(df) - swing_window):
            # Swing High: ราคา High สูงกว่า High รอบข้างฝั่งละ swing_window แท่ง
            val = df.loc[i, 'high']
            is_high = True
            for j in range(1, swing_window + 1):
                if val < df.loc[i - j, 'high'] or val < df.loc[i + j, 'high']:
                    is_high = False
                    break
            if is_high:
                df.loc[i, 'swing_high'] = True
                
            # Swing Low: ราคา Low ต่ำกว่า Low รอบข้างฝั่งละ swing_window แท่ง
            val = df.loc[i, 'low']
            is_low = True
            for j in range(1, swing_window + 1):
                if val > df.loc[i - j, 'low'] or val > df.loc[i + j, 'low']:
                    is_low = False
                    break
            if is_low:
                df.loc[i, 'swing_low'] = True
                
        return df

# ทดสอบดึงข้อมูล
if __name__ == "__main__":
    feed = GoldDataFeed()
    
    # 1. ทดสอบดึงราคาปัจจุบัน
    price = feed.get_current_price()
    print(f"=== ราคาทองคำ XAUUSD (GC=F) ปัจจุบัน ===")
    print(f"ราคา: {price} USD/oz\n")
    
    # 2. ทดสอบดึงแท่งเทียนย้อนหลัง 15 นาที ย้อนหลัง 2 วัน
    print(f"=== ดึงข้อมูลแท่งเทียนย้อนหลัง 15m และทดสอบวิเคราะห์ Price Action ===")
    df = feed.get_historical_data(interval="15m", period="2d")
    if not df.empty:
        df_analyzed = feed.analyze_price_action(df)
        print("--- 5 แถวประวัติวิเคราะห์ล่าสุด ---")
        print(df_analyzed[["timestamp", "close", "candle_type", "body_percent", "swing_high", "swing_low"]].tail(5))
        
        # แสดง Swing High / Low ล่าสุดบางตัว
        swings_high = df_analyzed[df_analyzed['swing_high']]
        swings_low = df_analyzed[df_analyzed['swing_low']]
        print("\n--- Swing High ล่าสุด ---")
        print(swings_high[["timestamp", "high"]].tail(3))
        print("\n--- Swing Low ล่าสุด ---")
        print(swings_low[["timestamp", "low"]].tail(3))
        print(f"\nจำนวนแท่งเทียนทั้งหมด: {len(df)} แท่ง")
    else:
        print("ไม่สามารถดึงข้อมูลย้อนหลังได้")
