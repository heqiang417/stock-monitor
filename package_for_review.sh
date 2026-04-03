#!/bin/bash
# 股票盯盘系统 - 打包脚本
# 用于专家评审

set -e

PROJECT_NAME="stock-monitor-app-py"
OUTPUT_DIR="."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="${OUTPUT_DIR}/${PROJECT_NAME}_review_${TIMESTAMP}.tar.gz"

echo "📦 开始打包 ${PROJECT_NAME}..."

# 创建临时目录
TMP_DIR=$(mktemp -d)
echo "📁 临时目录: ${TMP_DIR}"

# 复制核心文件
echo "📋 复制核心文件..."
cp -r \
    README.md \
    app.py \
    config.py \
    backtest_api.py \
    backtest_engine.py \
    download_all_history.py \
    requirements.txt \
    Dockerfile \
    docker-compose.yml \
    DEPLOY.md \
    PACKAGE_REVIEW.md \
    .gitignore \
    strategies.json \
    routes/ \
    services/ \
    models/ \
    static/ \
    templates/ \
    tests/ \
    "${TMP_DIR}/"

# 创建 .env.example（如果不存在）
if [ ! -f "${TMP_DIR}/.env.example" ]; then
    cat > "${TMP_DIR}/.env.example" << 'EOF'
# 环境变量配置示例
FLASK_ENV=production
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///stock_data.db
EOF
fi

# 创建 README.md
cat > "${TMP_DIR}/README.md" << 'EOF'
# 股票盯盘系统

## 快速开始

```bash
# Docker Compose
docker-compose up -d --build

# 或本地运行
pip install -r requirements.txt
python app.py
```

访问: http://localhost:3001

详细说明: 见 PACKAGE_REVIEW.md 和 DEPLOY.md
EOF

# 打包
echo "📦 创建 tar.gz 包..."
cd "${TMP_DIR}"
FULL_OUTPUT_PATH="${OLDPWD}/${OUTPUT_FILE}"
tar -czf "${FULL_OUTPUT_PATH}" *
cd - > /dev/null

# 清理
rm -rf "${TMP_DIR}"

# 统计
echo ""
echo "✅ 打包完成!"
echo "📄 文件: ${OUTPUT_FILE}"
echo "📊 大小: $(du -sh ${OUTPUT_FILE} | cut -f1)"
echo ""
echo "📋 包含内容:"
tar -tzf "${OUTPUT_FILE}" | head -30
echo "..."
echo ""
echo "🔗 解压: tar -xzf ${OUTPUT_FILE}"
