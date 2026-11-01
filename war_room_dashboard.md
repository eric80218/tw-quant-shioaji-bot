<!DOCTYPE html>
<html lang="zh-TW" class="dark">
<head>
  <meta charset="UTF-8">
  <title>6D Quant Auto-Trading War Room</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 p-6 max-w-5xl mx-auto font-sans">
  <header class="flex justify-between items-center border-b border-slate-800 pb-4 mb-6">
    <h1 class="text-2xl font-bold">⚡ 6D Quant Auto-Bot 戰情室</h1>
    <div id="last-updated" class="text-xs text-slate-400">載入中...</div>
  </header>
  <div class="grid grid-cols-3 gap-4 mb-6">
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">5萬池淨值 (NAV)</div>
      <div id="nav-val" class="text-xl font-bold mt-1">NT$ 50,000</div>
    </div>
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">剩餘可買現金</div>
      <div id="cash-val" class="text-xl font-bold text-sky-400 mt-1">NT$ 45,000</div>
    </div>
    <div class="bg-slate-900 p-4 rounded-xl border border-slate-800">
      <div class="text-xs text-slate-400">今日交易配額</div>
      <div id="quota-val" class="text-xl font-bold text-emerald-400 mt-1">0 / 3 筆</div>
    </div>
  </div>
  <script>
    fetch('./dashboard_data.json').then(r => r.json()).then(d => {
      document.getElementById('last-updated').innerText = '最後更新: ' + d.last_updated;
      document.getElementById('nav-val').innerText = 'NT$ ' + d.nav.toLocaleString();
      document.getElementById('cash-val').innerText = 'NT$ ' + d.available_cash.toLocaleString();
      document.getElementById('quota-val').innerText = d.daily_order_count + ' / ' + d.max_daily_orders + ' 筆';
    }).catch(e => console.log('等待首次資料生成'));
  </script>
</body>
</html>