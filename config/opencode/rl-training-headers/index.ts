import fs from "node:fs";
import path from "node:path";
import type { PluginModule } from "@opencode-ai/plugin";

type RlTrainingHeadersOptions = {
  /** Header name for session ID (default: X-Session-Id) */
  sessionIdHeader?: string;
  /** Header name for turn type (default: X-Turn-Type) */
  turnTypeHeader?: string;
  /** Workspace path to send with each request (default: process.cwd()) */
  workspace?: string;
  /** Header name for workspace path (default: X-Agent-Workspace) */
  workspaceHeader?: string;
  /** Write hook diagnostics to this file when debug is enabled */
  debugFile?: string;
  /** Enable hook diagnostics */
  debug?: boolean;
};

// Triggers classified as "side" (non-user-facing housekeeping runs).
const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

const appendDebugLog = (debugFile: string, event: string, data: unknown) => {
  if (!debugFile) return;
  try {
    const resolved = path.resolve(debugFile);
    fs.mkdirSync(path.dirname(resolved), { recursive: true });
    fs.appendFileSync(
      resolved,
      `[${new Date().toISOString()}] ${event}\n${JSON.stringify(data, null, 2)}\n`,
      "utf8",
    );
  } catch {
    // Debug logging must never break request header injection.
  }
};

const pluginModule: PluginModule = {
  id: "rl-training-headers",
  server: async (_input, rawOptions) => {
    const options = (rawOptions ?? {}) as RlTrainingHeadersOptions;
    const sessionIdHeader = options.sessionIdHeader ?? "X-Session-Id";
    const turnTypeHeader = options.turnTypeHeader ?? "X-Turn-Type";
    const workspace = options.workspace ?? process.cwd();
    const workspaceHeader = options.workspaceHeader ?? "X-Agent-Workspace";
    const debug = options.debug === true || process.env.RL_TRAINING_HEADERS_DEBUG === "1";
    const debugFile = options.debugFile ?? process.env.RL_TRAINING_HEADERS_LOG ?? "";

    console.log("[rl-training-headers] activated (via chat.headers hook)");
    if (debug) {
      appendDebugLog(debugFile, "activated", {
        sessionIdHeader,
        turnTypeHeader,
        workspaceHeader,
        workspace,
        debugFile,
      });
    }

    return {
      "chat.headers": async (input, output) => {
        const sessionId = input.sessionID ?? "";
        const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

        output.headers = {
          [sessionIdHeader]: sessionId,
          "X-Agent-Session-Id": sessionId,
          [turnTypeHeader]: turnType,
          [workspaceHeader]: workspace,
        };
        if (debug) {
          appendDebugLog(debugFile, "chat.headers", {
            inputKeys: Object.keys(input ?? {}),
            sessionID: input.sessionID ?? null,
            agent: input.agent ?? null,
            model: input.model ?? null,
            provider: input.provider ?? null,
            messageKeys: input.message ? Object.keys(input.message) : null,
            headers: output.headers,
          });
        }
      },
    };
  },
};

export default pluginModule;
