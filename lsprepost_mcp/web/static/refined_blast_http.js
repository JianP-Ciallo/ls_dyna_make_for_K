// Keep the HTTP response available for operation-specific conflict handling.
export async function fetchJson(fetcher, url, options = {}) {
  const response = await fetcher(url, options);
  const body = await response.json();
  return { response, body };
}
