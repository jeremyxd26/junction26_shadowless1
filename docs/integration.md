# How S-mobiili embeds Sentti

Sentti is **an embeddable web module for S-mobiili**. S-mobiili opens it in a WebView, and the bank's own app stays the host: it owns the sign-in, the navigation around the module, and every action that changes something. This page is for the bank's mobile team. Read it in ten minutes; each section says what exists in this repository today and what is planned.

Status markers:
- **main**: on `main` now.
- **dev**: on the dev host (https://sentti.jeremyxd.dev), not yet on `main`.
- **planned**: not built, or only on a branch.

## 1. What is embedded

| | | Status |
|---|---|---|
| Origin | The module and its API live on **one origin**: the API under `/api/*`, the app's static build on every other path, and client routes fall back to `index.html` (`deploy/Caddyfile`). The app calls the API on its own origin, so there is no CORS and no third-party request (`app/src/api/client.ts`). | main (#78) |
| Screen | Full screen inside the host's chrome. The module's header has a back button and the title "Sentti", with no logo and no navigation bar of its own. The back button shows only where it has somewhere to go: over a sheet, on an inner screen, or on the first screen when a host listens (it then sends `sentti.close`, section 3). In a plain browser the first screen shows no back arrow (`canGoBack` in `app/src/lib/url.ts`, #170). The source of truth is `app/src/components/Header.tsx`; `app/DESIGN.md` section 3 also describes an "AI" tag and a language switch in the header, which the header does not have. | main |
| Chat first | The first screen becomes a chat thread that Sentti opens; the overview becomes a row in that thread and a bottom sheet. The module still has no navigation of its own (#311, #321). | planned |
| Routes | Three: `/` (overview), `/chat` (the streamed chat on `POST /api/ask`, #87), and `/cards` (a component gallery, only in mock builds). Query parameters (`app/src/App.tsx`, `app/src/lib/url.ts`):<br>- `?lang=` the language, `?persona=` the demo customer;<br>- `?evidence=<ref>` an open evidence sheet;<br>- `?whatif=<kind>:<value>&cut=<pct>` an open what-if sheet (#154);<br>- `/chat?q=<question>` asks that question when the chat opens.<br>Sheets and screens are browser history entries, so the WebView's own back closes a sheet or leaves a screen. | main |
| Width | Designed at 375 px, at most 480 px wide; `viewport-fit=cover` with the safe-area insets applied (`app/index.html`, `Header.tsx`, `App.tsx`). | main |
| Writes | Read-only towards the bank's data: the tools only read and simulate (rule R6, `docs/design/agent-core.md`). The service stores only its own evidence records, the recipes behind each number. The single write is the customer's own answer to a review card (`POST /api/baskets/label`, #68), kept per viewer behind the cookie of section 5 (#144). | Read-only: main. Label API: main (PR #141). Answering from the app's review card: planned (#35, PR #157) |

The host loads the module **top-level** in its WebView, never inside an iframe of another page. The only frame is the demo page (planned, #325): `/demo.html` on the module's own origin, a neutral host frame around the module that stubs `window.sentti`, which the app's `frame-ancestors 'self'` allows.

## 2. Identity

**In the demo (main):** the customer is a demo persona chosen in the app.
- The app sends the persona's `customer_id`:
  - in the path of `GET /api/overview/{customer_id}` and as `?customer_id=` for evidence (`app/src/api/client.ts`);
  - in the body of `POST /api/whatif` (`app/src/api/client.ts`, #154) and of `POST /api/ask` (`app/src/lib/useChat.ts`, `app/src/api/ask.ts`).
- Five handlers take a customer. Overview, evidence, what-if and the label write enter through `customer_connection` (`core/app/api/deps.py`); ask applies the same two checks in `core/agent/api.py`:
  - **Personas only:** only the four personas are served (setting `DEMO_CUSTOMERS`, default `personas`, `core/app/settings.py`). Any other id answers 404 `customer_not_found` before the database is touched (issue #101): **main**.
  - **Existence check:** the service then checks that the customer exists (`require_customer`): **main**.

**Demo only, removed in a bank build:** `?persona=`, the persona sheet (a long press on the header; in a plain browser also a header button, #323) and `GET /api/personas`. The client then stops sending `customer_id`.

**In S-mobiili (planned):** the customer comes from the bank session, never from a client-supplied id (rule R4).
1. The host asks the bank's backend for a short-lived token for the signed-in customer (minutes, audience "sentti").
2. The host passes it to the module over the bridge (`host.session`, section 3), never in the URL.
3. The module exchanges it once at the service for an `HttpOnly`, `Secure`, `SameSite=Lax` session cookie, so the token does not stay in the page.
4. The service resolves the customer from that session.

**What changes in the service:**
- One function that resolves the customer from the session, used in the five handlers that take a customer today (overview, evidence, what-if, ask, label) instead of the `customer_id` they are given.
- A token-exchange endpoint that sets the session cookie.
- A contract change: the `customer_id` parameters leave the API.

**What does not change:**
- The tools already receive the customer only from a server-built context `{customer_id, as_of, language}` and have no customer argument (R4).
- The metric SQL runs for exactly that one customer's range, which the server sets (`core/tools/metric_sql.py`).
- Evidence refs are checked against the customer who asks (403 for another customer's ref).
- Numbers, methods and evidence stay as they are.

## 3. The bridge between the module and the host

Every message is `{"type": "...", "v": 1, "payload": {...}}`. Message names are camelCase after the `sentti.` prefix.
- **Module to host, iOS:** an object through `window.webkit.messageHandlers.sentti.postMessage(message)`.
- **Module to host, Android:** a string, `sentti.postMessage(JSON.stringify(message))`, on the `sentti` object that `addWebMessageListener` injects for the module's origin only.
- **Host to module, iOS (planned):** the host runs `window.postMessage(message, origin)` in the page. The module accepts a message only if `event.source === window` and `event.origin === location.origin`.
- **Host to module, Android (planned):** the host answers through the `replyProxy` it received with an earlier module message; the message arrives at `sentti.onmessage` in the page and can come from no one else.

**Built today (main, #170):** `app/src/lib/hostBridge.ts` sends the envelope on iOS (an object) and on Android (a JSON string). When both host objects exist, iOS wins, so a message is never sent twice.
- The only message sent today is `sentti.close`, from the back button on the module's first screen: the overview `/` with no sheet open (`goBack` in `app/src/lib/url.ts`).
- Without a host, the first screen shows no back arrow. If the host's handler throws, the back button does nothing there; the module never navigates away on its own.
- The module handles no message from the host yet.

| Direction | `type` | `payload` | What happens | Status |
|---|---|---|---|---|
| module → host | `sentti.close` | `{}` | The customer leaves the module: the back button on the module's first screen. The host closes the WebView. | main (#170) |
| module → host | `sentti.paymentDraft` | `{payee, iban, reference, amount, due_date}` | The customer taps "Add to payments" on an explained bill. **S-mobiili shows the payment in its own payment screen, and the customer confirms it there.** Sentti never pays (`contracts/api.md` section 11.3). | contract 0.3.0 on main; app: dev (#331, merged with #563) |
| module → host | `sentti.openHostScreen` | `{"target": "monthly_saving"}` | The customer taps a card's link into the bank's own screen. `target` is `monthly_saving` (the safe-to-save card), `bonus_to_fund` (the S-Bonus estimate) or `contact_bank` (the way to a human: refusals and bills with warning signs, contract 0.3.3, #420); the payday plan will reuse it (#258). The host ignores a target it does not know. | contract 0.3.1 on dev; app: dev for `monthly_saving` and `bonus_to_fund` (#268), `contact_bank` planned (#470) |
| module → host | `sentti.ready` | `{"version": "1", "language": "fi"}` | The module has loaded; the host may now send `host.context` and `host.session`. | planned, no issue yet |
| module → host | `sentti.openTransaction` | `{"transaction_id": "tx_606016"}` | The customer taps a transaction in an evidence sheet. The host opens it in its own transaction view; the host maps the id. | planned, no issue yet |
| host → module | `host.context` | `{"language": "fi", "theme": {"color-brand": "#007841"}}` | Language and theme, section 4. | planned, no issue yet |
| host → module | `host.session` | `{"token": "<short-lived token>"}` | Identity, section 2. | planned, no issue yet |
| host → module | `host.back` | `{}` | The Android back button: the module goes back one step (closes a sheet or leaves the chat), or answers `sentti.close` on its first screen. Until it exists, see the Android example in section 6. | planned, no issue yet |

Every amount in a message is a Number object of the API contract (`contracts/api.md` section 2.1), so the host shows the same `display` the customer saw.

**The generic hand-over message is retired.** An earlier draft of this page had one hand-over message for any action, with a free `action` field. Each hand-over now has its own named message with a fixed payload (`sentti.paymentDraft`, `sentti.openHostScreen`), and S-mobiili always carries it out with its own confirmation: Sentti never moves money, changes settings or contacts anyone (R6). In the app, one helper sends them (`handOver`, #324, PR #356); in a plain browser it shows "This continues in the bank app." instead.

**`sentti.openHostScreen`** (contract 0.3.1, section 3, the action `open_host_screen`; core #267, app #268). It is one step from a card into the bank's own app.
- The payload is `{target}` and nothing else: no amount, no customer data, no fund or product name.
- `target` comes from a closed list:

| `target` | Sent from | The host opens |
|---|---|---|
| `monthly_saving` | the safe-to-save card, when the monthly figure is above 0 | its monthly saving screen |
| `bonus_to_fund` | the S-Bonus estimate, when an estimate is offered | its Bonus to fund screen |
| `contact_bank` | a refusal, the "I can't answer that one yet" answer and the "nothing found" fallback of `/api/ask` (`done.actions`), and a bill explanation with a failed check or an unknown payee together with another sign (contract 0.3.3, #420) | its own way to contact S-Pankki, a human at the bank |

- The host shows its own screen, with its own figures and terms; the customer decides everything there. Sentti recommends nothing there, says nothing about returns and moves no money.
- **The host ignores a target it does not know**, so a newer module never makes an older host fail. No answer from the host is defined.
- The message uses the envelope above, which the app adopted in PR #175. The API's action type stays `open_host_screen`; the host message name is camelCase like `sentti.openTransaction`.

## 4. Language and theme from the host

- **Language:**
  - Today the module takes `?lang=fi` or `?lang=en` (default `en`), and every API response is already localised. The demo's persona sheet, opened by a long press on the header, also switches between EN and FI (main).
  - The host sets the language from S-mobiili's own setting, by the URL now and by `host.context` once the bridge exists.
  - Swedish (`sv`) is **planned**: the API and the app support `en` and `fi` only.
- **Theme:**
  - The palette, type and spacing are CSS variables in `app/design/tokens.css` (`--color-*`, `--text-*`, …), in the S-mobiili style (`app/DESIGN.md`, #92). The module is light only (main).
  - The host overriding single tokens through `host.context` is **planned**.
- **WebView basics (main):**
  - Safe areas: `viewport-fit=cover`; the header pads `env(safe-area-inset-top)`, and the content and the chat composer pad `env(safe-area-inset-bottom)`, so the module can draw under a transparent host status bar and above the home indicator (`app/index.html`, `Header.tsx`, `App.tsx`, `app/src/screens/Chat.tsx`).
  - Inputs are at least 16 px, so iOS does not zoom into them (`app/src/index.css`).
  - Tap targets are at least 44 × 44 px (`--tap-min`, `app/DESIGN.md` section 1).
- **Text size:** WKWebView ignores the system text size. The layout is designed to survive 200 % zoom; an in-app text-size switch is a follow-up (`app/DESIGN.md` section 5).
- **Read aloud (#252, `app/src/lib/speech.ts`, `SpeakButton.tsx`):** a speaker button next to each of Sentti's answers reads its `text_rendered` with the device's `speechSynthesis`. Only voices that run on the device are used (`localService: true`); a cloud voice, such as Chrome's "Google …" or Edge's "… Online (Natural)" voices, is never picked, so no text is sent anywhere. Without a local voice for the answer's language the button is hidden. Nothing plays without a tap; a second tap, another answer, a new question or leaving the chat stops it.
- **Speak a question (#735, `app/src/lib/stt.ts`, `ComposerMicButton.tsx`):** a mic in the composer, in a live build with a microphone API only. Nothing is recorded without a tap: a tap asks for the microphone and records at most 15 seconds (a second tap stops sooner), then the clip is sent to the core (`POST /api/stt`), which has the model provider (Gemini) turn it into text and sends the text back. The text lands in the composer and is sent only when the user taps send. Neither the app nor the core stores the audio or the text. In the demo frame the iframe carries `allow="microphone"`; a host WebView must grant the page microphone access (on iOS, WKWebView also needs the app's microphone usage description).

## 5. Security

- **Headers** (main, issue #102, `deploy/Caddyfile`):
  - HSTS, `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer` on every response.
  - The API sends `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.
  - The app sends a CSP that allows only its own origin for scripts, styles, fonts, images (plus `data:`) and API calls, with `frame-ancestors 'self'`. That stops other sites from framing the module; the host's WebView loads it top-level, which `frame-ancestors` does not restrict, and the demo page (#325) frames it from the same origin.
- **Cookies** (main, issue #144, PR #199): the module uses one first-party, functional cookie (`core/app/api/viewer.py`).
  - **Name and value:** `sentti_viewer`, 32 random characters (192 bits) with no personal data. The server keeps only a hash and never logs the value.
  - **Attributes:** `HttpOnly; SameSite=Lax; Secure; Path=/; Max-Age=7200`.
  - **Where it is set:** by the overview and by the review answer when the request has none, and by `GET /api/viewer/reset` always (a new cookie, so a presenter gets a fresh state).
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
- **Bridge:**
  - The host accepts messages only from the module's origin over HTTPS in the main frame (the examples check it).
  - The module posts from its own page, where the host injects its objects: Android's `sentti` only for the module's origin, and iOS's `webkit.messageHandlers.sentti` in a WebView that loads only the module. The app's CSP `script-src 'self'` keeps every other script out of that page, so only the module's own code can post on them.
  - The module will accept messages only from its host (section 3, planned).
  - Messages carry no secrets except `host.session`, which the module exchanges at once.

## 6. Host examples (documentation only, not built)

Both examples use the envelope of section 3. `sentti.close` is what the module sends today; the other messages are planned.

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
        webView.allowsBackForwardNavigationGestures = true                          // edge swipe closes a sheet or leaves a screen
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
        case "sentti.close": dismiss(animated: true)
        case "sentti.paymentDraft", "sentti.openHostScreen", "sentti.openTransaction":
            HostRouter.handle(body)                                                  // S-mobiili's own screens; an unknown target is ignored
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
                "sentti.paymentDraft", "sentti.openHostScreen", "sentti.openTransaction" ->
                    HostRouter.handle(this, msg)   // S-mobiili's own screens; an unknown target is ignored
            }
        }
        // Back, today: the module's sheets and screens are history entries, so step back in the
        // WebView and close the screen when there is nothing left. Once `host.back` exists (planned),
        // send it instead and let the module answer `sentti.close` on its first screen.
        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else finish()
        }
        web.loadUrl("$origin/?lang=fi")
    }

    private fun send(msg: JSONObject) { reply?.postMessage(msg.toString()) }   // arrives at sentti.onmessage
}
```

`BankSession` and `HostRouter` stand for S-mobiili's own session and navigation code.

## 7. What is not built yet

- **Identity from the host:** the token exchange, the session cookie it sets and the function that resolves the customer from it (section 2). The demo uses persona ids.
- **The bridge:** `sentti.close` on iOS and Android is built (#170); `sentti.paymentDraft` (#331) and `sentti.openHostScreen` (#268) are on dev. `sentti.ready`, `sentti.openTransaction` and every message from the host are planned.
- **Swedish:** `sv` in the API, the texts and the app.
- **Theme tokens from the host:** the module uses its own S-mobiili-style tokens.
- **Planned in the app:**
  - answering the review card, the module's one write (#35, PR #157; the API is on main, PR #141);
  - the chat-first first screen (#311);
  - the persona button outside a host (#323);
  - the demo page `/demo.html` (#325).
