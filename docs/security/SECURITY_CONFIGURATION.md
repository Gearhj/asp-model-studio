# ATLAS Security Configuration

ATLAS now starts from fail-closed authentication defaults:

| Setting | Default | Purpose |
|---|---:|---|
| `ATLAS_AUTH_ENABLED` | `true` | Enables session-cookie authentication. |
| `ATLAS_ALLOW_PUBLIC_REGISTRATION` | `false` | Enables self-service registration. Registrants are always `data_scientist`. |
| `ATLAS_LOCAL_DEV` | `false` | Marks an explicitly accepted local-development process. |
| `ATLAS_ENABLE_DEV_USER_HEADER` | `false` | Allows ATLAS to consider `X-ATLAS-USER-ID`; also requires local development, non-hosted mode, and a loopback request. |
| `ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP` | `false` | Creates local-only bootstrap/demo accounts when the security store is empty. |
| `ATLAS_HOSTED_MODE` | `false` | Enables fatal hosted security validation and Secure-cookie defaults. |
| `ATLAS_COOKIE_SECURE` | `true` in hosted mode, otherwise `false` | Controls the session cookie `Secure` attribute. |
| `ATLAS_CORS_ORIGINS` | empty | Comma-separated deployment origins. Hosted mode requires an explicit non-wildcard value. |
| `ATLAS_TRUSTED_PROXY_IPS` | empty | Comma-separated proxy IP addresses. Forwarded headers are not trusted by default. |

## Ordinary local authentication

Use session-cookie login for normal development. If self-service account creation is needed temporarily, set `ATLAS_ALLOW_PUBLIC_REGISTRATION=true`; the endpoint still ignores any caller-supplied role and creates only `data_scientist`.

On a new disposable local security database, an operator may explicitly set:

```text
ATLAS_LOCAL_DEV=true
ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP=true
```

This is a local bootstrap mode and must not be used for hosted deployment. Change the bootstrap administrator password before using the account beyond disposable development.

## Development identity header

The password-free development header is a narrow testing mode. It requires all of:

```text
ATLAS_ENABLE_DEV_USER_HEADER=true
ATLAS_LOCAL_DEV=true
ATLAS_HOSTED_MODE=false
```

The network peer must be `127.0.0.1` or `::1`. A remote peer cannot become loopback by supplying `Host`, `Forwarded`, or `X-Forwarded-For`. Forwarded chains are rejected unless the immediate peer is explicitly trusted, and the forwarded origin is also loopback. A valid session and a different header identity are rejected as conflicting identities.

## Hosted deployment

Hosted startup fails before persistence/checkpoint initialization when authentication is disabled, local development or the development header is enabled, local-user bootstrap is enabled, the session secret is default/short, the bootstrap password is the hardcoded local default, cookies are not Secure, or allowed origins are absent/wildcarded.

At minimum, hosted operators must supply a unique session secret of at least 32 characters, non-default bootstrap credentials if bootstrap credentials are configured, and explicit allowed origins. Startup errors identify unsafe setting names and never print secret values.
