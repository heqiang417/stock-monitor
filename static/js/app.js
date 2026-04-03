/**
 * 股票盯盘 - 主应用入口
 * 组件化架构
 * 支持 WebSocket 实时推送
 */

// ==================== 状态管理 ====================
const AppState = {
  currentTab: 'dashboard',
  currentSymbol: '',
  watchlist: [],
  strategies: [],
  scanResults: [],
  marketIndexes: {},
  isTrading: false,
  lastUpdate: null,
  wsConnected: false,
  priceCache: {}  // 缓存实时价格数据
};

// ==================== 请求缓存 ====================
const _requestCache = new Map();
const _CACHE_TTL = 3000; // 3秒内相同URL不重复请求

function _getCacheKey(url, options = {}) {
  const method = options.method || 'GET';
  const body = options.body || '';
  return `${method}:${url}:${body}`;
}

function _getCached(key) {
  const entry = _requestCache.get(key);
  if (entry && (Date.now() - entry.ts) < _CACHE_TTL) {
    return entry.data;
  }
  return null;
}

function _setCache(key, data) {
  _requestCache.set(key, { ts: Date.now(), data });
  // Prevent memory leak: keep at most 50 entries
  if (_requestCache.size > 50) {
    const firstKey = _requestCache.keys().next().value;
    _requestCache.delete(firstKey);
  }
}

// ==================== 工具函数 ====================
const Utils = {
  formatPrice(price) {
    if (price === null || price === undefined) return '--';
    return '¥' + parseFloat(price).toFixed(2);
  },
  
  formatChange(change) {
    if (change === null || change === undefined) return '--';
    const val = parseFloat(change);
    const sign = val >= 0 ? '+' : '';
    return sign + val.toFixed(2) + '%';
  },
  
  formatVolume(vol) {
    if (!vol) return '--';
    const v = parseFloat(vol);
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
    return v.toFixed(0);
  },
  
  formatAmount(amt) {
    if (!amt) return '--';
    const a = parseFloat(amt);
    if (a >= 1e8) return (a / 1e8).toFixed(2) + '亿';
    if (a >= 1e4) return (a / 1e4).toFixed(2) + '万';
    return a.toFixed(0);
  },
  
  isUp(change) {
    return parseFloat(change) >= 0;
  },
  
  async fetchJSON(url, options = {}) {
    const key = _getCacheKey(url, options);
    
    // Check cache for GET requests
    if (!options.method || options.method === 'GET') {
      const cached = _getCached(key);
      if (cached) return cached;
    }
    
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000); // 5s timeout
      
      const resp = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeoutId);
      
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      
      // Cache successful GET responses
      if (!options.method || options.method === 'GET') {
        _setCache(key, data);
      }
      
      return data;
    } catch (e) {
      if (e.name === 'AbortError') {
        console.warn('Request timeout (5s):', url);
      } else {
        console.error('Fetch error:', url, e);
      }
      return null;
    }
  },
  
  debounce(fn, delay = 300) {
    let timer;
    return function(...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  },
  
  getTradingStatus() {
    const now = new Date();
    const hour = now.getHours();
    const minute = now.getMinutes();
    const day = now.getDay();
    
    // 非交易日
    if (day === 0 || day === 6) return false;
    
    // 交易时间：9:30-11:30, 13:00-15:00
    const time = hour * 100 + minute;
    return (time >= 930 && time <= 1130) || (time >= 1300 && time <= 1500);
  }
};

