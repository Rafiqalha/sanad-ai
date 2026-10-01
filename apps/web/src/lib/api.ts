const base = process.env.SANAD_API_URL ?? "http://127.0.0.1:8000";

export type SearchResponse = unknown;

export async function postSearch(text: string): Promise<SearchResponse> {
  const res = await fetch(`${base}/v1/search`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
