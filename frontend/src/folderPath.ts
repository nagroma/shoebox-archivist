export function localPathFromUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (url.protocol !== 'file:' || url.hostname || url.search || url.hash) return
    const path = decodeURIComponent(url.pathname)
    return /^\/[a-z]:\//i.test(path) ? path.slice(1) : path
  } catch {
    return undefined
  }
}