// ==================== API 服务 ====================
const API = {
  baseURL: '',
  
  async getStock(symbol = '002149') {
    return Utils.fetchJSON(`${this.baseURL}/api/stock?symbol=${symbol}`);
  },
  
  async getDashboard() {
    return Utils.fetchJSON(`${this.baseURL}/api/v1/dashboard`);
  },
  
  async getHistory(symbol = '002149', limit = 100) {
    return Utils.fetchJSON(`${this.baseURL}/api/history?symbol=${symbol}&limit=${limit}`);
  },
  
  async getWatchlist() {
    const data = await Utils.fetchJSON(`${this.baseURL}/api/watchlist`);
    return data?.watchlist || data || [];
  },
  
  async addToWatchlist(symbol, name) {
    return Utils.fetchJSON(`${this.baseURL}/api/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, name })
    });
  },
  
  async removeFromWatchlist(symbol) {
    return Utils.fetchJSON(`${this.baseURL}/api/watchlist?symbol=${symbol}`, {
      method: 'DELETE'
    });
  },
  
  async getSectors() {
    return Utils.fetchJSON(`${this.baseURL}/api/sectors`);
  },
  
  async getSectorStocks(sectorName, page = 1, pageSize = 50) {
    return Utils.fetchJSON(`${this.baseURL}/api/sectors/${encodeURIComponent(sectorName)}?page=${page}&pageSize=${pageSize}`);
  },
  
  async getStockDetail(symbol) {
    return Utils.fetchJSON(`${this.baseURL}/api/stock/${symbol}`);
  },
  
  async getStrategies() {
    const data = await Utils.fetchJSON(`${this.baseURL}/api/strategies`);
    // 将 complex 数组作为主策略列表返回
    return {
      strategies: data?.complex || [],
      simple: data?.strategies || {}
    };
  },
  
  async getMarketIndexes() {
    return Utils.fetchJSON(`${this.baseURL}/api/market/indexes`);
  },
  
  async scanMarket() {
    return Utils.fetchJSON(`${this.baseURL}/api/market/scan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scan_all: true })
    });
  },
  
  async runBacktest(symbol, strategy, params = {}) {
    return Utils.fetchJSON(`${this.baseURL}/api/backtest/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, strategy, ...params })
    });
  },
  
  // Alerts API
  async getAlertHistory(page = 1, pageSize = 20, filters = {}) {
    let url = `${this.baseURL}/api/alerts/history?page=${page}&pageSize=${pageSize}`;
    if (filters.level) url += `&level=${filters.level}`;
    if (filters.is_read !== undefined) url += `&is_read=${filters.is_read}`;
    if (filters.stock) url += `&stock=${encodeURIComponent(filters.stock)}`;
    if (filters.strategy_id) url += `&strategy_id=${encodeURIComponent(filters.strategy_id)}`;
    return Utils.fetchJSON(url);
  },
  
  async markAlertsRead(alertIds = null, markAll = false) {
    return Utils.fetchJSON(`${this.baseURL}/api/alerts/mark_read`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(markAll ? { all: true } : { alert_ids: alertIds })
    });
  },
  
  async getUnreadAlertCount() {
    return Utils.fetchJSON(`${this.baseURL}/api/alerts/unread_count`);
  },
  
  async sendFeishuTest(message = '测试消息：股票盯盘系统正常运行') {
    return Utils.fetchJSON(`${this.baseURL}/api/alerts/feishu/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, level: 'info' })
    });
  }
};

// ==================== 事件总线 ====================
const EventBus = {
  listeners: {},
  
  on(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
  },
  
  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(cb => cb(data));
    }
  },
  
  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }
};

