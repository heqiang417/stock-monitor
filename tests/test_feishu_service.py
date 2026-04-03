"""
Unit Tests for FeishuService
Tests Feishu API interactions with mocked HTTP calls.
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime


# ============ Fixtures ============

@pytest.fixture
def feishu_service():
    """Create a FeishuService instance for testing."""
    from services.feishu_service import FeishuService
    return FeishuService(
        app_id='test_app_id',
        app_secret='test_app_secret',
        default_chat_id='test_chat_id'
    )


@pytest.fixture
def feishu_service_no_creds():
    """Create a FeishuService without credentials."""
    from services.feishu_service import FeishuService
    return FeishuService()


# ============ Init Tests ============

class TestFeishuServiceInit:
    """Test FeishuService initialization."""

    def test_init_with_credentials(self, feishu_service):
        """Test initialization with credentials."""
        assert feishu_service.app_id == 'test_app_id'
        assert feishu_service.app_secret == 'test_app_secret'
        assert feishu_service.default_chat_id == 'test_chat_id'

    def test_init_without_credentials(self, feishu_service_no_creds):
        """Test initialization without credentials."""
        assert feishu_service_no_creds.app_id is None
        assert feishu_service_no_creds.app_secret is None

    def test_token_initially_none(self, feishu_service):
        """Test token is initially None."""
        assert feishu_service.access_token is None
        assert feishu_service.token_expires == 0


# ============ Access Token Tests ============

class TestGetAccessToken:
    """Test access token acquisition."""

    def test_returns_cached_token(self, feishu_service):
        """Test that cached token is returned."""
        feishu_service.access_token = 'cached_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600
        token = feishu_service.get_access_token()
        assert token == 'cached_token'

    def test_fetches_new_token_when_expired(self, feishu_service):
        """Test fetching new token when expired."""
        feishu_service.access_token = 'old_token'
        feishu_service.token_expires = datetime.now().timestamp() - 100  # expired

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'tenant_access_token': 'new_token',
            'expire': 7200
        }

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            token = feishu_service.get_access_token()
            assert token == 'new_token'
            assert feishu_service.access_token == 'new_token'

    def test_returns_none_without_creds(self, feishu_service_no_creds):
        """Test returns None when no credentials."""
        token = feishu_service_no_creds.get_access_token()
        assert token is None

    def test_handles_api_error(self, feishu_service):
        """Test handling of API error response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 9999, 'msg': 'Invalid credentials'}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            token = feishu_service.get_access_token()
            assert token is None

    def test_handles_network_exception(self, feishu_service):
        """Test handling of network exception."""
        with patch('services.feishu_service.requests.post', side_effect=ConnectionError("Network error")):
            token = feishu_service.get_access_token()
            assert token is None

    def test_handles_timeout(self, feishu_service):
        """Test handling of request timeout."""
        with patch('services.feishu_service.requests.post', side_effect=TimeoutError("Timeout")):
            token = feishu_service.get_access_token()
            assert token is None

    def test_token_expiry_includes_buffer(self, feishu_service):
        """Test that token expiry has 60s buffer."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'tenant_access_token': 'new_token',
            'expire': 7200
        }

        before = datetime.now().timestamp()
        with patch('services.feishu_service.requests.post', return_value=mock_response):
            feishu_service.get_access_token()
        after = datetime.now().timestamp()

        # Token should expire before (now + 7200 - 60)
        assert feishu_service.token_expires < after + 7200
        assert feishu_service.token_expires > before + 7200 - 120  # 60s buffer


# ============ Send Message Tests ============

class TestSendMessage:
    """Test send_message method."""

    def test_send_text_message_success(self, feishu_service):
        """Test sending text message successfully."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {
            'code': 0,
            'data': {'message_id': 'msg_123'}
        }

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_message(
                receive_id='user_123',
                msg_type='text',
                content='Hello World'
            )
            assert result['success'] is True
            assert result['message_id'] == 'msg_123'

    def test_send_message_no_token(self, feishu_service_no_creds):
        """Test sending message without token."""
        result = feishu_service_no_creds.send_message(
            receive_id='user_123',
            content='Hello'
        )
        assert result['success'] is False
        assert result['error'] == 'no_token'

    def test_send_message_api_error(self, feishu_service):
        """Test sending message with API error."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 230001, 'msg': 'Invalid receive_id'}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_message(receive_id='bad_id', content='Hello')
            assert result['success'] is False
            assert 'error' in result

    def test_send_message_network_error(self, feishu_service):
        """Test sending message with network error."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        with patch('services.feishu_service.requests.post', side_effect=ConnectionError("Network error")):
            result = feishu_service.send_message(receive_id='user_123', content='Hello')
            assert result['success'] is False

    def test_send_message_dict_content(self, feishu_service):
        """Test sending message with dict content."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'msg_456'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response) as mock_post:
            result = feishu_service.send_message(
                receive_id='user_123',
                msg_type='interactive',
                content={'key': 'value'}
            )
            assert result['success'] is True
            # Verify content was JSON-serialized
            call_kwargs = mock_post.call_args[1]
            assert 'json' in call_kwargs
            assert call_kwargs['json']['msg_type'] == 'interactive'

    def test_send_message_custom_receive_type(self, feishu_service):
        """Test sending with custom receive_id_type."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'msg_789'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response) as mock_post:
            result = feishu_service.send_message(
                receive_id_type='chat_id',
                receive_id='oc_xxx',
                content='Hello group'
            )
            assert result['success'] is True
            # Verify URL has correct receive_id_type
            call_url = mock_post.call_args[0][0]
            assert 'receive_id_type=chat_id' in call_url


