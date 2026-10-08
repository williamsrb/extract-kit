---
id: how-to-log-in-to-an-xp7-admin-and-keep-the-session
when_skills: [extract-legacy, extract-agentic, run-plan, plan-task-evidence, develop-xp7-backend]
inputs: [XP7 base URL (local or review), the environment's su login]
outputs: [live session cookies, Playwright storage state]
stop_if: [the host is production, the login is denied twice]
read: section
prose: caveman-lite
---

# How to log in to an XP7 admin and keep the session

Calibrated 2026-09 on XP 7.14 to 7.16 with Content Studio 5.2.x. Use a local or review XP only. Never log in to a production host.

## Paths: XP7 vs XP8

| Surface | XP 7 | XP 8 |
|---|---|---|
| Admin tool list | `/admin/tool` | `/admin` |
| Id provider (login POST) | `/admin/tool/_/idprovider/system` | `/admin/_/idprovider/system` |
| Content Studio | `/admin/tool/com.enonic.app.contentstudio/main` | `/admin/com.enonic.app.contentstudio/main` |

A wrong-version path answers 404. When the version is unknown, try the XP8 login path first and then the XP7 one. A 404 on one of them is the answer, not a failure.

## Procedure

1. Probe reachability. A reachable instance answers `401` with `Enonic XP - Login` in the body:

```bash
curl -sS -L --max-time 15 -o /tmp/body.html -w "HTTP %{http_code}\n" "<base>/admin/tool"
grep -q "Enonic XP - Login" /tmp/body.html && echo REACHABLE || echo UNREACHABLE
```

2. Log in at the id provider root, not at `/…/login`:

```
POST <base>/admin/tool/_/idprovider/system
Content-Type: application/json

{"action":"login","user":"<login>","password":"<password>"}
```

3. Success is `{"authenticated":true,…}` plus a `JSESSIONID` cookie. Behind an ingress there is often also an `INGRESSCOOKIE` affinity cookie. `JSESSIONID` alone resolved the session on a review host, but send both when you have them.
4. Keep the cookies as a Playwright storage state so a browser, `playwright-cli` and the kit's HTTP calls can share one session:

```json
{"cookies":[{"name":"JSESSIONID","value":"…","domain":"<host without port>","path":"/","expires":-1,"httpOnly":true,"secure":false,"sameSite":"Lax"}],"origins":[]}
```

Write the file with mode 0600 from the start. The cookies are credentials.

5. Prove the session is live before spending a browser call:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -H "Cookie: JSESSIONID=$JS" "<base>/admin/tool"   # 200 live, 401 dead
```

## With extractkit

`extractkit assets --storage-state-out <file>` logs in with the supplied `cms_url` resource, tries both id provider paths and writes the 0600 storage state. `extractkit step enonic.cms` and `extractkit resume` take it as `--storage-state <file>`.

## Pitfalls

- A saved `user.json` or storage state goes stale. Re-mint it when a call answers 401 or 403. A saved state that lands on the login page means the session is dead.
- The cookie `domain` must match the host you call. A state minted for `localhost` does not work for `127.0.0.1`.
- A storage state holds cookies only. An app that keeps a token in `sessionStorage` needs it seeded separately.
- Use the credential the environment documents. If the first login is denied, try the documented fallback once, then stop. Do not loop on guesses.
- Do not print the password, the cookie values or the storage-state contents in logs, comments or reports.
- Dev and review logins differ. Never reuse a login across environments.
