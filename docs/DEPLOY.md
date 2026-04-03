# 股票盯盘系统 - 部署文档

## 概述

股票盯盘系统是一个基于 Flask 的股票监控和回测平台，支持实时行情、策略回测、风险分析等功能。

## 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 可用内存：512MB+
- 磁盘空间：1GB+ (用于数据库和日志)

## 快速部署

### 1. 克隆项目

```bash
cd /path/to/stock-monitor-app-py
```

### 2. 使用 Docker Compose 启动

```bash
# 构建并启动服务
docker-compose up -d --build

# 查看日志
docker-compose logs -f

# 检查服务状态
docker-compose ps
```

### 3. 访问应用

- 主页：http://localhost:3001
- 回测页面：http://localhost:3001/backtest
- API 健康检查：http://localhost:3001/api/stock

## 手动 Docker 部署

### 构建镜像

```bash
docker build -t stock-monitor:latest .
```

### 运行容器

```bash
docker run -d \
  --name stock-monitor \
  -p 3001:3001 \
  -v stock_data:/app/data \
  -v stock_logs:/app/logs \
  -e PORT=3001 \
  -e DEBUG=false \
  stock-monitor:latest
```

## 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `PORT` | `3001` | 服务监听端口 |
| `DEBUG` | `false` | 调试模式 |
| `DB_PATH` | `/app/data/stock_data.db` | SQLite 数据库路径 |
| `STOCK_SYMBOL` | `sz002149` | 默认监控股票代码 |
| `CORS_ORIGINS` | `*` | CORS 允许的来源 |
| `QUOTE_CACHE_TTL` | `10` | 行情缓存时间（秒） |
| `FETCH_INTERVAL` | `30` | 数据抓取间隔（秒） |
| `CLEANUP_DAYS` | `30` | 数据保留天数 |

## 数据持久化

应用使用 Docker Volume 持久化以下数据：

- `stock_data`：SQLite 数据库文件
- `stock_logs`：应用日志

查看数据卷：

```bash
docker volume ls | grep stock
docker volume inspect stock-monitor-app-py_stock_data
```

## 管理命令

```bash
# 停止服务
docker-compose down

# 停止并删除数据卷
docker-compose down -v

# 重新构建（不使用缓存）
docker-compose build --no-cache

# 进入容器
docker exec -it stock-monitor-app /bin/bash

# 查看容器日志
docker logs -f stock-monitor-app

# 重启服务
docker-compose restart
```

## 生产环境建议

### 1. 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name stock.example.com;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket support for /api/stream
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 2. 配置 HTTPS

使用 Let's Encrypt 获取免费 SSL 证书：

```bash
sudo certbot --nginx -d stock.example.com
```

### 3. 资源限制

在 `docker-compose.yml` 中添加资源限制：

```yaml
services:
  stock-monitor:
    # ... 其他配置
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '1.0'
        reservations:
          memory: 256M
          cpus: '0.5'
```

### 4. 日志轮转

Docker 自动管理日志轮转，可配置：

```yaml
services:
  stock-monitor:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
```

## API 端点

### 行情数据
- `GET /api/stock` - 获取实时行情
- `GET /api/history` - 获取历史数据
- `GET /api/stock/<symbol>` - 获取指定股票行情

### 策略管理
- `GET /api/strategies` - 获取策略列表
- `POST /api/strategies` - 更新策略
- `PUT /api/strategies/<id>` - 修改策略
- `DELETE /api/strategies/<id>` - 删除策略

### 回测
- `POST /api/backtest/run` - 运行回测
- `POST /api/backtest/compare` - 策略对比
- `POST /api/backtest/risk` - 风险分析
- `GET /api/backtest/strategies` - 可用策略列表

### 自选股
- `GET /api/watchlist` - 获取自选股
- `POST /api/watchlist` - 添加自选股
- `DELETE /api/watchlist` - 删除自选股

### 其他
- `GET /api/sectors` - 板块数据
- `GET /api/market/indexes` - 大盘指数
- `GET /api/kline/<symbol>` - K线数据

## 故障排查

### 服务无法启动

```bash
# 检查容器状态
docker-compose ps

# 查看错误日志
docker-compose logs stock-monitor

# 检查端口占用
ss -tlnp | grep 3001
```

### 数据库问题

```bash
# 进入容器检查数据库
docker exec -it stock-monitor-app ls -la /app/data/

# 检查数据库文件
docker exec -it stock-monitor-app sqlite3 /app/data/stock_data.db ".tables"
```

### API 请求失败

```bash
# 测试 API
curl http://localhost:3001/api/stock

# 检查网络连接
docker exec -it stock-monitor-app curl -v https://qt.gtimg.cn/q=sz002149
```

## 单元测试

### 运行测试

```bash
# 安装测试依赖
pip install pytest

# 运行所有测试
python3 -m pytest tests/ -v

# 运行特定测试文件
python3 -m pytest tests/test_backtest_engine.py -v
python3 -m pytest tests/test_api.py -v
python3 -m pytest tests/test_strategies.py -v

# 运行覆盖率测试
pip install pytest-cov
python3 -m pytest tests/ --cov=. --cov-report=html
```

### 测试覆盖

测试文件位于 `tests/` 目录：

- `test_backtest_engine.py` - 回测引擎测试（策略信号、指标计算）
- `test_api.py` - API 端点测试（路由、响应、错误处理）
- `test_strategies.py` - 策略逻辑测试（条件评估、信号生成）
- `conftest.py` - 共享测试夹具

### Docker 中运行测试

```bash
# 构建并运行测试容器
docker build -t stock-monitor:test .
docker run --rm stock-monitor:test python3 -m pytest tests/ -v
```

## PWA 安装

系统支持 PWA 安装，在支持的浏览器中：

1. 访问 http://localhost:3001
2. 浏览器会显示"安装应用"提示
3. 点击安装后可作为独立应用使用

## 性能调优

### 调整 Worker 数量

在 Dockerfile 中修改 gunicorn 参数：

```dockerfile
CMD ["gunicorn", "--bind", "0.0.0.0:3001", "--workers", "4", "--timeout", "120", "app:app"]
```

建议 workers = CPU 核心数 × 2 + 1

### 数据库优化

对于高频使用，建议：

1. 增加数据清理频率
2. 定期执行 VACUUM
3. 考虑迁移到 PostgreSQL

## 更新部署

```bash
# 拉取最新代码
git pull

# 重新构建并启动
docker-compose up -d --build

# 清理旧镜像
docker image prune -f
```

## 备份与恢复

### 备份

```bash
# 备份数据库
docker exec stock-monitor-app sqlite3 /app/data/stock_data.db ".backup /app/data/backup.db"

# 从容器复制备份
docker cp stock-monitor-app:/app/data/backup.db ./backup.db
```

### 恢复

```bash
# 停止服务
docker-compose down

# 恢复数据库
docker run --rm -v stock_data:/app/data -v $(pwd):/backup alpine \
  cp /backup/backup.db /app/data/stock_data.db

# 启动服务
docker-compose up -d
```

## 许可证

内部项目，仅供参考。
