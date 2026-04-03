/**
 * 股票组件（原自选股）
 * 合并：自选股列表 + 个股详情（K线图 + 基本面数据）+ 板块浏览
 */

const Watchlist = {
  stocks: [],
  refreshTimer: null,
  refreshInterval: 15000, // 15秒
  klineChart: null,
  volumeChart: null,
  candlestickSeries: null,
  volumeSeries: null,
  maSeries: {},
  MA_COLORS: { 5: '#f0b90b', 10: '#2962ff', 20: '#a371f7', 60: '#ff6d00' },
  currentKtype: 'day',

  async load() {
    await this.fetch();
    await this.render();
    this.startAutoRefresh();
    // 自动加载板块数据
    this.loadSectors();
  },

  async fetch() {
    const data = await API.getWatchlist();
    this.stocks = Array.isArray(data) ? data : [];
  },

  async render() {
    const container = document.getElementById('watchlistContent');
    if (!container) return;

    if (this.stocks.length === 0) {
      container.innerHTML = `
        <div class="card">
          <div class="card-title">📋 我的自选股</div>
          <div style="color:#8b949e;text-align:center;padding:40px">
            暂无自选股，请添加
          </div>
        </div>
        ${this.renderAddForm()}
        ${this.renderSectorBrowse()}
      `;
      return;
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>📋 我的自选股 (${this.stocks.length})</span>
          <div style="display:flex;gap:8px">
            <button class="btn btn-sm btn-secondary" onclick="Watchlist.refresh()">🔄 刷新</button>
          </div>
        </div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>价格</th>
                <th>涨跌幅</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              ${this.stocks.map(s => `
                <tr>
                  <td class="stock-symbol" style="cursor:pointer" onclick="Watchlist.showStockDetail('${esc(s.symbol)}')">${esc(s.symbol)}</td>
                  <td style="cursor:pointer" onclick="Watchlist.showStockDetail('${esc(s.symbol)}')">${esc(s.name || '')}</td>
                  <td class="stock-price">${Utils.formatPrice(s.price)}</td>
                  <td class="${Utils.isUp(s.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(s.chg_pct)}</td>
                  <td style="white-space:nowrap">
                    <button class="btn btn-sm btn-info" onclick="Watchlist.showStockDetail('${esc(s.symbol)}')">📈 详情</button>
                    <button class="btn btn-sm btn-secondary" onclick="Watchlist.remove('${esc(s.symbol)}')">删除</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
      ${this.renderAddForm()}
      ${this.renderSectorBrowse()}
    `;
  },

  renderAddForm() {
    return `
      <div class="card">
        <div class="card-title">+ 添加自选股</div>
        <div style="display:flex;gap:8px">
          <input type="text" id="newSymbol" class="input" placeholder="股票代码（如 002149）" style="width:200px">
          <input type="text" id="newName" class="input" placeholder="股票名称（可选）" style="width:200px">
          <button class="btn btn-primary" onclick="Watchlist.add()">添加</button>
        </div>
      </div>
    `;
  },

  renderSectorBrowse() {
    return `
      <div class="card">
        <div class="card-title">
          <span>🏢 板块浏览</span>
          <button class="btn btn-sm btn-secondary" onclick="Watchlist.loadSectors()">刷新板块</button>
        </div>
        <div id="sectorBrowseContent">
          <div style="color:#8b949e;font-size:13px;cursor:pointer" onclick="Watchlist.loadSectors()">点击加载板块数据</div>
        </div>
      </div>
    `;
  },

  async loadSectors() {
    const container = document.getElementById('sectorBrowseContent');
    if (!container) return;
    container.innerHTML = '<div class="loading"><div class="loading-spinner"></div>加载板块数据...</div>';

    const data = await API.getSectors();
    if (!data || !data.sectors) {
      container.innerHTML = '<div style="color:#8b949e">无法加载板块数据</div>';
      return;
    }

    container.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px">
        ${data.sectors.map(sector => `
          <div onclick="Watchlist.showSectorDetail('${esc(sector.name)}')"
               style="background:var(--bg-primary);border-radius:8px;padding:10px;cursor:pointer;border:1px solid var(--border-color);font-size:13px">
            <div style="font-weight:600">${esc(sector.name)}</div>
            <div style="color:#8b949e;font-size:12px">${sector.count || 0} 只
              ${sector.avg_chg !== undefined ? `<span class="${Utils.isUp(sector.avg_chg) ? 'up' : 'down'}">${Utils.formatChange(sector.avg_chg)}</span>` : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;
  },

  async showSectorDetail(sectorName, page = 1) {
    const modal = document.getElementById('stockDetailModal');
    const title = document.getElementById('stockDetailTitle');
    const body = document.getElementById('stockDetailBody');

    title.textContent = `板块: ${sectorName}`;
    body.innerHTML = '<div class="loading"><div class="loading-spinner"></div>加载板块股票...</div>';
    modal.style.display = 'flex';

    const data = await API.getSectorStocks(sectorName, page, 50);
    if (!data || !data.stocks) {
      body.innerHTML = '<div style="color:#8b949e">无法加载板块数据</div>';
      return;
    }

    const stocks = data.stocks;
    const pag = data.pagination || {};
    const total = pag.total || stocks.length;
    const totalPages = pag.totalPages || 1;
    const currentPage = pag.page || 1;

    let pagHtml = '';
    if (totalPages > 1) {
      pagHtml = `<div style="display:flex;justify-content:center;align-items:center;gap:8px;margin-top:12px;padding:8px 0">
        ${currentPage > 1 ? `<button onclick="Watchlist.showSectorDetail('${esc(sectorName)}', ${currentPage - 1})" class="btn btn-sm">上一页</button>` : ''}
        <span style="color:#8b949e;font-size:13px">第 ${currentPage}/${totalPages} 页（共 ${total} 只）</span>
        ${currentPage < totalPages ? `<button onclick="Watchlist.showSectorDetail('${esc(sectorName)}', ${currentPage + 1})" class="btn btn-sm">下一页</button>` : ''}
      </div>`;
    }

    body.innerHTML = `
      <div style="padding:12px">
        <div style="margin-bottom:8px;color:#8b949e;font-size:13px">共 ${total} 只股票，当前第 ${currentPage} 页</div>
        <div style="overflow-x:auto">
          <table class="data-table">
            <thead>
              <tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th><th>成交量</th></tr>
            </thead>
            <tbody>
              ${stocks.map(s => `
                <tr onclick="Watchlist.showStockDetail('${esc(s.symbol)}')" style="cursor:pointer">
                  <td class="stock-symbol">${esc(s.symbol)}</td>
                  <td>${esc(s.name || '')}</td>
                  <td>${Utils.formatPrice(s.price)}</td>
                  <td class="${Utils.isUp(s.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(s.chg_pct)}</td>
                  <td style="font-size:13px">${Utils.formatVolume(s.volume)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
        ${pagHtml}
      </div>
    `;
  },

  // ============ 个股详情（模态框：K线图 + 基本面数据） ============

  async showStockDetail(symbol) {
    const modal = document.getElementById('stockDetailModal');
    const title = document.getElementById('stockDetailTitle');
    const body = document.getElementById('stockDetailBody');

    title.textContent = `加载中...`;
    body.innerHTML = '<div class="loading"><div class="loading-spinner"></div>加载股票数据...</div>';
    modal.style.display = 'flex';

    // 并行加载行情、K线、基本面
    const [quoteData, klineData, fundamentalData] = await Promise.all([
      API.getStockDetail(symbol),
      Utils.fetchJSON(`/api/v1/kline/${symbol}?ktype=day&count=1250`),
      Utils.fetchJSON(`/api/fundamental/stock/${symbol}`).catch(() => null)
    ]);

    if (!quoteData || !quoteData.data) {
      body.innerHTML = '<div style="color:#8b949e;padding:40px;text-align:center">无法加载股票数据</div>';
      return;
    }

    const stock = quoteData.data;
    title.textContent = `${stock.name || symbol} (${symbol})`;

    let html = `
      <div style="padding:16px">
        <!-- 价格信息 -->
        <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:16px;flex-wrap:wrap">
          <span style="font-size:28px;font-weight:700">${Utils.formatPrice(stock.price)}</span>
          <span style="font-size:18px;color:${Utils.isUp(stock.chg_pct) ? '#3fb950' : '#f85149'}">
            ${Utils.formatChange(stock.chg_pct)}
          </span>
          <span style="color:#8b949e">涨跌: ${stock.chg || '--'}</span>
          <button class="btn btn-sm btn-primary" onclick="Watchlist.addToWatchlist('${esc(symbol)}', '${esc(stock.name || '')}')">+ 自选股</button>
        </div>

        <div class="metrics-grid" style="margin-bottom:16px">
          <div class="metric-card"><div class="metric-value">${Utils.formatPrice(stock.open)}</div><div class="metric-label">今开</div></div>
          <div class="metric-card"><div class="metric-value">${Utils.formatPrice(stock.high)}</div><div class="metric-label">最高</div></div>
          <div class="metric-card"><div class="metric-value">${Utils.formatPrice(stock.low)}</div><div class="metric-label">最低</div></div>
          <div class="metric-card"><div class="metric-value">${Utils.formatVolume(stock.volume)}</div><div class="metric-label">成交量</div></div>
          <div class="metric-card"><div class="metric-value">${Utils.formatAmount(stock.amount)}</div><div class="metric-label">成交额</div></div>
          <div class="metric-card"><div class="metric-value">${stock.turnover_rate !== undefined ? stock.turnover_rate + '%' : '--'}</div><div class="metric-label">换手率</div></div>
        </div>

        <!-- K线图 -->
        <div style="margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="font-weight:600;font-size:15px">📈 K线图</div>
            <div style="display:flex;gap:4px;align-items:center">
              <button class="btn btn-sm ${this.currentKtype === 'day' ? 'btn-primary' : 'btn-secondary'}" onclick="Watchlist.switchKtype('${esc(symbol)}','day')">日K</button>
              <button class="btn btn-sm ${this.currentKtype === 'week' ? 'btn-primary' : 'btn-secondary'}" onclick="Watchlist.switchKtype('${esc(symbol)}','week')">周K</button>
              <button class="btn btn-sm ${this.currentKtype === 'month' ? 'btn-primary' : 'btn-secondary'}" onclick="Watchlist.switchKtype('${esc(symbol)}','month')">月K</button>
              <button class="btn btn-sm btn-secondary" onclick="Watchlist.downloadKline('${esc(symbol)}')" title="下载更多历史数据（5年+）">📥 更多</button>
            </div>
          </div>
          <div style="background:var(--bg-primary);border-radius:8px;border:1px solid var(--border-color);overflow:hidden">
            <div id="modalKlineChart" style="width:100%;height:350px"></div>
            <div id="modalVolumeChart" style="width:100%;height:100px;border-top:1px solid var(--border-color)"></div>
          </div>
        </div>

        <!-- 基本面数据 -->
        <div id="stockFundamentalSection">
          ${this.renderFundamentalSection(fundamentalData)}
        </div>
      </div>
    `;

    body.innerHTML = html;

    // 渲染 K 线图
    if (klineData && klineData.success && klineData.data && klineData.data.length > 0) {
      this.renderKlineChart(klineData.data);
    }
  },

  renderFundamentalSection(data) {
    if (!data || !data.success || !data.data || data.data.length === 0) {
      return `
        <div style="font-weight:600;font-size:15px;margin-bottom:8px">💰 基本面数据</div>
        <div style="color:#8b949e;font-size:13px;padding:12px;background:var(--bg-primary);border-radius:8px">暂无基本面数据</div>
      `;
    }

    const records = data.data;
    const latest = records[0];

    return `
      <div style="font-weight:600;font-size:15px;margin-bottom:8px">💰 基本面数据</div>
      <div class="metrics-grid" style="margin-bottom:12px">
        <div class="metric-card"><div class="metric-value">${latest.roe?.toFixed(1) ?? '--'}</div><div class="metric-label">ROE(%)</div></div>
        <div class="metric-card"><div class="metric-value">${latest.eps?.toFixed(3) ?? '--'}</div><div class="metric-label">EPS</div></div>
        <div class="metric-card"><div class="metric-value ${latest.revenue_growth > 0 ? 'positive' : latest.revenue_growth < 0 ? 'negative' : ''}">${latest.revenue_growth?.toFixed(1) ?? '--'}%</div><div class="metric-label">营收增速</div></div>
        <div class="metric-card"><div class="metric-value ${latest.profit_growth > 0 ? 'positive' : latest.profit_growth < 0 ? 'negative' : ''}">${latest.profit_growth?.toFixed(1) ?? '--'}%</div><div class="metric-label">净利润增速</div></div>
        <div class="metric-card"><div class="metric-value">${latest.gross_margin?.toFixed(1) ?? '--'}%</div><div class="metric-label">毛利率</div></div>
        <div class="metric-card"><div class="metric-value">${latest.debt_ratio?.toFixed(1) ?? '--'}%</div><div class="metric-label">资产负债率</div></div>
      </div>
      <div style="overflow-x:auto">
        <table class="data-table">
          <thead><tr><th>报告期</th><th>EPS</th><th>ROE(%)</th><th>营收增速</th><th>净利润增速</th><th>毛利率</th><th>负债率</th></tr></thead>
          <tbody>
            ${records.slice(0, 8).map(r => `
              <tr>
                <td>${r.report_date || '--'}</td>
                <td>${r.eps?.toFixed(3) ?? '--'}</td>
                <td class="${r.roe > 15 ? 'up' : r.roe < 5 ? 'down' : ''}">${r.roe?.toFixed(1) ?? '--'}</td>
                <td class="${r.revenue_growth > 20 ? 'up' : r.revenue_growth < 0 ? 'down' : ''}">${r.revenue_growth?.toFixed(1) ?? '--'}</td>
                <td class="${r.profit_growth > 20 ? 'up' : r.profit_growth < 0 ? 'down' : ''}">${r.profit_growth?.toFixed(1) ?? '--'}</td>
                <td>${r.gross_margin?.toFixed(1) ?? '--'}</td>
                <td>${r.debt_ratio?.toFixed(1) ?? '--'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  },

  async switchKtype(symbol, ktype) {
    this.currentKtype = ktype;
    // Update button styles
    document.querySelectorAll('#stockDetailBody .btn-sm').forEach(btn => {
      if (btn.textContent.includes('K')) {
        btn.className = `btn btn-sm ${btn.textContent === (ktype === 'day' ? '日K' : ktype === 'week' ? '周K' : '月K') ? 'btn-primary' : 'btn-secondary'}`;
      }
    });

    const klineData = await Utils.fetchJSON(`/api/v1/kline/${symbol}?ktype=${ktype}&count=1250`);
    if (klineData && klineData.success && klineData.data) {
      this.renderKlineChart(klineData.data);
    }
  },

  async downloadKline(symbol) {
    if (!confirm(`下载 ${symbol} 的更多历史数据（约5年）？\n这可能需要几秒钟。`)) return;
    try {
      const res = await Utils.fetchJSON('/api/v1/kline/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, days: 1250, use_eastmoney: true })
      });
      if (res && res.success) {
        alert(`✅ 下载完成：${res.date_range}\n共 ${res.count} 条记录`);
        // 重新加载K线图
        await this.switchKtype(symbol, this.currentKtype || 'day');
      } else {
        alert('下载失败：' + (res?.error || '未知错误'));
      }
    } catch (e) {
      alert('下载失败：网络错误');
    }
  },

  renderKlineChart(data) {
    if (!window.LightweightCharts) return;

    const { createChart, CandlestickSeries, HistogramSeries, LineSeries } = window.LightweightCharts;

    // Destroy previous charts
    if (this.klineChart) { this.klineChart.remove(); this.klineChart = null; }
    if (this.volumeChart) { this.volumeChart.remove(); this.volumeChart = null; }

    const commonOptions = {
      layout: { background: { type: 'solid', color: '#0d1117' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      crosshair: { mode: 1, vertLine: { color: '#58a6ff', width: 1, style: 2 }, horzLine: { color: '#58a6ff', width: 1, style: 2 } },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: false },
    };

    const klineEl = document.getElementById('modalKlineChart');
    const volumeEl = document.getElementById('modalVolumeChart');
    if (!klineEl || !volumeEl) return;

    this.klineChart = createChart(klineEl, { ...commonOptions, handleScroll: { mouseWheel: true, pressedMouseMove: true }, handleScale: { mouseWheel: true, pinch: true } });
    this.candlestickSeries = this.klineChart.addSeries(CandlestickSeries, {
      upColor: '#f85149', downColor: '#3fb950', borderVisible: false, wickUpColor: '#f85149', wickDownColor: '#3fb950',
    });

    [5, 10, 20, 60].forEach(period => {
      this.maSeries[period] = this.klineChart.addSeries(LineSeries, {
        color: this.MA_COLORS[period], lineWidth: 1, priceLineVisible: false, lastValueVisible: false, visible: period !== 60,
      });
    });

    this.volumeChart = createChart(volumeEl, { ...commonOptions, handleScroll: { mouseWheel: true, pressedMouseMove: true }, handleScale: { mouseWheel: true, pinch: true } });
    this.volumeSeries = this.volumeChart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' });
    this.volumeChart.priceScale('').applyOptions({ scaleMargins: { top: 0.7, bottom: 0 } });

    // Link time axes
    this.klineChart.timeScale().subscribeVisibleLogicalRangeChange(range => { this.volumeChart.timeScale().setVisibleLogicalRange(range); });
    this.volumeChart.timeScale().subscribeVisibleLogicalRangeChange(range => { this.klineChart.timeScale().setVisibleLogicalRange(range); });

    // Set data
    const candleData = data.map(d => ({ time: d.date, open: d.open, high: d.high, low: d.low, close: d.close }));
    const volumeData = data.map(d => ({ time: d.date, value: d.volume, color: d.close >= d.open ? 'rgba(248,81,73,0.5)' : 'rgba(63,185,80,0.5)' }));

    this.candlestickSeries.setData(candleData);
    this.volumeSeries.setData(volumeData);

    [5, 10, 20, 60].forEach(period => {
      const maData = data.filter(d => d[`ma${period}`] != null).map(d => ({ time: d.date, value: d[`ma${period}`] }));
      this.maSeries[period].setData(maData);
    });

    this.klineChart.timeScale().fitContent();
  },

  closeStockDetail() {
    const modal = document.getElementById('stockDetailModal');
    modal.style.display = 'none';
    if (this.klineChart) { this.klineChart.remove(); this.klineChart = null; }
    if (this.volumeChart) { this.volumeChart.remove(); this.volumeChart = null; }
  },

  // ============ 自选股操作 ============

  async add() {
    const symbolInput = document.getElementById('newSymbol');
    const nameInput = document.getElementById('newName');
    const symbol = symbolInput.value.trim();
    const name = nameInput.value.trim();
    if (!symbol) { alert('请输入股票代码'); return; }
    await API.addToWatchlist(symbol, name);
    symbolInput.value = '';
    nameInput.value = '';
    await this.load();
  },

  async remove(symbol) {
    if (!confirm(`确定删除 ${symbol}？`)) return;
    await API.removeFromWatchlist(symbol);
    await this.load();
  },

  async refresh() {
    await this.load();
  },

  async addToWatchlist(symbol, name) {
    await API.addToWatchlist(symbol, name);
    alert(`已添加 ${symbol} 到自选股`);
  },

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.refreshTimer = setInterval(() => {
      if (AppState.currentTab === 'watchlist') { this.refresh(); }
    }, this.refreshInterval);
  },

  stopAutoRefresh() {
    if (this.refreshTimer) { clearInterval(this.refreshTimer); this.refreshTimer = null; }
  }
};

// 暴露全局
window.Watchlist = Watchlist;
