# Operator sign-in boundary

The public panel uses a same-origin login form. Caddy passes requests to the
Unix-socket relay and removes any browser-supplied `X-AWG-Operator` header. The
relay serves only `/login` and its CSS/JS without authentication. It validates
the existing operator username and bcrypt password hash, then issues a one-hour
`Secure`, `HttpOnly`, `SameSite=Strict`, host-only session cookie. The relay sets
the operator identity for the application after validating that cookie. The
application's own CSRF and session checks remain in force for mutations.

The hash is stored only on the host in a root-owned regular file readable by
the relay service group (`0640`). It is never copied into Git, a wheel, or a
browser response. The relay fails to start if the credential file or login
assets are missing or unsafe. A service restart expires all login sessions.

For migration from Caddy Basic Auth, copy its existing bcrypt hash into that
file without exposing it in command output. Stage the relay and assets first,
verify the service account can read the file, then enable `AWG_CITA_AUTH_MODE=form`
on the relay service. Validate the complete Caddy configuration before removing
Basic Auth. The proxy must keep its Unix socket upstream and use
`header_up -X-AWG-Operator`. Check an unauthenticated forged-header request,
invalid login, valid login, logout, and protected API access. Retain the prior
release and proxy configuration for rollback. Do not alter VPN interfaces or
peer configurations for this migration.
