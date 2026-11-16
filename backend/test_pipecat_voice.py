"""Standalone verification for MAYDAY's real-time (Pipecat) voice layer.

Run from the backend folder with the project virtualenv:

    python test_pipecat_voice.py

By default it uses lightweight *fake* engines so the whole run is fast and
never opens a microphone or downloads a model. To additionally exercise the
real Faster-Whisper and Kokoro engines, run:

    set MAYDAY_TEST_REAL_MODELS=1
    python test_pipecat_voice.py

Nothing here launches the app, opens the microphone or plays audio.
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL

    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  ->  {detail}")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fake engines (fast, deterministic, no model download)
# ---------------------------------------------------------------------------
class FakeTTSEngine:
    voice = "bf_emma"

    def __init__(self, chunks=3, delay=0.0):
        self.chunks = chunks
        self.delay = delay
        self.produced = 0
        self.stop_event = None

    def iter_audio_chunks(self, text, stop_event=None):
        self.stop_event = stop_event
        for _ in range(self.chunks):
            if stop_event is not None and stop_event.is_set():
                return
            self.produced += 1
            if self.delay:
                time.sleep(self.delay)
            yield np.full(2400, 0.1, dtype=np.float32)


class FakeSTTEngine:
    def __init__(self, text="open notepad"):
        self.text = text
        self.calls = 0

    def transcribe_array(self, audio):
        self.calls += 1
        return self.text


# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------
def test_config():
    print("\n[1] Configuration")

    from pipecat_voice.config import VoiceServiceConfig

    config = VoiceServiceConfig.from_env()
    check("defaults load", config.transport == "local" and config.port == 7860)
    check("base_url built", config.base_url.endswith(":7860"))

    os.environ["MAYDAY_VOICE_PORT"] = "9999"
    os.environ["MAYDAY_VAD_CONFIDENCE"] = "0.42"
    os.environ["MAYDAY_VOICE_AUTOSTART"] = "true"
    try:
        config = VoiceServiceConfig.from_env()
        check("env override port", config.port == 9999)
        check("env override float", abs(config.vad_confidence - 0.42) < 1e-9)
        check("env override bool", config.autostart is True)
    finally:
        os.environ.pop("MAYDAY_VOICE_PORT", None)
        os.environ.pop("MAYDAY_VAD_CONFIDENCE", None)
        os.environ.pop("MAYDAY_VOICE_AUTOSTART", None)


# ---------------------------------------------------------------------------
# 2. Event hub
# ---------------------------------------------------------------------------
def test_event_hub():
    print("\n[2] Event hub")

    from pipecat_voice.events import EventHub, STATE_LISTENING

    hub = EventHub()

    class FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, message):
            self.messages.append(message)

    async def scenario():
        hub.bind_loop(asyncio.get_running_loop())
        socket = FakeSocket()
        hub.subscribe(socket)

        hub.emit("state", state=STATE_LISTENING)
        hub.emit("transcript", text="hello", final=True)

        await asyncio.sleep(0.1)
        return socket.messages

    messages = run(scenario())
    check("two events delivered", len(messages) == 2, f"got {len(messages)}")
    check("state event carries state", messages[0].get("state") == STATE_LISTENING)
    check("hub remembers state", hub.state == STATE_LISTENING)
    check("transcript event carries text", messages[1].get("text") == "hello")
    check("events timestamped", all("timestamp" in m for m in messages))


# ---------------------------------------------------------------------------
# 3. STT adapter
# ---------------------------------------------------------------------------
def test_stt_adapter():
    print("\n[3] STT adapter")

    from pipecat.frames.frames import TranscriptionFrame
    from pipecat_voice.stt_adapter import (
        MAYDAY_STT_SAMPLE_RATE,
        MaydayWhisperSTTService,
    )

    engine = FakeSTTEngine("open notepad")
    service = MaydayWhisperSTTService(engine=engine)

    check("wants raw segments", service.wants_wav_segments is False)
    check("segment rate is 16k", service.segment_sample_rate == MAYDAY_STT_SAMPLE_RATE)

    async def collect(target, pcm):
        frames = []
        async for frame in target.run_stt(pcm):
            frames.append(frame)
        return frames

    audio = (np.zeros(16000, dtype=np.int16)).tobytes()
    frames = run(collect(service, audio))
    check("one transcription frame", len(frames) == 1, f"got {len(frames)}")
    check(
        "transcription frame type",
        frames and isinstance(frames[0], TranscriptionFrame),
    )
    check("transcription text", frames and frames[0].text == "open notepad")

    # Empty audio must not produce a frame and must not call the engine.
    engine2 = FakeSTTEngine("should not run")
    service2 = MaydayWhisperSTTService(engine=engine2)
    frames = run(collect(service2, b""))
    check("empty audio -> no frame", frames == [])
    check("empty audio -> no engine call", engine2.calls == 0)

    # Silence that transcribes to nothing must not emit a frame.
    engine3 = FakeSTTEngine("   ")
    service3 = MaydayWhisperSTTService(engine=engine3)
    frames = run(collect(service3, audio))
    check("blank transcript -> no frame", frames == [])


# ---------------------------------------------------------------------------
# 4. TTS adapter
# ---------------------------------------------------------------------------
def test_tts_adapter():
    print("\n[4] TTS adapter")

    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat_voice.tts_adapter import (
        MAYDAY_TTS_SAMPLE_RATE,
        MaydayKokoroTTSService,
    )

    engine = FakeTTSEngine(chunks=3)
    service = MaydayKokoroTTSService(engine=engine)

    async def collect(text):
        frames = []
        async for frame in service.run_tts(text, "ctx"):
            frames.append(frame)
        return frames

    frames = run(collect("hello there"))
    check("three audio frames", len(frames) == 3, f"got {len(frames)}")
    check(
        "frames are TTSAudioRawFrame",
        all(isinstance(f, TTSAudioRawFrame) for f in frames),
    )
    check("sample rate is 24k", frames[0].sample_rate == MAYDAY_TTS_SAMPLE_RATE)
    check("mono", frames[0].num_channels == 1)
    check("pcm byte length", len(frames[0].audio) == 2400 * 2)

    # A cancellation must set the stop event so synthesis stops for good.
    slow = FakeTTSEngine(chunks=1000, delay=0.02)
    slow_service = MaydayKokoroTTSService(engine=slow)

    async def cancel_early():
        generator = slow_service.run_tts("a very long sentence", "ctx")
        await generator.__anext__()
        await generator.aclose()
        await asyncio.sleep(0.1)
        after_close = slow.produced
        await asyncio.sleep(0.4)
        return after_close, slow.produced

    after_close, final = run(cancel_early())
    check("cancellation sets the stop flag", slow.stop_event is not None and slow.stop_event.is_set())
    check(
        "cancellation halts synthesis",
        after_close > 0 and final == after_close,
        f"after_close={after_close} final={final}",
    )


# ---------------------------------------------------------------------------
# 5. LLM adapter
# ---------------------------------------------------------------------------
def test_llm_adapter():
    print("\n[5] LLM adapter")

    from pipecat.frames.frames import (
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
    )
    from pipecat.processors.aggregators.llm_context import LLMContext

    import pipecat_voice.llm_adapter as llm_adapter

    events = []

    def hook(event_type, **payload):
        events.append((event_type, payload))

    service = llm_adapter.MaydayLLMService(event_hook=hook)

    original = llm_adapter.handle_utterance

    def fake_handle(text):
        return {
            "status": "success",
            "command": text,
            "response": "Opening notepad now.",
            "spoken": "Opening notepad.",
            "source": "system",
            "kind": "open_app",
        }

    llm_adapter.handle_utterance = fake_handle

    try:
        context = LLMContext()
        context.add_message({"role": "user", "content": "open notepad"})

        pushed = []

        async def fake_push_frame(frame, direction=None):
            pushed.append(frame)

        async def fake_push_error(*args, **kwargs):
            return None

        service.push_frame = fake_push_frame
        service.push_error = fake_push_error

        run(service._respond(context))

        check(
            "response start/end pushed",
            isinstance(pushed[0], LLMFullResponseStartFrame)
            and isinstance(pushed[-1], LLMFullResponseEndFrame),
        )
        text_frames = [f for f in pushed if isinstance(f, LLMTextFrame)]
        check("spoken text pushed", len(text_frames) == 1)
        check(
            "spoken text is the short version",
            text_frames and text_frames[0].text == "Opening notepad.",
        )

        kinds = [k for k, _ in events]
        check("executing event emitted", "executing" in kinds)
        check("response event emitted", "response" in kinds)
        response = {k: v for k, v in events}.get("response", {})
        check("response event carries full text", response.get("text") == "Opening notepad now.")
        check("response event carries source", response.get("source") == "system")

        # Failure path must not raise and must close the turn.
        def failing_handle(text):
            raise RuntimeError("boom")

        llm_adapter.handle_utterance = failing_handle
        pushed.clear()
        events.clear()
        run(service._respond(context))
        check(
            "failure still closes the turn",
            pushed and isinstance(pushed[-1], LLMFullResponseEndFrame),
        )
        check("failure emits error event", "error" in [k for k, _ in events])
    finally:
        llm_adapter.handle_utterance = original

    # _latest_user_text picks the most recent user message.
    context = LLMContext()
    context.add_message({"role": "user", "content": "first"})
    context.add_message({"role": "assistant", "content": "reply"})
    context.add_message({"role": "user", "content": "second"})
    check(
        "latest user text",
        llm_adapter.MaydayLLMService._latest_user_text(context) == "second",
    )


# ---------------------------------------------------------------------------
# 5b. Conversation brain
# ---------------------------------------------------------------------------
def test_brain():
    print("\n[5b] Conversation brain")

    import mayday_brain

    original_route = mayday_brain.route_command
    original_ai = mayday_brain.process_ai_command
    original_remember = mayday_brain.remember_conversation
    remembered = []

    mayday_brain.remember_conversation = lambda u, a, t=None: remembered.append((u, a))

    try:
        # 1. A deterministic system action wins over the AI engine.
        mayday_brain.route_command = lambda text: {
            "status": "success",
            "url": "https://youtube.com",
        }
        result = mayday_brain.handle_utterance("open youtube")
        check("routed action -> system source", result["source"] == "system")
        check("routed action has a reply", bool(result["response"]))
        check("routed action has short speech", bool(result["spoken"]))
        check("routed action remembered", len(remembered) == 1)

        # 2. No action -> the existing AI engine answers.
        mayday_brain.route_command = lambda text: None
        mayday_brain.process_ai_command = lambda text: {
            "status": "success",
            "response": "A detailed answer for the screen.",
            "spoken": "A short answer.",
            "source": "online",
            "mode": "online",
        }
        result = mayday_brain.handle_utterance("what is the capital of France")
        check("ai fallback -> online source", result["source"] == "online")
        check("ai fallback keeps full text", "detailed" in result["response"])
        check("ai fallback uses short speech", result["spoken"] == "A short answer.")

        # 3. AI failure -> error status, never an exception.
        mayday_brain.process_ai_command = lambda text: {
            "status": "error",
            "error": "no key",
        }
        result = mayday_brain.handle_utterance("hello")
        check("ai failure -> error status", result["status"] == "error")
        check("ai failure still remembered", len(remembered) == 3)

        # 3b. A provider error that carries a user-facing line (e.g. a Gemini
        #     429) is surfaced verbatim instead of a generic apology.
        mayday_brain.process_ai_command = lambda text: {
            "status": "error",
            "error": "Gemini rate limit reached (HTTP 429)",
            "response": "I'm being rate-limited right now.",
        }
        result = mayday_brain.handle_utterance("open google and search for claude")
        check("rate limit -> error status", result["status"] == "error")
        check(
            "rate limit -> friendly screen text",
            result["response"] == "I'm being rate-limited right now.",
            result["response"],
        )
        check(
            "rate limit -> friendly speech",
            result["spoken"] == "I'm being rate-limited right now.",
            result["spoken"],
        )

        # 4. Empty input is rejected.
        result = mayday_brain.handle_utterance("   ")
        check("empty utterance -> error", result["status"] == "error")
    finally:
        mayday_brain.route_command = original_route
        mayday_brain.process_ai_command = original_ai
        mayday_brain.remember_conversation = original_remember


# ---------------------------------------------------------------------------
# 6. State observer
# ---------------------------------------------------------------------------
def test_observer():
    print("\n[6] Voice state observer")

    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        ErrorFrame,
        InterruptionFrame,
        TranscriptionFrame,
        VADUserStartedSpeakingFrame,
    )
    from pipecat.observers.base_observer import FramePushed
    from pipecat_voice.observer import VoiceStateObserver

    events = []

    def hook(event_type, **payload):
        events.append((event_type, payload))

    observer = VoiceStateObserver(event_hook=hook)

    def push(frame):
        data = FramePushed(
            source=None,
            destination=None,
            frame=frame,
            direction=None,
            timestamp=0,
            first_push=True,
        )
        run(observer.on_push_frame(data))

    push(VADUserStartedSpeakingFrame())
    push(TranscriptionFrame("hello", "u", "t"))
    push(BotStartedSpeakingFrame())
    push(BotStoppedSpeakingFrame())
    push(InterruptionFrame())
    push(ErrorFrame(error="nope"))

    states = [p["state"] for k, p in events if k == "state"]
    check("state sequence", states == [
        "LISTENING",
        "THINKING",
        "SPEAKING",
        "LISTENING",
        "ERROR",
    ], f"got {states}")
    check("transcript event emitted", "transcript" in [k for k, _ in events])
    check("interrupted event emitted", "interrupted" in [k for k, _ in events])
    check("error event emitted", "error" in [k for k, _ in events])


# ---------------------------------------------------------------------------
# 6b. Playback mute processor
# ---------------------------------------------------------------------------
def test_mute_processor():
    print("\n[6b] Playback mute processor")

    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat.tests.utils import run_test
    from pipecat_voice.mute import MuteProcessor

    def audio_frame():
        return TTSAudioRawFrame(
            audio=b"\x10" * 480,
            sample_rate=24000,
            num_channels=1,
            context_id="ctx",
        )

    def through(muted):
        processor = MuteProcessor(muted=muted)
        down, _ = run(run_test(processor, frames_to_send=[audio_frame()]))
        return [f for f in down if isinstance(f, TTSAudioRawFrame)]

    toggle = MuteProcessor()
    check("starts unmuted", toggle.muted is False)
    check("set_muted returns new value", toggle.set_muted(True) is True)
    check("muted property follows", toggle.muted is True)
    check("set_muted back", toggle.set_muted(False) is False)

    audio = through(False)
    check("unmuted audio passes through", bool(audio) and audio[0].audio == b"\x10" * 480)

    audio = through(True)
    check("muted audio is silent", bool(audio) and audio[0].audio == b"\x00" * 480)
    check(
        "muted audio keeps its length",
        bool(audio) and len(audio[0].audio) == 480,
        str(len(audio[0].audio) if audio else -1),
    )
    check("muted frame keeps sample rate", bool(audio) and audio[0].sample_rate == 24000)


# ---------------------------------------------------------------------------
# 7. Pipeline assembly
# ---------------------------------------------------------------------------
def test_pipeline_assembly():
    print("\n[7] Pipeline assembly")

    from pipecat_voice.agent import MaydayVoiceAgent
    from pipecat_voice.config import VoiceServiceConfig
    from pipecat_voice.events import EventHub

    hub = EventHub()
    agent = MaydayVoiceAgent(
        VoiceServiceConfig(),
        hub,
        stt_engine=FakeSTTEngine(),
        tts_engine=FakeTTSEngine(),
    )

    status = agent.status()
    check("starts not running", status["running"] is False)
    check("status reports transport", status["transport"] == "local")

    # An unsupported transport must be rejected cleanly.
    config = VoiceServiceConfig()
    config.transport = "carrier-pigeon"
    bad_agent = MaydayVoiceAgent(
        config, hub, stt_engine=FakeSTTEngine(), tts_engine=FakeTTSEngine()
    )
    try:
        bad_agent._make_transport()
        check("bad transport rejected", False, "no error raised")
    except ValueError:
        check("bad transport rejected", True)

    # The worker can be built with a stub transport (no audio devices).
    class StubTransport:
        def input(self):
            from pipecat.processors.frame_processor import FrameProcessor

            return FrameProcessor()

        def output(self):
            from pipecat.processors.frame_processor import FrameProcessor

            return FrameProcessor()

    worker = agent.build_worker(StubTransport())
    check("worker built", worker is not None)
    check("user aggregator captured", agent._user_aggregator is not None)
    check("context created", agent._context is not None)


# ---------------------------------------------------------------------------
# 8. Full pipeline: user turn -> LLM -> TTS
# ---------------------------------------------------------------------------
def test_pipeline_end_to_end():
    print("\n[8] End-to-end pipeline (turn -> reply -> audio)")

    from pipecat.frames.frames import (
        EndFrame,
        Frame,
        TranscriptionFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import WorkerRunner
    from pipecat.pipeline.worker import PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    import pipecat_voice.llm_adapter as llm_adapter
    from pipecat_voice.llm_adapter import MaydayLLMService
    from pipecat_voice.tts_adapter import MaydayKokoroTTSService

    events = []

    def hook(event_type, **payload):
        events.append((event_type, payload))

    original = llm_adapter.handle_utterance

    def fake_handle(text):
        return {
            "status": "success",
            "command": text,
            "response": "Opening notepad now.",
            "spoken": "Opening notepad.",
            "source": "system",
        }

    llm_adapter.handle_utterance = fake_handle

    class Sink(FrameProcessor):
        def __init__(self):
            super().__init__()
            self.frames = []

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            self.frames.append(frame)
            await self.push_frame(frame, direction)

    async def scenario():
        context = LLMContext()
        aggregators = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(),
                user_turn_stop_timeout=1.0,
            ),
        )
        llm = MaydayLLMService(event_hook=hook)
        tts = MaydayKokoroTTSService(engine=FakeTTSEngine(chunks=2))
        sink = Sink()

        pipeline = Pipeline([aggregators.user(), llm, tts, sink])
        worker = PipelineWorker(
            pipeline, cancel_on_idle_timeout=False, idle_timeout_secs=None
        )

        started = asyncio.Event()

        @worker.event_handler("on_pipeline_started")
        async def _on_started(worker, frame):
            started.set()

        async def drive():
            await asyncio.wait_for(started.wait(), timeout=5)
            await worker.queue_frame(VADUserStartedSpeakingFrame())
            await worker.queue_frame(UserStartedSpeakingFrame())
            await worker.queue_frame(
                TranscriptionFrame("open notepad", "user", "2026-01-01T00:00:00")
            )
            await worker.queue_frame(VADUserStoppedSpeakingFrame())
            await worker.queue_frame(UserStoppedSpeakingFrame())
            await asyncio.sleep(3)
            await worker.queue_frame(EndFrame())

        runner = WorkerRunner()
        await runner.add_workers(worker)
        await asyncio.gather(runner.run(), drive())
        return sink.frames

    try:
        frames = run(scenario())
    finally:
        llm_adapter.handle_utterance = original

    audio = [f for f in frames if type(f).__name__ == "TTSAudioRawFrame"]
    # The TTS service consumes LLMTextFrame and re-emits its own text frame,
    # so look for the reply text on any frame that carries one.
    text = [
        f
        for f in frames
        if "notepad" in str(getattr(f, "text", "") or "").lower()
    ]

    check("turn produced reply text", len(text) >= 1, f"got {len(text)}")
    check("reply was synthesized to audio", len(audio) >= 1, f"got {len(audio)}")
    check("no pipeline errors", "error" not in [k for k, _ in events])


# ---------------------------------------------------------------------------
# 9. Control server
# ---------------------------------------------------------------------------
def test_control_server():
    print("\n[9] Control server")

    from aiohttp.test_utils import TestClient, TestServer

    from pipecat_voice.agent import MaydayVoiceAgent
    from pipecat_voice.config import VoiceServiceConfig
    from pipecat_voice.control_server import ControlServer
    from pipecat_voice.events import EventHub

    hub = EventHub()
    config = VoiceServiceConfig()
    agent = MaydayVoiceAgent(
        config, hub, stt_engine=FakeSTTEngine(), tts_engine=FakeTTSEngine()
    )
    server = ControlServer(agent=agent, hub=hub, config=config)

    async def scenario():
        results = {}
        async with TestClient(TestServer(server.build_app())) as client:
            response = await client.get("/voice/health")
            results["health"] = await response.json()

            response = await client.get("/voice/status")
            results["status"] = await response.json()

            websocket = await client.ws_connect("/ws/voice")
            hello = await websocket.receive_json()
            results["hello"] = hello

            await websocket.send_json({"type": "ping"})
            results["pong"] = await websocket.receive_json()

            await websocket.send_json({"type": "text", "text": "hi"})
            results["text_reply"] = await websocket.receive_json()

            await websocket.send_json({"type": "bogus"})
            results["bogus"] = await websocket.receive_json()

            await websocket.send_json({"type": "mute", "value": True})
            results["mute_on"] = await websocket.receive_json()

            await websocket.send_json({"type": "mute", "value": False})
            results["mute_off"] = await websocket.receive_json()

            await websocket.close()

        return results

    results = run(scenario())

    check("health ok", results["health"].get("status") == "ok")
    check("health reports not running", results["health"].get("running") is False)
    check("status ok", results["status"].get("status") == "ok")
    check("hello has state", "state" in results["hello"])
    check("hello reports transport", results["hello"].get("transport") == "local")
    check("hello reports mute flag", "muted" in results["hello"])
    check("ping -> pong", results["pong"].get("type") == "pong")
    check(
        "text before start -> error",
        results["text_reply"].get("type") == "error",
        str(results["text_reply"]),
    )
    check(
        "unknown command -> error",
        results["bogus"].get("type") == "error",
        str(results["bogus"]),
    )
    check(
        "mute on acknowledged",
        results["mute_on"].get("type") == "muted"
        and results["mute_on"].get("value") is True,
        str(results["mute_on"]),
    )
    check(
        "mute off acknowledged",
        results["mute_off"].get("type") == "muted"
        and results["mute_off"].get("value") is False,
        str(results["mute_off"]),
    )
    check("mute reflected in status", agent.status().get("muted") is False)


# ---------------------------------------------------------------------------
# 9b. Shutdown endpoint
# ---------------------------------------------------------------------------
def test_shutdown_endpoint():
    print("\n[9b] Shutdown endpoint")

    from aiohttp.test_utils import TestClient, TestServer

    from pipecat_voice.agent import MaydayVoiceAgent
    from pipecat_voice.config import VoiceServiceConfig
    from pipecat_voice.control_server import ControlServer
    from pipecat_voice.events import EventHub

    hub = EventHub()
    config = VoiceServiceConfig()
    agent = MaydayVoiceAgent(
        config, hub, stt_engine=FakeSTTEngine(), tts_engine=FakeTTSEngine()
    )

    called = []
    server = ControlServer(
        agent=agent,
        hub=hub,
        config=config,
        on_shutdown=lambda: called.append(True),
    )

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            response = await client.post("/voice/shutdown")
            return response.status, await response.json()

    status, body = run(scenario())
    check("shutdown returns ok", status == 200 and body.get("status") == "ok", str(body))
    check("shutdown callback fired", called == [True])


# ---------------------------------------------------------------------------
# 10. Token security
# ---------------------------------------------------------------------------
def test_token_security():
    print("\n[10] Control token")

    from aiohttp.test_utils import TestClient, TestServer

    from pipecat_voice.agent import MaydayVoiceAgent
    from pipecat_voice.config import VoiceServiceConfig
    from pipecat_voice.control_server import ControlServer
    from pipecat_voice.events import EventHub

    hub = EventHub()
    config = VoiceServiceConfig()
    config.token = "s3cret"
    agent = MaydayVoiceAgent(
        config, hub, stt_engine=FakeSTTEngine(), tts_engine=FakeTTSEngine()
    )
    server = ControlServer(agent=agent, hub=hub, config=config)

    async def scenario():
        async with TestClient(TestServer(server.build_app())) as client:
            denied = await client.get("/ws/voice")
            websocket = await client.ws_connect("/ws/voice?token=s3cret")
            hello = await websocket.receive_json()
            await websocket.close()
            return denied.status, hello

    denied, hello = run(scenario())
    check("socket without token denied", denied == 401, f"got {denied}")
    check("socket with token allowed", hello.get("type") == "hello", str(hello))


# ---------------------------------------------------------------------------
# 11. Real engines (opt-in)
# ---------------------------------------------------------------------------
def test_real_engines():
    print("\n[11] Real engines (Kokoro + Faster-Whisper)")

    from text_to_speech import tts_engine

    check("iter_audio_chunks exists", hasattr(tts_engine, "iter_audio_chunks"))

    start = time.time()
    total = 0
    for chunk in tts_engine.iter_audio_chunks("MAYDAY online."):
        total += int(chunk.size)
    elapsed = time.time() - start
    check("kokoro produced audio", total > 0, f"{total} samples")
    print(f"        kokoro: {total} samples in {elapsed:.1f}s")

    from speech_to_text import stt_engine

    check("transcribe_array exists", hasattr(stt_engine, "transcribe_array"))

    # Round-trip: synthesize a known phrase, then transcribe it back.
    samples = []
    for chunk in tts_engine.iter_audio_chunks("open notepad"):
        samples.append(chunk)

    if samples:
        audio = np.concatenate(samples)
        # Kokoro is 24 kHz, Whisper wants 16 kHz.
        indices = np.arange(0, audio.size, 24000 / 16000)
        resampled = np.interp(indices, np.arange(audio.size), audio).astype(np.float32)

        start = time.time()
        text = stt_engine.transcribe_array(resampled)
        elapsed = time.time() - start
        print(f"        whisper: {text!r} in {elapsed:.1f}s")
        check(
            "round-trip transcription is sensible",
            "notepad" in text.lower(),
            f"got {text!r}",
        )
    else:
        check("round-trip transcription is sensible", False, "no synthesized audio")


# ---------------------------------------------------------------------------
# 5c. Online (Gemini) error surfacing
# ---------------------------------------------------------------------------
def test_online_errors():
    print("\n[5c] Online error surfacing")

    import online_service

    class FakeError(Exception):
        pass

    # A rate-limited request must be bounded, not left to hang.
    svc = online_service.OnlineService()
    options = svc._http_options()
    check(
        "gemini timeout is bounded",
        isinstance(options.timeout, int) and options.timeout > 0,
        options.timeout,
    )
    check(
        "gemini retries are bounded",
        bool(options.retry_options.attempts) and options.retry_options.attempts >= 1,
        options.retry_options.attempts,
    )

    message, friendly = online_service.OnlineService._describe_error(
        FakeError("429 RESOURCE_EXHAUSTED: quota exceeded")
    )
    check("429 -> technical message", "429" in message, message)
    check(
        "429 -> friendly line",
        bool(friendly) and "rate" in friendly.lower(),
        friendly,
    )

    _message, friendly = online_service.OnlineService._describe_error(
        FakeError("request timed out")
    )
    check("timeout -> friendly line", bool(friendly), friendly)

    _message, friendly = online_service.OnlineService._describe_error(
        FakeError("something odd")
    )
    check("other error -> no friendly line", friendly is None, friendly)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 68)
    print("MAYDAY real-time voice (Pipecat) - verification")
    print("=" * 68)

    test_config()
    test_event_hub()
    test_stt_adapter()
    test_tts_adapter()
    test_llm_adapter()
    test_brain()
    test_online_errors()
    test_observer()
    test_mute_processor()
    test_pipeline_assembly()
    test_pipeline_end_to_end()
    test_control_server()
    test_shutdown_endpoint()
    test_token_security()

    if os.getenv("MAYDAY_TEST_REAL_MODELS", "").strip() in {"1", "true", "yes"}:
        test_real_engines()
    else:
        print("\n[11] Real engines skipped (set MAYDAY_TEST_REAL_MODELS=1 to run)")

    print("\n" + "=" * 68)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 68)

    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
