"""
Fake Pokemon Trainer Club (PTC) SSO — sso.pokemon.com

Reproduces the CAS/OAuth flow the 0.29 client performs, but accepts ANY
username/password. Whatever username is typed on the PTC login screen is
carried through to the RPC layer and used as the in-game trainer name.

Client flow (reverse-engineered from global-metadata.dat strings):
  1. GET  /sso/login?service=<callback>           -> JSON { lt, execution }
  2. POST /sso/login?service=<callback>            -> 302, Location ...?ticket=ST-..
        body: lt&execution&_eventId=submit&username&password
  3. POST /sso/oauth2.0/accessToken  (code=ST-..)  -> "access_token=..&expires=.."
  4. GET  /sso/oauth2.0/profile?access_token=..    -> JSON { "birthdate": "..." }

The access_token embeds the username (base64) so the RPC server can recover it
without shared state surviving restarts.
"""
import base64
import json
import os
import time
import urllib.parse

CALLBACK = "https://sso.pokemon.com/sso/oauth2.0/callback"


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode()


def make_token(username: str) -> str:
    return f"PTC.{_b64(username)}.{os.urandom(6).hex()}"


def username_from_token(token: str) -> str:
    try:
        if token.startswith("PTC."):
            return _unb64(token.split(".")[1])
    except Exception:
        pass
    return token or "Trainer"


def _resp(status, body, ctype="text/plain", extra=None):
    headers = {"Content-Type": ctype, "Cache-Control": "no-store"}
    if extra:
        headers.update(extra)
    if isinstance(body, str):
        body = body.encode("utf-8")
    return status, headers, body


def handle(method, path, query, headers, body, log):
    qs = urllib.parse.parse_qs(query)
    form = urllib.parse.parse_qs(body.decode("utf-8", "replace")) if body else {}

    # 1) login page -> hand the client the lt/execution tokens it expects
    if path == "/sso/login" and method == "GET":
        service = qs.get("service", [CALLBACK])[0]
        payload = {
            "lt": "LT-" + os.urandom(8).hex(),
            "execution": "e1s1",
            "_eventId": "submit",
            "service": service,
        }
        log(f"[ptc] login page issued lt/execution (service={service})")
        return _resp(200, json.dumps(payload), "application/json")

    # 2) credential submit -> check the password, then issue a service ticket
    if path == "/sso/login" and method == "POST":
        username = (form.get("username", [""])[0] or "Trainer").strip()
        password = form.get("password", [""])[0] or ""
        service = qs.get("service", [CALLBACK])[0]
        import world
        ok, why, real = world.check_login(username, password)
        if not ok:
            # CAS reports a bad login as 200 with an "errors" body and NO ticket.
            # The client then shows its own authentication-failed message.
            log(f"[ptc] LOGIN REFUSED  username={username!r}  ({why})")
            return _resp(200, json.dumps(
                {"errors": ["Unable to log in with the credentials provided."]}),
                "application/json")
        if why == "claimed":
            log(f"[ptc] NEW TRAINER {real!r} -- password set from this first login")
        ticket = "ST-" + make_token(real)            # carries username
        location = f"{service}?ticket={urllib.parse.quote(ticket)}"
        log(f"[ptc] LOGIN OK  username={real!r}  ->  ticket issued")
        # 302 with the ticket in Location; also echo in body for robustness
        return _resp(302, f"ticket={ticket}", extra={"Location": location})

    # 3) exchange ticket (code) for an access token
    if path == "/sso/oauth2.0/accessToken":
        code = (form.get("code", qs.get("code", [""]))[0]) or ""
        username = username_from_token(code[3:] if code.startswith("ST-") else code)
        token = make_token(username)
        log(f"[ptc] access_token issued for username={username!r}")
        return _resp(200, f"access_token={token}&expires=7200")

    # 4) profile -> only 'birthdate' is parsed by the client (age gate)
    if path == "/sso/oauth2.0/profile":
        token = qs.get("access_token", [""])[0]
        username = username_from_token(token)
        profile = {
            "id": _b64(username),
            "username": username,
            "screen_name": username,
            "birthdate": "1990-01-01",       # adult, passes the age gate
            "country": "US",
            "email_verified": "true",
        }
        log(f"[ptc] profile served for username={username!r}")
        return _resp(200, json.dumps(profile), "application/json")

    # OAuth authorize entrypoint -> bounce to the login page
    if path == "/sso/oauth2.0/authorize":
        service = qs.get("redirect_uri", [CALLBACK])[0]
        loc = f"https://sso.pokemon.com/sso/login?service={urllib.parse.quote(service)}"
        log("[ptc] authorize -> redirect to login")
        return _resp(302, "", extra={"Location": loc})

    log(f"[ptc] UNHANDLED {method} {path}?{query}")
    return _resp(404, "not found")
