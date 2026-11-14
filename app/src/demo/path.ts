// `?path=` of the demo frame (#326): the module path to load in the iframe. Only a path on the
// frame's own origin is taken. The value goes through the URL parser first, because the parser
// drops tabs and newlines: `/\t/evil.example` would otherwise become `//evil.example`, another host.

/** The same-origin path and query of `value`, or `/` for anything that leaves the origin. */
export function safePath(value: string | null, origin: string): string {
  if (!value) return '/'
  let url: URL
  try {
    url = new URL(value, origin)
  } catch {
    return '/'
  }
  if (url.origin !== origin) return '/'
  return url.pathname + url.search
}

/** The iframe URL: the safe path with `lang` (and `persona` when set) added to its query. */
export function moduleHref(path: string, origin: string, lang: string, persona: string): string {
  const url = new URL(safePath(path, origin), origin)
  url.searchParams.set('lang', lang)
  if (persona) url.searchParams.set('persona', persona)
  else url.searchParams.delete('persona')
  return url.pathname + url.search
}
