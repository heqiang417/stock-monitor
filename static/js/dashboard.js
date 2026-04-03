/**
 * Dashboard 组件
 * 首页聚合：大盘指数、自选摘要、策略告警、快速操作
 * 支持 WebSocket 实时推送
 */

const Dashboard = {
  refreshInterval: 8000, // 8秒刷新（Cloudflare 免费版 WebSocket 86秒断一次，缩短轮询间隔减少数据空白）
  timer: null,
  wsSubscribed: false,
  
  async load() {
    await this.render();
    this.startAutoRefresh();
    this.subscribeToWebSocket();
  },
  
  async render() {
    const container = document.getElementById('dashboardContent');
    if (!container) return;
    
    container.innerHTML = `
      <div class="dashboard-grid">
        <!-- 大盘指数 -->
        <div class="card">
          <div class="card-title">📊 大盘指数</div>
          <div id="marketIndexes" class="metrics-grid">
            <div class="loading"><div class="loading-spinner"></div></div>
          </div>
        </div>
        
        <!-- 今日关注 -->
        <div class="card">
          <div class="card-title">
            <span>⭐ 自选摘要</span>
            <button class="btn btn-sm btn-secondary" onclick="showTab('watchlist')">管理</button>
          </div>
          <div id="watchlistSummary">
            <div class="loading"><div class="loading-spinner"></div></div>
          </div>
        </div>
        
        <!-- 策略告警 -->
        <div class="card">
          <div class="card-title">
            <span>🔔 策略告警</span>
            <button class="btn btn-sm btn-secondary" onclick="showTab('strategies')">配置</button>
          </div>
          <div id="strategyAlerts">
            <div class="loading"><div class="loading-spinner"></div></div>
          </div>
        </div>
        
        <!-- 涨跌榜 -->
        <div class="card">
          <div class="card-title">🏆 今日涨跌榜</div>
          <div id="topMovers">
            <div class="loading"><div class="loading-spinner"></div></div>
          </div>
        </div>
        
        <!-- 全市场扫描 -->
        <div class="card" style="grid-column:1/-1">
          <div class="card-title">🔍 全市场扫描</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
            <button class="btn btn-primary" onclick="Dashboard.fullMarketScan()">🌐 全市场扫描</button>
          </div>
          <div id="quickScanResult"></div>
        </div>
    
    `;
    
    // 优先使用聚合接口，一次请求获取所有数据
    await this.loadDashboard();
  },
  
  async loadDashboard() {
    try {
      const data = await Utils.fetchJSON('/api/v1/dashboard');
      if (data && data.success) {
        // 聚合接口成功：分别渲染各个区块
        this.renderMarketIndexesFromData(data.market_indexes || []);
        this.renderWatchlistFromData(data.watchlist || []);
        this.renderStrategiesFromData(data.strategies || []);
        // 实时行情已移除
        // 涨跌榜保持占位
        this.loadTopMovers();
        return;
      }
    } catch (e) {
      console.warn('Dashboard aggregation API failed, falling back to parallel:', e);
    }
    
    // Fallback: 原来的并行加载（Promise.all）
    await Promise.all([
      this.loadMarketIndexes(),
      this.loadWatchlistSummary(),
      this.loadStrategyAlerts(),
      this.loadTopMovers(),
      this.loadRealtimeQuote()
    ]);
  },
  
  renderMarketIndexesFromData(indexes) {
    const container = document.getElementById('marketIndexes');
    if (!container) return;
    
    if (!indexes || indexes.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无数据</div>';
      return;
    }
    
    const sh = indexes.find(i => i.symbol === 'sh000001') || indexes[0];
    const sz = indexes.find(i => i.symbol === 'sz399001');
    const cyb = indexes.find(i => i.symbol === 'sz399006');
    const hs300 = indexes.find(i => i.symbol === 'sh000300');
    
    let html = `
      <div class="metric-card" id="index-sh000001" style="grid-column:1/-1">
        <div class="metric-value ${Utils.isUp(sh?.chg_pct) ? 'positive' : 'negative'}" style="font-size:28px">
          ${sh?.price?.toFixed(2) || '--'}
        </div>
        <div class="metric-label">${esc(sh?.name || '上证指数')} ${Utils.formatChange(sh?.chg_pct)}</div>
      </div>`;
    
    if (sz) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(sz.chg_pct) ? 'positive' : 'negative'}">
            ${sz.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">深证成指 ${Utils.formatChange(sz.chg_pct)}</div>
        </div>`;
    }
    if (cyb) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(cyb.chg_pct) ? 'positive' : 'negative'}">
            ${cyb.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">创业板指 ${Utils.formatChange(cyb.chg_pct)}</div>
        </div>`;
    }
    if (hs300) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(hs300.chg_pct) ? 'positive' : 'negative'}">
            ${hs300.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">沪深300 ${Utils.formatChange(hs300.chg_pct)}</div>
        </div>`;
    }
    
    container.innerHTML = html;
  },
  
  renderWatchlistFromData(watchlist) {
    const container = document.getElementById('watchlistSummary');
    if (!container) return;
    
    if (!watchlist || !Array.isArray(watchlist) || watchlist.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无自选股，点击"管理"添加</div>';
      return;
    }
    
    AppState.watchlist = watchlist;
    
    container.innerHTML = `
      <ul class="stock-list">
        ${watchlist.slice(0, 5).map(stock => `
          <li class="stock-item" onclick="Dashboard.showStock('${esc(stock.symbol)}')">
            <div>
              <span class="stock-symbol">${esc(stock.symbol)}</span>
              <span class="stock-name">${esc(stock.name || '')}</span>
            </div>
            <div>
              <span class="stock-price">${Utils.formatPrice(stock.price)}</span>
              <span class="stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(stock.chg_pct)}</span>
            </div>
          </li>
        `).join('')}
      </ul>
      ${watchlist.length > 5 ? `<div style="text-align:center;padding:8px;color:#8b949e;font-size:13px">还有 ${watchlist.length - 5} 只...</div>` : ''}
    `;
  },
  
  renderStrategiesFromData(strategies) {
    const container = document.getElementById('strategyAlerts');
    if (!container) return;
    
    if (!strategies || !Array.isArray(strategies) || strategies.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无启用的策略</div>';
      return;
    }
    
    container.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px">
        ${strategies.map(s => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px;background:var(--bg-primary);border-radius:8px">
            <div>
              <div style="font-weight:500">${esc(s.name)}</div>
              <div style="font-size:12px;color:#8b949e">触发 ${s.trigger_count || 0} 次</div>
            </div>
            <span class="badge info">${esc(s.logic || 'AND')}</span>
          </div>
        `).join('')}
      </div>
    `;
  },
  
  renderRealtimeQuoteFromData(q) {
    const container = document.getElementById('realtimeQuote'); if (!container) return;
    if (!container) return;
    
    if (!q || !q.price) {
      container.innerHTML = '<div style="color:#8b949e">暂无数据</div>';
      return;
    }
    
    container.innerHTML = `
      <div style="display:flex;flex-direction:column;align-items:center;min-width:120px">
        <span style="font-size:24px;font-weight:700;color:${Utils.isUp(q.chg_pct) ? '#3fb950' : '#f85149'}">¥${Utils.formatPrice(q.price)}</span>
        <span style="font-size:14px;color:${Utils.isUp(q.chg_pct) ? '#3fb950' : '#f85149'}">${Utils.formatChange(q.chg_pct)}</span>
        <span style="font-size:12px;color:#8b949e">${esc(q.name || '西部材料')}</span>
      </div>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div style="display:flex;flex-direction:column">
          <span style="font-size:12px;color:#8b949e">今开</span>
          <span style="font-size:14px;color:#c9d1d9">¥${Utils.formatPrice(q.open)}</span>
        </div>
        <div style="display:flex;flex-direction:column">
          <span style="font-size:12px;color:#8b949e">最高</span>
          <span style="font-size:14px;color:#f85149">¥${Utils.formatPrice(q.high)}</span>
        </div>
        <div style="display:flex;flex-direction:column">
          <span style="font-size:12px;color:#8b949e">最低</span>
          <span style="font-size:14px;color:#3fb950">¥${Utils.formatPrice(q.low)}</span>
        </div>
        <div style="display:flex;flex-direction:column">
          <span style="font-size:12px;color:#8b949e">成交量</span>
          <span style="font-size:14px;color:#c9d1d9">${Utils.formatVolume(q.volume)}</span>
        </div>
        <div style="display:flex;flex-direction:column">
          <span style="font-size:12px;color:#8b949e">成交额</span>
          <span style="font-size:14px;color:#c9d1d9">${Utils.formatAmount(q.amount)}</span>
        </div>
      </div>
    `;
    
    const updateTime = document.getElementById('realtimeUpdate'); if (!updateTime) return;
    if (updateTime) updateTime.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
  },
  
  async loadMarketIndexes() {
    const container = document.getElementById('marketIndexes');
    if (!container) return;
    
    const data = await API.getMarketIndexes();
    if (!data || !data.indexes || data.indexes.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无数据</div>';
      return;
    }
    
    const indexes = data.indexes;
    // Match key indexes
    const sh = indexes.find(i => i.symbol === 'sh000001') || indexes[0];
    const sz = indexes.find(i => i.symbol === 'sz399001');
    const cyb = indexes.find(i => i.symbol === 'sz399006');
    const hs300 = indexes.find(i => i.symbol === 'sh000300');
    
    // Build full HTML first, then assign once (single reflow)
    let html = `
      <div class="metric-card" id="index-sh000001" style="grid-column:1/-1">
        <div class="metric-value ${Utils.isUp(sh?.chg_pct) ? 'positive' : 'negative'}" style="font-size:28px">
          ${sh?.price?.toFixed(2) || '--'}
        </div>
        <div class="metric-label">${esc(sh?.name || '上证指数')} ${Utils.formatChange(sh?.chg_pct)}</div>
      </div>`;
    
    if (sz) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(sz.chg_pct) ? 'positive' : 'negative'}">
            ${sz.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">深证成指 ${Utils.formatChange(sz.chg_pct)}</div>
        </div>`;
    }
    if (cyb) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(cyb.chg_pct) ? 'positive' : 'negative'}">
            ${cyb.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">创业板指 ${Utils.formatChange(cyb.chg_pct)}</div>
        </div>`;
    }
    if (hs300) {
      html += `
        <div class="metric-card">
          <div class="metric-value ${Utils.isUp(hs300.chg_pct) ? 'positive' : 'negative'}">
            ${hs300.price?.toFixed(2) || '--'}
          </div>
          <div class="metric-label">沪深300 ${Utils.formatChange(hs300.chg_pct)}</div>
        </div>`;
    }
    
    container.innerHTML = html;
  },
  
  async loadWatchlistSummary() {
    const container = document.getElementById('watchlistSummary');
    if (!container) return;
    
    const data = await API.getWatchlist();
    if (!data || !Array.isArray(data) || data.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无自选股，点击"管理"添加</div>';
      return;
    }
    
    AppState.watchlist = data;
    
    // watchlist API 已返回 price, chg_pct 数据，直接使用
    container.innerHTML = `
      <ul class="stock-list">
        ${data.slice(0, 5).map(stock => `
          <li class="stock-item" onclick="Dashboard.showStock('${esc(stock.symbol)}')">
            <div>
              <span class="stock-symbol">${esc(stock.symbol)}</span>
              <span class="stock-name">${esc(stock.name || '')}</span>
            </div>
            <div>
              <span class="stock-price">${Utils.formatPrice(stock.price)}</span>
              <span class="stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(stock.chg_pct)}</span>
            </div>
          </li>
        `).join('')}
      </ul>
      ${data.length > 5 ? `<div style="text-align:center;padding:8px;color:#8b949e;font-size:13px">还有 ${data.length - 5} 只...</div>` : ''}
    `;
  },
  
  async loadStrategyAlerts() {
    const container = document.getElementById('strategyAlerts');
    if (!container) return;
    
    const data = await API.getStrategies();
    if (!data || !data.strategies) {
      container.innerHTML = '<div style="color:#8b949e">暂无策略</div>';
      return;
    }
    
    const enabled = data.strategies.filter(s => s.enabled);
    if (enabled.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无启用的策略</div>';
      return;
    }
    
    container.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px">
        ${enabled.map(s => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:8px;background:var(--bg-primary);border-radius:8px">
            <div>
              <div style="font-weight:500">${esc(s.name)}</div>
              <div style="font-size:12px;color:#8b949e">触发 ${s.trigger_count || 0} 次</div>
            </div>
            <span class="badge info">${esc(s.logic || 'AND')}</span>
          </div>
        `).join('')}
      </div>
    `;
  },
  
  async loadTopMovers() {
    const container = document.getElementById('topMovers');
    if (!container) return;

    container.innerHTML = '<div style="color:#8b949e">加载中...</div>';

    try {
      const [upRes, downRes] = await Promise.all([
        Utils.fetchJSON('/api/v1/limit-up'),
        Utils.fetchJSON('/api/v1/limit-down')
      ]);

      const upList = upRes?.up || [];
      const downList = downRes?.down || [];
      const dateStr = upRes?.date || '';

      const fmtDate = dateStr ? `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}` : '';

      const renderList = (list, max = 8) => {
        if (!list.length) return '<div style="font-size:12px;color:#8b949e">暂无数据</div>';
        return list.slice(0, max).map(s => {
          const pct = (s.chg_pct || 0).toFixed(2);
          const color = s.chg_pct >= 0 ? '#3fb950' : '#f85149';
          const consec = s.consecutive > 1 ? ` <span style="background:#f0883e22;color:#f0883e;border-radius:3px;padding:0 4px;font-size:11px">${s.consecutive}连板</span>` : '';
          return `<div style="font-size:12px;padding:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">
            <span style="color:${color};cursor:pointer" onclick="Watchlist.showStockDetail('sh${s.code}')">${s.code}</span>
            <span style="color:#c9d1d9">${esc(s.name)}</span>
            <span style="color:${color}">${pct}%</span>${consec}
          </div>`;
        }).join('');
      };

      container.innerHTML = `
        <div style="font-size:11px;color:#8b949e;margin-bottom:6px">${fmtDate} · 涨停${upList.length}只 · 跌停${downList.length}只</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div>
            <div style="font-size:12px;color:#3fb950;margin-bottom:4px">⬆ 涨停榜</div>
            ${renderList(upList)}
          </div>
          <div>
            <div style="font-size:12px;color:#f85149;margin-bottom:4px">⬇ 跌停榜</div>
            ${renderList(downList)}
          </div>
        </div>
      `;
    } catch (e) {
      console.error('loadTopMovers error:', e);
      container.innerHTML = '<div style="font-size:12px;color:#f85149">加载失败</div>';
    }
  },
  
  async loadRealtimeQuote() {
    const container = document.getElementById('realtimeQuote'); if (!container) return;
    if (!container) return;
    
    try {
      const data = await API.getStock('002149'); // 默认显示西部材料
      if (data && data.data) {
        const q = data.data;
        container.innerHTML = `
          <div style="display:flex;flex-direction:column;align-items:center;min-width:120px">
            <span style="font-size:24px;font-weight:700;color:${Utils.isUp(q.chg_pct) ? '#3fb950' : '#f85149'}">¥${Utils.formatPrice(q.price)}</span>
            <span style="font-size:14px;color:${Utils.isUp(q.chg_pct) ? '#3fb950' : '#f85149'}">${Utils.formatChange(q.chg_pct)}</span>
            <span style="font-size:12px;color:#8b949e">${esc(q.name || '西部材料')}</span>
          </div>
          <div style="display:flex;gap:16px;flex-wrap:wrap">
            <div style="display:flex;flex-direction:column">
              <span style="font-size:12px;color:#8b949e">今开</span>
              <span style="font-size:14px;color:#c9d1d9">¥${Utils.formatPrice(q.open)}</span>
            </div>
            <div style="display:flex;flex-direction:column">
              <span style="font-size:12px;color:#8b949e">最高</span>
              <span style="font-size:14px;color:#f85149">¥${Utils.formatPrice(q.high)}</span>
            </div>
            <div style="display:flex;flex-direction:column">
              <span style="font-size:12px;color:#8b949e">最低</span>
              <span style="font-size:14px;color:#3fb950">¥${Utils.formatPrice(q.low)}</span>
            </div>
            <div style="display:flex;flex-direction:column">
              <span style="font-size:12px;color:#8b949e">成交量</span>
              <span style="font-size:14px;color:#c9d1d9">${Utils.formatVolume(q.volume)}</span>
            </div>
            <div style="display:flex;flex-direction:column">
              <span style="font-size:12px;color:#8b949e">成交额</span>
              <span style="font-size:14px;color:#c9d1d9">${Utils.formatAmount(q.amount)}</span>
            </div>
          </div>
        `;
        
        const updateTime = document.getElementById('realtimeUpdate'); if (!updateTime) return;
        if (updateTime) updateTime.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
      }
    } catch (e) {
      container.innerHTML = '<div style="color:#8b949e">加载失败</div>';
    }
  },
  
  async fullMarketScan() {
    const container = document.getElementById('quickScanResult');
    container.innerHTML = '<div class="loading"><div class="loading-spinner"></div> 全市场扫描中（可能需要较长时间）...</div>';
    
    const data = await API.scanMarket();
    
    if (!data || !data.alerts || data.alerts.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">扫描完成，未发现告警</div>';
      return;
    }
    
    container.innerHTML = `
      <div style="margin-bottom:8px;color:#8b949e">发现 ${data.alerts.length} 个告警</div>
      <table class="data-table">
        <thead>
          <tr><th>代码</th><th>策略</th><th>触发条件</th><th>时间</th></tr>
        </thead>
        <tbody>
          ${data.alerts.slice(0, 20).map(a => `
            <tr>
              <td class="stock-symbol">${esc(a.symbol)}</td>
              <td>${esc(a.strategy || '--')}</td>
              <td>${esc(a.condition || '--')}</td>
              <td style="font-size:12px;color:#8b949e">${esc(a.timestamp || '--')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  },
  
  showStock(symbol) {
    showTab('watchlist');
    Watchlist.showStockDetail(symbol);
  },
  
  // ============ WebSocket 订阅 ============
  subscribeToWebSocket() {
    if (this.wsSubscribed) return;
    
    // 监听 WebSocket 重连事件 — 重连后立即刷新所有数据
    EventBus.on('wsReconnected', () => {
      console.log('📡 WebSocket 重连，刷新 Dashboard 数据...');
      this.loadDashboard();
    });
    
    // 监听价格更新事件
    EventBus.on('priceUpdate', (payload) => {
      const { symbols, data, timestamp } = payload;
      
      // 更新自选股摘要中的价格
      if (AppState.currentTab === 'dashboard') {
        this.updatePricesFromWS(data);
      }
    });
    
    // 监听告警事件
    EventBus.on('alert', (alertData) => {
      if (AppState.currentTab === 'dashboard') {
        this.addAlertToUI(alertData);
      }
    });
    
    // 监听告警日志更新
    EventBus.on('alertLogUpdated', (alertLog) => {
      if (AppState.currentTab === 'dashboard') {
        this.renderAlertsFromLog(alertLog);
      }
    });
    
    this.wsSubscribed = true;
  },
  
  updatePricesFromWS(data) {
    // Batch DOM updates to reduce reflows
    const updates = [];
    
    for (const [symbol, stock] of Object.entries(data)) {
      // Collect watchlist price updates
      const priceEl = document.getElementById(`wl-price-${symbol}`);
      const changeEl = document.getElementById(`wl-change-${symbol}`);
      if (priceEl) updates.push({ el: priceEl, text: Utils.formatPrice(stock.price) });
      if (changeEl) {
        updates.push({ el: changeEl, text: Utils.formatChange(stock.chg_pct) });
        updates.push({ el: changeEl, cls: `stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}` });
      }
      
      // Collect dashboard price updates
      const dashPriceEl = document.getElementById(`dash-price-${symbol}`);
      const dashChangeEl = document.getElementById(`dash-change-${symbol}`);
      if (dashPriceEl) updates.push({ el: dashPriceEl, text: Utils.formatPrice(stock.price) });
      if (dashChangeEl) {
        updates.push({ el: dashChangeEl, text: Utils.formatChange(stock.chg_pct) });
        updates.push({ el: dashChangeEl, cls: `stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}` });
      }
      
      // Update market index display (e.g. 上证指数)
      if (symbol === 'sh000001') {
        const idxEl = document.getElementById('index-sh000001');
        if (idxEl) {
          const valEl = idxEl.querySelector('.metric-value');
          const labelEl = idxEl.querySelector('.metric-label');
          if (valEl) {
            updates.push({ el: valEl, text: stock.price?.toFixed(2) || '--' });
            updates.push({ el: valEl, cls: `metric-value ${Utils.isUp(stock.chg_pct) ? 'positive' : 'negative'}` });
          }
          if (labelEl) {
            updates.push({ el: labelEl, text: `${esc(stock.name || '上证')} ${Utils.formatChange(stock.chg_pct)}` });
          }
        }
      }
    }
    
    // Apply all DOM updates in a single batch (minimize reflow)
    requestAnimationFrame(() => {
      for (const u of updates) {
        if (u.text !== undefined) u.el.textContent = u.text;
        if (u.cls !== undefined) u.el.className = u.cls;
      }
    });
    
    // Update last update time
    const lastUpdateEl = document.getElementById('lastUpdateTime');
    if (lastUpdateEl) {
      lastUpdateEl.textContent = `最后更新: ${new Date().toLocaleTimeString()}`;
    }
  },
  
  addAlertToUI(alertData) {
    const container = document.getElementById('strategyAlerts');
    if (!container) return;
    
    // 如果显示"暂无策略"，先清空
    const noDataEl = container.querySelector('div[style*="color:#8b949e"]');
    if (noDataEl && noDataEl.textContent.includes('暂无')) {
      container.innerHTML = '';
    }
    
    // 创建新的告警项
    const alertEl = document.createElement('div');
    alertEl.className = 'alert-item';
    alertEl.style.cssText = `
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px; background: var(--bg-primary); border-radius: 8px;
      border-left: 3px solid ${alertData.level === 'high' ? '#f85149' : alertData.level === 'medium' ? '#d29922' : '#58a6ff'};
      animation: slideIn 0.3s ease; margin-bottom: 8px;
    `;
    
    const levelEmoji = alertData.level === 'high' ? '🔴' : alertData.level === 'medium' ? '🟡' : '🔵';
    alertEl.innerHTML = `
      <div>
        <div style="font-weight:500">${levelEmoji} ${esc(alertData.type || '告警')}</div>
        <div style="font-size:12px;color:#8b949e">${esc(alertData.message)}</div>
      </div>
      <span style="font-size:11px;color:#8b949e">${esc(new Date(alertData.timestamp).toLocaleTimeString())}</span>
    `;
    
    // 插入到顶部
    container.insertBefore(alertEl, container.firstChild);
    
    // 限制显示数量
    const alerts = container.querySelectorAll('.alert-item');
    if (alerts.length > 10) {
      alerts[alerts.length - 1].remove();
    }
  },
  
  renderAlertsFromLog(alertLog) {
    const container = document.getElementById('strategyAlerts');
    if (!container) return;
    
    if (!alertLog || alertLog.length === 0) {
      container.innerHTML = '<div style="color:#8b949e">暂无告警</div>';
      return;
    }
    
    container.innerHTML = alertLog.slice(0, 10).map(alert => {
      const levelEmoji = alert.level === 'high' ? '🔴' : alert.level === 'medium' ? '🟡' : '🔵';
      return `
        <div class="alert-item" style="
          display: flex; justify-content: space-between; align-items: center;
          padding: 8px; background: var(--bg-primary); border-radius: 8px;
          border-left: 3px solid ${alert.level === 'high' ? '#f85149' : alert.level === 'medium' ? '#d29922' : '#58a6ff'};
          margin-bottom: 8px;
        ">
           <div>
             <div style="font-weight:500">${levelEmoji} ${esc(alert.type || '告警')}</div>
             <div style="font-size:12px;color:#8b949e">${esc(alert.message)}</div>
           </div>
           <span style="font-size:11px;color:#8b949e">${esc(new Date(alert.timestamp).toLocaleTimeString())}</span>
        </div>
      `;
    }).join('');
  },
  
  startAutoRefresh() {
    this.stopAutoRefresh();
    this.timer = setInterval(() => {
      if (AppState.currentTab === 'dashboard') {
        // 如果 WebSocket 断开，使用 HTTP 轮询作为降级
        if (!AppState.wsConnected) {
          this.loadDashboard();
        }
      }
    }, this.refreshInterval);
  },
  
  stopAutoRefresh() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  },
  
  // 在销毁时取消订阅
  destroy() {
    this.stopAutoRefresh();
    if (this.wsSubscribed) {
      EventBus.off('wsReconnected');
      EventBus.off('priceUpdate');
      EventBus.off('alert');
      EventBus.off('alertLogUpdated');
      this.wsSubscribed = false;
    }
  }
};

// 暴露全局
window.Dashboard = Dashboard;