// ==================== WebSocket 管理 ====================
const WebSocketManager = {
  socket: null,
  reconnectAttempts: 0,
  maxReconnectAttempts: 10,
  reconnectDelay: 3000,
  
  init() {
    this.connect();
  },
  
  connect() {
    try {
      // 连接到 Socket.IO 服务器
      this.socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: this.maxReconnectAttempts,
        reconnectionDelay: this.reconnectDelay,
        timeout: 10000
      });
      
      this.bindEvents();
    } catch (e) {
      console.error('WebSocket connection error:', e);
      this.scheduleReconnect();
    }
  },
  
  bindEvents() {
    if (!this.socket) return;
    
    // 连接成功
    this.socket.on('connect', () => {
      console.log('✅ WebSocket 已连接');
      AppState.wsConnected = true;
      this.reconnectAttempts = 0;
      StatusBar.updateWSStatus(true);
      
      // 订阅自选股价格更新
      const watchlistSymbols = (AppState.watchlist || []).map(w => w.symbol);
      if (watchlistSymbols.length > 0) {
        this.subscribe(watchlistSymbols);
      }
      
      // WebSocket 重连后自动刷新当前 Tab 数据
      EventBus.emit('wsReconnected');
    });
    
    // 断开连接
    this.socket.on('disconnect', (reason) => {
      console.log('❌ WebSocket 断开:', reason);
      AppState.wsConnected = false;
      StatusBar.updateWSStatus(false);
      
      if (reason === 'io server disconnect') {
        // 服务器主动断开，需要手动重连
        this.scheduleReconnect();
      }
    });
    
    // 重连失败
    this.socket.on('reconnect_failed', () => {
      console.error('WebSocket 重连失败');
      StatusBar.updateWSStatus(false, '重连失败');
    });
    
    // 重连成功
    this.socket.on('reconnect', (attemptNumber) => {
      console.log(`WebSocket 重连成功 (第${attemptNumber}次尝试)`);
      AppState.wsConnected = true;
      StatusBar.updateWSStatus(true);
      
      // 重连后自动刷新当前 Tab 数据
      EventBus.emit('wsReconnected');
    });
    
    // ============ 实时价格更新 ============
    this.socket.on('price_update', (payload) => {
      const { symbols, data, timestamp } = payload;
      if (data && Object.keys(data).length > 0) {
        // 更新价格缓存
        Object.assign(AppState.priceCache, data);
        AppState.lastUpdate = new Date(timestamp);
        
        // 触发价格更新事件
        EventBus.emit('priceUpdate', { symbols, data, timestamp });
        
        // 直接更新 DOM 中的价格显示
        this.updatePriceDisplay(data);
      }
    });
    
    // ============ 告警通知 ============
    this.socket.on('alert', (alertData) => {
      const { type, message, level, symbol, strategy, timestamp } = alertData;
      
      console.log(`🔔 告警 [${level}]: ${message}`);
      
      // 触发告警事件
      EventBus.emit('alert', alertData);
      
      // 显示通知
      this.showNotification(alertData);
      
      // 添加到告警日志
      this.addToAlertLog(alertData);
    });
    
    // ============ 市场状态 ============
    this.socket.on('market_status', (status) => {
      const { trading, connected_clients, timestamp } = status;
      AppState.isTrading = trading;
      StatusBar.update();
      
      // 更新连接数显示（可选）
      const connEl = document.getElementById('wsConnectionCount');
      if (connEl) {
        connEl.textContent = `连接数: ${connected_clients}`;
      }
    });
    
    // 订阅确认
    this.socket.on('subscription_confirmed', (data) => {
      console.log('已订阅:', data.symbols);
    });
    
    // Pong 响应
    this.socket.on('pong', (data) => {
      // 可用于延迟检测
    });
  },
  
  subscribe(symbols) {
    if (this.socket && this.socket.connected) {
      this.socket.emit('subscribe_price', { symbols });
    }
  },
  
  unsubscribe(symbols) {
    if (this.socket && this.socket.connected) {
      this.socket.emit('unsubscribe_price', { symbols });
    }
  },
  
  sendPing() {
    if (this.socket && this.socket.connected) {
      this.socket.emit('ping');
    }
  },
  
  scheduleReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('达到最大重连次数，停止重连');
      StatusBar.updateWSStatus(false, '连接失败');
      return;
    }
    
    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(1.5, this.reconnectAttempts - 1);
    console.log(`${delay}ms 后尝试第 ${this.reconnectAttempts} 次重连...`);
    
    setTimeout(() => {
      if (!AppState.wsConnected) {
        this.connect();
      }
    }, delay);
  },
  
  updatePriceDisplay(data) {
    // 更新页面上的价格显示
    for (const [symbol, stock] of Object.entries(data)) {
      // 更新自选股列表中的价格
      const priceEl = document.getElementById(`wl-price-${symbol}`);
      const changeEl = document.getElementById(`wl-change-${symbol}`);
      
      if (priceEl) {
        priceEl.textContent = Utils.formatPrice(stock.price);
      }
      if (changeEl) {
        changeEl.textContent = Utils.formatChange(stock.chg_pct);
        changeEl.className = `stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}`;
      }
      
      // 更新 Dashboard 中的价格
      const dashPriceEl = document.getElementById(`dash-price-${symbol}`);
      const dashChangeEl = document.getElementById(`dash-change-${symbol}`);
      if (dashPriceEl) {
        dashPriceEl.textContent = Utils.formatPrice(stock.price);
      }
      if (dashChangeEl) {
        dashChangeEl.textContent = Utils.formatChange(stock.chg_pct);
        dashChangeEl.className = `stock-change ${Utils.isUp(stock.chg_pct) ? 'up' : 'down'}`;
      }
    }
  },
  
  showNotification(alertData) {
    // 创建告警通知弹窗
    const container = document.getElementById('alertNotifications') || document.body;
    const notif = document.createElement('div');
    notif.className = `alert-notification alert-${alertData.level || 'info'}`;
    const icon = alertData.level === 'high' ? '🔴' : alertData.level === 'medium' ? '🟡' : '🔵';
    const iconEl = document.createElement('div');
    iconEl.className = 'alert-icon';
    iconEl.textContent = icon;

    const contentEl = document.createElement('div');
    contentEl.className = 'alert-content';

    const titleEl = document.createElement('div');
    titleEl.className = 'alert-title';
    titleEl.textContent = alertData.type || '告警';

    const msgEl = document.createElement('div');
    msgEl.className = 'alert-message';
    msgEl.textContent = alertData.message;

    const timeEl = document.createElement('div');
    timeEl.className = 'alert-time';
    timeEl.textContent = new Date(alertData.timestamp).toLocaleTimeString();

    contentEl.appendChild(titleEl);
    contentEl.appendChild(msgEl);
    contentEl.appendChild(timeEl);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'alert-close';
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', () => notif.remove());

    notif.appendChild(iconEl);
    notif.appendChild(contentEl);
    notif.appendChild(closeBtn);
    
    // 样式
    notif.style.cssText = `
      position: fixed; top: 20px; right: 20px; z-index: 10000;
      background: var(--bg-secondary, #161b22); border: 1px solid var(--border-color, #30363d);
      border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; gap: 12px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3); animation: slideIn 0.3s ease;
      max-width: 400px; color: #c9d1d9;
    `;
    
    container.appendChild(notif);
    
    // 5秒后自动消失
    setTimeout(() => {
      if (notif.parentElement) {
        notif.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => notif.remove(), 300);
      }
    }, 5000);
  },
  
  addToAlertLog(alertData) {
    // 添加到本地告警日志
    if (!AppState.alertLog) {
      AppState.alertLog = [];
    }
    AppState.alertLog.unshift({
      ...alertData,
      receivedAt: new Date()
    });
    // 只保留最近50条
    if (AppState.alertLog.length > 50) {
      AppState.alertLog = AppState.alertLog.slice(0, 50);
    }
    EventBus.emit('alertLogUpdated', AppState.alertLog);
  },
  
  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
      AppState.wsConnected = false;
    }
  }
};

