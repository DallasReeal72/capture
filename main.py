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

    inject_and_navigate = f"""
    async () => {{
        const AUTH_KEY  = {json.dumps(auth_key)};
        const authUser  = {json.dumps(auth_user)};
        const DEVICE_ID = {json.dumps(DEVICE_ID)};
        const TARGET    = "/comprobante/{mvalue}";

        console.log("[PW] Inyectando sesión...");

        localStorage.setItem(AUTH_KEY, JSON.stringify(authUser));
        localStorage.setItem("device_id", DEVICE_ID);
        localStorage.setItem("accountType", "deposit");
        localStorage.setItem("security_notice_dont_show_again", "true");

        console.log("[PW] localStorage OK — key:", AUTH_KEY.substring(0, 30));

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
            req.onerror = () => {{ console.log("[PW] IndexedDB ERROR"); resolve(); }};
        }});

        // PWA spoof
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

        console.log("[PW] PWA spoofed");
        console.log("[PW] URL actual:", window.location.pathname);

        // Esperar ion-router
        const ionRouter = await new Promise(resolve => {{
            let n = 0;
            const t = setInterval(() => {{
                const r = document.querySelector("ion-router");
                if (r || ++n > 50) {{ clearInterval(t); resolve(r); }}
            }}, 100);
        }});

        console.log("[PW] ion-router:", ionRouter ? "encontrado" : "NO encontrado");

        if (ionRouter) {{
            await ionRouter.push(TARGET, "forward");
            console.log("[PW] Navegado via ion-router a", TARGET);
        }} else {{
            window.history.pushState({{}}, "", TARGET);
            window.dispatchEvent(new PopStateEvent("popstate", {{ state: {{}} }}));
            console.log("[PW] Navegado via history API a", TARGET);
        }}

        console.log("[PW] URL después de navegar:", window.location.pathname);
    }}
    """

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

        # Capturar logs del browser en Python
        page.on("console", lambda msg: print(f"[BROWSER] {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[BROWSER ERROR] {err}"))

        print(f"[PW] Cargando {APP_URL}...")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"[PW] App cargada — URL: {page.url}")

        print("[PW] Ejecutando inyección + navegación...")
        page.evaluate(inject_and_navigate)
        print(f"[PW] Post-inyección — URL: {page.url}")

        print("[PW] Esperando comprobante...")
        try:
            page.wait_for_function("""
                () => {
                    const ok = document.querySelector(".receipt-container") ||
                               document.querySelector(".receipt-content")   ||
                               document.querySelector(".labeled-value")     ||
                               document.querySelector(".receipt-container__content-base");
                    if (ok) console.log("[PW] receipt encontrado:", ok.className);
                    return ok;
                }
            """, timeout=30000)
            print("[PW] receipt detectado ✅")
        except Exception as e:
            print(f"[PW] Timeout esperando receipt: {e}")

        # Log del DOM actual para debug
        dom_info = page.evaluate("""
            () => ({
                url:      window.location.pathname,
                title:    document.title,
                receipt:  !!document.querySelector(".receipt-container"),
                labeled:  document.querySelectorAll(".labeled-value__value").length,
                spinner:  !!document.querySelector("ion-spinner"),
                ionPage:  document.querySelectorAll("ion-page").length,
                body100:  document.body.innerHTML.substring(0, 100),
            })
        """)
        print(f"[DOM] {json.dumps(dom_info, ensure_ascii=False)}")

        # Esperar datos reales
        try:
            page.wait_for_function("""
                () => {
                    const vals = document.querySelectorAll(".labeled-value__value");
                    const loaded = vals.length >= 2 &&
                                   [...vals].filter(e => e.textContent.trim().length > 1).length >= 2;
                    if (loaded) console.log("[PW] datos cargados ✅ — campos:", vals.length);
                    return loaded;
                }
            """, timeout=20000)
            print("[PW] Datos del comprobante listos ✅")
        except Exception as e:
            print(f"[PW] Timeout esperando datos: {e}")

        page.wait_for_timeout(1500)

        # Log final
        final_info = page.evaluate("""
            () => ({
                url:     window.location.pathname,
                receipt: !!document.querySelector(".receipt-container"),
                labeled: [...document.querySelectorAll(".labeled-value__value")].map(e => e.textContent.trim()).slice(0,4),
            })
        """)
        print(f"[DOM FINAL] {json.dumps(final_info, ensure_ascii=False)}")

        # Ocultar UI
        page.evaluate("""
        () => {
            [".bc-vouch-topbar","ion-header","[class*=topbar]",
             ".button-listo",".button-container","ion-spinner"].forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.style.display = "none");
            });
        }
        """)

        el = (
            page.query_selector(".receipt-wrapper") or
            page.query_selector(".receipt-container") or
            page.query_selector(".receipt-container__content-base")
        )

        print(f"[PW] Elemento a capturar: {el is not None}")
        png = el.screenshot(type="png") if el else page.screenshot(type="png", full_page=True)
        print(f"[PW] PNG generado: {len(png)} bytes")

        browser.close()
        return png

# ─── Rutas ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/captura/<mvalue>", methods=["GET"])
def captura_get(mvalue):
    print(f"\n[REQ] GET /captura/{mvalue}")
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png",
                         download_name=f"{mvalue}.png")
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/captura", methods=["POST"])
def captura_post():
    data   = request.json or {}
    mvalue = data.get("mvalue")
    print(f"\n[REQ] POST /captura — mvalue: {mvalue}")
    if not mvalue:
        return jsonify({"error": "mvalue requerido"}), 400
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png",
                         download_name=f"{mvalue}.png")
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
