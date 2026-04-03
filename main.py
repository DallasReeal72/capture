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

    # Mismo script que funciona en el browser — inyectar sesión + PWA spoof
    inject_and_navigate = f"""
    async () => {{
        const AUTH_KEY  = {json.dumps(auth_key)};
        const authUser  = {json.dumps(auth_user)};
        const DEVICE_ID = {json.dumps(DEVICE_ID)};
        const TARGET    = "/comprobante/{mvalue}";

        // 1. Sesión en localStorage
        localStorage.setItem(AUTH_KEY, JSON.stringify(authUser));
        localStorage.setItem("device_id", DEVICE_ID);
        localStorage.setItem("accountType", "deposit");
        localStorage.setItem("security_notice_dont_show_again", "true");

        // 2. IndexedDB
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
                tx.oncomplete = resolve; tx.onerror = resolve;
            }};
            req.onerror = resolve;
        }});

        // 3. PWA spoof
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

        // 4. Esperar ion-router (igual que en el script del browser)
        const ionRouter = await new Promise(resolve => {{
            let n = 0;
            const t = setInterval(() => {{
                const r = document.querySelector("ion-router");
                if (r || ++n > 50) {{ clearInterval(t); resolve(r); }}
            }}, 100);
        }});

        // 5. Navegar
        if (ionRouter) {{
            await ionRouter.push(TARGET, "forward");
        }} else {{
            window.history.pushState({{}}, "", TARGET);
            window.dispatchEvent(new PopStateEvent("popstate", {{ state: {{}} }}));
        }}
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

        # 1. Cargar app en la raíz (igual que cuando abres el browser)
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=30000)

        # 2. Ejecutar inyección + navegación (exactamente como el inject_session.js)
        page.evaluate(inject_and_navigate)

        # 3. Esperar que aparezca el comprobante (igual que el script del browser)
        try:
            page.wait_for_function("""
                () => {
                    return document.querySelector(".receipt-container") ||
                           document.querySelector(".receipt-content")   ||
                           document.querySelector(".labeled-value")     ||
                           document.querySelector(".receipt-container__content-base");
                }
            """, timeout=30000)
        except:
            pass

        # 4. Esperar que los datos estén cargados (no spinner)
        try:
            page.wait_for_function("""
                () => {
                    const vals = document.querySelectorAll(".labeled-value__value");
                    return vals.length >= 2 &&
                           [...vals].filter(e => e.textContent.trim().length > 1).length >= 2;
                }
            """, timeout=20000)
        except:
            pass

        # 5. Buffer final igual que en el script (1500ms)
        page.wait_for_timeout(1500)

        # 6. Ocultar topbar
        page.evaluate("""
        () => {
            [".bc-vouch-topbar", "ion-header", "[class*=topbar]",
             ".button-listo", ".button-container", "ion-spinner"].forEach(sel => {
                document.querySelectorAll(sel).forEach(el => el.style.display = "none");
            });
        }
        """)

        # 7. Capturar el elemento del comprobante
        el = (
            page.query_selector(".receipt-wrapper") or
            page.query_selector(".receipt-container") or
            page.query_selector(".receipt-container__content-base")
        )

        png = el.screenshot(type="png") if el else page.screenshot(type="png", full_page=True)
        browser.close()
        return png

# ─── Rutas ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/captura/<mvalue>", methods=["GET"])
def captura_get(mvalue):
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png",
                         download_name=f"{mvalue}.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/captura", methods=["POST"])
def captura_post():
    data   = request.json or {}
    mvalue = data.get("mvalue")
    if not mvalue:
        return jsonify({"error": "mvalue requerido"}), 400
    try:
        png = capture(mvalue)
        return send_file(io.BytesIO(png), mimetype="image/png",
                         download_name=f"{mvalue}.png")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
