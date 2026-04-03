from flask import Flask, request, send_file, jsonify
from playwright.sync_api import sync_playwright
import io, os, time, requests, json

app = Flask(__name__)

API_KEY   = os.getenv("FIREBASE_API_KEY", "AIzaSyDBefDvlrg1n7haTuoiQqekKoV139BmK5c")
EMAIL     = os.getenv("FIREBASE_EMAIL",   "3998880000@gmail.com")
PASSWORD  = os.getenv("FIREBASE_PASS",    "0000##")
DEVICE_ID = os.getenv("DEVICE_ID",        "n9N1cd2jsF3xGfsVNf9x")
APP_URL   = "https://xn--eky-6ma.com"

_cache = {"token": None, "refresh": None, "exp": 0}

def get_session():
    if _cache["token"] and time.time() < _cache["exp"]:
        return _cache
    r = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}",
        json={"email": EMAIL, "password": PASSWORD, "returnSecureToken": True}
    )
    d = r.json()
    if not r.ok:
        raise Exception(d.get("error", {}).get("message", "Login failed"))
    _cache["token"]   = d["idToken"]
    _cache["refresh"] = d["refreshToken"]
    _cache["uid"]     = d["localId"]
    _cache["exp"]     = time.time() + int(d["expiresIn"]) - 60
    print(f"[AUTH] Login OK — uid: {_cache['uid']}")
    return _cache

