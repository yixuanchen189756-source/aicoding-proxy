---
active: true
iteration: 2
completion_promise: "VERIFIED"
initial_completion_promise: "DONE"
verification_attempt_id: "8eba4ffd-459b-465c-973d-b95698621980"
verification_session_id: "ses_2d1ea0bd4ffe2ISexMXbs5rJLb"
started_at: "2026-03-27T06:51:48.510Z"
session_id: "ses_2d1efc6d9ffeQ0HyHrFlVP7JqF"
ultrawork: true
verification_pending: true
strategy: "continue"
message_count_at_start: 1
---
你先去参考 @index.ts ，他是一个openclaw的插件，可以监听openclaw要调用模型的事件，然后给请求添加一些"headers"，主要是"session id" 和 "user name"。你研究一下，找办法给"opencode"（另外一个coding助手，也是你自己）配这样的插件，同样能够监听opencode发给模型的请求这个事件，然后加一个这种插件。这个需要先搞一个完整的方案，然后一步一步推进。
