.PHONY: pick sync eval test lint run help

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

pick: ## 运行每日选股
	cd scripts/daily && python daily_pick_combined.py

sync: ## 同步行情数据
	cd scripts/daily && python daily_sync.py

eval: ## 运行策略评估
	python scripts/evaluation/strategy_evaluator.py

test: ## 运行测试
	pytest tests/ -v

lint: ## 代码检查
	ruff check .

format: ## 格式化代码
	ruff format .

run: ## 启动 Flask 服务
	python app.py
