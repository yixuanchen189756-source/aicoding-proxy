import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

type RlTrainingConfig = {
  sessionIdHeader: string;
  turnTypeHeader: string;
  instanceIdHeader: string;
  instanceId: string;
  proxyRegisterUrl: string;
  gatewayUrl: string;
  gatewayToken: string;
  gatewayPort: string;
  registerOnStart: boolean;
};

function rawFileLog(message: string): void {
  const stateDir =
    process.env.OPENCLAW_STATE_DIR ||
    (process.env.USERPROFILE ? join(process.env.USERPROFILE, ".openclaw") : "") ||
    (process.env.HOME ? join(process.env.HOME, ".openclaw") : "") ||
    join(homedir(), ".openclaw");
  try {
    const logDir = join(stateDir, "logs");
    mkdirSync(logDir, { recursive: true });
    appendFileSync(
      join(logDir, "rl-training-headers.log"),
      `${new Date().toISOString()} ${message}\n`,
      "utf8",
    );
  } catch {
    // Best-effort diagnostic only.
  }
}

rawFileLog("module loaded");

function log(api: OpenClawPluginApi, level: "info" | "warn", message: string): void {
  const line = `rl-training-headers: ${message}`;
  console.error(line);
  rawFileLog(message);
  api.logger[level]?.(line);
}

function candidateStateDirs(): string[] {
  const dirs = [
    process.env.OPENCLAW_STATE_DIR,
    process.env.USERPROFILE ? join(process.env.USERPROFILE, ".openclaw") : "",
    process.env.HOME ? join(process.env.HOME, ".openclaw") : "",
    join(homedir(), ".openclaw"),
  ];
  return [...new Set(dirs.filter((dir): dir is string => Boolean(dir)))];
}

function readGatewayTokenFromOpenClawState(api: OpenClawPluginApi): string {
  for (const stateDir of candidateStateDirs()) {
    const path = join(stateDir, "openclaw.json");
    try {
      const raw = readFileSync(path, "utf8");
      const parsed = JSON.parse(raw);
      const token = parsed?.gateway?.auth?.token;
      if (typeof token === "string" && token.trim()) {
        log(api, "info", `loaded gateway token from ${path}`);
        return token.trim();
      }
      log(api, "warn", `no gateway.auth.token in ${path}`);
    } catch (err) {
      log(api, "warn", `could not read gateway token from ${path}: ${String(err)}`);
    }
  }
  return "";
}

function resolveConfig(api: OpenClawPluginApi): RlTrainingConfig {
  const cfg = (api.pluginConfig ?? {}) as Partial<RlTrainingConfig>;
  const gatewayPort = cfg.gatewayPort ?? process.env.OPENCLAW_GATEWAY_PORT ?? "18789";
  return {
    sessionIdHeader: cfg.sessionIdHeader ?? "X-Session-Id",
    turnTypeHeader: cfg.turnTypeHeader ?? "X-Turn-Type",
    instanceIdHeader: cfg.instanceIdHeader ?? "X-Instance-Id",
    instanceId:
      cfg.instanceId ??
      process.env.OPENCLAW_INSTANCE_ID ??
      process.env.COMPUTERNAME ??
      "openclaw-default",
    proxyRegisterUrl:
      cfg.proxyRegisterUrl ??
      process.env.OPENCLAW_PROXY_REGISTER_URL ??
      "http://127.0.0.1:8288/register-instance",
    gatewayUrl:
      cfg.gatewayUrl ??
      process.env.OPENCLAW_GATEWAY_URL ??
      `http://127.0.0.1:${gatewayPort}/v1/chat/completions`,
    gatewayToken:
      cfg.gatewayToken ??
      process.env.OPENCLAW_GATEWAY_TOKEN ??
      readGatewayTokenFromOpenClawState(api),
    gatewayPort,
    registerOnStart: cfg.registerOnStart ?? true,
  };
}

