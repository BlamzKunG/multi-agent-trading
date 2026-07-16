//+------------------------------------------------------------------+
//|                                             QuantumBridgeEA.mq5  |
//|                                  Copyright 2026, Antigravity AI  |
//|                                             https://google.com   |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Antigravity AI"
#property link      "https://google.com"
#property version   "1.30"
#property strict

//--- Input Parameters
input string             InpIndicatorName  = "Quantum TrendPulse"; // Name of the ex5 indicator (e.g. "Quantum TrendPulse" or "Market\\Quantum TrendPulse")
input int                InpBuyBuffer      = 4;                    // Buffer index for BUY signals
input int                InpSellBuffer     = 5;                    // Buffer index for SELL signals
input int                InpScanBars       = 1000;                 // Max historical bars to scan

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
   
   // ป้องกันปัญหาการขอ Copy เกินแท่งประวัติที่มีจริงบนชาร์ต (iBars) ซึ่งจะทำให้ CopyBuffer ล้มเหลวและได้ค่า -1
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
      static datetime last_err_time = 0;
      if (TimeCurrent() - last_err_time > 10) {
         PrintFormat("⚠️ [QuantumBridgeEA] CopyBuffer failed for %s. Available Bars: %d, Requested: %d. BuyCopied: %d, SellCopied: %d, TimeCopied: %d. Error Code: %d", 
                     EnumToString(tf), available_bars, scan_bars, copied_buy, copied_sell, copied_time, GetLastError());
         last_err_time = TimeCurrent();
      }
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
   double dir_m1 = 0, dir_m5 = 0, dir_m15 = 0;
   datetime time_m1 = 0, time_m5 = 0, time_m15 = 0;
   double price_m1 = 0, price_m5 = 0, price_m15 = 0;
   
   // Fetch signals for M1, M5, M15
   GetLatestSignal(handle_m1,  PERIOD_M1,  dir_m1,  time_m1,  price_m1);
   GetLatestSignal(handle_m5,  PERIOD_M5,  dir_m5,  time_m5,  price_m5);
   GetLatestSignal(handle_m15, PERIOD_M15, dir_m15, time_m15, price_m15);
   
   // Set MT5 Global Variables for all three timeframes
   GlobalVariableSet("QUANTUM_M1_DIR", dir_m1);
   GlobalVariableSet("QUANTUM_M1_TIME", (double)time_m1);
   GlobalVariableSet("QUANTUM_M1_PRICE", price_m1);
   
   GlobalVariableSet("QUANTUM_M5_DIR", dir_m5);
   GlobalVariableSet("QUANTUM_M5_TIME", (double)time_m5);
   GlobalVariableSet("QUANTUM_M5_PRICE", price_m5);
   
   GlobalVariableSet("QUANTUM_M15_DIR", dir_m15);
   GlobalVariableSet("QUANTUM_M15_TIME", (double)time_m15);
   GlobalVariableSet("QUANTUM_M15_PRICE", price_m15);
   
   GlobalVariableSet("QUANTUM_UPDATE_TIME", (double)TimeCurrent());
}
