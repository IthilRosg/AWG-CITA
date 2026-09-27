import unittest

from scripts.operator_auth import COOKIE_NAME, OperatorAuth, clear_cookie, session_cookie

HASH = b'$2a$12$' + b'A' * 53


class OperatorAuthTests(unittest.TestCase):
    def test_login_cookie_expiry_and_logout(self):
        now = [100.0]
        auth = OperatorAuth('operator', HASH, verify=lambda password, _hash: password == b'correct', clock=lambda: now[0])
        self.assertIsNone(auth.authenticate('operator', 'wrong'))
        self.assertIsNone(auth.authenticate('other', 'correct'))
        token = auth.authenticate('operator', 'correct')
        self.assertIsNotNone(token)
        cookie = session_cookie(token)
        self.assertIn('Secure; HttpOnly; SameSite=Strict; Path=/;', cookie)
        self.assertEqual(auth.actor(cookie.split(';', 1)[0]), 'operator')
        self.assertIsNone(auth.actor(COOKIE_NAME + '=' + token + '; ' + COOKIE_NAME + '=' + token))
        auth.revoke(cookie)
        self.assertIsNone(auth.actor(cookie))
        token = auth.authenticate('operator', 'correct')
        now[0] += 3600
        self.assertIsNone(auth.actor(session_cookie(token)))
        self.assertIn('Max-Age=0', clear_cookie())

    def test_password_and_username_are_bounded(self):
        calls = []
        auth = OperatorAuth('operator', HASH, verify=lambda password, _hash: calls.append(password) or True)
        self.assertIsNone(auth.authenticate('operator', ''))
        self.assertIsNone(auth.authenticate('operator', 'x' * 257))
        self.assertEqual(calls, [])
        self.assertIsNone(auth.authenticate('other', 'valid'))
        self.assertEqual(calls, [b'valid'])


if __name__ == '__main__':
    unittest.main()
