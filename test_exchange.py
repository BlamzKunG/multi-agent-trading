from exchange_sim import MockExchange

def run_test():
    print("=== เริ่มการทดสอบ Mock Exchange ===")
    
    # 1. เริ่มต้นพอร์ตด้วยทุน $30 เลิฟเวอเรจ 1:100
    ex = MockExchange(initial_balance=30.0, leverage=100.0)
    print(f"ยอดเงินเริ่มต้น: ${ex.balance} | Equity: ${ex.equity}")
    
    # 2. ตั้งราคาทองปัจจุบันที่ $2300
    ex.update_price(2300.0)
    print(f"อัปเดตราคาทองเป็น: ${ex.current_price}")
    
    # 3. ลองเปิดออเดอร์ BUY ขนาด 0.01
    # SL อยู่ที่ 2295.0, TP อยู่ที่ 2315.0
    res = ex.open_position(direction='BUY', lot=0.01, sl=2295.0, tp=2315.0)
    print(f"ผลการเปิดออเดอร์: {res['status']}")
    
    status = ex.get_status()
    print(f"ออเดอร์ที่ค้างอยู่: {status['open_positions']}")
    print(f"มาร์จิ้นที่ใช้: ${status['open_positions'][0]['margin']:.2f}")
    
    # 4. อัปเดตราคาตลาดวิ่งขึ้นไปที่ $2310 (+10 USD)
    print("\n--- ราคาทองวิ่งขึ้นไปที่ $2310 ---")
    ex.update_price(2310.0)
    status = ex.get_status()
    print(f"P&L ออเดอร์ปัจจุบัน: ${status['floating_pnl']:.2f}")
    print(f"Equity ล่าสุด: ${ex.equity:.2f}")
    
    # 5. แก้ไขจุด Stop Loss (เลื่อนกันหน้าทุนมาที่ $2301)
    print("\n--- เลื่อน SL กันหน้าทุนมาที่ $2301 ---")
    pos_id = status['open_positions'][0]['id']
    ex.modify_sl_tp(pos_id, new_sl=2301.0)
    
    # 6. ราคาทองตกวูบชน SL ที่ราคา $2301
    print("\n--- ราคาทองร่วงลงไปที่ $2299 ---")
    ex.update_price(2299.0)  # ตัวจำลองจะตัดปิดที่จุด SL เลื่อนอัตโนมัติ ($2301)
    
    status = ex.get_status()
    print(f"ออเดอร์ที่ค้างเหลือ: {len(status['open_positions'])} ไม้")
    print(f"บาลานซ์สุดท้ายในบัญชี: ${status['balance']:.2f}")
    print(f"ประวัติการปิดออเดอร์: {status['history']}")

if __name__ == "__main__":
    run_test()
