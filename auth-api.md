# Auth & Subscription API — Frontend Guide

Base URL: `/api/v1`

This document is the contract for the frontend. The backend implementation lives
in `users/` (auth) and `subscriptions/` (plans/tiers). If something here disagrees
with the OpenAPI schema later, treat the schema as authoritative and open an
issue.

Interactive Swagger UI: `/api-docs/`  
Raw OpenAPI schema: `/api/schema/` (YAML, or JSON with `Accept: application/json`)

---

## 1. TL;DR

1. **Access token** (15 min) is kept **in memory** and sent as
   `Authorization: Bearer <access>`.
2. **Refresh token** (7 days, rotating) lives in an **`HttpOnly` cookie** that JS
   cannot read. Every auth request must use `credentials: "include"`.
3. **Login** returns only `{access}` in the body; the cookie is set by
   `Set-Cookie`.
4. On a **`401`** from a normal API call, call `POST /auth/token/refresh/` once,
   store the new access token, and retry the original request **once**.
5. **Single-flight** the refresh call. Two parallel refreshes invalidate each
   other because the refresh token rotates.
6. On page load, call refresh once to restore the session (the in-memory access
   token is gone after a reload).
7. Branch on the **`code`** field of errors, never on `detail`.
8. `403 email_not_verified` is **not** an expired token — show “verify your
   email”, do not refresh.
9. `403 tier_required` means the plan is too low — show the upgrade prompt.
10. The server always checks the plan in the database. The `tier` inside the JWT
    is only a UI hint and can be stale.

---

## 2. Cookies, CORS and security

### 2.1 Refresh cookie

| Attribute  | Value (default)                              |
| ---------- | -------------------------------------------- |
| Name       | `refresh_token`                              |
| `HttpOnly` | yes — JavaScript cannot read it              |
| `Secure`   | yes in production (`DEBUG=False`)            |
| `SameSite` | `Lax` (configurable on the server)           |
| `Path`     | `/api/v1/auth/`                              |
| `Max-Age`  | 7 days; refreshed (slid) on every rotation   |

Consequences:

- The cookie is **not** sent to `/api/v1/subscriptions/...` or other endpoints;
  that is intentional.
- The cookie is sent to `/api/v1/auth/token/refresh/` and
  `/api/v1/auth/logout/` automatically.
- JavaScript cannot inspect it. To know whether a session exists, call
  `/auth/me/` (after restoring the access token) or try refresh on page load.

### 2.2 Fetch requirements

Same-origin frontend (recommended):

```ts
fetch("/api/v1/auth/login/", { method: "POST", credentials: "include", ... })
```

Cross-origin frontend (`app.example.com` → `api.example.com`):

```ts
fetch("https://api.example.com/api/v1/auth/login/", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username, password }),
});
```

The backend must allow the exact origin (`CORS_ALLOWED_ORIGINS`) with
`CORS_ALLOW_CREDENTIALS = True`. Wildcards do not work with credentials.

If frontend and API are on **different sites** (not just different subdomains),
the refresh cookie needs `SameSite=None; Secure` and the backend needs an
additional CSRF defense. The default `Lax` setup assumes a same-site deployment.
If the backend asks for `X-Requested-With: XMLHttpRequest` on cookie-authenticated
POSTs, include it on **refresh** and **logout** (and on login/register is fine
too).

### 2.3 What to store where

| Data          | Storage                    | Why                                        |
| ------------- | -------------------------- | ------------------------------------------ |
| Access token  | JS variable / memory       | short-lived; XSS cannot exfiltrate refresh |
| Refresh token | server-set `HttpOnly` cookie | unreadable by JS                          |
| User profile  | state/query cache          | can be refetched from `/auth/me/`          |
| Tier          | state/query cache          | refetch after billing events               |

**Never** put the access or refresh token in `localStorage` or
`sessionStorage`. Never decode the JWT to make authorization decisions.

---

## 3. Error format

Every error has this shape:

```json
{
  "detail": "Please verify your email before logging in.",
  "code": "email_not_verified"
}
```

Validation errors add `errors`, keyed by field:

```json
{
  "detail": "Validation failed.",
  "code": "invalid",
  "errors": {
    "email": ["A user with this email already exists."],
    "password": ["This password is too common."]
  }
}
```

