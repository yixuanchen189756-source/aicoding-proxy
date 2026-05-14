// @ts-check
// RL Training Headers — OpenCode plugin
// Injects X-Session-Id and X-Turn-Type HTTP headers into LLM API requests

const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

/** @type {import('@opencode-ai/plugin').PluginModule} */
const pluginModule = {
  id: "rl-training-headers",
  server: async (_input, rawOptions) => {
    const options = rawOptions ?? {};
    const userName = options.userName ?? "default-user";
    const sessionIdHeader = options.sessionIdHeader ?? "X-Session-Id";
    const turnTypeHeader = options.turnTypeHeader ?? "X-Turn-Type";

    console.log(
      `[rl-training-headers] activated (chat.headers hook, user: ${userName})`,
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