// Triggers classified as "side" (non-user-facing housekeeping runs).
const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

export default function register(api: OpenClawPluginApi) {
  const config = resolveConfig(api);
  log(
    api,
    "info",
    `resolved config instanceId=${config.instanceId}, proxyRegisterUrl=${config.proxyRegisterUrl}, gatewayUrl=${config.gatewayUrl}, gatewayPort=${config.gatewayPort}, hasGatewayToken=${Boolean(config.gatewayToken)}`,
  );

  // Fixed user namespace used to make session ids unique across users/machines.
  const FIXED_USER_NAME = "your-fixed-user-name";

  let hasRegistered = false;

  async function registerGatewayInstance(reason: string): Promise<void> {
    if (!config.registerOnStart) {
      log(api, "info", `registration disabled (${reason})`);
      return;
    }
    if (!config.gatewayToken) {
      log(api, "warn", "missing gatewayToken; cannot register gateway instance");
      return;
    }
    log(api, "info", `registering gateway instance (${reason}) at ${config.proxyRegisterUrl}`);
    const payload = {
      instance_id: config.instanceId,
      gateway_url: config.gatewayUrl,
      gateway_token: config.gatewayToken,
      gateway_port: config.gatewayPort,
      source: "rl-training-headers",
      reason,
      updated_at: new Date().toISOString(),
    };
    const resp = await fetch(config.proxyRegisterUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await resp.text().catch(() => "");
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}: ${text.slice(0, 300)}`);
    }
    hasRegistered = true;
    log(api, "info", `registered gateway instance ${config.instanceId} -> ${config.gatewayUrl}`);
  }

  // Pending headers to inject into the next LLM fetch request.
  // Set during before_prompt_build, consumed by the patched fetch, cleared on agent_end.
  let pendingHeaders: Record<string, string> | null = null;

  const originalFetch = globalThis.fetch;

  globalThis.fetch = function rlPatchedFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> {
    if (pendingHeaders && init?.method?.toUpperCase() === "POST") {
      const extra = pendingHeaders;
      const merged = new Headers(init.headers);
      for (const [k, v] of Object.entries(extra)) {
        // Plugin headers go first; per-request headers can still override.
        if (!merged.has(k)) {
          merged.set(k, v);
        }
      }
      return originalFetch.call(globalThis, input, { ...init, headers: merged });
    }
    return originalFetch.call(globalThis, input, init);
  } as typeof globalThis.fetch;

  api.registerService?.({
    id: "rl-training-headers",
    start: async () => {
      try {
        log(api, "info", "service start hook fired");
        await registerGatewayInstance("service_start");
      } catch (err) {
        log(api, "warn", `registration failed on start: ${String(err)}`);
      }
    },
    stop: () => {
      log(api, "info", "service stopped");
    },
  });

  api.on("before_prompt_build", (_event, ctx) => {
    log(api, "info", `before_prompt_build sessionId=${ctx.sessionId ?? ""}, trigger=${ctx.trigger ?? ""}, hasRegistered=${hasRegistered}`);
    if (!hasRegistered) {
      registerGatewayInstance("before_prompt_build").catch((err) => {
        log(api, "warn", `registration retry failed: ${String(err)}`);
      });
    }

    const sessionId = ctx.sessionId ?? "";
    const combinedSessionId = `${FIXED_USER_NAME}_${sessionId}`;

    const turnType = SIDE_TRIGGERS.has(ctx.trigger ?? "") ? "side" : "main";
    pendingHeaders = {
      [config.sessionIdHeader]: combinedSessionId,
      [config.turnTypeHeader]: turnType,
      [config.instanceIdHeader]: config.instanceId,
    };
    return {};
  });

  api.on("agent_end", () => {
    log(api, "info", "agent_end clearing pending headers");
    pendingHeaders = null;
  });

  log(api, "info", "activated (fetch patched, with gateway registration)");
}
