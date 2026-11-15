// src/App.jsx
import TextToSpeech from "./components/TextToSpeech";
import SpeechToText from "./components/SpeechToText";
import AIStateProvider from "./context/AIStateProvider";

import CoreScene from "./scenes/CoreScene";
import HUD from "./components/hud/HUD";

import "./index.css";
import BackendBridge from "./components/hud/BackendBridge";

export default function App() {
  return (
    <AIStateProvider>
      <CoreScene />
      <BackendBridge />
      <HUD />
      <SpeechToText />
      <TextToSpeech />
    </AIStateProvider>
  );
}
