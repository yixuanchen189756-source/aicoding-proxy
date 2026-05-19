// @ts-check
// RL Training Headers - OpenCode plugin
// Injects X-Session-Id and X-Turn-Type HTTP headers into LLM API requests.

import fs from "node:fs";
import path from "node:path";

const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

const appendDebugLog = (debugFile, event, data) => {
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

/** @type {import('@opencode-ai/plugin').PluginModule} */
const pluginModule = {
  id: "rl-training-headers",
  server: async (_input, rawOptions) => {
    const options = rawOptions ?? {};
    const sessionIdHeader = options.sessionIdHeader ?? "X-Session-Id";
    const turnTypeHeader = options.turnTypeHeader ?? "X-Turn-Type";
    const workspace = options.workspace ?? process.cwd();
    const workspaceHeader = options.workspaceHeader ?? "X-Agent-Workspace";
    const debug = options.debug === true || process.env.RL_TRAINING_HEADERS_DEBUG === "1";
    const debugFile = options.debugFile ?? process.env.RL_TRAINING_HEADERS_LOG ?? "";

    console.log("[rl-training-headers] activated (chat.headers hook)");
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
