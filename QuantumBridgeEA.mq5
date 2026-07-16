//+------------------------------------------------------------------+
//|                                             QuantumBridgeEA.mq5  |
//|                                  Copyright 2026, Antigravity AI  |
//|                                             https://google.com   |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://google.com"
#property version   "2.00"
#property strict

//--- Input Parameters
input string             InpIndicatorName  = "Quantum TrendPulse"; // Name of the ex5 indicator (e.g. "Quantum TrendPulse" or "Market\\Quantum TrendPulse")
input int                InpBuyBuffer      = 4;                    // Buffer index for BUY signals
input int                InpSellBuffer     = 5;                    // Buffer index for SELL signals
input int                InpScanBars       = 1000;                 // Max historical bars to scan
input string             InpServerURL      = "http://127.0.0.1:8018/api/signals"; // URL of local Python API

//--- Global Handles
int handle_m1  = INVALID_HANDLE;
int handle_m5  = INVALID_HANDLE;
int handle_m15 = INVALID_HANDLE;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("🚀 [QuantumBridgeEA] Initializing Expert Advisor...");
   Print("⚠️ [QuantumBridgeEA] IMPORTANT: Please make sure 'http://127.0.0.1:8018' is added to allowed WebRequest URLs in MT5 settings (Tools -> Options -> Expert Advisors).");
   
   // Initialize handles for M1, M5, M15
   ResetLastError();
   handle_m1  = iCustom(_Symbol, PERIOD_M1,  InpIndicatorName);
   if (handle_m1 == INVALID_HANDLE) {
      PrintFormat("❌ [QuantumBridgeEA] Failed to create handle for M1. Error: %d.", GetLastError());
   }
   
   ResetLastError();
   handle_m5  = iCustom(_Symbol, PERIOD_M5,  InpIndicatorName);
   if (handle_m5 == INVALID_HANDLE) {
      PrintFormat("❌ [QuantumBridgeEA] Failed to create handle for M5. Error: %d.", GetLastError());
   }
   
   ResetLastError();
   handle_m15 = iCustom(_Symbol, PERIOD_M15, InpIndicatorName);
   if (handle_m15 == INVALID_HANDLE) {
      PrintFormat("❌ [QuantumBridgeEA] Failed to create handle for M15. Error: %d.", GetLastError());
   }
   
   if(handle_m1 == INVALID_HANDLE || handle_m5 == INVALID_HANDLE || handle_m15 == INVALID_HANDLE)
   {
      Print("❌ [QuantumBridgeEA] Initialization failed due to invalid handles. Check indicator name or path.");
      return(INIT_FAILED);
   }
   
   Print("✅ [QuantumBridgeEA] Handles initialized successfully for M1, M5, and M15.");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(handle_m1  != INVALID_HANDLE) IndicatorRelease(handle_m1);
   if(handle_m5  != INVALID_HANDLE) IndicatorRelease(handle_m5);
   if(handle_m15 != INVALID_HANDLE) IndicatorRelease(handle_m15);
   Print("🚪 [QuantumBridgeEA] Expert Advisor stopped.");
}

