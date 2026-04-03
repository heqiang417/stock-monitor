"""Web UI functional tests using Playwright.

Run standalone: python3 tests/test_web_ui.py
Not a pytest test file - uses custom testcase decorator.
"""
import pytest
pytestmark = pytest.mark.skip(reason="Playwright UI tests - run standalone with: python3 tests/test_web_ui.py")

from playwright.sync_api import sync_playwright
import sys

BASE_URL = "http://localhost:3001"
results = []
TESTS = []


def testcase(name):
    def decorator(func):
        TESTS.append((name, func))
        return func
    return decorator


@testcase("首页加载")
def test_homepage(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    assert page.locator("text=大盘指数").is_visible()
    assert page.locator("text=上证指数").is_visible()


@testcase("自选股列表")
def test_watchlist(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.click("text=股票")
    page.wait_for_timeout(500)
    assert page.locator("table").is_visible()
    assert page.get_by_role("cell", name="贵州茅台").is_visible()


@testcase("策略页面")
def test_strategy(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.click("text=策略")
    page.wait_for_timeout(500)
    assert page.get_by_text("📚 策略库").is_visible()
    assert page.locator("text=我的策略").first.is_visible()


@testcase("告警页面")
def test_alerts(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.click("text=告警")
    page.wait_for_timeout(500)
    assert page.locator("text=告警历史").is_visible()


@testcase("搜索功能")
def test_search(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    search = page.locator("input[placeholder*='搜索']")
    assert search.is_visible()
    search.fill("贵州茅台")
    page.wait_for_timeout(500)


@testcase("大盘指数数据")
def test_market_indexes(page):
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    assert page.locator("text=上证指数").is_visible()
    assert page.locator("text=深证成指").is_visible()
    assert page.locator("text=创业板指").is_visible()


if __name__ == "__main__":
    with sync_playwright() as p:
        print(f"\n🧪 Web UI Tests - {BASE_URL}\n{'='*50}")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for name, func in TESTS:
            try:
                func(page)
                results.append((name, "PASS"))
                print(f"  ✅ {name}")
            except Exception as e:
                results.append((name, f"FAIL: {e}"))
                print(f"  ❌ {name}: {e}")
        browser.close()

    print(f"\n{'='*50}")
    passed = sum(1 for _, r in results if r == "PASS")
    failed = sum(1 for _, r in results if "FAIL" in r)
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")

    if failed > 0:
        print("\nFailed tests:")
        for name, r in results:
            if "FAIL" in r:
                print(f"  ❌ {name}: {r}")
        sys.exit(1)
    print("\n🎉 All tests passed!")
