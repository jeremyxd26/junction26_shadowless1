// Messages from the module to the host app (docs/integration.md, section 3).
// Every message is an envelope `{ type: "sentti.<name>", v: 1, payload }`:
// - iOS (WKWebView): `window.webkit.messageHandlers.sentti.postMessage(message)`, as an object;
// - Android (WebView, `addWebMessageListener` named "sentti"): `window.sentti.postMessage(json)`,
//   as a JSON string, because that channel carries strings;
// - a plain browser has neither, so nothing is sent.
// Messages from the host to the module are out of scope here.

export const BRIDGE_VERSION = 1

export interface HostMessage {
  type: `sentti.${string}`
  v: typeof BRIDGE_VERSION
  payload: Record<string, unknown>
}

interface PostMessage<T> {
  postMessage(message: T): void
}

/** The globals a host injects; `window` in the app, a stub in tests. */
export interface HostScope {
  webkit?: { messageHandlers?: { sentti?: PostMessage<HostMessage> } }
  sentti?: PostMessage<string>
}

function currentScope(): HostScope {
  return (typeof window !== 'undefined' ? window : globalThis) as unknown as HostScope
}

export function envelope(name: string, payload: Record<string, unknown> = {}): HostMessage {
  return { type: `sentti.${name}`, v: BRIDGE_VERSION, payload }
}

/**
 * Which host is listening: iOS, Android or none (a plain browser). iOS wins when both objects
 * exist, so a message is never sent twice: a page in WKWebView cannot get a real Android bridge,
 * but a page may define its own `window.sentti`.
 */
export function hostPlatform(scope: HostScope = currentScope()): 'ios' | 'android' | null {
  if (typeof scope.webkit?.messageHandlers?.sentti?.postMessage === 'function') return 'ios'
  if (typeof scope.sentti?.postMessage === 'function') return 'android'
  return null
}

/**
 * Sends `sentti.<name>` to the host. Returns true when a host took the message, so the caller
 * can fall back to in-app behaviour in a plain browser or when the host's handler throws.
 */
export function sendToHost(name: string, payload: Record<string, unknown> = {}, scope: HostScope = currentScope()): boolean {
  const message = envelope(name, payload)
  try {
    switch (hostPlatform(scope)) {
      case 'ios':
        scope.webkit!.messageHandlers!.sentti!.postMessage(message)
        return true
      case 'android':
        scope.sentti!.postMessage(JSON.stringify(message))
        return true
      default:
        return false
    }
  } catch {
    return false
  }
}
