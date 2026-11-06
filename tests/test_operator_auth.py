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

    def test_bcrypt_byte_limit_never_truncates_password(self):
        calls = []
        auth = OperatorAuth('operator', HASH, verify=lambda password, _hash: calls.append(password) or True)
        self.assertIsNotNone(auth.authenticate('operator', 'x' * 72))
        self.assertIsNone(auth.authenticate('operator', 'x' * 73))
        self.assertIsNotNone(auth.authenticate('operator', '\u044f' * 36))
        self.assertIsNone(auth.authenticate('operator', '\u044f' * 37))
        self.assertEqual(calls, [b'x' * 72, ('\u044f' * 36).encode('utf-8')])
        self.assertEqual(len(auth.sessions), 2)

    def test_verifier_failure_does_not_create_session(self):
        for error in (ValueError('invalid password'), TypeError('invalid input'), RuntimeError('backend unavailable')):
            with self.subTest(error=type(error).__name__):
                def reject(_password, _hash):
                    raise error
                auth = OperatorAuth('operator', HASH, verify=reject)
                self.assertIsNone(auth.authenticate('operator', 'password'))
                self.assertEqual(auth.sessions, {})

    def test_non_ascii_username_does_not_reach_ascii_comparison(self):
        calls = []
        auth = OperatorAuth('operator', HASH, verify=lambda password, _hash: calls.append(password) or True)
        self.assertIsNone(auth.authenticate('\u043e\u043f\u0435\u0440\u0430\u0442\u043e\u0440', 'password'))
        self.assertEqual(calls, [])
        self.assertEqual(auth.sessions, {})


if __name__ == '__main__':
    unittest.main()
