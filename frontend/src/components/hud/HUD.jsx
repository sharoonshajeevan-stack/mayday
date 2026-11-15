// src/components/hud/HUD.jsx

import AIStatusIndicator from "./AIStatusIndicator";
import HUDStatus from "./HUDStatus";
import CommandPrompt from "./CommandPrompt";
import CommandStatus from "./CommandStatus";
import VoiceActivity from "./VoiceActivity";
import WakeWordIndicator from "./WakeWordIndicator";
import VoiceControl from "./VoiceControl";
import CommandHistory from "./CommandHistory";
import SystemClock from "./SystemClock";
import Calendar from "./Calendar";
import ConnectionStatus from "./ConnectionStatus";
import ThinkingIndicator from "./ThinkingIndicator";
import ConversationFlow from "./ConversationFlow";
import StateTransition from "./StateTransition";
import ResponseStateController from "./ResponseStateController";
import PersonalitySettings from "./PersonalitySettings";
import RealtimeVoice from "./RealtimeVoice";

import "./HUD.css";

export default function HUD() {
  return (
    <div className="mayday-hud">
      {/* Core AI status */}

      <AIStatusIndicator />

      <HUDStatus />

      <ThinkingIndicator />

      <WakeWordIndicator />

      {/* Conversation */}

      <ConversationFlow />

      <CommandStatus />

      <CommandPrompt />

      {/* Voice */}

      <VoiceActivity />

      <VoiceControl />

      {/* Real-time voice (Pipecat) */}

      <RealtimeVoice />

      {/* History */}

      <CommandHistory />

      {/* System */}

      <SystemClock />

      <Calendar />

      <ConnectionStatus />

      <PersonalitySettings />

      {/* State controllers */}

      <StateTransition />

      <ResponseStateController />

      {/* Cinematic HUD frame */}

      <div
        className="hud-corner hud-top-left"
        aria-hidden="true"
      >
        <div className="hud-line" />

        <span>MAYDAY</span>

        <small>AI SYSTEM</small>
      </div>

      <div
        className="hud-corner hud-top-right"
        aria-hidden="true"
      >
        <span>ONLINE</span>

        <div className="hud-line" />
      </div>

      <div
        className="hud-corner hud-bottom-left"
        aria-hidden="true"
      >
        <small>CORE</small>

        <span>ACTIVE</span>
      </div>

      <div
        className="hud-corner hud-bottom-right"
        aria-hidden="true"
      >
        <small>SECURE CHANNEL</small>
      </div>
    </div>
  );
}