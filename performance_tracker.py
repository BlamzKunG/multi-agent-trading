import logging
from datetime import datetime

class PerformanceTracker:
    @staticmethod
    def calculate_metrics(closed_trades):
        """
        คำนวณสถิติประสิทธิภาพการเทรด (Win Rate, Profit Factor, Expectancy, Average Hold Time, Average R, Drawdown)
        จากรายการประวัติออเดอร์ที่ปิดแล้ว
        """
        if not closed_trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "avg_hold_time_mins": 0.0,
                "avg_r": 0.0,
                "max_drawdown_usd": 0.0
            }
            
        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if float(t.get('pnl', 0)) > 0]
        losses = [t for t in closed_trades if float(t.get('pnl', 0)) <= 0]
        
        win_rate = (len(wins) / total_trades) * 100.0 if total_trades > 0 else 0.0
        
        total_profit = sum(float(t.get('pnl', 0)) for t in wins)
        total_loss = abs(sum(float(t.get('pnl', 0)) for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (total_profit if total_profit > 0 else 1.0)
        
        avg_win = total_profit / len(wins) if len(wins) > 0 else 0.0
        avg_loss = total_loss / len(losses) if len(losses) > 0 else 0.0
        # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
        expectancy = ((win_rate / 100.0) * avg_win) - ((1.0 - win_rate / 100.0) * avg_loss)
        
        # คำนวณระยะเวลาถือครองเฉลี่ย (Average Hold Time)
        hold_times_sec = []
        for t in closed_trades:
            open_t = t.get('open_time')
            close_t = t.get('close_time')
            if open_t and close_t:
                try:
                    fmt = '%Y-%m-%d %H:%M:%S'
                    dt_open = datetime.strptime(open_t, fmt)
                    dt_close = datetime.strptime(close_t, fmt)
                    diff = (dt_close - dt_open).total_seconds()
                    hold_times_sec.append(diff)
                except Exception:
                    pass
        avg_hold_time_mins = (sum(hold_times_sec) / len(hold_times_sec)) / 60.0 if hold_times_sec else 0.0
        
        # คำนวณ Average R (Risk-to-Reward Ratio)
        # R = (Close Price - Entry Price) / (Entry Price - SL)
        r_values = []
        for t in closed_trades:
            entry = float(t.get('entry_price', 0))
            close = float(t.get('close_price', 0))
            sl = t.get('sl')
            direction = t.get('direction', 'BUY')
            if sl is not None and float(sl) > 0:
                sl = float(sl)
                risk = abs(entry - sl)
                if risk > 0:
                    reward = (close - entry) if direction == 'BUY' else (entry - close)
                    r_values.append(reward / risk)
        avg_r = sum(r_values) / len(r_values) if r_values else 0.0
        
        # คำนวณ Drawdown (Peak to Trough Balance/Equity)
        balance_curve = [0.0]
        current_bal = 0.0
        sorted_trades = sorted(closed_trades, key=lambda x: x.get('close_time', ''))
        for t in sorted_trades:
            current_bal += float(t.get('pnl', 0))
            balance_curve.append(current_bal)
            
        peak = 0.0
        max_dd = 0.0
        for bal in balance_curve:
            if bal > peak:
                peak = bal
            dd = peak - bal
            if dd > max_dd:
                max_dd = dd
                
        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "avg_hold_time_mins": round(avg_hold_time_mins, 2),
            "avg_r": round(avg_r, 2),
            "max_drawdown_usd": round(max_dd, 2)
        }