`errors` can also contain `non_field_errors` for cross-field problems.

### 3.1 Error codes

| HTTP | `code`                  | Meaning / UI action                                                    |
| ---- | ----------------------- | ---------------------------------------------------------------------- |
| 400  | `invalid`               | Validation failed; render `errors` next to the fields                  |
| 401  | `not_authenticated`     | No bearer token sent; try refresh, then log in                         |
| 401  | `token_not_valid`       | Access or refresh token invalid/expired/replayed; refresh once / log out |
| 401  | `no_active_account`     | Wrong username or password (login)                                     |
| 401  | `no_refresh_cookie`     | No refresh cookie; treat as logged out                                 |
| 401  | `user_inactive`         | Account deactivated (or deleted, on refresh); clear the session        |
| 401  | `user_not_found`        | Account deleted (access token); clear the session                      |
| 401  | `bad_authorization_header` | Malformed `Authorization` header; clear it and retry after login   |
| 403  | `email_not_verified`    | Credentials were correct, but the email must be verified first         |
| 403  | `tier_required`         | Plan too low; show the upgrade prompt                                  |
| 403  | `permission_denied`     | Generic permission failure                                             |
| 404  | `not_found`             | Route/resource does not exist                                          |
| 405  | `method_not_allowed`    | Wrong HTTP method                                                      |
| 429  | `throttled`             | Rate-limited; back off (see `Retry-After` header if present)           |

`Retry-After` is set by DRF on `429` responses where a wait time is known.

### 3.2 How to decide what to do

```ts
switch (err.code) {
  case "email_not_verified":   // 403: go to “check your email” screen, DO NOT refresh
  case "tier_required":        // 403: open upgrade modal
  case "no_active_account":    // 401 on login: wrong credentials
  case "token_not_valid":
  case "not_authenticated":    // 401: refresh access token, retry once
  case "no_refresh_cookie":
  case "user_inactive":        // 401: clear session, go to login
  case "throttled":            // 429: disable the button, show retry later
  default:                     // show err.detail
}
```

Only refresh on `401` responses from **normal API calls** (not from the refresh
endpoint itself, and not for login/register).

---

## 4. Auth endpoints

All request/response bodies are JSON. Send `Content-Type: application/json` for
requests with a body. Include `credentials: "include"` on **every** call to
these endpoints.

### 4.1 `POST /auth/register/`

Creates an unverified account and a free Basic subscription.

Request:

```json
{
  "username": "sam",
  "email": "sam@example.com",
  "first_name": "Sam",
  "last_name": "Lee",
  "password": "S0me-Str0ng-Pass"
}
```

- `first_name` / `last_name` are optional.
- Password must pass Django's validators (length ≥ 8, not too common, not
  entirely numeric, not too similar to username/email).
- Email is normalised to lower case.
- Usernames/emails of **soft-deleted** accounts are still reserved.

Response `201`:

```json
{
  "id": "c27a5b0e-7ae3-482f-bc5e-33be1e325a5f",
  "username": "sam",
  "email": "sam@example.com",
  "first_name": "Sam",
  "last_name": "Lee"
}
```

No tokens are issued. The user must verify their email before logging in.

Errors: `400 invalid` (`errors.username`, `errors.email`, `errors.password`),
`429 throttled`.

### 4.2 `POST /auth/verify-email/`

Request:

```json
{ "token": "<token from the email link>" }
```

Response `200`:

```json
{ "detail": "Email verified. You can now log in." }
```

- Idempotent: verifying twice is harmless.
- The link looks like
  `${FRONTEND_URL}/verify-email?token=...`.
- The token expires after **24 hours**, and changing the account email
  invalidates it.
- `400 invalid` with `errors.token` when missing/expired/tampered.
- The endpoint is rate-limited (`5/hour` per IP), so avoid retry loops.

Frontend handling:

```ts
const token = new URLSearchParams(window.location.search).get("token");
if (!token) showInvalidLink();
else await postJson("/auth/verify-email/", { token }); // 200 -> go to /login
```

### 4.3 `POST /auth/resend-verification/`

Request:

```json
{ "email": "sam@example.com" }
```

Response `200` (always the same, even if the account does not exist):

