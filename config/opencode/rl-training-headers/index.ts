import type { PluginModule } from "@opencode-ai/plugin";

type RlTrainingHeadersOptions = {
  /** User identifier to prefix session IDs with */
  userName?: string;
  /** Header name for session ID (default: X-Session-Id) */
  sessionIdHeader?: string;
  /** Header name for turn type (default: X-Turn-Type) */
  turnTypeHeader?: string;
};

// Triggers classified as "side" (non-user-facing housekeeping runs).
const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

const pluginModule: PluginModule = {
  id: "rl-training-headers",
  server: async (_input, rawOptions) => {
    const options = (rawOptions ?? {}) as RlTrainingHeadersOptions;
    const userName = options.userName ?? "default-user";
    const sessionIdHeader = options.sessionIdHeader ?? "X-Session-Id";
    const turnTypeHeader = options.turnTypeHeader ?? "X-Turn-Type";

    console.log(
      `[rl-training-headers] activated (via chat.headers hook, user: ${userName})`,
    );

    return {
      "chat.headers": async (input, output) => {
        const sessionId = input.sessionID ?? "";
        const combinedSessionId = `${userName}_${sessionId}`;
        const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

        output.headers = {
          [sessionIdHeader]: combinedSessionId,
          [turnTypeHeader]: turnType,
        };
      },
    };
  },
};

export default pluginModule;
