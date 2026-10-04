import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PhoneCall, Search } from "lucide-react";
import { Field, Loading, Modal, Notice } from "./components";
type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
type Owned = { phone_number: string; status: string; label: string };
type Available = {
  phone_number: string;
  locality?: string;
  state?: string;
  upfront_cost?: string;
  monthly_cost?: string;
  currency?: string;
};
const STATES =
  "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(
    " ",
  );
export const formatPhone = (n: string) =>
  /^\+1\d{10}$/.test(n)
    ? `+1 (${n.slice(2, 5)}) ${n.slice(5, 8)}-${n.slice(8)}`
    : n;
const money = (value?: string) =>
  value === undefined ? "?" : `$${Number(value).toFixed(2)}`;
export function CallerNumbers({ api, demo }: { api: Api; demo: boolean }) {
  const [owned, setOwned] = useState<Owned[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [state, setState] = useState("FL");
  const [areaCode, setAreaCode] = useState("");
  const [results, setResults] = useState<Available[] | null>(null);
  const [buying, setBuying] = useState<Available | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [ordered, setOrdered] = useState("");
  const [quota, setQuota] = useState<{ used: number; limit: number } | null>(
    null,
  );
  const load = useCallback(
    () =>
      api<{
        selected: string | null;
        numbers: Owned[];
        used?: number;
        limit?: number;
      }>("/numbers")
        .then((r) => {
          setOwned(Array.isArray(r?.numbers) ? r.numbers : []);
          setSelected(r?.selected ?? null);
          setQuota(
            typeof r?.limit === "number"
              ? { used: r.used ?? 0, limit: r.limit }
              : null,
          );
        })
        .catch((e) => {
          setOwned([]);
          setError((e as Error).message);
        }),
    [api],
  );
  useEffect(() => {
    load();
  }, [load]);
  const pending = !!owned?.some((n) => n.status !== "active");
  useEffect(() => {
    // Newly bought numbers activate within about a minute; re-check until they do.
    if (!pending) return;
    let checks = 0;
    const timer = setInterval(() => {
      if (++checks > 24) clearInterval(timer);
      else load();
    }, 5000);
    return () => clearInterval(timer);
  }, [pending, load]);
  useEffect(() => {
    if (
      owned?.some((n) => n.phone_number === ordered && n.status === "active")
    ) {
      setOrdered("");
      setNotice(
        `${formatPhone(ordered)} is active. Choose "Use this number" to call from it.`,
      );
    }
  }, [owned, ordered]);
  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function search(e: FormEvent) {
    e.preventDefault();
    act(async () => {
      const found = await api<Available[]>(
        `/numbers/available?state=${state}&area_code=${areaCode}`,
      );
      setResults(Array.isArray(found) ? found : []);
    });
  }
  return (
    <section className="card caller-numbers">
      <h2>Caller number</h2>
      <p className="muted">
        Leads see this number when the AI or an agent calls them.
      </p>
      {error && <Notice error>{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      {!owned ? (
        <Loading />
      ) : (
        <ul className="number-list">
          {owned.map((n) => (
            <li key={n.phone_number}>
              <div>
                <strong>{formatPhone(n.phone_number)}</strong>
                <small>{n.label || "Telnyx number"}</small>
              </div>
              {n.phone_number === selected ? (
                <span className="badge active">In use</span>
              ) : n.status !== "active" ? (
                <span className="badge">{n.status.replaceAll("_", " ")}</span>
              ) : (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await api("/numbers/select", "POST", {
                        phone_number: n.phone_number,
                      });
                      await load();
                    })
                  }
                >
                  Use this number
                </button>
              )}
            </li>
          ))}
          {!owned.length && (
            <li className="muted">No numbers on this account yet.</li>
          )}
        </ul>
      )}
      <form className="number-search" onSubmit={search}>
        <h3>Find a new number</h3>
        {quota && (
          <p className="muted">
            {quota.used} of {quota.limit} numbers bought through the app
            {quota.used >= quota.limit &&
              ". Raise the limit in Settings to buy more."}
          </p>
        )}
        <div className="row wrap">
          <Field label="State">
            <select value={state} onChange={(e) => setState(e.target.value)}>
              {STATES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Area code" hint="Optional, e.g. 407">
            <input
              inputMode="numeric"
              pattern="\d{3}"
              maxLength={3}
              value={areaCode}
              onChange={(e) => setAreaCode(e.target.value.replace(/\D/g, ""))}
            />
          </Field>
          <button disabled={busy}>
            <Search size={16} /> Search
          </button>
        </div>
      </form>
      {results &&
        (results.length ? (
          <ul className="number-list">
            {results.map((n) => (
              <li key={n.phone_number}>
                <div>
                  <strong>{formatPhone(n.phone_number)}</strong>
                  <small>
                    {[n.locality, n.state].filter(Boolean).join(", ")} ·{" "}
                    {money(n.upfront_cost)} now + {money(n.monthly_cost)}/month
                  </small>
                </div>
                <button
                  className="secondary"
                  disabled={busy || (!!quota && quota.used >= quota.limit)}
                  title={
                    quota && quota.used >= quota.limit
                      ? "Purchase limit reached; raise it in Settings"
                      : undefined
                  }
                  onClick={() => setBuying(n)}
                >
                  <PhoneCall size={15} /> Buy
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            No numbers available there. Try another area code or leave it empty.
          </p>
        ))}
      {buying && (
        <Modal title="Buy this number?" onClose={() => setBuying(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const number = buying;
              act(async () => {
                await api("/numbers/order", "POST", {
                  phone_number: number.phone_number,
                });
                setBuying(null);
                setResults(null);
                if (!demo) setOrdered(number.phone_number);
                setNotice(
                  demo
                    ? "Demo mode: nothing was bought."
                    : `Ordered ${formatPhone(number.phone_number)}. It appears above once Telnyx activates it, usually within a minute. Then choose "Use this number".`,
                );
                await load();
              });
            }}
          >
            <p>
              <strong>{formatPhone(buying.phone_number)}</strong>
              {buying.locality && ` in ${buying.locality}, ${buying.state}`}
            </p>
            <p>
              {demo
                ? "Demo mode: this is simulated and nothing is charged."
                : `Telnyx charges ${money(buying.upfront_cost)} now and ${money(buying.monthly_cost)} per month until you release it. It is connected to your calling app automatically.`}
            </p>
            {error && <Notice error>{error}</Notice>}
            <footer className="actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setBuying(null)}
              >
                Cancel
              </button>
              <button disabled={busy}>{busy ? "Buying…" : "Buy number"}</button>
            </footer>
          </form>
        </Modal>
      )}
    </section>
  );
}