```json
{ "detail": "If that account needs verification, an email has been sent." }
```

- Only sends if the account exists, is active and is not yet verified.
- `400 invalid` for a malformed email.
- `429 throttled` (email scope, `5/hour` per IP).

### 4.4 `POST /auth/login/`

Login is by **username**, not email (the email field exists for verification and
account recovery).

Request:

```json
{ "username": "sam", "password": "S0me-Str0ng-Pass" }
```

Success `200`:

```json
{ "access": "<JWT access token>" }
```

plus a response header:

```http
Set-Cookie: refresh_token=<JWT>; Path=/api/v1/auth/; Max-Age=604800; HttpOnly; Secure; SameSite=Lax
```

`refresh` is **never** in the JSON body.

Errors:

| Status | `code`                 | Meaning                                 |
| ------ | ---------------------- | --------------------------------------- |
| 401    | `no_active_account`    | Wrong username/password or inactive user |
| 403    | `email_not_verified`   | Correct credentials, email not verified |
| 429    | `throttled`            | Too many attempts (`5/min` per IP)      |

Important: the backend checks the password **before** the verification flag, so a
wrong password always looks like `no_active_account`. `email_not_verified` means
the password was right — take the user to the “check your email” screen and offer
“resend verification”.

The access token claims look like:

```json
{
  "token_type": "access",
  "exp": 1793264827,
  "iat": 1793263927,
  "jti": "1721278c6d6446f09c43f6338f2be16d",
  "user_id": "c27a5b0e-7ae3-482f-bc5e-33be1e325a5f",
  "username": "sam",
  "tier": "basic"
}
```

`tier` is a convenience hint only; the server re-checks the database on every
request.

### 4.5 `POST /auth/token/refresh/`

No request body. The browser sends the refresh cookie automatically.

Success `200`:

```json
{ "access": "<new JWT access token>" }
```

plus a **new** `Set-Cookie` with a rotated refresh token. The old refresh token is
blacklisted immediately.

Errors (`401`):

| `code`               | Meaning                                                   |
| -------------------- | --------------------------------------------------------- |
| `no_refresh_cookie`  | No cookie sent; treat as logged out                       |
| `token_not_valid`    | Invalid, expired, blacklisted or already-rotated token    |
| `user_inactive`      | The user was deleted/deactivated; clear the session       |

Rules:

- Treat any `401` here as “logged out”. Do **not** retry in a loop.
- **Single-flight** this request. If five widgets all get a `401` and each calls
  refresh, only the first succeeds; the others present an already-rotated token
  and are rejected — logging the user out.
- Do not send `Authorization`; the cookie is enough.

### 4.6 `POST /auth/logout/`

No request body, no access token required (so it works after the access token
expired). The browser sends the refresh cookie.

Response `204 No Content` and the cookie is cleared:

```http
Set-Cookie: refresh_token=; Path=/api/v1/auth/; Max-Age=0; ...
```

The refresh token is blacklisted server-side, so a copy taken before logout stops
working too.

Frontend: clear the in-memory access token and navigate to `/login`. The access
token itself stays valid for at most 15 minutes (stateless JWT trade-off); do not
reuse it after logout.

### 4.7 `GET /auth/me/`

Requires `Authorization: Bearer <access>`.

Response `200`:

```json
{
  "id": "c27a5b0e-7ae3-482f-bc5e-33be1e325a5f",
  "username": "sam",
  "email": "sam@example.com",
  "first_name": "Sam",
  "last_name": "Lee",
  "tier": "basic",
  "email_verified": true,
  "created_at": "2026-10-29T08:52:05.380092Z"
}
```

`tier` is read from the database, so it is fresh after an upgrade/downgrade.
`email_verified` is `true` after verification; unverified users cannot obtain an
access token through login anyway.

### 4.8 `POST /auth/change-password/`

Requires `Authorization: Bearer <access>`.

Request:

```json
{ "old_password": "S0me-Str0ng-Pass", "new_password": "An0ther-Str0ng-Pass" }
```

Response `200`:

```json
{ "detail": "Password updated. Please log in again." }
```

The refresh cookie is cleared and **all** refresh tokens for the user are
revoked (every device). The access token remains valid for at most 15 minutes;
the client must immediately clear it and send the user to the login screen.