//+------------------------------------------------------------------+
//| Helper to retrieve latest signal for a timeframe                 |
//+------------------------------------------------------------------+
bool GetLatestSignal(int handle, ENUM_TIMEFRAMES tf, double &direction, datetime &sig_time, double &sig_price)
{
   double buy_buffer[];
   double sell_buffer[];
   datetime times[];
   
   ArraySetAsSeries(buy_buffer, true);
   ArraySetAsSeries(sell_buffer, true);
   ArraySetAsSeries(times, true);
   
   int available_bars = iBars(_Symbol, tf);
   int scan_bars = MathMin(InpScanBars, available_bars);
   if (scan_bars <= 0) {
      direction = 0.0;
      sig_time = 0;
      sig_price = 0.0;
      return false;
   }
   
   ResetLastError();
   int copied_buy = CopyBuffer(handle, InpBuyBuffer, 0, scan_bars, buy_buffer);
   int copied_sell = CopyBuffer(handle, InpSellBuffer, 0, scan_bars, sell_buffer);
   int copied_time = CopyTime(_Symbol, tf, 0, scan_bars, times);
   
   if(copied_buy <= 0 || copied_sell <= 0 || copied_time <= 0)
   {
      direction = 0.0;
      sig_time = 0;
      sig_price = 0.0;
      return false;
   }
   
   int latest_buy_idx = -1;
   int latest_sell_idx = -1;
   
   for(int i = 0; i < scan_bars; i++)
   {
      if(latest_buy_idx == -1 && buy_buffer[i] != EMPTY_VALUE && buy_buffer[i] != 0.0)
      {
         latest_buy_idx = i;
      }
      if(latest_sell_idx == -1 && sell_buffer[i] != EMPTY_VALUE && sell_buffer[i] != 0.0)
      {
         latest_sell_idx = i;
      }
      if(latest_buy_idx != -1 && latest_sell_idx != -1) break;
   }
   
   direction = 0.0;
   sig_time = 0;
   sig_price = 0.0;
   
   if(latest_buy_idx != -1 && (latest_sell_idx == -1 || latest_buy_idx < latest_sell_idx))
   {
      direction = 1.0;
      sig_time = times[latest_buy_idx];
      sig_price = iClose(_Symbol, tf, latest_buy_idx);
      return true;
   }
   else if(latest_sell_idx != -1 && (latest_buy_idx == -1 || latest_sell_idx < latest_buy_idx))
   {
      direction = -1.0;
      sig_time = times[latest_sell_idx];
      sig_price = iClose(_Symbol, tf, latest_sell_idx);
      return true;
   }
   
   return false;
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Rate limit: ส่งข้อมูลทุกๆ 1 วินาที (1000 ms) เพื่อประหยัด CPU ของระบบ
   static uint last_send_tick = 0;
   if(GetTickCount() - last_send_tick < 1000) return;
   last_send_tick = GetTickCount();

   double dir_m1 = 0, dir_m5 = 0, dir_m15 = 0;
   datetime time_m1 = 0, time_m5 = 0, time_m15 = 0;
   double price_m1 = 0, price_m5 = 0, price_m15 = 0;
   
   // Fetch signals for M1, M5, M15
   GetLatestSignal(handle_m1,  PERIOD_M1,  dir_m1,  time_m1,  price_m1);
   GetLatestSignal(handle_m5,  PERIOD_M5,  dir_m5,  time_m5,  price_m5);
   GetLatestSignal(handle_m15, PERIOD_M15, dir_m15, time_m15, price_m15);
   
   // ส่งข้อมูลไปยัง Python API ผ่าน WebRequest ของ MQL5
   string cookie = NULL, headers;
   char post[], result[];
   string result_headers;
   
   // สร้าง JSON String
   string json = StringFormat(
      "{\"m1_dir\":%.1f,\"m1_time\":%d,\"m1_price\":%.5f,"
      "\"m5_dir\":%.1f,\"m5_time\":%d,\"m5_price\":%.5f,"
      "\"m15_dir\":%.1f,\"m15_time\":%d,\"m15_price\":%.5f}",
      dir_m1, (long)time_m1, price_m1,
      dir_m5, (long)time_m5, price_m5,
      dir_m15, (long)time_m15, price_m15
   );
   
   StringToCharArray(json, post, 0, StringLen(json));
   headers = "Content-Type: application/json\r\n";
   
   ResetLastError();
   int res = WebRequest("POST", InpServerURL, cookie, NULL, 500, post, 0, result, result_headers);
   
   if(res == -1)
   {
      static datetime last_warn_time = 0;
      if (TimeCurrent() - last_warn_time > 10) {
         int err = GetLastError();
         PrintFormat("❌ [QuantumBridgeEA] WebRequest to Python failed. Error Code: %d", err);
         if (err == 4014) {
            Print("⚠️ [QuantumBridgeEA] Error 4014 means URL is not allowed. Please add 'http://127.0.0.1:8018' in MT5 -> Tools -> Options -> Expert Advisors -> Allow WebRequest.");
         }
         last_warn_time = TimeCurrent();
      }
   }
}