// ==================== Tab 管理 ====================
function showTab(tabName) {
  AppState.currentTab = tabName;
  
  // 更新 Tab 按钮状态
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });
  
  // 显示对应内容
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === `tab-${tabName}`);
    content.classList.toggle('hidden', content.id !== `tab-${tabName}`);
  });
  
  // 触发 tab 切换事件
  EventBus.emit('tabChange', tabName);
  
  // 加载对应数据
  loadTabData(tabName);
}

function loadTabData(tabName) {
  switch (tabName) {
    case 'dashboard':
      Dashboard.load();
      break;
    case 'watchlist':
      Watchlist.load();
      break;
    case 'strategies':
      Strategies.load();
      break;
    case 'alerts':
      AlertsPanel.load();
      break;
    case 'db':
      DBQuery.load();
      break;
  }
}

// ==================== 全局搜索 ====================
const GlobalSearch = {
  init() {
    const input = document.getElementById('globalSearch');
    const results = document.getElementById('searchResults');
    
    if (!input) return;
    
    input.addEventListener('input', Utils.debounce(async (e) => {
      const query = e.target.value.trim();
      if (query.length < 2) {
        results.classList.remove('active');
        results.innerHTML = '';
        return;
      }
      
      this.search(query);
    }, 300));
    
    // 点击外部关闭
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.search-container')) {
        results.classList.remove('active');
      }
    });
    
    // ESC 关闭
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        results.classList.remove('active');
        input.blur();
      }
    });
  },
  
  async search(query) {
    const results = document.getElementById('searchResults');
    
    // 搜索自选股和板块
    const watchlist = await API.getWatchlist() || [];
    const sectors = await API.getSectors() || { sectors: [] };
    
    const matches = [];
    
    // 自选股匹配
    watchlist.forEach(stock => {
      if (stock.symbol.includes(query) || stock.name.includes(query)) {
        matches.push({
          code: stock.symbol,
          name: stock.name,
          type: 'watchlist'
        });
      }
    });
    
    // 板块匹配
    sectors.sectors?.forEach(sector => {
      if (sector.name.includes(query)) {
        matches.push({
          code: sector.name,
          name: `${sector.count || 0} 只股票`,
          type: 'sector'
        });
      }
    });
    
    // 股票代码直接搜索
    if (/^\d{6}$/.test(query)) {
      matches.unshift({
        code: query,
        name: '直接查询',
        type: 'direct'
      });
    }
    
    if (matches.length === 0) {
      results.innerHTML = '<div class="search-result-item"><span style="color:#8b949e">未找到匹配结果</span></div>';
    } else {
      results.innerHTML = matches.slice(0, 10).map(m => `
        <div class="search-result-item" onclick="GlobalSearch.select('${esc(m.code)}', '${esc(m.type)}')">
          <span class="search-result-code">${esc(m.code)}</span>
          <span class="search-result-name">${esc(m.name)}</span>
        </div>
      `).join('');
    }
    
    results.classList.add('active');
  },
  
  select(code, type) {
    const results = document.getElementById('searchResults');
    const input = document.getElementById('globalSearch');
    
    results.classList.remove('active');
    input.value = '';
    
    if (type === 'watchlist' || type === 'direct') {
      showTab('watchlist');
      Watchlist.showStockDetail(code);
    } else if (type === 'sector') {
      showTab('watchlist');
      Watchlist.showSectorDetail(code);
    }
  }
};

