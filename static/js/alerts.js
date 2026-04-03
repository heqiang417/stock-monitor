/**
 * Alerts Panel - 告警历史管理
 * 支持分页、筛选、标记已读
 */

const AlertsPanel = {
  currentPage: 1,
  pageSize: 20,
  totalPages: 1,
  totalAlerts: 0,
  filters: {
    level: '',
    is_read: '',
    stock: '',
    strategy_id: ''
  },

  async load() {
    await this.render();
    await this.loadAlerts();
  },

  async render() {
    const container = document.getElementById('alertsContent');
    if (!container) return;

    container.innerHTML = `
      <div class="card">
        <div class="card-title">
          <span>🔔 告警历史</span>
          <div style="display:flex;gap:8px;">
            <button class="btn btn-sm btn-info" onclick="AlertsPanel.sendTestAlert()">📤 发送测试</button>
            <button class="btn btn-sm btn-secondary" onclick="AlertsPanel.markAllRead()">全部已读</button>
          </div>
        </div>

        <!-- 筛选栏 -->
        <div class="form-grid" style="margin-bottom:12px;">
          <div class="form-group">
            <label class="label">级别</label>
            <select class="select" id="alertFilterLevel" onchange="AlertsPanel.applyFilters()">
              <option value="">全部</option>
              <option value="high">🔴 高</option>
              <option value="medium">🟡 中</option>
              <option value="low">🔵 低</option>
              <option value="info">⚪ 信息</option>
            </select>
          </div>
          <div class="form-group">
            <label class="label">状态</label>
            <select class="select" id="alertFilterRead" onchange="AlertsPanel.applyFilters()">
              <option value="">全部</option>
              <option value="0">未读</option>
              <option value="1">已读</option>
            </select>
          </div>
          <div class="form-group">
            <label class="label">股票代码</label>
            <input type="text" class="input" id="alertFilterStock" placeholder="如: 002149" oninput="AlertsPanel.debounceFilter()">
          </div>
        </div>

        <!-- 告警表格 -->
        <div style="overflow-x:auto;">
          <table class="trades-table" id="alertTable">
            <thead>
              <tr>
                <th><input type="checkbox" id="alertSelectAll" onclick="AlertsPanel.toggleSelectAll()"></th>
                <th>时间</th>
                <th>级别</th>
                <th>股票</th>
                <th>策略</th>
                <th>触发条件</th>
                <th>价格</th>
                <th>消息</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody id="alertTableBody">
              <tr><td colspan="9" style="text-align:center;color:#8b949e;padding:20px;">加载中...</td></tr>
            </tbody>
          </table>
        </div>

        <!-- 分页 -->
        <div id="alertPagination" style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap;gap:8px;"></div>

        <!-- 批量操作 -->
        <div style="margin-top:12px;display:flex;gap:8px;">
          <button class="btn btn-sm btn-primary" onclick="AlertsPanel.markSelectedRead()">✅ 标记选中为已读</button>
        </div>
      </div>
    `;
  },

  async loadAlerts(page = 1) {
    this.currentPage = page;
    
    try {
      const data = await API.getAlertHistory(page, this.pageSize, this.filters);
      
      if (!data.success) {
        this.showError('加载失败: ' + (data.error || '未知错误'));
        return;
      }

      this.totalAlerts = data.pagination.total;
      this.totalPages = data.pagination.totalPages;
      this.renderAlertTable(data.alerts, data.pagination);
    } catch (e) {
      this.showError('请求失败: ' + e.message);
    }
  },

  renderAlertTable(alerts, pagination) {
    const tbody = document.getElementById('alertTableBody');
    if (!tbody) return;

    if (!alerts || alerts.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#8b949e;padding:20px;">暂无告警记录</td></tr>';
      document.getElementById('alertPagination').innerHTML = '';
      return;
    }

    const levelEmoji = { high: '🔴', medium: '🟡', low: '🔵', info: '⚪' };

    tbody.innerHTML = alerts.map(a => {
      const ts = new Date(a.timestamp);
      const timeStr = ts.toLocaleString('zh-CN', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      });
      const readClass = a.is_read ? 'color:#8b949e' : 'color:#fff;font-weight:600';
      const opacity = a.is_read ? 'opacity:0.7;' : '';

      return `<tr style="${readClass};${opacity}">
        <td><input type="checkbox" class="alert-checkbox" value="${esc(a.id)}"></td>
        <td>${esc(timeStr)}</td>
        <td>${levelEmoji[a.level] || '⚪'} ${esc(a.level)}</td>
        <td>${esc(a.stock || '-')}</td>
        <td>${esc(a.strategy_id || '-')}</td>
        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(a.trigger_condition || '')}">${esc(a.trigger_condition || '-')}</td>
        <td>${a.price ? '¥' + parseFloat(a.price).toFixed(2) : '-'}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(a.message || '')}">${esc(a.message || '-')}</td>
        <td>${a.is_read ? '<span style="color:#8b949e">已读</span>' : '<span style="color:#f85149;font-weight:600;">未读</span>'}</td>
      </tr>`;
    }).join('');

    // 分页
    const p = pagination;
    let pageHtml = `<span>第 ${p.page}/${p.totalPages} 页 (共 ${p.total} 条)</span>`;
    pageHtml += `<div style="display:flex;gap:4px;">`;
    if (p.hasPrev) pageHtml += `<button class="btn btn-sm btn-secondary" onclick="AlertsPanel.loadAlerts(${p.page - 1})">上一页</button>`;
    if (p.hasNext) pageHtml += `<button class="btn btn-sm btn-secondary" onclick="AlertsPanel.loadAlerts(${p.page + 1})">下一页</button>`;
    pageHtml += `</div>`;
    document.getElementById('alertPagination').innerHTML = pageHtml;
  },

  applyFilters() {
    this.filters.level = document.getElementById('alertFilterLevel').value;
    this.filters.is_read = document.getElementById('alertFilterRead').value;
    this.filters.stock = document.getElementById('alertFilterStock').value;
    this.loadAlerts(1);
  },

  debounceTimer: null,
  debounceFilter() {
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(() => this.applyFilters(), 500);
  },

  toggleSelectAll() {
    const selectAll = document.getElementById('alertSelectAll').checked;
    document.querySelectorAll('.alert-checkbox').forEach(cb => cb.checked = selectAll);
  },

  async markSelectedRead() {
    const checked = Array.from(document.querySelectorAll('.alert-checkbox:checked')).map(cb => parseInt(cb.value));
    if (checked.length === 0) {
      alert('请先选择要标记的告警');
      return;
    }

    try {
      const data = await API.markAlertsRead(checked);
      if (data.success) {
        await this.loadAlerts(this.currentPage);
        EventBus.emit('alertRead', checked);
      } else {
        alert('标记失败: ' + (data.error || '未知错误'));
      }
    } catch (e) {
      alert('请求失败: ' + e.message);
    }
  },

  async markAllRead() {
    if (!confirm('确定要将所有告警标记为已读吗？')) return;

    try {
      const data = await API.markAlertsRead(null, true);
      if (data.success) {
        await this.loadAlerts(this.currentPage);
        EventBus.emit('alertRead', 'all');
      } else {
        alert('标记失败: ' + (data.error || '未知错误'));
      }
    } catch (e) {
      alert('请求失败: ' + e.message);
    }
  },

  async sendTestAlert() {
    const message = prompt('输入测试消息:', '测试消息：股票盯盘系统飞书通知正常运行');
    if (!message) return;

    try {
      const data = await API.sendFeishuTest(message);
      if (data.success) {
        alert('✅ 飞书测试消息已发送');
      } else {
        alert('❌ 发送失败: ' + (data.error || '未知错误'));
      }
    } catch (e) {
      alert('请求失败: ' + e.message);
    }
  },

  showError(msg) {
    const tbody = document.getElementById('alertTableBody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:#f85149;padding:20px;">${esc(msg)}</td></tr>`;
    }
  },

  escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
};

// Expose globally
window.AlertsPanel = AlertsPanel;
