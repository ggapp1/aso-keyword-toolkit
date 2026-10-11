import unittest
from unittest import mock

from asokit import asc


class BearerTests(unittest.TestCase):
    def test_mints_once_then_reuses_until_near_expiry(self):
        minted = []
        bearer = asc.Bearer(mint=lambda: minted.append(1) or f"jwt{len(minted)}", lifetime=1200)
        with mock.patch("asokit.asc.time.time", return_value=1000):
            self.assertEqual(str(bearer), "jwt1")
            self.assertEqual(str(bearer), "jwt1")
        with mock.patch("asokit.asc.time.time", return_value=1000 + 1200 - 179):
            self.assertEqual(str(bearer), "jwt2")
        self.assertEqual(len(minted), 2)

    def test_formats_into_authorization_header(self):
        bearer = asc.Bearer(mint=lambda: "abc")
        self.assertEqual(f"Bearer {bearer}", "Bearer abc")


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        asc.RATE.clear()
        self.addCleanup(asc.RATE.clear)

    def test_parses_header(self):
        asc._note_rate("user-hour-lim:3500;user-hour-rem:3120;")
        self.assertEqual(asc.RATE, {"limit": 3500, "remaining": 3120})

    def test_ignores_malformed_header(self):
        asc._note_rate("garbage")
        asc._note_rate(None)
        self.assertEqual(asc.RATE, {})

    def test_throttle_sleeps_only_below_floor(self):
        with mock.patch("asokit.asc.time.sleep") as sleep:
            asc._note_rate("user-hour-lim:3500;user-hour-rem:400;")
            asc._throttle()
            sleep.assert_not_called()
            asc._note_rate("user-hour-lim:3500;user-hour-rem:349;")
            asc._throttle()
            sleep.assert_called_once_with(asc.RATE_PAUSE)

    def test_call_throttles_before_each_request(self):
        asc._note_rate("user-hour-lim:100;user-hour-rem:1;")
        with mock.patch("asokit.asc.time.sleep") as sleep, \
             mock.patch("asokit.asc._request", return_value={"data": []}):
            asc.call("GET", "/apps/1", "t")
        sleep.assert_called_once_with(asc.RATE_PAUSE)


class RawTransportTests(unittest.TestCase):
    def test_upload_http_error_becomes_asc_error(self):
        import io
        import urllib.error
        error = urllib.error.HTTPError("https://upload.invalid/x", 403, "Forbidden", {}, io.BytesIO(b"denied"))
        with mock.patch("asokit.asc.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(asc.ASCError, "upload failed.*403.*nothing was placed.*reuses completed uploads"):
                asc._raw("PUT", "https://upload.invalid/x", {}, b"data")

    def test_network_error_becomes_asc_error(self):
        import urllib.error
        with mock.patch("asokit.asc.urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            with self.assertRaisesRegex(asc.ASCError, "upload failed"):
                asc._raw("PUT", "https://upload.invalid/x", {}, b"data")
        with mock.patch("asokit.asc.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(asc.ASCError, "download failed"):
                asc._raw("GET", "https://cdn.invalid/x", {}, None)


if __name__ == "__main__":
    unittest.main()
