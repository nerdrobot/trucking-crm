import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Grid3x3, Mic, MicOff, PhoneIncoming, PhoneOff } from "lucide-react";
import { type Lead, type Session } from "./api";
import { formatPhone } from "./CallerNumbers";
import { Modal, Notice } from "./components";
import { LogCallForm } from "./Queue";

type Api = <T>(path: string, method?: string, body?: unknown) => Promise<T>;
// The parts of the Telnyx SDK's Call object the dialer uses.
interface RtcCall {
  id: string;
  state: string;
  direction: string;
  options: { remoteCallerNumber?: string; remoteCallerName?: string };
  answer(): Promise<void>;
  hangup(): Promise<void>;
  toggleAudioMute(): void;
  dtmf(digit: string): void;
}
interface RtcClient {
  remoteElement: string;
  on(event: string, handler: (payload: never) => void): void;
  connect(): Promise<void>;
  disconnect(): Promise<void>;
}
type Status = "off" | "connecting" | "ready" | "error" | "demo";
interface DialerValue {
  status: Status;
  ready: boolean;
  callLead: (lead: Lead) => Promise<void>;
}
const DialerContext = createContext<DialerValue | null>(null);
export const useDialer = () => useContext(DialerContext);

const ENDED = ["hangup", "destroy", "purge"];
const KEYS = "123456789*0#".split("");
// A dialer leg that rings within this window of clicking "Call in browser" is answered automatically.
const AUTO_ANSWER_MS = 60000;
const elapsed = (since: number) => {
  const seconds = Math.max(0, Math.floor((Date.now() - since) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
};

export function DialerProvider({
  api,
  session,
  onChanged,
  children,
}: {
  api: Api;
  session: Session;
  onChanged: () => void;
  children: ReactNode;
}) {
  const demo = session.mode === "demo";
  const enabled = demo || !!session.browser_ready;
  const [status, setStatus] = useState<Status>(demo ? "demo" : "off");
  const [error, setError] = useState("");
  const [call, setCall] = useState<RtcCall | null>(null);
  const [, setTick] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [muted, setMuted] = useState(false);
  const [keypad, setKeypad] = useState(false);
  const [activeLead, setActiveLead] = useState<Lead | null>(null);
  const [logLead, setLogLead] = useState<Lead | null>(null);
  const client = useRef<RtcClient | null>(null);
  const expected = useRef<{ lead: Lead; until: number } | null>(null);
  const current = useRef<string | null>(null);
  const changed = useRef(onChanged);
  changed.current = onChanged;

  const onNotification = useCallback(
    (notification: { type?: string; call?: RtcCall }) => {
      const c = notification.call;
      if (notification.type !== "callUpdate" || !c) return;
      if (ENDED.includes(c.state)) {
        if (current.current !== c.id) return;
        current.current = null;
        setCall(null);
        setStartedAt(null);
        setMuted(false);
        setKeypad(false);
        setActiveLead((lead) => {
          if (lead) setLogLead(lead);
          return null;
        });
        changed.current();
        return;
      }
      current.current = c.id;
      setCall(c);
      if (c.state === "ringing" && c.direction === "inbound") {
        const pending = expected.current;
        if (pending && pending.until > Date.now()) {
          // This is the leg we asked the server to place: pick it up and connect the carrier.
          expected.current = null;
          setActiveLead(pending.lead);
          c.answer().catch(() =>
            setError("Could not answer; check the microphone"),
          );
        }
      }
      if (c.state === "active") setStartedAt((t) => t ?? Date.now());
    },
    [],
  );

  const connect = useCallback(async () => {
    if (demo || !enabled) return;
    setStatus("connecting");
    setError("");
    try {
      const login = await api<{ login_token: string }>("/webrtc/token");
      const { TelnyxRTC } = await import("@telnyx/webrtc");
      await client.current?.disconnect().catch(() => undefined);
      const rtc = new TelnyxRTC({
        login_token: login.login_token,
      }) as unknown as RtcClient;
      rtc.remoteElement = "dialer-remote-audio";
      rtc.on("telnyx.ready", () => setStatus("ready"));
      rtc.on("telnyx.error", () => {
        setStatus("error");
        setError("Browser dialer disconnected");
      });
      rtc.on("telnyx.socket.close", () => setStatus("error"));
      rtc.on("telnyx.notification", onNotification as (p: never) => void);
      client.current = rtc;
      await rtc.connect();
    } catch (e) {
      setStatus("error");
      setError((e as Error).message || "Could not start the browser dialer");
    }
  }, [api, demo, enabled, onNotification]);

  useEffect(() => {
    connect();
    return () => {
      client.current?.disconnect().catch(() => undefined);
      client.current = null;
    };
  }, [connect]);

  useEffect(() => {
    if (!startedAt) return;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  const callLead = useCallback(
    async (lead: Lead) => {
      setError("");
      expected.current = { lead, until: Date.now() + AUTO_ANSWER_MS };
      try {
        await api(`/leads/${lead.id}/connect`, "POST", { via: "browser" });
      } catch (e) {
        expected.current = null;
        setError((e as Error).message);
        throw e;
      }
      if (demo) {
        // Demo mode simulates the whole call on the server; go straight to logging it.
        expected.current = null;
        setLogLead(lead);
        changed.current();
      }
    },
    [api, demo],
  );

  const value: DialerValue = {
    status,
    ready: status === "ready" || status === "demo",
    callLead,
  };
  const ringing =
    call && call.state === "ringing" && call.direction === "inbound";
  const caller =
    activeLead?.company ||
    activeLead?.name ||
    call?.options.remoteCallerName ||
    formatPhone(call?.options.remoteCallerNumber || "") ||
    "Unknown caller";

  return (
    <DialerContext.Provider value={enabled ? value : null}>
      {children}
      <audio id="dialer-remote-audio" autoPlay />
      {(call || (status === "error" && error)) && (
        <aside className="dialer" aria-label="Browser dialer">
          {call ? (
            <>
              <header>
                <strong>{caller}</strong>
                <small>
                  {ringing
                    ? "Incoming call"
                    : startedAt
                      ? elapsed(startedAt)
                      : "Connecting…"}
                </small>
              </header>
              {ringing ? (
                <footer>
                  <button
                    onClick={() =>
                      call
                        .answer()
                        .catch(() =>
                          setError("Could not answer; check the microphone"),
                        )
                    }
                  >
                    <PhoneIncoming size={16} /> Answer
                  </button>
                  <button
                    className="secondary"
                    onClick={() => call.hangup().catch(() => undefined)}
                  >
                    Decline
                  </button>
                </footer>
              ) : (
                <>
                  {keypad && (
                    <div className="dialer-keypad">
                      {KEYS.map((k) => (
                        <button
                          key={k}
                          className="secondary"
                          onClick={() => call.dtmf(k)}
                        >
                          {k}
                        </button>
                      ))}
                    </div>
                  )}
                  <footer>
                    <button
                      className="secondary"
                      aria-pressed={muted}
                      onClick={() => {
                        call.toggleAudioMute();
                        setMuted((m) => !m);
                      }}
                    >
                      {muted ? <MicOff size={16} /> : <Mic size={16} />}
                      {muted ? "Unmute" : "Mute"}
                    </button>
                    <button
                      className="secondary"
                      aria-pressed={keypad}
                      aria-label="Keypad"
                      onClick={() => setKeypad((k) => !k)}
                    >
                      <Grid3x3 size={16} />
                    </button>
                    <button
                      className="danger"
                      onClick={() => call.hangup().catch(() => undefined)}
                    >
                      <PhoneOff size={16} /> Hang up
                    </button>
                  </footer>
                </>
              )}
              {error && <Notice error>{error}</Notice>}
            </>
          ) : (
            <>
              <Notice error>{error}</Notice>
              <footer>
                <button className="secondary" onClick={() => connect()}>
                  Reconnect dialer
                </button>
              </footer>
            </>
          )}
        </aside>
      )}
      {logLead && (
        <Modal title="Log this call" onClose={() => setLogLead(null)}>
          <LogCallForm
            lead={logLead}
            onClose={() => setLogLead(null)}
            onSubmit={async (body) => {
              await api(`/leads/${logLead.id}/log-call`, "POST", body);
              changed.current();
            }}
          />
        </Modal>
      )}
    </DialerContext.Provider>
  );
}
