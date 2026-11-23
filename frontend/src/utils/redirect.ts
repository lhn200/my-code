export function sanitizeRedirect(raw: unknown): string {
  if (typeof raw !== 'string') {
    return '/'
  }
  const value = raw.trim()
  if (!value.startsWith('/') || value.startsWith('//')) {
    return '/'
  }
  if (value.startsWith('/login') || value.startsWith('/register')) {
    return '/'
  }
  return value
}
