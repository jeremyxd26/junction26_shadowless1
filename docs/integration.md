# How S-mobiili embeds Sentti

Sentti is an **embeddable web module (WebView)**. S-mobiili opens it in a WebView, and the bank's own app stays the host: it owns the sign-in, the navigation around the module, and every action that changes something. This page is for the bank's mobile team. Read it in ten minutes; each section says what exists in this repository today and what is planned.

Status markers:
- **main**: on `main` now.
- **dev**: on the dev host (https://sentti.jeremyxd.dev), not yet on `main`.
- **planned**: not built, or only on a branch.

## 1. What is embedded

| | | Status |
|---|---|---|
| Origin | The module and its API live on **one origin**: the API under `/api/*`, the app's static build on every other path, and client routes fall back to `index.html` (`deploy/Caddyfile`). The app calls the API on its own origin, so there is no CORS and no third-party request (`app/src/api/client.ts`). | main (#78) |
| Screen | Full screen inside the host's chrome. The module's header has a back button and the title "Sentti", with no logo and no navigation bar of its own. The source of truth is `app/src/components/Header.tsx`; `app/DESIGN.md` section 3 also describes an "AI" tag and a language switch in the header, which the header does not have. | main |
| Routes | Three: `/` (overview), `/chat`, and `/cards` (a component gallery, only in mock builds). `?lang`, `?persona` and `?evidence` select the language, the demo customer and an open evidence sheet (`app/src/App.tsx`, `app/src/lib/url.ts`). | main |
| Width | Designed at 375 px, at most 480 px wide; `viewport-fit=cover` with the safe-area insets applied (`app/index.html`, `Header.tsx`, `App.tsx`). | main |
| Writes | Read-only towards the bank's data: the tools only read and simulate (rule R6, `docs/design/agent-core.md`). The service stores only its own evidence records, the recipes behind each number. The single planned write is the customer's own answer to a review card (`POST /api/baskets/label`, #68). | Read-only: main. Label write: planned (PR #141) |

The host loads the module **top-level** in its WebView, never inside an iframe of another page.

## 2. Identity

**In the demo (main):** the customer is a demo persona chosen in the app.
- The app sends the persona's `customer_id` in the path of `GET /api/overview/{customer_id}` and as `?customer_id=` for evidence (`app/src/api/client.ts`). The API also takes it in the body of `POST /api/whatif`, which the app does not call yet.
- The service checks that the customer exists (`core/app/api/deps.py`, `require_customer`).
- Only the four personas are served; any other id answers 404 `customer_not_found` (issue #101, PR #125): **dev**.

**In S-mobiili (planned):** the customer comes from the bank session, never from a client-supplied id (rule R4).
1. The host asks the bank's backend for a short-lived token for the signed-in customer (minutes, audience "sentti").
2. The host passes it to the module over the bridge (`host.session`, section 3), never in the URL.
3. The module exchanges it once at the service for an `HttpOnly`, `Secure`, `SameSite=Lax` session cookie, so the token does not stay in the page.
4. The service resolves the customer from that session.

**What changes in the service:**
- One function that resolves the customer from the session, used in the three handlers that take a customer today (overview, evidence, what-if) instead of the `customer_id` they are given.
- A token-exchange endpoint that sets the session cookie.
- A contract change: the `customer_id` parameters leave the API.

**What does not change:**
- The tools already receive the customer only from a server-built context `{customer_id, as_of, language}` and have no customer argument (R4).
- The metric SQL runs for exactly that one customer's range, which the server sets (`core/tools/metric_sql.py`).
- Evidence refs are checked against the customer who asks (403 for another customer's ref).
- Numbers, methods and evidence stay as they are.

## 3. The bridge between the module and the host

**Built today (main), iOS only:**
- The back button on the module's first screen posts `{ type: 'close' }` through `window.webkit.messageHandlers.sentti.postMessage(...)`, if that handler exists (`app/src/lib/url.ts`, `goBack`). Without the handler it steps back in the module's own history.
- Nothing is posted on Android, and the module handles no message from the host.

**The target (planned):** the versioned envelope below; the app aligns with it in issue #170.

Every message is `{"type": "...", "v": 1, "payload": {...}}`.
- **Module to host, iOS:** an object through `window.webkit.messageHandlers.sentti.postMessage(message)`.
- **Module to host, Android:** a string, `sentti.postMessage(JSON.stringify(message))`, on the `sentti` object that `addWebMessageListener` injects for the module's origin only.
- **Host to module, iOS:** the host runs `window.postMessage(message, origin)` in the page. The module accepts a message only if `event.source === window` and `event.origin === location.origin`.
- **Host to module, Android:** the host answers through the `replyProxy` it received with an earlier module message; the message arrives at `sentti.onmessage` in the page and can come from no one else.

| Direction | `type` | `payload` | What happens |
|---|---|---|---|
| module → host | `sentti.ready` | `{"version": "1", "language": "fi"}` | The module has loaded; the host may now send `host.context` and `host.session`. |
| module → host | `sentti.close` | `{}` | The customer leaves the module: the back button on the overview. The host closes the WebView. Today's `{ type: 'close' }` becomes this message. |
| module → host | `sentti.openTransaction` | `{"transaction_id": "tx_606016"}` | The customer taps a transaction in an evidence sheet. The host opens it in its own transaction view; the host maps the id. |
| module → host | `sentti.handoff` | `{"action": "transfer_to_savings", "amount": {"value": 50.0, "unit": "eur", "display": "€50.00"}, "label": "Move to savings"}` | The module suggests an action, for example "set up a transfer to savings". **S-mobiili carries it out with its own confirmation**; Sentti never moves money, changes settings or contacts anyone (R6). |
| host → module | `host.context` | `{"language": "fi", "theme": {"color-brand": "#007841"}}` | Language and theme, section 4. |
| host → module | `host.session` | `{"token": "<short-lived token>"}` | Identity, section 2. |
| host → module | `host.back` | `{}` | The Android back button: the module goes back one step (closes a sheet or leaves the chat), or answers `sentti.close` on the overview. |

The amount in a handoff is a Number object of the API contract (`contracts/api.md` section 2.1), so the host shows the same `display` the customer saw.

## 4. Language and theme from the host

- **Language:**
  - Today the module takes `?lang=fi` or `?lang=en` (default `en`), and every API response is already localised. The demo's persona sheet, opened by a long press on the header, also switches between EN and FI (main).
  - The host sets the language from S-mobiili's own setting, by the URL now and by `host.context` once the bridge exists.
  - Swedish (`sv`) is **planned**: the API and the app support `en` and `fi` only.
- **Theme:**
  - The palette, type and spacing are CSS variables in `app/design/tokens.css` (`--color-*`, `--text-*`, …), in the S-mobiili style (`app/DESIGN.md`, #92). The module is light only (main).
  - The host overriding single tokens through `host.context` is **planned**.
- **Safe areas:** `viewport-fit=cover`; the header pads `env(safe-area-inset-top)` and the content `env(safe-area-inset-bottom)`, so the module can draw under a transparent host status bar (main).
- **Text size:** WKWebView ignores the system text size. The layout survives 200 % zoom; an in-app text-size switch is a follow-up (`app/DESIGN.md` section 5).

## 5. Security

- **Headers** (dev, issue #102, PR #119):
  - HSTS, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` on every response.
  - The API sends `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
  - The app sends a CSP that allows only its own origin for scripts, styles, fonts, images (plus `data:`) and API calls, with `frame-ancestors 'self'`. That stops other sites from framing the module; the host's WebView loads it top-level, which `frame-ancestors` does not restrict.
  - `main`'s Caddyfile has no security headers yet.
- **Cookies** (**planned**, issue #144): the module will use one first-party, functional cookie. It is on neither `main` nor `dev` yet, only on the branch `r/144-viewer-sessions` (`core/app/api/viewer.py`).
  - **Name and value:** `sentti_viewer`, 32 random characters (192 bits) with no personal data. The server keeps only a hash and never logs the value.
  - **Attributes:** `HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=7200`.
  - **Where it is set,** when the request has none: by the overview, by the review answer, and by `GET /api/viewer/reset`, which gives a presenter a fresh state.
  - **Without it:** a client sees the shared pending state.
  - **In the bank:** the session of section 2 would ride on the same mechanism.
- **In the WebViews:** the cookie is first-party on the page's own origin.
  - **WKWebView:** Intelligent Tracking Prevention blocks third-party cookies. Its 7-day cap applies to storage that scripts write, not to a 2-hour `HttpOnly` cookie the server sets.
  - **Android WebView:** accepts first-party cookies by default.
  - No third-party cookie or request is used.
- **Nothing left on the device:**
  - The app stores nothing in `localStorage`, `sessionStorage` or IndexedDB, and registers no service worker (main; `app/DESIGN.md` section 5).
  - `index.html` is revalidated on every load; only the content-hashed assets are cached (main, `deploy/Caddyfile`).
  - For no state at all after the module closes, the host can use a non-persistent store: `WKWebsiteDataStore.nonPersistent()` on iOS, or clearing the WebView's cookies and cache on close on Android.
- **Bridge:** the host accepts messages only from the module's origin over HTTPS in the main frame (the examples check it), and the module only from its host (section 3). Messages carry no secrets except `host.session`, which the module exchanges at once.

## 6. Host examples (documentation only, not built)

Both examples target the planned envelope of section 3. The iOS example also accepts today's `{ type: 'close' }`.

iOS, `WKWebView`:

```swift
final class SenttiViewController: UIViewController, WKScriptMessageHandler {
    private let origin = URL(string: "https://sentti.example.fi")!
    private var webView: WKWebView!

    override func viewDidLoad() {
        super.viewDidLoad()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()                                    // nothing stays on the device
        config.userContentController.add(WeakHandler(self), name: "sentti")          // module -> host, no retain cycle
        webView = WKWebView(frame: view.bounds, configuration: config)
        webView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(webView)
        webView.load(URLRequest(url: origin.appending(queryItems: [.init(name: "lang", value: "fi")])))
    }

    func userContentController(_ c: WKUserContentController, didReceive message: WKScriptMessage) {
        let from = message.frameInfo.securityOrigin
        guard message.frameInfo.isMainFrame, from.protocol == "https", from.host == origin.host,
              let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
        switch type {
        case "sentti.ready": send(["type": "host.session", "v": 1, "payload": ["token": BankSession.senttiToken()]])
        case "sentti.close", "close": dismiss(animated: true)                     // "close": today's message
        case "sentti.openTransaction", "sentti.handoff": HostRouter.handle(body)   // S-mobiili's own screens
        default: break
        }
    }

    private func send(_ message: [String: Any]) {
        let json = String(data: try! JSONSerialization.data(withJSONObject: message), encoding: .utf8)!
        webView.evaluateJavaScript("window.postMessage(\(json), '\(origin.absoluteString)')")
    }
}

/// The content controller retains its handlers; this proxy keeps only a weak reference to the screen.
final class WeakHandler: NSObject, WKScriptMessageHandler {
    weak var target: WKScriptMessageHandler?
    init(_ target: WKScriptMessageHandler) { self.target = target }
    func userContentController(_ c: WKUserContentController, didReceive m: WKScriptMessage) {
        target?.userContentController(c, didReceive: m)
    }
}
```

Android, `WebView` (with `androidx.webkit`):

```kotlin
class SenttiActivity : AppCompatActivity() {
    private val origin = "https://sentti.example.fi"
    private var reply: JavaScriptReplyProxy? = null   // set by the module's first message

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) { finish(); return }
        val web = WebView(this).also { setContentView(it) }
        web.settings.javaScriptEnabled = true
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false)   // first-party only
        // `sentti` is injected for the module's origin only; the module posts JSON strings on it.
        WebViewCompat.addWebMessageListener(web, "sentti", setOf(origin)) { _, message, _, isMainFrame, replyProxy ->
            if (!isMainFrame) return@addWebMessageListener
            reply = replyProxy
            val msg = JSONObject(message.data ?: return@addWebMessageListener)
            when (msg.getString("type")) {
                "sentti.ready" -> send(JSONObject(mapOf("type" to "host.session", "v" to 1,
                    "payload" to mapOf("token" to BankSession.senttiToken()))))
                "sentti.close" -> finish()
                "sentti.openTransaction", "sentti.handoff" -> HostRouter.handle(this, msg)  // S-mobiili's own screens
            }
        }
        // Back: to the module once it has spoken, otherwise (not loaded yet) close the screen.
        onBackPressedDispatcher.addCallback(this) {
            if (reply == null) finish() else send(JSONObject(mapOf("type" to "host.back", "v" to 1, "payload" to JSONObject())))
        }
        web.loadUrl("$origin/?lang=fi")
    }

    private fun send(msg: JSONObject) { reply?.postMessage(msg.toString()) }   // arrives at sentti.onmessage
}
```

`BankSession` and `HostRouter` stand for S-mobiili's own session and navigation code.

## 7. What is not built yet

- **Identity from the host:** the token exchange, the session cookie it sets and the function that resolves the customer from it (section 2). The demo uses persona ids.
- **The bridge:** only today's iOS `{ type: 'close' }` is built. The versioned messages of section 3, Android, and handling messages from the host are planned; the app aligns in issue #170.
- **Swedish:** `sv` in the API, the texts and the app.
- **Theme tokens from the host:** the module uses its own S-mobiili-style tokens.
- **On `dev`, not yet on `main`:**
  - the security headers (issue #102, PR #119);
  - only the persona customers served (issue #101, PR #125).
- **Planned:**
  - the viewer-session cookie and the rate limit on the review answer (issue #144, on a branch only);
  - the review-card answer, the module's one write (#68, PR #141).
