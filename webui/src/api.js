// Every API call goes through api() — a 401 (expired session) → /login.
export async function api(url, opts) {
  const r = await fetch(url, opts);
  if (r.status === 401) {
    // сохраняем текущий URL (в т.ч. ?project=…) — после логина вернёмся
    location = "/login?next=" +
      encodeURIComponent(location.pathname + location.search);
    throw new Error("401");
  }
  return r;
}

export const apiJson = async (url, opts) => (await api(url, opts)).json();

export const post = (url, body) =>
  apiJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
