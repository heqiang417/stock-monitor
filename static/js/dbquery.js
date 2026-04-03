/**
 * 数据库查询组件 v2
 * 功能：表浏览、SQL查询、Facet筛选、CSV导出、查询历史、URL状态、外键跳转
 */

const DBQuery = {
  currentTable: null,
  currentOffset: 0,
  currentLimit: 50,
  currentWhere: '',        // 当前 facet 筛选条件
  currentOrder: '',        // 当前排序列
  currentDir: 'DESC',      // 当前排序方向
  queryHistory: [],         // 查询历史
  tableSchema: null,        // 当前表结构缓存
  foreignKeys: null,        // 当前表外键缓存
  facets: null,             // 当前 facet 缓存

  init() {
    this.loadHistory();
  },

  async load() {
    this.init();
    await this.render();
    await this.loadTables();
    this.restoreFromURL();
  },

  // ==================== URL 状态 ====================

  /** 将当前状态编码到 URL hash */
  updateURL() {
    const state = {};
    if (this.currentTable) state.t = this.currentTable;
    if (this.currentOffset > 0) state.o = this.currentOffset;
    if (this.currentWhere) state.f = this.currentWhere;
    if (this.currentOrder) state.s = this.currentOrder + ':' + this.currentDir;
    const sql = document.getElementById('dbSqlInput')?.value?.trim();
    if (sql) state.q = sql;

    const hash = Object.entries(state).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    history.replaceState(null, '', hash ? `#db&${hash}` : '#db');
  },

  /** 从 URL hash 恢复状态 */
  restoreFromURL() {
    const hash = location.hash;
    if (!hash.startsWith('#db')) return;

    const params = new URLSearchParams(hash.slice(1));
    // 只恢复 tab= db 且有实际参数的情况
    if (!params.has('t') && !params.has('q')) return;

    const table = params.get('t');
    const sql = params.get('q');
    const offset = parseInt(params.get('o') || '0');
    const filter = params.get('f') || '';
    const sort = params.get('s') || '';

    if (sort) {
      const [col, dir] = sort.split(':');
      this.currentOrder = col;
      this.currentDir = dir || 'DESC';
    }
    if (filter) this.currentWhere = filter;

    if (sql) {
      const input = document.getElementById('dbSqlInput');
      if (input) {
        input.value = sql;
        this.runQuery();
      }
    } else if (table) {
      this.currentOffset = offset;
      this.selectTable(table, false);
    }
  },

  // ==================== 查询历史 ====================

  loadHistory() {
    try {
      this.queryHistory = JSON.parse(localStorage.getItem('db_query_history') || '[]');
    } catch { this.queryHistory = []; }
  },

  saveToHistory(sql) {
    // 去重 + 限制 10 条
    this.queryHistory = [sql, ...this.queryHistory.filter(s => s !== sql)].slice(0, 10);
    localStorage.setItem('db_query_history', JSON.stringify(this.queryHistory));
  },

  renderHistory() {
    const container = document.getElementById('dbHistory');
    if (!container) return;
    if (this.queryHistory.length === 0) {
      container.innerHTML = '';
      return;
    }
    container.innerHTML = `
      <div style="margin-bottom:6px;font-size:12px;color:#8b949e">📜 最近查询：</div>
      ${this.queryHistory.map(sql => `
        <div style="display:flex;align-items:center;gap:4px;margin-bottom:3px">
          <code style="flex:1;font-size:11px;color:#79c0ff;cursor:pointer;padding:3px 6px;background:var(--bg-primary);border-radius:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                onclick="DBQuery.useHistoryQuery(this.textContent)"
                title="${esc(sql)}">${esc(sql.length > 80 ? sql.slice(0, 80) + '...' : sql)}</code>
        </div>
      `).join('')}
    `;
  },

  useHistoryQuery(sql) {
    const input = document.getElementById('dbSqlInput');
    if (input) {
      input.value = sql;
      this.runQuery();
    }
  },

  // ==================== 渲染 ====================

  async render() {
    const container = document.getElementById('dbContent');
    if (!container) return;
    container.innerHTML = `
      <div style="display:grid;grid-template-columns:240px 1fr;gap:12px;height:calc(100vh - 140px)">
        <!-- 左侧面板 -->
        <div style="display:flex;flex-direction:column;gap:10px;overflow:hidden">
          <!-- 表列表 -->
          <div class="card" style="flex:1;overflow-y:auto;padding:8px">
            <div style="font-weight:600;font-size:14px;margin-bottom:8px;padding:4px">📋 数据表</div>
            <div id="dbTableList">加载中...</div>
          </div>
          <!-- 外键关系 -->
          <div class="card" id="dbFkeysCard" style="display:none;flex-shrink:0;max-height:200px;overflow-y:auto;padding:8px">
            <div style="font-weight:600;font-size:13px;margin-bottom:6px">🔗 外键关系</div>
            <div id="dbFkeys"></div>
          </div>
          <!-- Facet 筛选 -->
          <div class="card" id="dbFacetsCard" style="display:none;flex-shrink:0;max-height:300px;overflow-y:auto;padding:8px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
              <span style="font-weight:600;font-size:13px">🎯 Facet 筛选</span>
              <button class="btn btn-sm btn-secondary" onclick="DBQuery.clearFacets()" style="font-size:11px;padding:2px 6px">清除</button>
            </div>
            <div id="dbFacets"></div>
          </div>
        </div>
        <!-- 右侧内容区 -->
        <div style="display:flex;flex-direction:column;gap:12px;overflow:hidden">
          <!-- SQL 查询框 -->
          <div class="card" style="flex-shrink:0">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <div style="font-weight:600;font-size:14px">💻 SQL 查询</div>
              <div style="display:flex;gap:6px">
                <button class="btn btn-sm btn-secondary" onclick="DBQuery.toggleHistory()" id="dbHistoryBtn" style="font-size:12px">📜 历史</button>
              </div>
            </div>
            <div style="display:flex;gap:8px">
              <textarea id="dbSqlInput" placeholder="输入 SELECT 查询语句..." style="flex:1;height:60px;background:var(--bg-primary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:6px;padding:8px;font-family:monospace;font-size:13px;resize:none"></textarea>
              <button class="btn btn-primary" onclick="DBQuery.runQuery()" style="align-self:flex-end">执行</button>
            </div>
            <!-- 查询历史面板 -->
            <div id="dbHistory" style="display:none;margin-top:8px;padding-top:8px;border-top:1px solid var(--border-color)"></div>
          </div>
          <!-- 查询结果 / 表数据 -->
          <div class="card" style="flex:1;overflow:hidden;display:flex;flex-direction:column">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-shrink:0">
              <div id="dbResultTitle" style="font-weight:600;font-size:14px">选择一个表或输入 SQL</div>
              <div style="display:flex;gap:6px;align-items:center">
                <div id="dbPagination" style="display:flex;gap:4px;align-items:center"></div>
                <button class="btn btn-sm btn-secondary" id="dbExportBtn" onclick="DBQuery.exportCSV()" style="display:none;font-size:12px">📥 导出CSV</button>
              </div>
            </div>
            <!-- 当前筛选条件 -->
            <div id="dbFilterBar" style="display:none;margin-bottom:8px;flex-shrink:0;padding:6px 10px;background:var(--bg-primary);border-radius:6px;font-size:12px">
              <span style="color:#8b949e">筛选：</span>
              <code id="dbFilterWhere" style="color:#79c0ff;flex:1"></code>
              <button onclick="DBQuery.clearFacets()" style="color:#f85149;cursor:pointer;background:none;border:none;font-size:14px" title="清除筛选">✕</button>
            </div>
            <div id="dbSchema" style="margin-bottom:8px;flex-shrink:0"></div>
            <div id="dbResult" style="overflow:auto;flex:1">
              <div style="color:#8b949e;font-size:13px;padding:20px;text-align:center">点击左侧表名查看数据</div>
            </div>
          </div>
        </div>
      </div>
    `;

    // Ctrl+Enter 执行
    const sqlInput = document.getElementById('dbSqlInput');
    if (sqlInput) {
      sqlInput.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          e.preventDefault();
          this.runQuery();
        }
      });
    }
  },

  // ==================== 表列表 ====================

  async loadTables() {
    const container = document.getElementById('dbTableList');
    try {
      const res = await Utils.fetchJSON('/api/v1/db/tables');
      if (!res?.success) { container.innerHTML = '加载失败'; return; }
      container.innerHTML = res.tables.map(t => {
        const isActive = this.currentTable === t.name;
        const bg = isActive ? 'background:var(--bg-tertiary)' : '';
        const displayName = t.display_name || t.name;
        return `
        <div style="padding:8px;cursor:pointer;border-radius:6px;font-size:13px;${bg}"
             onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background='${isActive ? 'var(--bg-tertiary)' : 'transparent'}'"
             onclick="DBQuery.selectTable('${t.name}')">
          <div style="display:flex;justify-content:space-between;align-items:baseline">
            <span style="color:#c9d1d9;font-weight:${isActive ? '600' : '400'}">${esc(displayName)}</span>
            <span style="color:#8b949e;font-size:11px">${t.rows.toLocaleString()}</span>
          </div>
          <div style="font-size:11px;color:#8b949e;margin-top:2px;font-family:monospace">${esc(t.name)}</div>
          ${t.desc ? `<div style="font-size:11px;color:#6e7681;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.desc)}">${esc(t.desc.length > 30 ? t.desc.slice(0, 30) + '…' : t.desc)}</div>` : ''}
        </div>
      `}).join('');
    } catch (e) {
      container.innerHTML = '<div style="color:#f85149;padding:8px">加载失败</div>';
    }
  },

  // ==================== 选择表 ====================

  async selectTable(name, updateUrl = true) {
    this.currentTable = name;
    this.currentOffset = 0;
    if (!this.currentWhere) this.currentWhere = ''; // 保留已有的 facet 筛选
    if (updateUrl) this.updateURL();

    await this.loadTables(); // refresh highlight
    // 并行加载所有数据
    await Promise.all([
      this.loadSchema(name),
      this.loadData(name),
      this.loadFacets(name),
      this.loadForeignKeys(name)
    ]);
  },

  // ==================== 表结构 ====================

  async loadSchema(name) {
    const container = document.getElementById('dbSchema');
    try {
      const res = await Utils.fetchJSON(`/api/v1/db/schema/${name}`);
      if (!res?.success) return;
      this.tableSchema = res.columns;

      // 表描述
      let html = '';
      if (res.display_name || res.table_desc) {
        html += `<div style="margin-bottom:6px;padding:6px 10px;background:var(--bg-primary);border-radius:6px">
          <span style="font-size:14px;font-weight:600;color:#c9d1d9">${esc(res.display_name || '')}</span>
          ${res.table_desc ? `<span style="font-size:12px;color:#8b949e;margin-left:8px">${esc(res.table_desc)}</span>` : ''}
        </div>`;
      }

      // 字段列表（含中文说明）
      html += '<div style="margin-bottom:4px;font-size:12px;color:#8b949e">表结构：</div><div style="display:flex;flex-wrap:wrap;gap:2px">';
      html += res.columns.map(c => {
        const desc = c.desc ? ` title="${esc(c.desc)}"` : '';
        return `<span style="display:inline-block;padding:2px 8px;margin:2px;background:var(--bg-primary);border-radius:4px;font-size:12px;font-family:monospace;cursor:help"${desc}>
          <span style="color:#79c0ff">${esc(c.name)}</span>
          <span style="color:#8b949e">${esc(c.type || 'TEXT')}${c.pk ? ' PK' : ''}${c.notnull ? ' NOT NULL' : ''}</span>
          ${c.desc ? `<span style="color:#6e7681;margin-left:4px;font-size:11px">${esc(c.desc.length > 10 ? c.desc.slice(0, 10) + '…' : c.desc)}</span>` : ''}
        </span>`;
      }).join('');
      html += '</div>';
      container.innerHTML = html;
    } catch (e) {
      container.innerHTML = '';
    }
  },

  // ==================== 外键关系 ====================

  async loadForeignKeys(name) {
    const card = document.getElementById('dbFkeysCard');
    const container = document.getElementById('dbFkeys');
    try {
      const res = await Utils.fetchJSON(`/api/v1/db/fkeys/${name}`);
      if (!res?.success) return;

      const hasData = (res.foreign_keys?.length > 0) || (res.referenced_by?.length > 0);
      card.style.display = hasData ? 'block' : 'none';
      this.foreignKeys = res;

      let html = '';
      if (res.foreign_keys?.length > 0) {
        html += '<div style="font-size:11px;color:#8b949e;margin-bottom:4px">本表引用 →</div>';
        html += res.foreign_keys.map(fk => `
          <div style="padding:3px 0;font-size:12px">
            <span style="color:#f0883e">${esc(fk.from)}</span>
            <span style="color:#8b949e"> → </span>
            <span style="color:#58a6ff;cursor:pointer;text-decoration:underline"
                  onclick="DBQuery.selectTable('${esc(fk.to_table)}')">${esc(fk.to_table)}</span>.<span style="color:#79c0ff">${esc(fk.to_column)}</span>
          </div>
        `).join('');
      }
      if (res.referenced_by?.length > 0) {
        html += '<div style="font-size:11px;color:#8b949e;margin:6px 0 4px">被引用 ←</div>';
        html += res.referenced_by.map(rfk => `
          <div style="padding:3px 0;font-size:12px">
            <span style="color:#58a6ff;cursor:pointer;text-decoration:underline"
                  onclick="DBQuery.selectTable('${esc(rfk.from_table)}')">${esc(rfk.from_table)}</span>.<span style="color:#79c0ff">${esc(rfk.from_column)}</span>
            <span style="color:#8b949e"> → </span>
            <span style="color:#f0883e">${esc(rfk.to_column)}</span>
          </div>
        `).join('');
      }
      container.innerHTML = html;
    } catch {
      card.style.display = 'none';
    }
  },

  // ==================== Facet 筛选 ====================

  async loadFacets(name) {
    const card = document.getElementById('dbFacetsCard');
    const container = document.getElementById('dbFacets');

    if (!this.tableSchema) {
      card.style.display = 'none';
      return;
    }

    // 选最多 6 个适合做 facet 的列（TEXT 或低 cardinality INTEGER）
    const candidateCols = this.tableSchema
      .filter(c => !c.pk)
      .map(c => c.name)
      .slice(0, 8); // 先取前 8 列试

    if (candidateCols.length === 0) {
      card.style.display = 'none';
      return;
    }

    try {
      const res = await Utils.fetchJSON(
        `/api/v1/db/facets/${name}?columns=${candidateCols.join(',')}&limit=15&where=${encodeURIComponent(this.currentWhere || '')}`
      );
      if (!res?.success || !res.facets) {
        card.style.display = 'none';
        return;
      }

      // 过滤掉 too_many 或只有 1 个值的 facet
      const usefulFacets = Object.entries(res.facets).filter(([col, f]) => !f.too_many && f.values.length > 1);

      if (usefulFacets.length === 0) {
        card.style.display = 'none';
        return;
      }

      card.style.display = 'block';
      this.facets = res.facets;

      container.innerHTML = usefulFacets.map(([col, f]) => {
        const items = f.values.map(v => {
          const val = v.value === null ? 'NULL' : String(v.value);
          const isActive = this.currentWhere.includes(`"${col}"`);
          return `
            <div style="display:flex;justify-content:space-between;padding:2px 6px;cursor:pointer;border-radius:3px;font-size:11px;${isActive ? 'background:rgba(88,166,255,0.15)' : ''}"
                 onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background='${isActive ? 'rgba(88,166,255,0.15)' : 'transparent'}'"
                 onclick="DBQuery.toggleFacet('${esc(col)}', '${esc(val.replace(/'/g, "\\'"))}')">
              <span style="color:#c9d1d9;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(val)}">${esc(val.length > 18 ? val.slice(0, 18) + '...' : val)}</span>
              <span style="color:#8b949e;font-size:10px">${v.count.toLocaleString()}</span>
            </div>
          `;
        }).join('');
        return `
          <div style="margin-bottom:8px">
            <div style="font-size:12px;font-weight:500;color:#58a6ff;margin-bottom:3px">${esc(col)} <span style="color:#8b949e;font-size:10px">(${f.distinct})</span></div>
            ${items}
          </div>
        `;
      }).join('');
    } catch {
      card.style.display = 'none';
    }
  },

  toggleFacet(col, value) {
    // 构建 WHERE 条件: "col" = 'value'
    const cond = `"${col}" = '${value}'`;

    if (this.currentWhere === cond) {
      // 点击同一个 facet → 清除
      this.currentWhere = '';
    } else {
      this.currentWhere = cond;
    }

    this.currentOffset = 0;
    this.loadData(this.currentTable);
    this.loadFacets(this.currentTable); // 重新加载 facet 计数
    this.updateURL();
    this.updateFilterBar();
  },

  clearFacets() {
    this.currentWhere = '';
    this.currentOffset = 0;
    if (this.currentTable) {
      this.loadData(this.currentTable);
      this.loadFacets(this.currentTable);
    }
    this.updateURL();
    this.updateFilterBar();
  },

  updateFilterBar() {
    const bar = document.getElementById('dbFilterBar');
    const whereEl = document.getElementById('dbFilterWhere');
    if (!bar) return;
    if (this.currentWhere) {
      bar.style.display = 'flex';
      bar.style.alignItems = 'center';
      bar.style.gap = '6px';
      whereEl.textContent = this.currentWhere;
    } else {
      bar.style.display = 'none';
    }
  },

  // ==================== 数据加载 ====================

  async loadData(name, offset) {
    if (offset !== undefined) this.currentOffset = offset;
    const container = document.getElementById('dbResult');
    const title = document.getElementById('dbResultTitle');
    const pagination = document.getElementById('dbPagination');
    const exportBtn = document.getElementById('dbExportBtn');

    title.textContent = `📊 ${name}`;
    container.innerHTML = '<div style="color:#8b949e;padding:20px;text-align:center">加载中...</div>';
    if (exportBtn) exportBtn.style.display = 'inline-block';

    this.updateFilterBar();

    try {
      let url = `/api/v1/db/data/${name}?limit=${this.currentLimit}&offset=${this.currentOffset}`;
      if (this.currentOrder) url += `&order=${this.currentOrder}&dir=${this.currentDir}`;
      if (this.currentWhere) url += `&where=${encodeURIComponent(this.currentWhere)}`;

      const res = await Utils.fetchJSON(url);
      if (!res?.success) {
        container.innerHTML = `<div style="color:#f85149">${esc(res?.error || '查询失败')}</div>`;
        return;
      }
      this.renderTable(res.columns, res.data);
      // pagination
      const total = res.total;
      const page = Math.floor(this.currentOffset / this.currentLimit) + 1;
      const totalPages = Math.max(1, Math.ceil(total / this.currentLimit));
      const filterLabel = this.currentWhere ? ' (筛选后)' : '';
      pagination.innerHTML = `
        <span style="font-size:12px;color:#8b949e">${total.toLocaleString()}${filterLabel} 行</span>
        ${this.currentOffset > 0 ? `<button class="btn btn-sm btn-secondary" onclick="DBQuery.loadData('${name}', ${Math.max(0, this.currentOffset - this.currentLimit)})">上页</button>` : ''}
        <span style="font-size:12px;color:#8b949e">${page}/${totalPages}</span>
        ${this.currentOffset + this.currentLimit < total ? `<button class="btn btn-sm btn-secondary" onclick="DBQuery.loadData('${name}', ${this.currentOffset + this.currentLimit})">下页</button>` : ''}
      `;
    } catch (e) {
      container.innerHTML = '<div style="color:#f85149;padding:20px;text-align:center">查询失败</div>';
    }
  },

  // ==================== SQL 查询 ====================

  async runQuery() {
    const input = document.getElementById('dbSqlInput');
    const sql = input?.value?.trim();
    if (!sql) return;

    // 保存到历史
    this.saveToHistory(sql);

    const container = document.getElementById('dbResult');
    const title = document.getElementById('dbResultTitle');
    const pagination = document.getElementById('dbPagination');
    const exportBtn = document.getElementById('dbExportBtn');

    title.textContent = '💻 查询结果';
    pagination.innerHTML = '';
    if (exportBtn) exportBtn.style.display = 'inline-block';
    this.currentSql = sql; // 保存当前 SQL 供导出用
    container.innerHTML = '<div style="color:#8b949e;padding:20px;text-align:center">执行中...</div>';

    this.updateURL();

    try {
      const res = await Utils.fetchJSON('/api/v1/db/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql, limit: 500 })
      });
      if (!res?.success) {
        container.innerHTML = `<div style="color:#f85149;padding:12px;background:#f8514911;border-radius:6px;font-family:monospace;font-size:13px">${esc(res?.error || '查询失败')}</div>`;
        if (exportBtn) exportBtn.style.display = 'none';
        return;
      }
      title.textContent = `💻 查询结果 (${res.count} 行)`;
      this.lastQueryColumns = res.columns;
      this.lastQueryData = res.data;
      this.renderTable(res.columns, res.data);
    } catch (e) {
      container.innerHTML = '<div style="color:#f85149;padding:20px">网络错误</div>';
      if (exportBtn) exportBtn.style.display = 'none';
    }
  },

  // ==================== CSV 导出 ====================

  exportCSV() {
    // 如果当前有 SQL 查询，导出 SQL 结果
    if (this.currentSql) {
      // 客户端直接导出已有的数据
      if (this.lastQueryColumns && this.lastQueryData) {
        this._downloadCSV(this.lastQueryColumns, this.lastQueryData, 'query_result.csv');
        return;
      }
    }
    // 如果当前在浏览表，用服务端导出
    if (this.currentTable) {
      let url = `/api/v1/db/export/${this.currentTable}?limit=50000`;
      if (this.currentWhere) url += `&where=${encodeURIComponent(this.currentWhere)}`;
      if (this.currentOrder) url += `&order=${this.currentOrder}&dir=${this.currentDir}`;
      window.open(url, '_blank');
    }
  },

  _downloadCSV(columns, data, filename) {
    const escapeCsv = (val) => {
      if (val === null || val === undefined) return '';
      const s = String(val);
      if (s.includes(',') || s.includes('"') || s.includes('\n')) {
        return '"' + s.replace(/"/g, '""') + '"';
      }
      return s;
    };

    const rows = [columns.map(escapeCsv).join(',')];
    data.forEach(row => {
      rows.push(columns.map(c => escapeCsv(row[c])).join(','));
    });

    const blob = new Blob(['\uFEFF' + rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  // ==================== 历史面板 ====================

  toggleHistory() {
    const panel = document.getElementById('dbHistory');
    const btn = document.getElementById('dbHistoryBtn');
    if (!panel) return;
    const visible = panel.style.display !== 'none';
    panel.style.display = visible ? 'none' : 'block';
    if (!visible) this.renderHistory();
    if (btn) btn.textContent = visible ? '📜 历史' : '📜 隐藏';
  },

  // ==================== 表格渲染 ====================

  renderTable(columns, data) {
    const container = document.getElementById('dbResult');
    if (!data || data.length === 0) {
      container.innerHTML = '<div style="color:#8b949e;padding:20px;text-align:center">无数据</div>';
      return;
    }

    // 检查是否有外键列可链接
    const fkMap = {};
    if (this.foreignKeys?.foreign_keys) {
      this.foreignKeys.foreign_keys.forEach(fk => {
        fkMap[fk.from] = { table: fk.to_table, column: fk.to_column };
      });
    }

    // 列名 → 中文描述映射
    const colDescs = {};
    if (this.tableSchema) {
      this.tableSchema.forEach(c => { if (c.desc) colDescs[c.name] = c.desc; });
    }

    const thead = `<tr>${columns.map(c => {
      const sortable = this.currentTable ? `onclick="DBQuery.sortBy('${esc(c)}')" style="cursor:pointer;` : `style="`;
      const sortIcon = this.currentOrder === c ? (this.currentDir === 'ASC' ? ' ▲' : ' ▼') : '';
      const desc = colDescs[c] ? ` title="${esc(colDescs[c])}"` : '';
      return `<th ${sortable}position:sticky;top:0;background:var(--bg-secondary);white-space:nowrap;padding:6px 10px;font-size:12px;border-bottom:1px solid var(--border-color)"${desc}>${esc(c)}${sortIcon}</th>`;
    }).join('')}</tr>`;

    const tbody = data.map(row => {
      const cells = columns.map(c => {
        let v = row[c];
        const fk = fkMap[c];
        if (v === null || v === undefined) {
          return `<td style="padding:4px 10px;font-size:12px;border-bottom:1px solid var(--border-color)"><span style="color:#484f58">NULL</span></td>`;
        }
        let display;
        if (fk) {
          // 外键值可点击跳转
          display = `<span style="color:#58a6ff;cursor:pointer;text-decoration:underline" onclick="DBQuery.jumpFK('${esc(fk.table)}','${esc(fk.column)}','${esc(String(v))}')">${esc(String(v))}</span>`;
        } else if (typeof v === 'number') {
          display = `<span style="color:#79c0ff">${v}</span>`;
        } else {
          display = esc(String(v));
        }
        return `<td style="padding:4px 10px;font-size:12px;font-family:monospace;white-space:nowrap;max-width:300px;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid var(--border-color)">${display}</td>`;
      }).join('');
      return `<tr onmouseover="this.style.background='var(--bg-tertiary)'" onmouseout="this.style.background='transparent'">${cells}</tr>`;
    }).join('');

    container.innerHTML = `
      <div style="overflow:auto;height:100%">
        <table style="border-collapse:collapse;width:100%">${thead}${tbody}</table>
      </div>
    `;

    // 缓存最近数据供导出
    this.lastQueryColumns = columns;
    this.lastQueryData = data;
  },

  // ==================== 排序 ====================

  sortBy(col) {
    if (this.currentOrder === col) {
      this.currentDir = this.currentDir === 'ASC' ? 'DESC' : 'ASC';
    } else {
      this.currentOrder = col;
      this.currentDir = 'DESC';
    }
    this.currentOffset = 0;
    this.loadData(this.currentTable);
    this.updateURL();
  },

  // ==================== 外键跳转 ====================

  jumpFK(toTable, toColumn, value) {
    // 切换到目标表并自动筛选
    this.currentWhere = `"${toColumn}" = '${value}'`;
    this.selectTable(toTable);
  }
};

window.DBQuery = DBQuery;