Errors: `400 invalid` (`errors.old_password`, `errors.new_password`), `401`
missing/expired access token.

### 4.9 `POST /auth/password-reset/`

Request:

```json
{ "email": "sam@example.com" }
```

Response `200` (identical whether or not the account exists):

```json
{ "detail": "If that email is registered, a reset link has been sent." }
```

The email contains
`${FRONTEND_URL}/reset-password?uid=...&token=...`. The link expires in **1
hour** and is single-use.

Error `400 invalid` only for a malformed email; `429 throttled` (`5/hour` per IP).

### 4.10 `POST /auth/password-reset/confirm/`

Request:

```json
{
  "uid": "<uid from the link>",
  "token": "<token from the link>",
  "new_password": "An0ther-Str0ng-Pass"
}
```

Response `200`:

```json
{ "detail": "Password reset. Please log in with your new password." }
```

- All refresh tokens for the user are revoked.
- The email is marked verified as a side effect (consuming the link proves
  ownership).
- The reset token cannot be reused.
- Errors: `400 invalid` (`errors.token` for a bad/expired/reused link,
  `errors.new_password` for a weak password).

Frontend:

```ts
const params = new URLSearchParams(window.location.search);
await postJson("/auth/password-reset/confirm/", {
  uid: params.get("uid"),
  token: params.get("token"),
  new_password,
});
// success -> /login
```

---

## 5. Subscription endpoints

### 5.1 `GET /subscriptions/plans/`

Public (no auth). Returns the active catalog sorted by monthly price:

```json
[
  {
    "tier": "basic",
    "name": "Basic",
    "description": "Free plan. Get started with the essentials.",
    "price_monthly": "0.00",
    "price_yearly": "0.00",
    "currency": "USD",
    "limits": { "max_projects": 3, "api_calls_per_day": 1000, "export": false },
    "rank": 1
  }
]
```

Money fields are **strings** (DRF decimals), not numbers. `limits` is plan-specific
and may contain `null` for “unlimited”.

### 5.2 `GET /subscriptions/me/`

Requires auth. Returns the caller's live subscription:

```json
{
  "tier": "platinum",
  "plan": {
    "tier": "platinum",
    "name": "Platinum",
    "description": "For growing teams that need more room.",
    "price_monthly": "19.00",
    "price_yearly": "190.00",
    "currency": "USD",
    "limits": { "max_projects": 25, "api_calls_per_day": 25000, "export": true },
    "rank": 2
  },
  "limits": { "max_projects": 25, "api_calls_per_day": 25000, "export": true },
  "status": "active",
  "billing_cycle": "monthly",
  "started_at": "2026-10-29T08:52:05.383010Z",
  "current_period_start": "2026-10-29T08:52:05.383012Z",
  "current_period_end": "2026-11-28T08:52:12.440884Z",
  "cancel_at_period_end": false
}
```

For Basic, `current_period_end` is `null` (never expires). `status` is one of
`trialing`, `active`, `past_due`, `canceled`, `expired`; only a live row is
returned, so in practice it is `trialing`, `active`, or `past_due`.

This is the best endpoint for feature flags/limits in the UI. It is always
database-fresh.

### 5.3 Demo gated endpoints

```
GET /subscriptions/demo/platinum/   # Platinum or Diamond
GET /subscriptions/demo/diamond/    # Diamond only
```

`200` when allowed. `403` otherwise:

```json
{
  "detail": "This feature requires the platinum plan or higher.",
  "code": "tier_required"
}
```

Use the same pattern for real features: a `403 tier_required` should open an
upgrade modal, not log the user out.

### 5.4 Upgrades

There is **no** `POST /subscriptions/upgrade/`. Plans change only through
verified payment-provider webhooks on the backend. The frontend should send the
user to the billing/checkout flow and then refresh `/subscriptions/me/`.
Never trust a client-provided tier.

---

## 6. Reference client (TypeScript)

A compact, framework-agnostic implementation of the contract. It single-flights
refresh and retries each request at most once.