# ============ Send Alert Tests ============

class TestSendAlert:
    """Test send_alert method."""

    def test_send_alert_success(self, feishu_service):
        """Test sending alert successfully."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'alert_1'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_alert(
                symbol='sz002149',
                price=55.0,
                change_pct=2.5,
                strategy_name='价格突破',
                level='high',
                receive_id='user_123'
            )
            assert result['success'] is True

    def test_send_alert_no_receive_id(self, feishu_service_no_creds):
        """Test alert without receive_id falls back to default."""
        feishu_service_no_creds.default_receive_id = None
        result = feishu_service_no_creds.send_alert(
            symbol='sz002149',
            price=55.0,
            change_pct=2.5,
            strategy_name='test'
        )
        assert result['success'] is False
        assert result['error'] == 'no_receive_id'

    def test_send_alert_uses_default_chat_id(self, feishu_service):
        """Test alert uses default_chat_id as receive_id."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600
        feishu_service.default_receive_id = 'default_user'

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'alert_2'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_alert(
                symbol='sz002149',
                price=55.0,
                change_pct=2.5,
                strategy_name='test'
            )
            assert result['success'] is True

    def test_send_alert_negative_change(self, feishu_service):
        """Test alert with negative change (下跌)."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'alert_3'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_alert(
                symbol='sz002149',
                price=45.0,
                change_pct=-3.5,
                strategy_name='价格跌破',
                level='warning',
                receive_id='user_123'
            )
            assert result['success'] is True

    def test_send_alert_level_colors(self, feishu_service):
        """Test that different levels produce correct card colors."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'x'}}

        for level, expected_color in [('info', 'blue'), ('warning', 'yellow'), ('high', 'red')]:
            with patch('services.feishu_service.requests.post', return_value=mock_response) as mock_post:
                feishu_service.send_alert(
                    symbol='s1', price=50, change_pct=1,
                    strategy_name='test', level=level, receive_id='u1'
                )
                call_body = mock_post.call_args[1]['json']
                content = json.loads(call_body['content'])
                assert content['header']['template'] == expected_color

    def test_send_alert_unknown_level_defaults_blue(self, feishu_service):
        """Test unknown level defaults to blue."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'x'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response) as mock_post:
            feishu_service.send_alert(
                symbol='s1', price=50, change_pct=1,
                strategy_name='test', level='unknown_level', receive_id='u1'
            )
            call_body = mock_post.call_args[1]['json']
            content = json.loads(call_body['content'])
            assert content['header']['template'] == 'blue'


# ============ Send Stock Alert Tests ============

class TestSendStockAlert:
    """Test send_stock_alert method."""

    def test_send_stock_alert(self, feishu_service):
        """Test send_stock_alert delegates to send_alert."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'x'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_stock_alert(
                stock='sz002149',
                price=55.0,
                chg_pct=2.5,
                strategy_name='突破策略',
                trigger_condition='价格 > ¥50',
                level='high'
            )
            assert result['success'] is True


# ============ Send Test Message Tests ============

class TestSendTestMessage:
    """Test send_test_message method."""

    def test_send_test_message(self, feishu_service):
        """Test sending test message."""
        feishu_service.access_token = 'valid_token'
        feishu_service.token_expires = datetime.now().timestamp() + 3600

        mock_response = MagicMock()
        mock_response.json.return_value = {'code': 0, 'data': {'message_id': 'test_1'}}

        with patch('services.feishu_service.requests.post', return_value=mock_response):
            result = feishu_service.send_test_message(receive_id='user_123')
            assert result['success'] is True

    def test_send_test_message_no_receive_id(self, feishu_service_no_creds):
        """Test test message without receive_id."""
        result = feishu_service_no_creds.send_test_message()
        assert result['success'] is False


# ============ Integration-style Tests ============

class TestFeishuIntegration:
    """Integration-style tests with mocked HTTP."""

    def test_full_flow_token_then_send(self, feishu_service):
        """Test full flow: get token then send message."""
        token_response = MagicMock()
        token_response.json.return_value = {
            'code': 0,
            'tenant_access_token': 'fetched_token',
            'expire': 7200
        }

        send_response = MagicMock()
        send_response.json.return_value = {
            'code': 0,
            'data': {'message_id': 'sent_1'}
        }

        with patch('services.feishu_service.requests.post') as mock_post:
            mock_post.side_effect = [token_response, send_response]
            result = feishu_service.send_message(
                receive_id='user_123',
                content='Hello'
            )
            assert result['success'] is True
            assert mock_post.call_count == 2