def capture(mvalue: str) -> bytes:
    sess     = get_session()
    auth_key = f"firebase:authUser:{API_KEY}:[DEFAULT]"
    auth_user = {
        "uid": sess["uid"], "email": EMAIL, "emailVerified": False, "isAnonymous": False,
        "providerData": [{"providerId": "password", "uid": EMAIL, "email": EMAIL, "displayName": None, "photoURL": None}],
        "stsTokenManager": {
            "refreshToken":   sess["refresh"],
            "accessToken":    sess["token"],
            "expirationTime": int(time.time()*1000) + 3600000
        },
        "createdAt":   str(int(time.time()*1000)),
        "lastLoginAt": str(int(time.time()*1000)),
        "apiKey":  API_KEY,
        "appName": "[DEFAULT]",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        ctx = browser.new_context(
            viewport={"width": 430, "height": 932},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            device_scale_factor=3,
        )
        page = ctx.new_page()
        page.on("console", lambda msg: print(f"[JS] {msg.text}"))
        page.on("pageerror", lambda err: print(f"[JS ERROR] {err}"))

        # ── PASO 1: Cargar app y esperar que React monte completamente ─────────
        print(f"[PW] Cargando {APP_URL}...")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=30000)

        # Esperar que ion-app esté en el DOM (React montó)
        print("[PW] Esperando que React monte...")
        try:
            page.wait_for_selector("ion-app", timeout=15000)
            print("[PW] ion-app detectado ✅")
        except:
            print("[PW] ion-app timeout")

        # Esperar ion-router también
        try:
            page.wait_for_selector("ion-router", timeout=10000)
            print("[PW] ion-router detectado ✅")
        except:
            print("[PW] ion-router timeout")

        print(f"[PW] URL actual: {page.url}")
        print(f"[PW] Pathname: {page.evaluate('() => window.location.pathname')}")

        # ── PASO 2: Inyectar sesión (igual que inject_session.js) ─────────────
        print("[PW] Inyectando sesión...")
        page.evaluate(f"""
        async () => {{
            const AUTH_KEY  = {json.dumps(auth_key)};
            const authUser  = {json.dumps(auth_user)};
            const DEVICE_ID = {json.dumps(DEVICE_ID)};

            localStorage.setItem(AUTH_KEY, JSON.stringify(authUser));
            localStorage.setItem("device_id", DEVICE_ID);
            localStorage.setItem("accountType", "deposit");
            localStorage.setItem("security_notice_dont_show_again", "true");
            console.log("[PW] localStorage OK");

            await new Promise((resolve) => {{
                const req = indexedDB.open("firebaseLocalStorageDb", 1);
                req.onupgradeneeded = e => {{
                    if (!e.target.result.objectStoreNames.contains("firebaseLocalStorage"))
                        e.target.result.createObjectStore("firebaseLocalStorage", {{ keyPath: "fbase_key" }});
                }};
                req.onsuccess = e => {{
                    const db = e.target.result;
                    if (!db.objectStoreNames.contains("firebaseLocalStorage")) return resolve();
                    const tx = db.transaction("firebaseLocalStorage", "readwrite");
                    tx.objectStore("firebaseLocalStorage").put({{ fbase_key: AUTH_KEY, value: authUser }});
                    tx.oncomplete = () => {{ console.log("[PW] IndexedDB OK"); resolve(); }};
                    tx.onerror = resolve;
                }};
                req.onerror = resolve;
            }});

            const _orig = window.matchMedia.bind(window);
            window.matchMedia = (q) => {{
                if (q && q.includes("display-mode")) return {{
                    matches: q.includes("standalone"), media: q, onchange: null,
                    addEventListener: () => {{}}, removeEventListener: () => {{}}, dispatchEvent: () => false,
                }};
                return _orig(q);
            }};
            try {{ Object.defineProperty(navigator, "standalone", {{ get: () => true, configurable: true }}); }} catch(e) {{}}
            try {{ Object.defineProperty(navigator.serviceWorker, "controller", {{ get: () => ({{ state: "activated" }}), configurable: true }}); }} catch(e) {{}}

            sessionStorage.setItem("comprobante_navigation_source", "movements");
            sessionStorage.setItem("security_notice_dont_show_again", "true");
            console.log("[PW] Sesión + PWA spoof OK");
        }}
        """)

        # ── PASO 3: Esperar que ion-router procese la sesión y navegue ─────────
        # En el browser tú ya tienes la app montada, aquí necesitamos
        # que Firebase Auth procese el localStorage — damos tiempo
        print("[PW] Esperando que Firebase Auth procese la sesión...")
        page.wait_for_timeout(3000)

        # ── PASO 4: Navegar via ion-router ────────────────────────────────────
        print(f"[PW] Navegando a /comprobante/{mvalue}...")
        nav_result = page.evaluate(f"""
        async () => {{
            const ionRouter = document.querySelector("ion-router");
            console.log("[PW] ion-router al navegar:", ionRouter ? "OK" : "null");
            sessionStorage.setItem("comprobante_navigation_source", "movements");

            if (ionRouter) {{
                await ionRouter.push("/comprobante/{mvalue}", "forward");
                console.log("[PW] push ejecutado");
                return "ion-router";
            }} else {{
                window.history.pushState({{}}, "", "/comprobante/{mvalue}");
                window.dispatchEvent(new PopStateEvent("popstate", {{ state: {{}} }}));
                console.log("[PW] history API usado");
                return "history";
            }}
        }}
        """)
        print(f"[PW] Navegación via: {nav_result}")
        print(f"[PW] URL post-nav: {page.evaluate('() => window.location.pathname')}")

        # ── PASO 5: Esperar comprobante ────────────────────────────────────────
        print("[PW] Esperando .receipt-container...")
        try:
            page.wait_for_selector(
                ".comprobante-container, .receipt-container, .receipt-content, .labeled-value, .receipt-container__content-base",
                timeout=30000
            )
            print("[PW] receipt encontrado ✅")
        except Exception as e:
            print(f"[PW] receipt timeout: {e}")

        # Log DOM intermedio
        dom = page.evaluate("""
        () => ({
            path:    window.location.pathname,
            receipt: !!document.querySelector(".receipt-container"),
            labels:  document.querySelectorAll(".labeled-value__value").length,
            spinner: !!document.querySelector("ion-spinner"),
            pages:   document.querySelectorAll("ion-page").length,
        })
        """)
        print(f"[DOM] {json.dumps(dom)}")

        # Esperar datos reales
        try:
            page.wait_for_function("""
                () => {
                    const vals = document.querySelectorAll(".labeled-value__value");
                    return vals.length >= 2 &&
                           [...vals].filter(e => e.textContent.trim().length > 1).length >= 2;
                }
            """, timeout=20000)
            print("[PW] Datos del comprobante listos ✅")
        except Exception as e:
            print(f"[PW] datos timeout: {e}")

        page.wait_for_timeout(4000)

        # Log final
        final = page.evaluate("""
        () => ({
            path:   window.location.pathname,
            fields: [...document.querySelectorAll(".labeled-value__value")]
                        .map(e => e.textContent.trim()).slice(0, 5),
        })
        """)
        print(f"[DOM FINAL] {json.dumps(final, ensure_ascii=False)}")

        # ── PASO 6: Capturar ──────────────────────────────────────────────────
        page.evaluate("""
        () => {
            [".bc-vouch-topbar","ion-header","[class*=topbar]",
             ".button-listo",".button-container","ion-spinner"].forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.style.display = "none");
            });
        }
        """)

        # Selector correcto del comprobante
        el = (
            page.query_selector(".comprobante-container") or
            page.query_selector(".receipt-wrapper")        or
            page.query_selector(".receipt-container__content-base")
        )
        print(f"[PW] Elemento captura: {'encontrado' if el else 'body fallback'}")

        if el:
            # Medir altura real del contenido
            el_height = page.evaluate("""
                () => {
                    const el = document.querySelector(".comprobante-container") ||
                               document.querySelector(".receipt-wrapper") ||
                               document.querySelector(".receipt-container__content-base");
                    return el ? el.scrollHeight : document.body.scrollHeight;
                }
            """)
            print(f"[PW] Altura elemento: {el_height}px")
            # Expandir viewport a la altura completa del comprobante
            page.set_viewport_size({"width": 430, "height": max(el_height + 100, 932)})
            page.wait_for_timeout(500)
            png = el.screenshot(type="png")
        else:
            png = page.screenshot(type="png", full_page=True)

        print(f"[PW] PNG: {len(png)} bytes")

        browser.close()
        return png

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/captura/<mvalue>", methods=["GET"])
def captura_get(mvalue):
    print(f"\n{'='*50}\n[REQ] GET /captura/{mvalue}\n{'='*50}")
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png", download_name=f"{mvalue}.png")
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/captura", methods=["POST"])
def captura_post():
    data   = request.json or {}
    mvalue = data.get("mvalue")
    print(f"\n{'='*50}\n[REQ] POST /captura — {mvalue}\n{'='*50}")
    if not mvalue:
        return jsonify({"error": "mvalue requerido"}), 400
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png", download_name=f"{mvalue}.png")
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
