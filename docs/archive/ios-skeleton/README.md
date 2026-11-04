# BrainSense iOS companion (skeleton)

Not buildable on this machine (Xcode is not installed; only Command Line Tools). Open in Xcode 26.4+:

1. File → New → App "BrainSense" (SwiftUI, iOS 17.2+), bundle id `co.sweetspot.brainsense`.
2. Add Swift Package `https://github.com/facebook/meta-wearables-dat-ios` (1.0.1) → products `MWDATCore`, `MWDATCamera`, `MWDATSpeech`, `MWDATMockDevice` (debug only).
3. Drop the files in `BrainSense/` into the target. Set `BRAINSENSE_SERVER_URL` in `Config.swift` to the agent server (`uv run uvicorn brainsense.agent.server:app`), which forwards clips to the Modal TRIBE endpoint.
4. Info.plist: `NSCameraUsageDescription`, `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`, Bluetooth usage, and the DAT `APPLICATION_ID` / `CLIENT_TOKEN` from the Wearables Developer Center (beta channel).
5. Debug build → ladybug icon → **Enable MockDeviceKit** → pair a virtual Ray-Ban Meta → feed the camera stream from the phone camera. The code path is identical with real glasses.

Flow: glasses stream (MEDIUM 504×896, 15 fps) → 6 s ring buffer → on "이거 어때?" (on-device ASR final result) → encode MP4 → POST /tribe → POST /agent → `AVSpeechSynthesizer` over A2DP.
