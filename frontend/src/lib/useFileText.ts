import { useEffect, useState } from "react";

export type Loaded = { status: "loading" } | { status: "error"; message: string } | { status: "ok"; text: string };

/** Fetches a file's text; shared by the text, table and notebook previews. */
export function useFileText(url: string): Loaded {
  const [state, setState] = useState<Loaded>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.text();
      })
      .then((text) => !cancelled && setState({ status: "ok", text }))
      .catch((error: Error) => !cancelled && setState({ status: "error", message: error.message }));
    return () => {
      cancelled = true;
    };
  }, [url]);
  return state;
}