// ==================== 状态栏 ====================
const StatusBar = {
  update() {
    const dot = document.getElementById('statusDot');
    const text = document.getElementById('statusText');
    
    AppState.isTrading = Utils.getTradingStatus();
    
    if (AppState.isTrading) {
      dot.className = 'status-dot trading';
      text.textContent = '交易中';
    } else {
      dot.className = 'status-dot closed';
      text.textContent = '休市';
    }
    
    // 更新WebSocket状态指示器
    this.updateWSStatus(AppState.wsConnected);
  },
  
  updateWSStatus(connected, message = null) {
    const wsDot = document.getElementById('wsStatusDot');
    const wsText = document.getElementById('wsStatusText');
    
    if (wsDot) {
      wsDot.className = connected ? 'ws-status-dot connected' : 'ws-status-dot disconnected';
    }
    if (wsText) {
      if (message) {
        wsText.textContent = message;
      } else {
        wsText.textContent = connected ? '实时连接' : '连接断开';
      }
    }
  },
  
  startAutoUpdate() {
    this.update();
    setInterval(() => this.update(), 60000); // 每分钟更新
  }
};

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
  // 初始化搜索
  GlobalSearch.init();
  
  // 初始化状态栏
  StatusBar.startAutoUpdate();
  
  // 初始化 WebSocket 连接
  WebSocketManager.init();
  
  // 全局 ESC 键关闭弹窗
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const modal = document.getElementById('stockDetailModal');
      if (modal && modal.style.display !== 'none') {
        if (typeof Watchlist !== 'undefined' && Watchlist.closeStockDetail) {
          Watchlist.closeStockDetail();
        } else {
          modal.style.display = 'none';
        }
      }
    }
  });
  
  // 绑定 Tab 按钮
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const tab = btn.dataset.tab;
      if (tab) showTab(tab);
    });
  });
  
  // 加载默认 Tab
  showTab('dashboard');
  
  console.log('📈 股票盯盘应用已初始化 (WebSocket 已启用)');
});

// 暴露全局函数
window.showTab = showTab;
window.GlobalSearch = GlobalSearch;
window.Utils = Utils;
window.API = API;
window.AppState = AppState;
window.WebSocketManager = WebSocketManager;
window.EventBus = EventBus;
