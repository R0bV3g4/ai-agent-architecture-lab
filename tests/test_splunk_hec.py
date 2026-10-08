import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from splunk_hec import HECClient, HECError, NoRedirects


EVENT = {
    "timestamp": "2026-09-29T14:00:00+00:00",
    "run_id": "test-run", "event_id": "test-event", "evento": "prueba_conexion",
}


def response(code=0):
    result = MagicMock()
    result.__enter__.return_value.read.return_value = json.dumps({"code": code}).encode()
    return result


class HECTests(unittest.TestCase):
    def client(self):
        client = HECClient("https://inputs.example.splunkcloud.com:8088", "test-token")
        client._opener = MagicMock()
        return client

    def test_sends_json_event_with_auth_header_and_timestamp(self):
        client = self.client()
        client._opener.open.return_value = response()
        client.send(EVENT)
        request = client._opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://inputs.example.splunkcloud.com:8088/services/collector/event")
        self.assertEqual(request.get_header("Authorization"), "Splunk test-token")
        payload = json.loads(request.data)
        self.assertEqual(payload["event"], EVENT)
        self.assertEqual(payload["sourcetype"], "_json")
        self.assertNotIn("test-token", request.data.decode())
        self.assertNotIn("index", payload) # Se utiliza el índice configurado en el token.

    def test_connection_retry_preserves_event_id(self):
        client = self.client()
        client._opener.open.side_effect = [URLError("offline"), response()]
        with patch("splunk_hec.time.sleep"):
            client.send(EVENT)
        calls = client._opener.open.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].args[0].data, calls[1].args[0].data)

    def test_unauthorized_is_not_retried_or_exposed(self):
        client = self.client()
        client._opener.open.side_effect = HTTPError(client.url, 401, "test-token", {}, None)
        with self.assertRaisesRegex(HECError, "^HTTP 401$"):
            client.send(EVENT)
        self.assertEqual(client._opener.open.call_count, 1)

    def test_http_success_with_hec_error_is_not_success(self):
        client = self.client()
        client._opener.open.return_value = response(4)
        with self.assertRaises(HECError):
            client.send(EVENT)

    def test_delivery_failure_is_bounded(self):
        client = self.client()
        client._opener.open.side_effect = URLError("test-token")
        with patch("splunk_hec.time.sleep"), self.assertRaisesRegex(HECError, "Error de conexión con HEC"):
            client.send(EVENT)
        self.assertEqual(client._opener.open.call_count, 3)

    def test_redirects_are_not_followed(self):
        self.assertIsNone(NoRedirects().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_rejects_non_https_or_token_in_url(self):
        for url in ["http://example.com", "https://user:password@example.com", "https://example.com/?token=x"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                HECClient(url, "test-token")

    def test_disabled_without_endpoint(self):
        with patch.dict("os.environ", {"SPLUNK_HEC_URL": ""}):
            self.assertIsNone(HECClient.from_environment())

    def test_trial_can_explicitly_disable_tls_verification(self):
        with patch("splunk_hec.build_opener") as opener:
            HECClient("https://inputs.example.splunkcloud.com:8088", "test-token", verify_tls=False)
        https_handler = opener.call_args.args[0]
        self.assertFalse(https_handler._context.check_hostname)
        self.assertEqual(https_handler._context.verify_mode, 0)


if __name__ == "__main__":
    unittest.main()
