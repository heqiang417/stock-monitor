"""
Unit Tests for utils/__init__.py
Tests is_trading_time function.
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestIsTradingTime:
    """Test is_trading_time function."""

    def test_weekday_morning_trading(self):
        """Test weekday during morning session (9:30-11:30)."""
        from utils import is_trading_time
        # Wednesday 10:00
        mock_now = datetime(2024, 3, 20, 10, 0, 0)
        with patch('utils.datetime', MagicMock(now=MagicMock(return_value=mock_now), wraps=datetime)):
            # We need to patch datetime.now specifically
            pass
        # Simpler: just patch at module level
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 10, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_weekday_afternoon_trading(self):
        """Test weekday during afternoon session (13:00-15:00)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 14, 30, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_weekday_lunch_break(self):
        """Test weekday during lunch break (11:31-12:59)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 12, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False

    def test_weekday_before_open(self):
        """Test weekday before market opens (before 9:30)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 9, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False

    def test_weekday_after_close(self):
        """Test weekday after market closes (after 15:00)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 15, 30, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False

    def test_saturday_not_trading(self):
        """Test Saturday is not trading time."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 16, 10, 0, 0)  # Saturday
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False

    def test_sunday_not_trading(self):
        """Test Sunday is not trading time."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 17, 10, 0, 0)  # Sunday
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False

    def test_morning_session_boundary_start(self):
        """Test exactly at morning session start (9:30)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 9, 30, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_morning_session_boundary_end(self):
        """Test exactly at morning session end (11:30)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 11, 30, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_afternoon_session_boundary_start(self):
        """Test exactly at afternoon session start (13:00)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 13, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_afternoon_session_boundary_end(self):
        """Test exactly at afternoon session end (15:00)."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 20, 15, 0, 0)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is True

    def test_weekend_saturday_trading_hours(self):
        """Test Saturday during normal trading hours."""
        from utils import is_trading_time
        with patch('utils.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2024, 3, 16, 10, 0, 0)  # Saturday 10:00
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            assert is_trading_time() is False
