#!/usr/bin/env bash
# run_tests.sh - Run all tests with coverage reporting
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if present
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

echo "============================================"
echo " Stock Monitor App - Test Suite"
echo "============================================"
echo ""

# Check if pytest is available
if ! command -v pytest &>/dev/null; then
    echo "pytest not found. Installing..."
    pip install pytest pytest-cov
fi

echo "Running tests with coverage..."
echo ""

python -m pytest tests/ \
    --tb=short \
    -v \
    --cov=services \
    --cov=models \
    --cov=utils \
    --cov-report=term-missing \
    --cov-config=.coveragerc 2>&1

EXIT_CODE=$?

echo ""
echo "============================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo " ✅ All tests passed!"
else
    echo " ❌ Some tests failed (exit code: $EXIT_CODE)"
fi
echo "============================================"

exit $EXIT_CODE
