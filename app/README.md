# NeuroMuse app

The client: a React Native + Expo app (web, iOS, Android) and a Hono server that runs the Muse Spark agent with the brain tools. The brain itself (TRIBE v2 service, calibrated heads, memory) is the Python server in the repository root.

```bash
pnpm install
OPENAI_API_KEY=<Meta Model API key> CPK_INTELLIGENCE_API_KEY=dummy-local RICH_THREADS=false BRAINSENSE_URL=http://127.0.0.1:8000 pnpm dev   # agent server :8787
pnpm --dir apps/mobile web                                                                                                          # http://localhost:8081
node scripts/lan-https.mjs                                                                                                          # phone: https://<laptop-ip>:8443, glasses mode with the live camera
```

Where things are:

- `apps/server/src/engine/conversation.ts`, `glasses-tool.ts`: the agent's brain tools (`brain_eval`, `look_at`, `brain_recall`, `brain_rules`) and the first-person brain voice.
- `apps/mobile/src/brain-live.web.tsx`, `brainsense.tsx`, `bars.tsx`: the live 3D cortex card, head bars, drivers, per-second region response.
- `apps/mobile/src/glasses-ui.tsx`, `glasses.web.tsx`, `glasses.tsx`, `apps/server/src/glasses-routes.ts`: glasses mode (landscape first-person frame, rolling 6 s clip, voice in, spoken captions out).
- `apps/mobile/src/lab.tsx`, `about.tsx`: the Lab (real stimuli, like/dislike, memory written live) and the About tab.
- `apps/mobile/assets/CREDITS.md`: sample photo credits.

The app runtime is built on CopilotKit's MIT-licensed OpenMuse agent app; see `LICENSE`.