```ts
const API = "/api/v1";

type ApiError = {
  detail: string;
  code: string;
  errors?: Record<string, string[]>;
};

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;

function setAccessToken(token: string | null) {
  accessToken = token;
}

async function readError(res: Response): Promise<ApiError> {
  try {
    return (await res.json()) as ApiError;
  } catch {
    return { detail: `Request failed (${res.status})`, code: "unknown" };
  }
}

/** Call on page load. Returns null when there is no valid session. */
export function restoreSession(): Promise<string | null> {
  return refreshAccessToken();
}

/** Single-flight refresh. All concurrent callers share one request. */
function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API}/auth/token/refresh/`, {
      method: "POST",
      credentials: "include",
    })
      .then(async (res) => {
        if (!res.ok) {
          accessToken = null;
          return null;
        }
        const data = (await res.json()) as { access: string };
        accessToken = data.access;
        return data.access;
      })
      .catch(() => {
        accessToken = null;
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function apiFetch(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);

  const res = await fetch(`${API}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (res.status !== 401 || !retry) return res;

  // An unverified login is 403, so a 401 here means a missing/expired token.
  // Do not try to refresh the refresh endpoint itself.
  if (path.startsWith("/auth/token/refresh/")) return res;

  const newToken = await refreshAccessToken();
  if (!newToken) return res; // caller sees the original 401; go to /login
  return apiFetch(path, init, false);
}

export async function login(username: string, password: string) {
  const res = await fetch(`${API}/auth/login/`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });

  if (!res.ok) {
    const err = await readError(res);
    if (err.code === "email_not_verified") {
      return { ok: false as const, reason: "verify_email" as const };
    }
    return { ok: false as const, reason: "credentials" as const, error: err };
  }

  const data = (await res.json()) as { access: string };
  setAccessToken(data.access);
  return { ok: true as const };
}

export async function logout() {
  try {
    await fetch(`${API}/auth/logout/`, {
      method: "POST",
      credentials: "include",
    });
  } finally {
    setAccessToken(null);
  }
}
```

Usage:

```ts
// app bootstrap
const token = await restoreSession();
if (!token) {
  // no session: render the public app / login page
}

// normal API calls
const res = await apiFetch("/auth/me/");
if (res.status === 401) {
  // not logged in
} else if (res.status === 403) {
  const err = await readError(res);
  if (err.code === "tier_required") showUpgradeModal();
}
```

For a rate-limited call:

```ts
if (res.status === 429) {
  const wait = Number(res.headers.get("Retry-After") ?? 30);
  showMessage(`Too many attempts. Try again in ${wait}s.`);
}
```

---

## 7. Types

```ts
export type Tier = "basic" | "platinum" | "diamond";
export type SubscriptionStatus =
  | "trialing"
  | "active"
  | "past_due"
  | "canceled"
  | "expired";
export type BillingCycle = "monthly" | "yearly";

export interface PlanLimits {
  max_projects: number | null;
  api_calls_per_day: number | null;
  export: boolean;
}

export interface Plan {
  tier: Tier;
  name: string;
  description: string;
  price_monthly: string; // decimal string
  price_yearly: string;  // decimal string
  currency: string;      // ISO 4217
  limits: Record<string, unknown>;
  rank: number;
}

export interface Me {
  id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  tier: Tier;
  email_verified: boolean;
  created_at: string;
}

export interface Subscription {
  tier: Tier;
  plan: Plan;
  limits: Record<string, unknown>;
  status: SubscriptionStatus;
  billing_cycle: BillingCycle;
  started_at: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}
```

---

## 8. Complete user journeys

### 8.1 Sign up → verify → log in

```text
POST /auth/register/            -> 201, user unverified, Basic created
(the backend emails a link: ${FRONTEND_URL}/verify-email?token=...)
POST /auth/verify-email/ {token} -> 200
POST /auth/login/               -> 200 {access} + Set-Cookie refresh
GET  /auth/me/                  -> 200 profile + tier
```

If the user tries to log in before verifying: `403 email_not_verified`.
Offer `POST /auth/resend-verification/ {email}`.

### 8.2 Reload the page

```text
POST /auth/token/refresh/ (cookie) -> 200 {access} + rotated cookie
GET  /auth/me/                     -> 200
```

If refresh returns `401`, show the login page. Do not show an error toast for the
normal “no session” case.

### 8.3 Access token expires during use

```text
GET  /some-endpoint/              -> 401 (token_not_valid)
POST /auth/token/refresh/         -> 200 {access}
GET  /some-endpoint/ (retry)      -> 200
```

If the retry also returns `401`, clear the session and go to login.

### 8.4 Plan gate

```text
GET  /subscriptions/demo/platinum/ -> 403 {code:"tier_required"}
```

Show the upgrade prompt. After the billing webhook changes the plan, the **same
access token** works on the next request; re-fetch `/subscriptions/me/` to update
the UI.

### 8.5 Password reset

```text
POST /auth/password-reset/ {email}          -> 200 (always generic)
(the backend emails: /reset-password?uid=...&token=...)
POST /auth/password-reset/confirm/ {uid,token,new_password} -> 200
POST /auth/login/                            -> new password works; old sessions revoked
```

### 8.6 Logout

```text
POST /auth/logout/ (cookie) -> 204, cookie cleared, refresh blacklisted
(local) accessToken = null; navigate to /login
```

---

## 9. Endpoint summary

| Method | Path                                 | Auth | Success | Main errors |
| ------ | ------------------------------------ | ---- | ------- | ----------- |
| POST   | `/api/v1/auth/register/`             | No   | 201     | 400, 429    |
| POST   | `/api/v1/auth/verify-email/`         | No   | 200     | 400, 429    |
| POST   | `/api/v1/auth/resend-verification/`  | No   | 200     | 400, 429    |
| POST   | `/api/v1/auth/login/`                | No   | 200     | 401, 403, 429 |
| POST   | `/api/v1/auth/token/refresh/`        | Cookie | 200   | 401, 429    |
| POST   | `/api/v1/auth/logout/`               | Cookie (optional) | 204 | — |
| GET    | `/api/v1/auth/me/`                   | Bearer | 200   | 401         |
| POST   | `/api/v1/auth/change-password/`      | Bearer | 200   | 400, 401    |
| POST   | `/api/v1/auth/password-reset/`       | No   | 200     | 400, 429    |
| POST   | `/api/v1/auth/password-reset/confirm/` | No | 200     | 400, 429    |
| GET    | `/api/v1/subscriptions/plans/`       | No   | 200     | —           |
| GET    | `/api/v1/subscriptions/me/`          | Bearer | 200   | 401         |
| GET    | `/api/v1/subscriptions/demo/platinum/` | Bearer | 200 | 401, 403  |
| GET    | `/api/v1/subscriptions/demo/diamond/`  | Bearer | 200 | 401, 403  |

---

## 10. FAQ / troubleshooting

**The refresh cookie is not being set / sent.**

- Use `credentials: "include"` on every auth request.
- Cross-origin: exact `CORS_ALLOWED_ORIGINS` + `CORS_ALLOW_CREDENTIALS`, and
  `Secure` cookies over HTTPS.
- The cookie path is `/api/v1/auth/`; it will not appear on other endpoints.
- `SameSite=None` requires `Secure`; `Lax` does not work across different sites.
- Check the browser devtools Application → Cookies panel, and the `Set-Cookie`
  response header.

**I get `403 email_not_verified` on login.**

The password was correct; the email is not verified. Do not refresh tokens. Show
“check your email” and, if needed, call resend-verification.

**Refresh returns `401 token_not_valid` immediately after another refresh.**

Two refreshes raced with the same rotating cookie. Single-flight refresh calls so
only one request is in flight at a time.

**Everything returns `401` after reload.**

The access token is memory-only and was lost. Call refresh once on page load. If
it fails, the session is gone.

**The `tier` in the JWT is old after an upgrade.**

Expected. The claim is a hint. The server reads the DB; re-fetch `/auth/me/` or
`/subscriptions/me/` for UI.

**A gated feature returns `403`, not `401`.**

That is authorization (plan), not authentication. Do not refresh; show the
upgrade prompt.

**I changed my password but my other tab still works for a few minutes.**

Access tokens are stateless and live up to 15 minutes. All refresh tokens are
revoked immediately, so the session ends at the next refresh. Close the tab or
call logout in the app.

**Rate-limited (`429`).**

Limits are per IP/scope: login `5/min`, register `10/hour`, email endpoints
`5/hour`, refresh `60/hour`, anonymous `100/hour`, authenticated `2000/hour`.
Back off using `Retry-After`.
