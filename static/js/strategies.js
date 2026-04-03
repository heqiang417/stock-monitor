/**
 * 策略管理组件
 * 策略库浏览 + 我的策略 + 组合扫描
 */

const Strategies = {
  strategies: [],      // 我的策略（已启用/收藏）
  templates: [],       // 策略模板库
  library: [],         // 策略库（所有可用策略）
  templatesLoaded: false,
  selectedCategory: 'all',
  selectedForScan: [], // 选中用于扫描的策略ID
  
  async load() {
    this.loadCustomTemplates();
    await this.fetch();
    await this.fetchTemplates();
    await this.render();
    this.initBacktestDates();
  },

  initBacktestDates() {
    const endDateEl = document.getElementById('btEndDate');
    const startDateEl = document.getElementById('btStartDate');
    if (endDateEl && !endDateEl.value) endDateEl.valueAsDate = new Date();
    if (startDateEl && !startDateEl.value) {
      const d = new Date();
      d.setMonth(d.getMonth() - 6);
      startDateEl.valueAsDate = d;
    }
  },
  
  async fetch() {
    const data = await API.getStrategies();
    // 我的策略 = complex strategies
    this.strategies = data?.strategies || [];
  },
  
  async fetchTemplates() {
    if (this.templatesLoaded) return;
    try {
      const resp = await fetch('/api/backtest/templates');
      const data = await resp.json();
      this.templates = data.templates || [];
      this.templatesLoaded = true;
    } catch (e) {
      console.error('Failed to fetch templates:', e);
      this.templates = [];
    }
  },
  
  async render() {
    const container = document.getElementById('strategiesContent');
    if (!container) return;
    
    // Reload custom templates from localStorage
    this.loadCustomTemplates();
    
    const categories = [...new Set(this.templates.map(t => t.category))];
    const filteredTemplates = this.selectedCategory === 'all' 
      ? this.templates 
      : this.templates.filter(t => t.category === this.selectedCategory);
    
    container.innerHTML = `
      <!-- 策略扫描控制面板 -->
      <div class="card" style="margin-bottom:16px;border-color:#58a6ff">
        <div class="card-title">
          <span>🔍 组合策略扫描</span>
          <span style="font-size:12px;color:#8b949e">选择策略进行全市场/自选股扫描</span>
        </div>
        <div style="display:flex;flex-direction:column;gap:12px">
          <!-- 已选策略 -->
          <div>
            <label style="font-size:12px;color:#8b949e;margin-bottom:4px;display:block">已选策略 (AND 逻辑):</label>
            <div id="selectedStrategies" style="display:flex;gap:8px;flex-wrap:wrap;min-height:32px;padding:8px;background:var(--bg-primary);border-radius:6px">
              ${this.selectedForScan.length === 0 ? 
                '<span style="color:#8b949e;font-size:12px">请从下方策略库选择策略</span>' :
                this.selectedForScan.map(id => {
                  // 查找策略：先从我的策略找，再从模板找，再从临时策略找
                  let s = this.strategies.find(x => x.id === id);
                  if (!s) s = this.templates.find(x => x.id === id);
                  if (!s && this._tempStrategies && this._tempStrategies[id]) s = this._tempStrategies[id];
                  return s ? `<span class="badge up" style="cursor:pointer" onclick="Strategies.removeFromScan('${esc(id)}')">${esc(s.name)} ✕</span>` : `<span class="badge info">${esc(id)} ✕</span>`;
                }).join('')
              }
            </div>
          </div>
          
          <!-- 扫描按钮 -->
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary" onclick="Strategies.scanWatchlist()" ${this.selectedForScan.length === 0 ? 'disabled' : ''}>
              📋 扫描自选股
            </button>
            <button class="btn btn-primary" onclick="Strategies.scanMarket()" ${this.selectedForScan.length === 0 ? 'disabled' : ''}>
              🌐 全市场扫描
            </button>
            <button class="btn btn-success" onclick="Strategies.saveSelectedToMyStrategies()" ${this.selectedForScan.length === 0 ? 'disabled' : ''}>
              ⭐ 添加到我的策略
            </button>
            <button class="btn btn-secondary" onclick="Strategies.clearScanSelection()">
              清空选择
            </button>
          </div>
          
          <!-- 扫描结果 -->
          <div id="scanResult" style="display:none"></div>
        </div>
      </div>
      
      <!-- 策略库 -->
      <div class="card" style="margin-bottom:16px">
        <div class="card-title">
          <span>📚 策略库</span>
          <span style="font-size:12px;color:#8b949e">浏览所有可用策略，点击收藏添加到"我的策略"</span>
          <button class="btn btn-sm btn-primary" onclick="Strategies.showCreateTemplateForm()">+ 新建模板</button>
        </div>
        
        <!-- 策略模板库 -->
        <div style="margin-bottom:16px">
          <div style="font-weight:600;margin-bottom:8px">📋 预设模板</div>
          <!-- 分类过滤 -->
          <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
            <button class="btn btn-sm ${this.selectedCategory === 'all' ? 'btn-primary' : 'btn-secondary'}" 
                    onclick="Strategies.filterTemplates('all')">全部</button>
            ${categories.map(cat => `
              <button class="btn btn-sm ${this.selectedCategory === cat ? 'btn-primary' : 'btn-secondary'}" 
                      onclick="Strategies.filterTemplates('${esc(cat)}')">${esc(cat)}</button>
            `).join('')}
          </div>
          
          <!-- 模板卡片网格 -->
          <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(280px, 1fr));gap:12px">
            ${filteredTemplates.map(t => `
              <div style="padding:12px;background:var(--bg-primary);border-radius:8px;border:1px solid var(--border-color);cursor:pointer;transition:all 0.2s" 
                   onmouseover="this.style.borderColor='#58a6ff'" 
                   onmouseout="this.style.borderColor='var(--border-color)'">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                  <span style="font-size:20px">${t.icon}</span>
                  <span class="badge ${t.risk_level === '高' ? 'down' : t.risk_level === '低' ? 'up' : 'info'}">${esc(t.risk_level)}风险</span>
                </div>
                <div style="font-weight:600;margin-bottom:4px">${esc(t.name)}</div>
                <div style="font-size:12px;color:#8b949e;margin-bottom:8px">${esc(t.description)}</div>
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <div style="font-size:11px;color:#6e7681">
                    ${esc(t.recommended_period || '')} · ${esc(t.tags.slice(0, 2).join(' / '))}
                  </div>
                  <div style="display:flex;gap:4px">
                    <button class="btn btn-sm btn-primary" onclick="Strategies.applyTemplate('${esc(t.id)}')">应用</button>
                    <button class="btn btn-sm btn-secondary" onclick="Strategies.addToScanFromTemplate('${esc(t.id)}')">+扫描</button>
                  </div>
                </div>
              </div>
            `).join('')}
          </div>
          
          ${filteredTemplates.length === 0 ? 
            '<div style="text-align:center;padding:20px;color:#8b949e">暂无模板</div>' : ''}
        </div>
        
        <!-- 自定义模板列表 -->
        <div id="customTemplates" style="margin-top:16px">
          <div style="font-weight:600;margin-bottom:8px">👤 我的模板</div>
          <div id="customTemplatesList">
            ${this.renderCustomTemplates()}
          </div>
        </div>
      </div>
      
      <!-- 新建模板表单 -->
      <div id="templateEditor" class="card" style="display:none;margin-bottom:16px">
        <div class="card-title">
          <span id="templateEditorTitle">新建模板</span>
          <button class="btn btn-sm btn-secondary" onclick="Strategies.hideTemplateEditor()">取消</button>
        </div>
        ${this.renderTemplateEditor()}
      </div>
      
      <!-- 我的策略 -->
      <div class="card">
        <div class="card-title">
          <span>⚙️ 我的策略</span>
          <button class="btn btn-sm btn-primary" onclick="Strategies.showCreateForm()">+ 新建策略</button>
        </div>
        ${this.strategies.length === 0 ? 
          '<div style="color:#8b949e;text-align:center;padding:20px">暂无策略，可从上方策略库应用模板或手动创建</div>' :
          `<div style="display:flex;flex-direction:column;gap:8px">
            ${this.strategies.map(s => `
              <div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:var(--bg-primary);border-radius:8px;border-left:3px solid ${s.enabled ? '#3fb950' : '#30363d'}">
                <div style="display:flex;align-items:center;gap:12px">
                    <input type="checkbox" ${this.selectedForScan.includes(s.id) ? 'checked' : ''} 
                          onchange="Strategies.toggleScanSelection('${esc(s.id)}')" style="width:16px;height:16px;cursor:pointer">
                  <div>
                    <div style="font-weight:600">${esc(s.name)} ${s.template_name ? `<span style="font-size:11px;color:#8b949e">(来自: ${esc(s.template_name)})</span>` : ''}</div>
                    <div style="font-size:12px;color:#8b949e">
                      ${s.conditions?.length || 0} 个条件 · ${esc(s.logic || 'AND')} · 触发 ${s.trigger_count || 0} 次
                    </div>
                  </div>
                </div>
                <div style="display:flex;gap:8px;align-items:center">
                  <span class="badge ${s.enabled ? 'up' : 'info'}">${s.enabled ? '启用' : '禁用'}</span>
                  <button class="btn btn-sm btn-secondary" onclick="Strategies.edit('${esc(s.id)}')">编辑</button>
                  <button class="btn btn-sm btn-secondary" onclick="Strategies.toggle('${esc(s.id)}', ${!s.enabled})">
                    ${s.enabled ? '禁用' : '启用'}
                  </button>
                  <button class="btn btn-sm btn-secondary" onclick="Strategies.delete('${esc(s.id)}')">删除</button>
                </div>
              </div>
            `).join('')}
          </div>`
        }
      </div>
      
      <!-- 策略编辑器 -->
      <div id="strategyEditor" class="card" style="display:none;margin-top:16px">
        <div class="card-title">
          <span id="editorTitle">新建策略</span>
          <button class="btn btn-sm btn-secondary" onclick="Strategies.hideEditor()">取消</button>
        </div>
        ${this.renderEditor()}
      </div>
      
      <!-- 模板应用确认弹窗 -->
      <div id="templateModal" class="modal" style="display:none">
        <div class="modal-content" style="max-width:500px">
          <div class="modal-header">
            <span id="modalTitle">应用模板</span>
            <button class="btn btn-sm btn-secondary" onclick="Strategies.hideTemplateModal()">✕</button>
          </div>
          <div id="modalBody"></div>
        </div>
      </div>

      <!-- ==================== 回测区域 ==================== -->
      <div class="card" style="margin-top:16px;border-color:#a371f7">
        <div class="card-title">📊 策略回测</div>
        <div class="form-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:12px">
          <div class="form-group">
            <label class="label">股票代码</label>
            <input type="text" class="input" id="btSymbol" value="002149" placeholder="如: 002149">
          </div>
          <div class="form-group">
            <label class="label">策略</label>
            <select class="select" id="btStrategy">
              <option value="ma_cross">MA均线交叉</option>
              <option value="rsi_mean_reversion">RSI均值回归</option>
              <option value="macd_crossover">MACD交叉</option>
              <option value="bollinger_bounce">布林带反弹</option>
              <option value="volume_breakout">成交量突破</option>
              <option value="dual_ma_trend">双均线趋势</option>
              <option value="golden_cross">黄金交叉</option>
            </select>
          </div>
          <div class="form-group">
            <label class="label">开始日期</label>
            <input type="date" class="input" id="btStartDate">
          </div>
          <div class="form-group">
            <label class="label">结束日期</label>
            <input type="date" class="input" id="btEndDate">
          </div>
          <div class="form-group">
            <label class="label">初始资金</label>
            <input type="number" class="input" id="btCapital" value="100000">
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="btn btn-primary" onclick="Strategies.runBacktest()">🚀 运行回测</button>
          <button class="btn btn-info" onclick="Strategies.compareStrategies()">📈 策略对比</button>
          <button class="btn btn-secondary" onclick="Strategies.calculateRisk()">⚠️ 风险分析</button>
        </div>

        <!-- 回测结果 -->
        <div id="btResultCard" style="display:none;margin-top:12px">
          <div style="font-weight:600;margin-bottom:8px">📈 回测结果</div>
          <div id="btResultMetrics" class="metrics-grid"></div>
          <div style="margin-top:8px"><canvas id="btEquityChart" width="800" height="200"></canvas></div>
        </div>

        <!-- 策略对比/风险 -->
        <div id="btCompareCard" style="display:none;margin-top:12px">
          <div id="btCompareResults"></div>
        </div>

        <!-- 交易记录 -->
        <div id="btTradesCard" style="display:none;margin-top:12px">
          <div style="font-weight:600;margin-bottom:8px">📋 交易记录</div>
          <div style="overflow-x:auto">
            <table class="data-table">
              <thead><tr><th>日期</th><th>操作</th><th>价格</th><th>数量</th><th>盈亏</th><th>持仓天数</th></tr></thead>
              <tbody id="btTradesBody"></tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- ==================== Walk-Forward 分析 ==================== -->
      <div class="card" style="margin-top:16px;border-color:#a371f7">
        <div class="card-title">
          <span>🏆 Walk-Forward 分析</span>
          <button class="btn btn-sm btn-primary" onclick="Strategies.loadWalkForward()">加载数据</button>
        </div>
        <p style="color:#8b949e;font-size:12px;margin-bottom:12px">严格禁止时间穿越，策略参数只用训练集选择，验证集和测试集仅做样本外检验</p>
        <div id="wfMetrics" class="metrics-grid" style="margin-bottom:12px"></div>
        <div id="wfTable"></div>
        <div id="wfReport" style="font-size:12px;white-space:pre-wrap;max-height:400px;overflow-y:auto;margin-top:12px;color:#8b949e"></div>
      </div>
    `;
  },
  
  // ==================== 扫描相关 ====================
  
  toggleScanSelection(id) {
    const idx = this.selectedForScan.indexOf(id);
    if (idx >= 0) {
      this.selectedForScan.splice(idx, 1);
    } else {
      this.selectedForScan.push(id);
    }
    this.render();
  },
  
  removeFromScan(id) {
    const idx = this.selectedForScan.indexOf(id);
    if (idx >= 0) {
      this.selectedForScan.splice(idx, 1);
    }
    this.render();
  },
  
  clearScanSelection() {
    this.selectedForScan = [];
    this.render();
  },
  
  async saveSelectedToMyStrategies() {
    if (this.selectedForScan.length === 0) {
      alert('请先选择策略');
      return;
    }
    
    const strategies = this.getScanStrategies();
    if (strategies.length === 0) {
      alert('未找到有效的策略');
      return;
    }
    
    let savedCount = 0;
    for (const s of strategies) {
      // 检查是否已在我的策略中
      const existing = this.strategies.find(x => x.name === s.name || x.id === s.id);
      if (existing) {
        continue; // 已存在，跳过
      }
      
      // 保存到我的策略
      const strategy = {
        id: `strategy_${Date.now()}_${savedCount}`,
        name: s.name,
        enabled: true,
        logic: s.logic || 'AND',
        conditions: s.conditions || [],
        actions: [
          { type: 'notify_feishu', message: `🔔 策略触发: ${s.name}` },
          { type: 'alert_web', level: 'high' }
        ]
      };
      
      await Utils.fetchJSON('/api/strategies/complex', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(strategy)
      });
      
      savedCount++;
    }
    
    if (savedCount > 0) {
      alert(`已添加 ${savedCount} 个策略到"我的策略"`);
      // 清空选择
      this.selectedForScan = [];
      // 重新加载
      await this.load();
    } else {
      alert('所选策略已在"我的策略"中');
    }
  },
  
  addToScanFromTemplate(templateId) {
    // 从模板创建临时策略并添加到扫描
    const tpl = this.templates.find(t => t.id === templateId);
    if (!tpl) return;
    
    // 创建一个临时策略ID
    const tempId = `template_${tpl.id}`;
    
    // 如果不在已选中，添加到选中
    if (!this.selectedForScan.includes(tempId)) {
      this.selectedForScan.push(tempId);
    }
    
    // 保存模板信息到内存供扫描使用
    if (!this._tempStrategies) this._tempStrategies = {};
    this._tempStrategies[tempId] = {
      id: tempId,
      name: tpl.name,
      enabled: true,
      logic: tpl.logic || 'AND',
      conditions: tpl.conditions || []
    };
    
    this.render();
  },
  
  // 获取用于扫描的策略对象
  getScanStrategies() {
    const strategies = [];
    for (const id of this.selectedForScan) {
      // 先从我的策略找
      let s = this.strategies.find(x => x.id === id);
      if (s) {
        strategies.push(s);
        continue;
      }
      // 从临时策略找
      if (this._tempStrategies && this._tempStrategies[id]) {
        strategies.push(this._tempStrategies[id]);
        continue;
      }
      // 从模板找
      const tpl = this.templates.find(t => t.id === id);
      if (tpl) {
        strategies.push({
          id: tpl.id,
          name: tpl.name,
          enabled: true,
          logic: tpl.logic || 'AND',
          conditions: tpl.conditions || []
        });
      }
    }
    return strategies;
  },
  
  // 合并多个策略为一个
  mergeStrategies(strategies) {
    if (strategies.length === 0) return null;
    if (strategies.length === 1) return strategies[0];
    
    // 合并所有条件，使用 AND 逻辑
    const allConditions = [];
    for (const s of strategies) {
      if (s.conditions && s.conditions.length > 0) {
        allConditions.push(...s.conditions);
      }
    }
    
    return {
      id: 'combined_' + Date.now(),
      name: strategies.map(s => s.name).join(' + '),
      enabled: true,
      logic: 'AND',
      conditions: allConditions
    };
  },
  
  async scanWatchlist() {
    const strategies = this.getScanStrategies();
    if (strategies.length === 0) {
      alert('请先选择策略');
      return;
    }
    
    const merged = this.mergeStrategies(strategies);
    
    const resultDiv = document.getElementById('scanResult');
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div class="loading"><div class="loading-spinner"></div>扫描自选股中...</div>';
    
    const data = await Utils.fetchJSON('/api/watchlist/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(merged)
    });
    
    if (!data || !data.stocks || data.stocks.length === 0) {
      resultDiv.innerHTML = `<div style="color:#8b949e;padding:12px">扫描完成，未发现匹配信号</div>`;
      return;
    }
    
    // 保存合并后的策略用于保存
    this._lastMergedStrategy = merged;
    
    resultDiv.innerHTML = `
      <div class="card" style="border-color:#58a6ff">
        <div class="card-title">
          <span>🔍 自选股扫描结果 (${data.count} 个匹配) - 策略: ${esc(merged.name)}</span>
          <button class="btn btn-sm btn-success" onclick="Strategies.saveLastMergedStrategy()">⭐ 保存到我的策略</button>
        </div>
        <table class="data-table">
          <thead>
            <tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th></tr>
          </thead>
          <tbody>
            ${data.stocks.map(s => `
              <tr>
                <td class="stock-symbol">${esc(s.symbol)}</td>
                <td>${esc(s.name || '--')}</td>
                <td>${Utils.formatPrice(s.price)}</td>
                <td class="${Utils.isUp(s.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(s.chg_pct)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;
  },
  
  async scanMarket() {
    const strategies = this.getScanStrategies();
    if (strategies.length === 0) {
      alert('请先选择策略');
      return;
    }
    
    const merged = this.mergeStrategies(strategies);
    
    const resultDiv = document.getElementById('scanResult');
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div class="loading"><div class="loading-spinner"></div>全市场扫描中（可能需要较长时间）...</div>';
    
    const data = await Utils.fetchJSON('/api/v1/market/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy: merged, batch_size: 50 })
    });
    
    if (!data || !data.matches || data.matches.length === 0) {
      resultDiv.innerHTML = `<div style="color:#8b949e;padding:12px">扫描完成，未发现匹配信号</div>`;
      return;
    }
    
    // 保存合并后的策略用于保存
    this._lastMergedStrategy = merged;
    
    resultDiv.innerHTML = `
      <div class="card" style="border-color:#58a6ff">
        <div class="card-title">
          <span>🔍 全市场扫描结果 (${data.count} 个匹配) - 策略: ${esc(merged.name)}</span>
          <button class="btn btn-sm btn-success" onclick="Strategies.saveLastMergedStrategy()">⭐ 保存到我的策略</button>
        </div>
        <div style="font-size:12px;color:#8b949e;margin-bottom:8px">扫描模式: ${esc(data.scan_mode)} · 工作线程: ${esc(data.max_workers)}</div>
        <table class="data-table">
          <thead>
            <tr><th>代码</th><th>名称</th><th>价格</th><th>涨跌幅</th></tr>
          </thead>
          <tbody>
            ${data.matches.slice(0, 50).map(s => `
              <tr>
                <td class="stock-symbol">${esc(s.symbol)}</td>
                <td>${esc(s.name || '--')}</td>
                <td>${Utils.formatPrice(s.price)}</td>
                <td class="${Utils.isUp(s.chg_pct) ? 'up' : 'down'}">${Utils.formatChange(s.chg_pct)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
        ${data.matches.length > 50 ? `<div style="text-align:center;padding:8px;color:#8b949e">还有 ${data.matches.length - 50} 个匹配结果...</div>` : ''}
      </div>
    `;
  },
  
  async saveLastMergedStrategy() {
    if (!this._lastMergedStrategy) {
      alert('没有可保存的策略');
      return;
    }
    
    const s = this._lastMergedStrategy;
    
    // 检查是否已存在
    const existing = this.strategies.find(x => x.name === s.name);
    if (existing) {
      alert('该策略已在"我的策略"中');
      return;
    }
    
    // 保存到我的策略
    const strategy = {
      id: `strategy_${Date.now()}`,
      name: s.name,
      enabled: true,
      logic: s.logic || 'AND',
      conditions: s.conditions || [],
      actions: [
        { type: 'notify_feishu', message: `🔔 策略触发: ${s.name}` },
        { type: 'alert_web', level: 'high' }
      ]
    };
    
    await Utils.fetchJSON('/api/strategies/complex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(strategy)
    });
    
    alert(`策略 "${s.name}" 已保存到"我的策略"`);
    await this.load();
  },
  
  // ==================== 模板管理 ====================
  
  _customTemplates: JSON.parse(localStorage.getItem('customTemplates') || '[]'),
  
  loadCustomTemplates() {
    this._customTemplates = JSON.parse(localStorage.getItem('customTemplates') || '[]');
  },
  
  renderCustomTemplates() {
    if (this._customTemplates.length === 0) {
      return '<div style="color:#8b949e;font-size:12px;padding:8px">暂无自定义模板，点击"+ 新建模板"创建</div>';
    }
    
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(280px, 1fr));gap:12px">
        ${this._customTemplates.map(t => `
          <div style="padding:12px;background:var(--bg-primary);border-radius:8px;border:1px solid #58a6ff;cursor:pointer">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <span style="font-size:20px">📝</span>
              <span class="badge info">自定义</span>
            </div>
            <div style="font-weight:600;margin-bottom:4px">${esc(t.name)}</div>
            <div style="font-size:12px;color:#8b949e;margin-bottom:8px">${esc(t.description || '无描述')}</div>
            <div style="display:flex;gap:4px">
              <button class="btn btn-sm btn-primary" onclick="Strategies.applyCustomTemplate('${esc(t.id)}')">应用</button>
              <button class="btn btn-sm btn-secondary" onclick="Strategies.addToScanFromCustomTemplate('${esc(t.id)}')">+扫描</button>
              <button class="btn btn-sm btn-secondary" onclick="Strategies.deleteCustomTemplate('${esc(t.id)}')">删除</button>
            </div>
          </div>
        `).join('')}
      </div>
    `;
  },
  
  showCreateTemplateForm() {
    document.getElementById('templateEditorTitle').textContent = '新建模板';
    document.getElementById('templateEditor').style.display = 'block';
    // 清空表单
    document.getElementById('templateName').value = '';
    document.getElementById('templateDesc').value = '';
    document.getElementById('templateCategory').value = '自定义';
    document.getElementById('templateRisk').value = '中';
    document.getElementById('templateLogic').value = 'AND';
    document.getElementById('templateConditionsList').innerHTML = '';
  },
  
  hideTemplateEditor() {
    document.getElementById('templateEditor').style.display = 'none';
  },
  
  renderTemplateEditor() {
    return `
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label class="label">模板名称</label>
          <input type="text" id="templateName" class="input" placeholder="输入模板名称">
        </div>
        <div>
          <label class="label">描述</label>
          <input type="text" id="templateDesc" class="input" placeholder="简短描述">
        </div>
        <div style="display:flex;gap:12px">
          <div style="flex:1">
            <label class="label">分类</label>
            <input type="text" id="templateCategory" class="input" value="自定义" placeholder="如: 趋势/震荡">
          </div>
          <div style="flex:1">
            <label class="label">风险等级</label>
            <select id="templateRisk" class="select" style="width:100%">
              <option value="低">低风险</option>
              <option value="中" selected>中风险</option>
              <option value="高">高风险</option>
            </select>
          </div>
        </div>
        <div>
          <label class="label">逻辑关系</label>
          <select id="templateLogic" class="select" style="width:100%">
            <option value="AND">AND (所有条件都满足)</option>
            <option value="OR">OR (任一条件满足)</option>
          </select>
        </div>
        <div>
          <label class="label">条件列表</label>
          <div id="templateConditionsList" style="display:flex;flex-direction:column;gap:8px"></div>
          <button class="btn btn-sm btn-secondary" style="margin-top:8px" onclick="Strategies.addTemplateCondition()">+ 添加条件</button>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn btn-secondary" onclick="Strategies.hideTemplateEditor()">取消</button>
          <button class="btn btn-primary" onclick="Strategies.saveTemplate()">保存模板</button>
        </div>
      </div>
    `;
  },
  
  addTemplateCondition(condition = null) {
    const container = document.getElementById('templateConditionsList');
    const div = document.createElement('div');
    div.className = 'template-condition-item';
    div.style.cssText = 'display:flex;gap:8px;align-items:center;margin-bottom:8px;padding:8px;background:var(--bg-primary);border-radius:6px';
    
    div.innerHTML = `
      <select class="select condition-type" style="width:120px">
        <option value="price" ${condition?.type === 'price' ? 'selected' : ''}>价格</option>
        <option value="change_pct" ${condition?.type === 'change_pct' ? 'selected' : ''}>涨跌幅</option>
        <option value="volume" ${condition?.type === 'volume' ? 'selected' : ''}>成交量</option>
        <option value="volume_surge" ${condition?.type === 'volume_surge' ? 'selected' : ''}>放量倍数</option>
      </select>
      <select class="select condition-operator" style="width:80px">
        <option value=">=" ${condition?.operator === '>=' ? 'selected' : ''}>&gt;=</option>
        <option value=">" ${condition?.operator === '>' ? 'selected' : ''}>&gt;</option>
        <option value="<=" ${condition?.operator === '<=' ? 'selected' : ''}>&lt;=</option>
        <option value="<" ${condition?.operator === '<' ? 'selected' : ''}>&lt;</option>
        <option value="==" ${condition?.operator === '==' ? 'selected' : ''}>=</option>
      </select>
       <input type="number" class="input condition-value" style="width:100px" placeholder="数值" value="${esc(condition?.value || '')}">
       <button class="btn btn-sm btn-secondary" onclick="this.parentElement.remove()">删除</button>
     `;
     
     container.appendChild(div);
   },
   
   async saveTemplate() {
    const name = document.getElementById('templateName').value.trim();
    const desc = document.getElementById('templateDesc').value.trim();
    const category = document.getElementById('templateCategory').value.trim() || '自定义';
    const risk = document.getElementById('templateRisk').value;
    const logic = document.getElementById('templateLogic').value;
    
    if (!name) {
      alert('请输入模板名称');
      return;
    }
    
    const conditions = [];
    document.querySelectorAll('.template-condition-item').forEach(item => {
      const type = item.querySelector('.condition-type').value;
      const operator = item.querySelector('.condition-operator').value;
      const value = parseFloat(item.querySelector('.condition-value').value);
      
      if (!isNaN(value)) {
        conditions.push({ type, operator, value });
      }
    });
    
    if (conditions.length === 0) {
      alert('请至少添加一个条件');
      return;
    }
    
    const template = {
      id: `custom_${Date.now()}`,
      name,
      description: desc,
      category,
      risk_level: risk,
      logic,
      conditions,
      icon: '📝',
      tags: ['自定义'],
      recommended_period: '自定义'
    };
    
    this._customTemplates.push(template);
    localStorage.setItem('customTemplates', JSON.stringify(this._customTemplates));
    
    this.hideTemplateEditor();
    await this.render();
    alert(`模板 "${name}" 已创建！`);
  },
  
  applyCustomTemplate(templateId) {
    const tpl = this._customTemplates.find(t => t.id === templateId);
    if (!tpl) return;
    
    // 使用与 applyTemplate 相同的逻辑
    const modal = document.getElementById('templateModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    
    modalTitle.textContent = `应用模板: ${tpl.name}`;
    modalBody.innerHTML = `
      <div style="margin-bottom:16px">
        <div style="font-size:14px;color:#8b949e;margin-bottom:8px">${esc(tpl.description || '无描述')}</div>
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <span class="badge info">${esc(tpl.category)}</span>
          <span class="badge ${tpl.risk_level === '高' ? 'down' : tpl.risk_level === '低' ? 'up' : 'info'}">${esc(tpl.risk_level)}风险</span>
        </div>
      </div>
      
      <div style="margin-bottom:16px">
        <label class="label">策略名称</label>
        <input type="text" id="templateStrategyName" class="input" value="${esc(tpl.name)}" placeholder="策略名称">
      </div>
      
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" onclick="Strategies.hideTemplateModal()">取消</button>
        <button class="btn btn-primary" onclick="Strategies.confirmApplyCustomTemplate('${esc(tpl.id)}')">确认应用</button>
      </div>
    `;
    
    modal.style.display = 'flex';
  },
  
  async confirmApplyCustomTemplate(templateId) {
    const tpl = this._customTemplates.find(t => t.id === templateId);
    if (!tpl) return;
    
    const name = document.getElementById('templateStrategyName').value.trim() || tpl.name;
    
    const strategy = {
      id: `strategy_${Date.now()}`,
      name: name,
      template_id: templateId,
      template_name: tpl.name,
      enabled: true,
      logic: tpl.logic || 'AND',
      conditions: tpl.conditions || [],
      actions: [
        { type: 'notify_feishu', message: `🔔 策略触发: ${name}` },
        { type: 'alert_web', level: 'high' }
      ]
    };
    
    await Utils.fetchJSON('/api/strategies/complex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(strategy)
    });
    
    this.hideTemplateModal();
    await this.load();
    alert(`策略 "${name}" 已创建！`);
  },
  
  addToScanFromCustomTemplate(templateId) {
    const tpl = this._customTemplates.find(t => t.id === templateId);
    if (!tpl) return;
    
    const tempId = `custom_${tpl.id}`;
    
    if (!this.selectedForScan.includes(tempId)) {
      this.selectedForScan.push(tempId);
    }
    
    if (!this._tempStrategies) this._tempStrategies = {};
    this._tempStrategies[tempId] = {
      id: tempId,
      name: tpl.name,
      enabled: true,
      logic: tpl.logic || 'AND',
      conditions: tpl.conditions || []
    };
    
    this.render();
  },
  
  deleteCustomTemplate(templateId) {
    if (!confirm('确定删除此模板？')) return;
    
    this._customTemplates = this._customTemplates.filter(t => t.id !== templateId);
    localStorage.setItem('customTemplates', JSON.stringify(this._customTemplates));
    this.render();
  },
  
  // ==================== 原有功能（策略管理） ====================
  
  filterTemplates(category) {
    this.selectedCategory = category;
    this.render();
  },
  
  async applyTemplate(templateId) {
    await this.fetchTemplates();
    const tpl = this.templates.find(t => t.id === templateId);
    if (!tpl) return;
    
    const modal = document.getElementById('templateModal');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');
    
    modalTitle.textContent = `应用模板: ${tpl.name}`;
    modalBody.innerHTML = `
      <div style="margin-bottom:16px">
        <div style="font-size:14px;color:#8b949e;margin-bottom:8px">${esc(tpl.description)}</div>
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <span class="badge info">${esc(tpl.category)}</span>
          <span class="badge ${tpl.risk_level === '高' ? 'down' : tpl.risk_level === '低' ? 'up' : 'info'}">${esc(tpl.risk_level)}风险</span>
          <span style="font-size:12px;color:#6e7681">${esc(tpl.recommended_period)}</span>
        </div>
      </div>
      
      <div style="margin-bottom:16px">
        <label class="label">策略名称</label>
        <input type="text" id="templateStrategyName" class="input" value="${esc(tpl.name)}" placeholder="策略名称">
      </div>
      
      <div style="margin-bottom:16px">
        <label class="label">自定义参数 (可选)</label>
        <div id="templateParams">
          ${Object.entries(tpl.default_params || {}).map(([key, val]) => `
            <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
              <span style="width:80px;font-size:12px;color:#8b949e">${esc(key)}</span>
              <input type="number" class="input template-param" data-key="${esc(key)}" value="${esc(val)}" style="flex:1">
            </div>
          `).join('')}
        </div>
      </div>
      
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn btn-secondary" onclick="Strategies.hideTemplateModal()">取消</button>
        <button class="btn btn-primary" onclick="Strategies.confirmApplyTemplate('${esc(tpl.id)}')">确认应用</button>
      </div>
    `;
    
    modal.style.display = 'flex';
  },
  
  async confirmApplyTemplate(templateId) {
    const tpl = this.templates.find(t => t.id === templateId);
    if (!tpl) return;
    
    const name = document.getElementById('templateStrategyName').value.trim() || tpl.name;
    const params = {};
    document.querySelectorAll('.template-param').forEach(input => {
      const key = input.dataset.key;
      params[key] = parseFloat(input.value);
    });
    
    const strategy = {
      id: `strategy_${Date.now()}`,
      name: name,
      template_id: templateId,
      template_name: tpl.name,
      enabled: true,
      logic: tpl.logic || 'AND',
      conditions: tpl.conditions || [],
      actions: [
        { type: 'notify_feishu', message: `🔔 策略触发: ${name}` },
        { type: 'alert_web', level: 'high' }
      ]
    };
    
    await Utils.fetchJSON('/api/strategies/complex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(strategy)
    });
    
    this.hideTemplateModal();
    await this.load();
    alert(`策略 "${name}" 已创建！`);
  },
  
  hideTemplateModal() {
    const modal = document.getElementById('templateModal');
    if (modal) modal.style.display = 'none';
  },
  
  renderEditor() {
    return `
      <div style="display:flex;flex-direction:column;gap:12px">
        <div>
          <label class="label">策略名称</label>
          <input type="text" id="strategyName" class="input" placeholder="输入策略名称">
        </div>
        
        <div>
          <label class="label">逻辑关系</label>
          <select id="strategyLogic" class="select" style="width:100%">
            <option value="AND">AND (所有条件都满足)</option>
            <option value="OR">OR (任一条件满足)</option>
          </select>
        </div>
        
        <div>
          <label class="label">条件列表</label>
          <div id="conditionsList" style="display:flex;flex-direction:column;gap:8px"></div>
          <button class="btn btn-sm btn-secondary" style="margin-top:8px" onclick="Strategies.addCondition()">+ 添加条件</button>
        </div>
        
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn btn-secondary" onclick="Strategies.hideEditor()">取消</button>
          <button class="btn btn-primary" onclick="Strategies.save()">保存策略</button>
        </div>
      </div>
    `;
  },
  
  showCreateForm() {
    this.editingId = null;
    document.getElementById('editorTitle').textContent = '新建策略';
    document.getElementById('strategyName').value = '';
    document.getElementById('strategyLogic').value = 'AND';
    document.getElementById('conditionsList').innerHTML = '';
    document.getElementById('strategyEditor').style.display = 'block';
  },
  
  hideEditor() {
    document.getElementById('strategyEditor').style.display = 'none';
  },
  
  async edit(id) {
    const strategy = this.strategies.find(s => s.id === id);
    if (!strategy) return;
    
    this.editingId = id;
    document.getElementById('editorTitle').textContent = '编辑策略';
    document.getElementById('strategyName').value = strategy.name;
    document.getElementById('strategyLogic').value = strategy.logic || 'AND';
    
    const container = document.getElementById('conditionsList');
    container.innerHTML = '';
    
    (strategy.conditions || []).forEach(c => {
      this.addCondition(c);
    });
    
    document.getElementById('strategyEditor').style.display = 'block';
  },
  
  addCondition(condition = null) {
    const container = document.getElementById('conditionsList');
    const div = document.createElement('div');
    div.className = 'condition-item';
    div.style.cssText = 'display:flex;gap:8px;align-items:center;margin-bottom:8px;padding:8px;background:var(--bg-primary);border-radius:6px';
    
    div.innerHTML = `
      <select class="select condition-type" style="width:120px">
        <option value="price" ${condition?.type === 'price' ? 'selected' : ''}>价格</option>
        <option value="change_pct" ${condition?.type === 'change_pct' ? 'selected' : ''}>涨跌幅</option>
        <option value="volume" ${condition?.type === 'volume' ? 'selected' : ''}>成交量</option>
        <option value="volume_surge" ${condition?.type === 'volume_surge' ? 'selected' : ''}>放量倍数</option>
      </select>
      <select class="select condition-operator" style="width:80px">
        <option value=">=" ${condition?.operator === '>=' ? 'selected' : ''}>&gt;=</option>
        <option value=">" ${condition?.operator === '>' ? 'selected' : ''}>&gt;</option>
        <option value="<=" ${condition?.operator === '<=' ? 'selected' : ''}>&lt;=</option>
        <option value="<" ${condition?.operator === '<' ? 'selected' : ''}>&lt;</option>
        <option value="==" ${condition?.operator === '==' ? 'selected' : ''}>=</option>
      </select>
       <input type="number" class="input condition-value" style="width:100px" placeholder="数值" value="${esc(condition?.value || '')}">
       <button class="btn btn-sm btn-secondary" onclick="this.parentElement.remove()">删除</button>
     `;
     
     container.appendChild(div);
   },
   
   async save() {
    const name = document.getElementById('strategyName').value.trim();
    const logic = document.getElementById('strategyLogic').value;
    
    if (!name) {
      alert('请输入策略名称');
      return;
    }
    
    const conditions = [];
    document.querySelectorAll('.condition-item').forEach(item => {
      const type = item.querySelector('.condition-type').value;
      const operator = item.querySelector('.condition-operator').value;
      const value = parseFloat(item.querySelector('.condition-value').value);
      
      if (!isNaN(value)) {
        conditions.push({ type, operator, value });
      }
    });
    
    if (conditions.length === 0) {
      alert('请至少添加一个条件');
      return;
    }
    
    const strategy = {
      id: this.editingId || `strategy_${Date.now()}`,
      name,
      logic,
      conditions,
      enabled: true,
      actions: [
        { type: 'notify_feishu', message: `🔔 策略触发: ${name}` },
        { type: 'alert_web', level: 'high' }
      ]
    };
    
    await Utils.fetchJSON('/api/strategies/complex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(strategy)
    });
    
    this.hideEditor();
    await this.load();
  },
  
  async toggle(id, enabled) {
    await Utils.fetchJSON('/api/strategies/complex', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, enabled })
    });
    await this.load();
  },
  
  async delete(id) {
    if (!confirm('确定删除此策略？')) return;
    
    await Utils.fetchJSON(`/api/strategies/complex?id=${id}`, { method: 'DELETE' });
    await this.load();
  },

  // ==================== 回测功能 ====================

  async runBacktest() {
    const symbol = document.getElementById('btSymbol').value;
    const strategy = document.getElementById('btStrategy').value;
    const startDate = document.getElementById('btStartDate').value;
    const endDate = document.getElementById('btEndDate').value;
    const capital = parseFloat(document.getElementById('btCapital').value);

    this.showBtLoading();

    try {
      const resp = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, strategy, start_date: startDate || null, end_date: endDate || null, initial_capital: capital })
      });
      const data = await resp.json();
      if (data.error) { alert('回测失败: ' + data.error); return; }
      this.displayBtResult(data);
    } catch (e) { alert('请求失败: ' + e.message); }
  },

  displayBtResult(data) {
    const r = data.result;
    const metricsHtml = `
      <div class="metric-card"><div class="metric-value ${r.total_return_pct >= 0 ? 'positive' : 'negative'}">${r.total_return_pct.toFixed(2)}%</div><div class="metric-label">总收益率</div></div>
      <div class="metric-card"><div class="metric-value">${r.annual_return.toFixed(2)}%</div><div class="metric-label">年化收益</div></div>
      <div class="metric-card"><div class="metric-value negative">${r.max_drawdown_pct.toFixed(2)}%</div><div class="metric-label">最大回撤</div></div>
      <div class="metric-card"><div class="metric-value">${r.sharpe_ratio.toFixed(2)}</div><div class="metric-label">Sharpe比率</div></div>
      <div class="metric-card"><div class="metric-value">${r.win_rate.toFixed(1)}%</div><div class="metric-label">胜率</div></div>
      <div class="metric-card"><div class="metric-value">${r.total_trades}</div><div class="metric-label">交易次数</div></div>
      <div class="metric-card"><div class="metric-value">${r.profit_factor.toFixed(2)}</div><div class="metric-label">盈亏比</div></div>
      <div class="metric-card"><div class="metric-value">${r.avg_hold_days.toFixed(1)}</div><div class="metric-label">平均持仓(天)</div></div>
    `;
    document.getElementById('btResultMetrics').innerHTML = metricsHtml;
    document.getElementById('btResultCard').style.display = 'block';

    this.drawEquityChart(data.equity_curve);

    if (data.trades && data.trades.length > 0) {
      document.getElementById('btTradesBody').innerHTML = data.trades.map(t => `
        <tr>
          <td>${esc(t.date)}</td>
          <td><span class="${t.action.includes('BUY') ? 'up' : 'down'}">${esc(t.action)}</span></td>
          <td>¥${t.price.toFixed(2)}</td>
          <td>${t.quantity}</td>
          <td class="${t.profit >= 0 ? 'up' : 'down'}">${t.profit !== undefined ? '¥' + t.profit.toFixed(2) : '-'}</td>
          <td>${t.hold_days || '-'}</td>
        </tr>
      `).join('');
      document.getElementById('btTradesCard').style.display = 'block';
    }
  },

  drawEquityChart(equityCurve) {
    const canvas = document.getElementById('btEquityChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width, height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    if (!equityCurve || equityCurve.length === 0) return;

    const values = equityCurve.map(p => p.equity);
    const minVal = Math.min(...values), maxVal = Math.max(...values);
    const range = maxVal - minVal || 1;

    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = 20 + (height - 40) * i / 4;
      ctx.beginPath(); ctx.moveTo(60, y); ctx.lineTo(width - 20, y); ctx.stroke();
      const val = maxVal - range * i / 4;
      ctx.fillStyle = '#8b949e'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
      ctx.fillText('¥' + val.toFixed(0), 55, y + 4);
    }

    ctx.beginPath(); ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2;
    equityCurve.forEach((point, i) => {
      const x = 60 + (width - 80) * i / (equityCurve.length - 1);
      const y = 20 + (height - 40) * (1 - (point.equity - minVal) / range);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const lastX = 60 + (width - 80);
    ctx.lineTo(lastX, height - 20); ctx.lineTo(60, height - 20); ctx.closePath();
    const gradient = ctx.createLinearGradient(0, 20, 0, height - 20);
    gradient.addColorStop(0, 'rgba(88, 166, 255, 0.3)'); gradient.addColorStop(1, 'rgba(88, 166, 255, 0.05)');
    ctx.fillStyle = gradient; ctx.fill();
  },

  async compareStrategies() {
    const symbol = document.getElementById('btSymbol').value;
    const strategies = ['ma_cross', 'rsi_mean_reversion', 'macd_crossover', 'bollinger_bounce', 'volume_breakout'];
    this.showBtLoading();

    try {
      const resp = await fetch('/api/backtest/compare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, strategies })
      });
      const data = await resp.json();
      if (data.error) { alert('对比失败: ' + data.error); return; }

      let html = '<table class="data-table"><thead><tr><th>策略</th><th>总收益</th><th>年化</th><th>最大回撤</th><th>Sharpe</th><th>胜率</th><th>交易次数</th></tr></thead><tbody>';
      data.results.forEach(r => {
        if (r.error) { html += `<tr><td>${esc(r.strategy_name)}</td><td colspan="6" style="color:#f85149">${esc(r.error)}</td></tr>`; }
        else {
          html += `<tr><td>${esc(r.strategy_name)}</td><td class="${r.total_return_pct >= 0 ? 'up' : 'down'}">${r.total_return_pct.toFixed(2)}%</td><td>${r.annual_return.toFixed(2)}%</td><td class="down">${r.max_drawdown_pct.toFixed(2)}%</td><td>${r.sharpe_ratio.toFixed(2)}</td><td>${r.win_rate.toFixed(1)}%</td><td>${r.total_trades}</td></tr>`;
        }
      });
      html += '</tbody></table>';
      if (data.best_strategy) {
        html = `<div style="margin-bottom:8px;padding:8px;background:var(--bg-primary);border-radius:8px;border:1px solid #238636;font-size:13px">🏆 最佳策略: <strong>${esc(data.best_strategy.strategy_name)}</strong> (Sharpe: ${data.best_strategy.sharpe_ratio.toFixed(2)})</div>` + html;
      }
      document.getElementById('btCompareResults').innerHTML = html;
      document.getElementById('btCompareCard').style.display = 'block';
    } catch (e) { alert('请求失败: ' + e.message); }
  },

  async calculateRisk() {
    const symbol = document.getElementById('btSymbol').value;
    this.showBtLoading();
    try {
      const resp = await fetch('/api/backtest/risk', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol })
      });
      const data = await resp.json();
      if (data.error) { alert('风险分析失败: ' + data.error); return; }
      const m = data.risk_metrics, s = data.statistics;
      const html = `
        <div class="metrics-grid">
          <div class="metric-card"><div class="metric-value negative">${(m.var_95 * 100).toFixed(2)}%</div><div class="metric-label">VaR (95%)</div></div>
          <div class="metric-card"><div class="metric-value negative">${(m.var_99 * 100).toFixed(2)}%</div><div class="metric-label">VaR (99%)</div></div>
          <div class="metric-card"><div class="metric-value negative">${(m.cvar_95 * 100).toFixed(2)}%</div><div class="metric-label">CVaR (95%)</div></div>
          <div class="metric-card"><div class="metric-value">${(m.annualized_volatility * 100).toFixed(2)}%</div><div class="metric-label">年化波动率</div></div>
          <div class="metric-card"><div class="metric-value">${s.positive_days}</div><div class="metric-label">上涨天数</div></div>
          <div class="metric-card"><div class="metric-value">${s.negative_days}</div><div class="metric-label">下跌天数</div></div>
        </div>
        <div style="margin-top:8px;color:#8b949e;font-size:12px">基于 ${data.data_points} 条历史数据计算。VaR表示在95%/99%置信度下，单日最大可能损失。</div>
      `;
      document.getElementById('btCompareResults').innerHTML = html;
      document.getElementById('btCompareCard').style.display = 'block';
    } catch (e) { alert('请求失败: ' + e.message); }
  },

  showBtLoading() {
    const ids = ['btResultCard', 'btTradesCard', 'btCompareCard'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
    const cc = document.getElementById('btCompareCard');
    if (cc) { cc.style.display = 'block'; document.getElementById('btCompareResults').innerHTML = '<div style="text-align:center;padding:20px;color:#8b949e">⏳ 加载中...</div>'; }
  },

  // ==================== Walk-Forward ====================

  async loadWalkForward() {
    const wfTable = document.getElementById('wfTable');
    if (!wfTable) return;
    wfTable.innerHTML = '<div style="text-align:center;padding:20px;color:#8b949e">加载中...</div>';

    try {
      const [wfResp, reportResp] = await Promise.all([
        fetch('/api/v1/analysis/walkforward'),
        fetch('/api/v1/analysis/walkforward/report')
      ]);
      const wf = await wfResp.json();
      const report = await reportResp.json();

      if (!wf.success) { wfTable.innerHTML = '<div style="color:#f85149">加载失败</div>'; return; }

      const d = wf.data;
      const best = d.final_ranking[0];
      document.getElementById('wfMetrics').innerHTML = `
        <div class="metric-card"><div class="metric-value">${d.phase1_total_combos}</div><div class="metric-label">测试组合数</div></div>
        <div class="metric-card"><div class="metric-value positive">${best.train.avg_return}%</div><div class="metric-label">训练收益</div></div>
        <div class="metric-card"><div class="metric-value positive">${best.val.avg_return}%</div><div class="metric-label">验证收益</div></div>
        <div class="metric-card"><div class="metric-value positive">${best.test.avg_return}%</div><div class="metric-label">测试收益</div></div>
        <div class="metric-card"><div class="metric-value">${best.avg_return_3p}%</div><div class="metric-label">三阶段均值</div></div>
        <div class="metric-card"><div class="metric-value">${best.avg_positive_rate_3p}%</div><div class="metric-label">平均正收益率</div></div>
      `;

      let html = '<table class="data-table"><thead><tr><th>#</th><th>策略</th><th>TOP N</th><th>持有天数</th><th>训练收益</th><th>验证收益</th><th>测试收益</th><th>三阶段均值</th><th>正收益率</th></tr></thead><tbody>';
      d.final_ranking.forEach((r, i) => {
        const badge = i === 0 ? '<span class="badge up">最优</span>' : i < 3 ? '<span class="badge info">TOP3</span>' : '';
        html += `<tr><td>${i + 1} ${badge}</td><td>${esc(r.strategy)}</td><td>${r.top_n}</td><td>${r.hold_days}天</td>
          <td class="${r.train.avg_return >= 0 ? 'up' : 'down'}">${r.train.avg_return}% (${r.train.positive_rate}%)</td>
          <td class="${r.val.avg_return >= 0 ? 'up' : 'down'}">${r.val.avg_return}% (${r.val.positive_rate}%)</td>
          <td class="${r.test.avg_return >= 0 ? 'up' : 'down'}">${r.test.avg_return}% (${r.test.positive_rate}%)</td>
          <td><strong>${r.avg_return_3p}%</strong></td><td>${r.avg_positive_rate_3p}%</td></tr>`;
      });
      html += '</tbody></table>';
      wfTable.innerHTML = html;

      if (report.success) document.getElementById('wfReport').textContent = report.report;
    } catch (e) { wfTable.innerHTML = '<div style="color:#f85149">加载失败</div>'; }
  }
};

// 暴露全局
window.Strategies = Strategies;
