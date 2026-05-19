import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

function rawFileLog(message) {
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

function log(api, level, message) {
  const line = `rl-training-headers: ${message}`;
  console.error(line);
  rawFileLog(message);
  api.logger[level]?.(line);
}

function candidateStateDirs() {
  const dirs = [
    process.env.OPENCLAW_STATE_DIR,
    process.env.USERPROFILE ? join(process.env.USERPROFILE, ".openclaw") : "",
    process.env.HOME ? join(process.env.HOME, ".openclaw") : "",
    join(homedir(), ".openclaw"),
  ];
  return [...new Set(dirs.filter(Boolean))];
}

function readOpenClawState(api) {
  for (const stateDir of candidateStateDirs()) {
    const path = join(stateDir, "openclaw.json");
    try {
      const raw = readFileSync(path, "utf8");
      return { path, data: JSON.parse(raw) };
    } catch (err) {
      log(api, "warn", `could not read OpenClaw state from ${path}: ${String(err)}`);
    }
  }
  return null;
}

function readGatewayTokenFromOpenClawState(api, state) {
  const token = state?.data?.gateway?.auth?.token;
  if (typeof token === "string" && token.trim()) {
    log(api, "info", `loaded gateway token from ${state?.path}`);
    return token.trim();
  }
  log(api, "warn", "no gateway.auth.token in OpenClaw state");
  return "";
}

function proxyRegisterUrlFromOpenClawModelBaseUrl(api, state) {
  const primary = state?.data?.agents?.defaults?.model?.primary;
  const providerName = typeof primary === "string" ? primary.split("/", 1)[0] : "";
  const baseUrl = providerName ? state?.data?.models?.providers?.[providerName]?.baseUrl : "";
  if (typeof baseUrl !== "string" || !baseUrl.trim()) {
    log(api, "warn", "could not resolve proxy baseUrl from OpenClaw default model provider");
    return "";
  }
  const proxyBase = baseUrl.trim().replace(/\/+$/, "").replace(/\/v1$/i, "");
  log(api, "info", `resolved proxy register URL from ${providerName}.baseUrl in ${state?.path}`);
  return `${proxyBase}/register-instance`;
}

function instanceIdFromGatewayUrl(gatewayUrl) {
  try {
    const url = new URL(gatewayUrl);
    const host = url.hostname.trim();
    const port = url.port.trim();
    if (host && port) {
      return `${host}_${port}`;
    }
    if (host) {
      return host;
    }
  } catch {
    // Fall through to conservative string cleanup.
  }
  return gatewayUrl.replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/[^A-Za-z0-9._-]+/g, "_");
}

function resolveConfig(api) {
  const cfg = api.pluginConfig ?? {};
  const state = readOpenClawState(api);
  if (cfg.proxyRegisterUrl || process.env.OPENCLAW_PROXY_REGISTER_URL) {
    log(api, "warn", "proxyRegisterUrl override is ignored; using OpenClaw default model provider baseUrl");
  }
  const gatewayPort = cfg.gatewayPort ?? process.env.OPENCLAW_GATEWAY_PORT ?? "18789";
  const gatewayUrl = cfg.gatewayUrl ?? process.env.OPENCLAW_GATEWAY_URL ?? "";
  return {
    sessionIdHeader: cfg.sessionIdHeader ?? "X-Session-Id",
    turnTypeHeader: cfg.turnTypeHeader ?? "X-Turn-Type",
    instanceIdHeader: cfg.instanceIdHeader ?? "X-Instance-Id",
    workspaceHeader: cfg.workspaceHeader ?? "X-Agent-Workspace",
    instanceId:
      gatewayUrl ? instanceIdFromGatewayUrl(gatewayUrl) : "openclaw-default",
    proxyRegisterUrl:
      proxyRegisterUrlFromOpenClawModelBaseUrl(api, state),
    gatewayUrl,
    gatewayToken:
      cfg.gatewayToken ??
      process.env.OPENCLAW_GATEWAY_TOKEN ??
      readGatewayTokenFromOpenClawState(api, state),
    gatewayPort,
    registerOnStart: cfg.registerOnStart ?? true,
  };
}

const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

export default function register(api) {
  const config = resolveConfig(api);
  log(
    api,
    "info",
    `resolved config instanceId=${config.instanceId}, proxyRegisterUrl=${config.proxyRegisterUrl}, gatewayUrl=${config.gatewayUrl}, gatewayPort=${config.gatewayPort}, hasGatewayToken=${Boolean(config.gatewayToken)}`,
  );

  let hasRegistered = false;

  async function registerGatewayInstance(reason, workspace = process.cwd()) {
    if (!config.registerOnStart) {
      log(api, "info", `registration disabled (${reason})`);
      return;
    }
    if (!config.gatewayToken) {
      log(api, "warn", "missing gatewayToken; cannot register gateway instance");
      return;
    }
    if (!config.proxyRegisterUrl || !config.gatewayUrl) {
      log(api, "warn", "missing proxyRegisterUrl or gatewayUrl; cannot register gateway instance");
      return;
    }
    log(api, "info", `registering gateway instance (${reason}) at ${config.proxyRegisterUrl}`);
    const payload = {
      instance_id: config.instanceId,
      gateway_url: config.gatewayUrl,
      gateway_token: config.gatewayToken,
      gateway_port: config.gatewayPort,
      workspace,
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

  let pendingHeaders = null;

  const originalFetch = globalThis.fetch;

  globalThis.fetch = function rlPatchedFetch(input, init) {
    if (pendingHeaders && init?.method?.toUpperCase() === "POST") {
      const extra = pendingHeaders;
      const merged = new Headers(init.headers);
      for (const [k, v] of Object.entries(extra)) {
        if (!merged.has(k)) {
          merged.set(k, v);
        }
      }
      return originalFetch.call(globalThis, input, { ...init, headers: merged });
    }
    return originalFetch.call(globalThis, input, init);
  };

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
    const workspace = String(ctx.workspace ?? ctx.workspaceDir ?? process.cwd() ?? "").trim();
    registerGatewayInstance(hasRegistered ? "before_prompt_build_refresh" : "before_prompt_build", workspace).catch((err) => {
      log(api, "warn", `registration retry failed: ${String(err)}`);
    });

    const sessionId = ctx.sessionId ?? "";

    const turnType = SIDE_TRIGGERS.has(ctx.trigger ?? "") ? "side" : "main";
    pendingHeaders = {
      [config.sessionIdHeader]: sessionId,
      [config.turnTypeHeader]: turnType,
      [config.instanceIdHeader]: config.instanceId,
      [config.workspaceHeader]: workspace,
    };
    return {};
  });

  api.on("agent_end", () => {
    log(api, "info", "agent_end clearing pending headers");
    pendingHeaders = null;
  });

  log(api, "info", "activated (fetch patched, with gateway registration)");
}
