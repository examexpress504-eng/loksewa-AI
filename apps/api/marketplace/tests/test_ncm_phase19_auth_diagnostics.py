from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status
from django.contrib.auth import get_user_model
import requests

from marketplace.models import NCMConfiguration, clean_ncm_token
from marketplace.ncm_service import NCMService

User = get_user_model()


class NCMPhase19AuthDiagnosticsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            username="phase19_admin",
            email="admin_phase19@loksewa.com",
            password="testpassword123",
            role="super-admin"
        )
        self.client.force_authenticate(user=self.admin)
        self.config = NCMConfiguration.get_settings()
        self.config.is_enabled = True
        self.config.environment = 'demo'
        self.config.custom_base_url = ''
        self.config.custom_api_token = ''
        self.config.save()

    def test_01_clean_ncm_token_sanitization(self):
        """Verify clean_ncm_token strips whitespace, quotes, and prefix headers."""
        self.assertEqual(clean_ncm_token(""), "")
        self.assertEqual(clean_ncm_token(None), "")
        self.assertEqual(clean_ncm_token("   abc123token   "), "abc123token")
        self.assertEqual(clean_ncm_token('"abc123token"'), "abc123token")
        self.assertEqual(clean_ncm_token("'abc123token'"), "abc123token")
        self.assertEqual(clean_ncm_token("Token abc123token"), "abc123token")
        self.assertEqual(clean_ncm_token("token: abc123token"), "abc123token")
        self.assertEqual(clean_ncm_token("Bearer abc123token"), "abc123token")
        self.assertEqual(clean_ncm_token("bearer: abc123token"), "abc123token")
        self.assertEqual(clean_ncm_token("Authorization: Token abc123token"), "abc123token")
        self.assertEqual(clean_ncm_token("\r\n  Token abc123token \n"), "abc123token")

    def test_02_endpoint_and_environment_consistency(self):
        """Verify get_effective_base_url strictly follows environment setting without silent switches."""
        self.config.environment = 'production'
        self.config.custom_base_url = ''
        self.config.save()
        self.assertEqual(self.config.get_effective_base_url(), 'https://portal.nepalcanmove.com/api/')

        self.config.environment = 'demo'
        self.config.save()
        self.assertEqual(self.config.get_effective_base_url(), 'https://demo.nepalcanmove.com/api/')

        # Custom base URL override takes precedence if set
        self.config.custom_base_url = 'https://custom-proxy.loksewa.com/api/'
        self.config.save()
        self.assertEqual(self.config.get_effective_base_url(), 'https://custom-proxy.loksewa.com/api/')

    @patch.dict('os.environ', {'NCM_API_TOKEN': 'render_env_token_456'})
    @override_settings(NCM_API_TOKEN="render_env_token_456")
    def test_03_credential_precedence_and_source_tracking(self):
        """Verify database custom token takes precedence over Render environment token."""
        # 1. No database custom token: source is RENDER_ENVIRONMENT_TOKEN
        self.config.custom_api_token = ''
        self.config.save()
        self.assertEqual(self.config.get_token_source(), 'RENDER_ENVIRONMENT_TOKEN')
        self.assertEqual(self.config.get_effective_token(), 'render_env_token_456')

        service = NCMService()
        self.assertEqual(service._token_source, 'RENDER_ENVIRONMENT_TOKEN')
        self.assertEqual(service.api_token, 'render_env_token_456')

        # 2. Database custom token set: source is DATABASE_CUSTOM_TOKEN
        self.config.custom_api_token = 'db_custom_token_789'
        self.config.save()
        self.assertEqual(self.config.get_token_source(), 'DATABASE_CUSTOM_TOKEN')
        self.assertEqual(self.config.get_effective_token(), 'db_custom_token_789')

        service_db = NCMService()
        self.assertEqual(service_db._token_source, 'DATABASE_CUSTOM_TOKEN')
        self.assertEqual(service_db.api_token, 'db_custom_token_789')

    @patch.dict('os.environ', {'NCM_API_TOKEN': ''})
    @override_settings(NCM_API_TOKEN="")
    def test_04_missing_credential_diagnostics(self):
        """Verify test_connection returns MISSING_CREDENTIALS safely without making network requests."""
        self.config.custom_api_token = ''
        self.config.save()

        service = NCMService()
        res = service.test_connection()

        self.assertFalse(res['success'])
        self.assertEqual(res['auth_result'], 'MISSING_CREDENTIALS')
        self.assertFalse(res['credential_present'])
        self.assertEqual(res['token_source'], 'MISSING')
        self.assertIsNone(res['http_status'])
        self.assertIn("not configured", res['error'].lower())

    @override_settings(NCM_API_TOKEN="sample_test_token")
    @patch('marketplace.ncm_service.NCMService.get_branches')
    def test_05_http_401_invalid_token_diagnostics(self, mock_get_branches):
        """Verify test_connection properly captures and diagnoses HTTP 401 invalid credentials."""
        mock_get_branches.side_effect = requests.exceptions.HTTPError(
            "401 Client Error: Unauthorized for url: https://demo.nepalcanmove.com/api/v2/branches",
            response=MagicMock(status_code=401, text='{"detail":"Invalid token."}')
        )

        service = NCMService()
        res = service.test_connection()

        self.assertFalse(res['success'])
        self.assertEqual(res['auth_result'], 'INVALID_TOKEN')
        self.assertTrue(res['credential_present'])
        self.assertEqual(res['http_status'], 401)
        self.assertIn("HTTP 401: Invalid token", res['error'])
        # Never reveals credentials in diagnostics
        self.assertNotIn("sample_test_token", str(res))

    @override_settings(NCM_API_TOKEN="valid_test_token")
    @patch('marketplace.ncm_service.NCMService._probe_protected_auth')
    @patch('marketplace.ncm_service.NCMService.get_branches')
    def test_06_http_200_authenticated_diagnostics(self, mock_get_branches, mock_probe):
        """Verify test_connection properly reports successful authentication with metadata."""
        mock_get_branches.return_value = [{'name': 'Kathmandu'}, {'name': 'Pokhara'}]
        mock_probe.return_value = (True, "v1/orders/statuses", 200, {"result": {}, "errors": [1]})

        service = NCMService()
        res = service.test_connection()

        self.assertTrue(res['success'])
        self.assertEqual(res['auth_result'], 'AUTHENTICATED')
        self.assertTrue(res['credential_present'])
        self.assertEqual(res['http_status'], 200)
        self.assertEqual(res['branch_count'], 2)
        self.assertIsNotNone(res['latency_ms'])
        self.assertEqual(res['hostname'], 'demo.nepalcanmove.com')
        self.assertTrue(res.get('protected_auth_verified'))

    def test_07_database_token_persistence_via_api(self):
        """Verify admin endpoint persists custom token, updates audit log, and clears cleanly."""
        # 1. Save new token
        resp = self.client.patch('/api/marketplace/admin/courier/settings/', {
            'new_api_token': '   ncm_override_secret_999   '
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.config.refresh_from_db()
        self.assertEqual(self.config.custom_api_token, 'ncm_override_secret_999')
        self.assertEqual(self.config.get_token_source(), 'DATABASE_CUSTOM_TOKEN')

        # Serializer should never expose plaintext token
        self.assertNotIn('ncm_override_secret_999', str(resp.json()))
        self.assertEqual(resp.json()['token_source'], 'DATABASE_CUSTOM_TOKEN')

        # 2. Clear database token override
        clear_resp = self.client.patch('/api/marketplace/admin/courier/settings/', {
            'clear_database_token': True
        }, format='json')
        self.assertEqual(clear_resp.status_code, status.HTTP_200_OK)

        self.config.refresh_from_db()
        self.assertEqual(self.config.custom_api_token, '')

    @override_settings(NCM_API_TOKEN="token_phase20_abc123")
    @patch('marketplace.ncm_service.NCMService._probe_protected_auth')
    @patch('marketplace.ncm_service.NCMService.get_branches')
    def test_08_phase20_runtime_fingerprint_and_diagnostics(self, mock_get_branches, mock_probe):
        """Verify Phase 20 diagnostics: deployed version, SHA-256 fingerprint match, and endpoints."""
        mock_get_branches.return_value = [{'name': 'Kathmandu'}]
        mock_probe.return_value = (True, "v1/orders/statuses", 200, {"result": {}, "errors": [1]})

        service = NCMService()
        res = service.test_connection()

        self.assertTrue(res['success'])
        self.assertEqual(res['deployed_code_version'], 'phase20-v1.0.0')
        self.assertTrue(res['credential_fingerprint'].startswith('sha256:'))
        self.assertTrue(res['credential_fingerprint_match'])
        self.assertIn('Token sha256:', res['authentication_scheme'])
        self.assertEqual(res['endpoint'], 'v1/orders/statuses')
        self.assertNotIn('token_phase20_abc123', str(res))
