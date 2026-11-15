# 🤖 MAYDAY OS - AI Voice Assistant

A **futuristic AI desktop assistant** for Windows 11 with voice input/output, system control, memory, and offline AI processing.

![MAYDAY OS](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)
![Python](https://img.shields.io/badge/Python-3.12.10-blue)
![React](https://img.shields.io/badge/React-19.2.8-blue)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ **Features**

### 🎤 **Voice Interaction**
- **Wake Word Detection** - Listen for "Mayday" voice command
- **Speech-to-Text** - Convert voice to text locally with Faster-Whisper
- **Text-to-Speech** - Warm, natural female voice with Kokoro-82M
- **Real-time Audio Processing** - Fast audio capture and playback

### 🤖 **AI Intelligence**
- **Ollama Integration** - Run local Mistral AI models (offline, no internet needed)
- **Smart Command Processing** - Understand natural language commands
- **Conversation History** - Context-aware responses based on memory
- **Fallback System** - Works even if internet connection fails

### 💾 **Memory System**
- **Persistent Storage** - Save all conversations to JSON
- **Search Functionality** - Find past conversations by keyword
- **Context Awareness** - AI recalls previous chats
- **Statistics & Analytics** - Track memory usage and patterns

### 🖥️ **System Control**
- **Launch Applications** - Open any Windows app (Notepad, Chrome, etc.)
- **Web Browser** - Open URLs in default browser
- **File Management** - Open and manage files
- **System Commands** - Shutdown, restart PC with permission system
- **Process Monitoring** - View running applications and system resources

### 🎨 **Beautiful UI**
- **3D Cinematic Interface** - JARVIS/Mayday-style holographic design
- **Real-time Status Display** - See AI state (idle, listening, thinking, responding)
- **Interactive Components** - HUD, command history, system status
- **Dark Theme** - Eye-friendly sci-fi aesthetic

---

## 🏗️ **Architecture**

### **Tech Stack**
- **Frontend:** React 19.2.8 + Vite + Three.js (3D graphics)
- **Backend:** Python 3.12.10 + Flask API
- **AI:** Ollama (local models) + Gemini (online)
- **Voice:** Faster-Whisper (speech-to-text) + Kokoro-82M (text-to-speech) + PyAudio (voice capture)
- **Database:** JSON file storage (local)

### **Project Structure**

MAYDAY-OS/
├── frontend/ # React UI
│ ├── src/
│ │ ├── components/ # UI components (HUD, TTS, STT, etc.)
│ │ ├── services/ # API communication
│ │ ├── scenes/ # 3D scene rendering
│ │ ├── context/ # React state management
│ │ └── App.jsx # Main component
│ ├── package.json
│ └── vite.config.js
│
├── backend/ # Python API
│ ├── main.py # Flask server (port 5000)
│ ├── ai_engine.py # AI command processing
│ ├── speech_to_text.py # Voice-to-text conversion
│ ├── text_to_speech.py # Text-to-voice conversion
│ ├── wake_word_detector.py # "Mayday" detection
│ ├── system_commands.py # Windows control
│ ├── memory_system.py # Conversation storage
│ ├── ollama_service.py # Local LLM integration
│ ├── requirements.txt # Python dependencies
│ └── memory/ # Persistent storage
│ └── conversations.json
│
└── README.md # This file
---

## 🚀 **Quick Start**

### **Prerequisites**
- Windows 11
- Python 3.12.10
- Node.js (for React)
- Ollama (for AI)
- ~4GB disk space (for Mistral model)

### **Installation**

#### **1. Install Ollama**
1. Download from https://ollama.ai
2. Run installer
3. Download Mistral model:
```powershell
ollama pull mistral
```

#### **2. Setup Backend**
```powershell
cd D:\MAYDAY-OS\backend

# Install dependencies
pip install -r requirements.txt

# Start server
python main.py
```
Server runs on: `http://localhost:5000`

#### **3. Setup Frontend**
```powershell
cd D:\MAYDAY-OS\frontend

# Install dependencies
npm install

# Start development server
npm run dev
```
UI runs on: `http://localhost:5173`

#### **4. Start Ollama**
```powershell
ollama serve
```
Ollama runs on: `http://localhost:11434`

---

## 📖 **Usage Guide**

### **Starting MAYDAY OS**

1. **Terminal 1:** Start Ollama
```powershell
   ollama serve
```

2. **Terminal 2:** Start Python backend
```powershell
   cd D:\MAYDAY-OS\backend
   python main.py
```

3. **Terminal 3:** Start React frontend
```powershell
   cd D:\MAYDAY-OS\frontend
   npm run dev
```

4. **Browser:** Open http://localhost:5173

### **Voice Interaction**

#### **Wake Word Detection (Top-Right Box)**
- Click "Start Listening" to activate wake word detection
- Say "Mayday" to trigger
- Shows detection status and timestamp

#### **Speech-to-Text (Left Side Box)**
- Click "Start Recording" to begin recording
- Speak clearly for 3-5 seconds
- Click "Stop Recording" to process
- Transcript appears with confidence score

#### **AI Console (Right Side Box)**
- Type commands like "hello", "status", "help", "time"
- Click "Send Test" or use quick buttons
- AI responds with relevant information
- Responses saved to memory

#### **Text-to-Speech (Hidden but functional)**
- AI responses are automatically converted to speech
- Control volume and speed through API
- Customizable voice selection

#### **Real-Time Voice (Pipecat Layer)**

MAYDAY also ships an optional real-time voice mode. It adds continuous
listening, voice-activity detection (VAD), turn detection, barge-in and
streaming speech on top of the **same** Faster-Whisper, Kokoro and
Gemini/Ollama engines - nothing is duplicated and no audio ever leaves the
machine.

- Look for the **VOICE LINK** panel at the bottom of the HUD
- Click **ACTIVATE VOICE** - the mic indicator lights up and MAYDAY listens
- Just speak; MAYDAY detects the end of your turn and replies
- Speak while MAYDAY is talking to **interrupt** it mid-sentence
- Click **MUTE** to silence MAYDAY's voice while it keeps listening (and keeps
  showing replies on screen); click **UNMUTE** to bring the voice back
- Click **DEACTIVATE** to release the microphone

Privacy: nothing is activated automatically, the microphone indicator is always
visible while live, and the mic is released the moment you deactivate or close
the HUD. The service binds to `127.0.0.1` only.

### **System Commands (Middle Box)**

#### **Launch Apps**
- Quick buttons: Notepad, Explorer, CMD, Chrome
- Or type custom app name
- Apps launch immediately

#### **Open URLs**
- Quick buttons: Google, YouTube, GitHub
- Or paste custom URL
- Opens in default browser

#### **Permissions Panel**
- Toggle permissions for sensitive commands
- shutdown: Requires explicit permission
- restart: Requires explicit permission
- launch_app: Enabled by default
- open_url: Enabled by default

#### **System Monitor**
- Click "Show Processes" to view running apps
- See CPU cores, RAM usage, disk space
- Monitor system health

---

## 🔧 **API Endpoints**

### **AI & Commands**
- `POST /api/ai/process` - Process command through AI
- `GET /api/ai/status` - Get AI engine status
- `GET /api/ai/history` - Get command history
- `DELETE /api/ai/history` - Clear history

### **Speech-to-Text**
- `POST /api/stt/start` - Start recording
- `POST /api/stt/stop` - Stop and transcribe
- `GET /api/stt/status` - Get recording status
- `GET /api/stt/transcript` - Get last transcript

### **Text-to-Speech**
- `POST /api/tts/speak` - Convert text to speech
- `POST /api/tts/stop` - Stop speaking
- `GET /api/tts/voices` - Get available voices
- `POST /api/tts/rate` - Set speech speed
- `POST /api/tts/volume` - Set volume level

### **Real-Time Voice (Pipecat)**
- `GET /api/voice/realtime/status` - Check the real-time voice service
- `POST /api/voice/realtime/start` - Start the real-time voice service
- `POST /api/voice/realtime/stop` - Stop the real-time voice service
- `GET /voice/health` (service) - Service health probe
- `POST /voice/shutdown` (service) - Clean service shutdown
- `ws://127.0.0.1:7860/ws/voice` - Control/event channel (JSON only, no audio)

### **System Commands**
- `POST /api/system/shutdown` - Shutdown PC
- `POST /api/system/restart` - Restart PC
- `POST /api/system/launch-app` - Launch application
- `POST /api/system/open-url` - Open URL
- `GET /api/system/processes` - Get running processes
- `GET /api/system/info` - Get system info
- `GET /api/system/permissions` - Get permissions
- `POST /api/system/permissions` - Set permissions

### **Memory System**
- `POST /api/memory/add` - Add conversation to memory
- `GET /api/memory/recent` - Get recent memories
- `POST /api/memory/search` - Search memories
- `GET /api/memory/context` - Get conversation context
- `GET /api/memory/status` - Get memory status
- `GET /api/memory/stats` - Get memory statistics
- `GET /api/memory/export` - Export all memories
- `POST /api/memory/clear-session` - Clear session
- `POST /api/memory/clear-all` - Clear all memory

### **Ollama AI**
- `GET /api/ollama/status` - Check if Ollama running
- `GET /api/ollama/models` - List available models
- `POST /api/ollama/generate` - Generate response
- `POST /api/ollama/chat` - Chat with context
- `POST /api/ollama/model` - Set active model

---

## ⚙️ **Configuration**

### **Backend Settings** (`D:\MAYDAY-OS\backend\.env`)
FLASK_ENV=development
API_PORT=5000
OLLAMA_HOST=http://localhost:11434
### **AI Models**
- **Local:** Mistral (4B parameters, ~4GB)
- **Fast:** mistral:latest (recommended)
- **Larger:** Other Ollama models available

### **Voice Settings**
- **Speech Rate:** 50-300 (default: 150)
- **Volume:** 0.0-1.0 (default: 1.0)
- **Languages:** English (expandable)

### **Memory Settings**
- **Short-term:** Last 50 messages in session
- **Long-term:** Last 1000 messages persisted
- **Storage:** `backend/memory/conversations.json`

---

## 🛠️ **Troubleshooting**

### **Issue: Ollama not connecting**
Error: Connection refused to localhost:11434

**Solution:**
1. Ensure Ollama is running: `ollama serve`
2. Check port 11434 is open
3. Restart Ollama service

### **Issue: Microphone not working**

Error: No audio device found

**Solution:**
1. Check Windows audio settings
2. Ensure microphone is enabled
3. Check PyAudio installation: `pip install --upgrade pyaudio`

### **Issue: Faster-Whisper model not found**

Error: Model not found

**Solution:**
1. Install Faster-Whisper: `pip install faster-whisper`
2. The `base` model downloads automatically from Hugging Face on first use (~150 MB)
3. The first run may take a few minutes depending on your connection

### **Issue: Kokoro voice model not found**

Error: Voice pack missing

**Solution:**
1. Install Kokoro: `pip install kokoro`
2. The voice pack downloads automatically from Hugging Face on first use (~330 MB)
3. If text-to-speech is silent, check the voice ID is valid (`GET /api/tts/voices`)

### **Issue: Port already in use**

Error: Address already in use

**Solution:**
```powershell
# Find process using port
netstat -ano | findstr :5000

# Kill process (replace PID)
taskkill /PID <PID> /F
```

---

## 📊 **Performance**

### **Typical Response Times**
- **Wake Word Detection:** <100ms
- **Speech-to-Text:** 2-5 seconds
- **AI Response (Ollama):** 5-15 seconds (first run longer)
- **Text-to-Speech:** <2 seconds
- **System Command:** <500ms

### **System Requirements**
- **CPU:** 4+ cores recommended
- **RAM:** 8GB minimum (16GB+ recommended)
- **Disk:** 20GB free (10GB for Ollama models)
- **Network:** Optional (works offline!)

---

## 🔐 **Security & Privacy**

✅ **Privacy-First Design**
- All data stored locally
- No cloud sync (optional)
- Full conversation history under your control
- Permission system for sensitive commands

✅ **Permissions**
- Shutdown/Restart requires explicit permission
- File access logged
- URL opening checked
- System commands audited

✅ **Data Protection**
- Conversations stored as JSON (plaintext)
- Can export or delete anytime
- No telemetry or tracking
- Open-source (audit the code!)

---

## 🚀 **Future Enhancements**

- [ ] Add more AI models (Llama 2, Neural Chat)
- [ ] Implement conversation backup/cloud sync
- [ ] Add plugins/extensions system
- [ ] Mobile app control (Android/iOS)
- [ ] Advanced gesture control
- [ ] Custom wake words
- [ ] Multi-language support
- [ ] Video/webcam integration
- [ ] Database instead of JSON
- [ ] Docker containerization

---

## 📝 **Dependencies**

### **Python (Backend)**

Flask==3.0.0
Flask-CORS==4.0.0
python-dotenv==1.0.0
pyaudio
faster-whisper>=1.2.1
kokoro>=0.9.4
psutil
requests==2.31.0


### **Node.js (Frontend)**

react@19.2.8
vite@8.2.0
three@0.185.1
react-three-fiber@9.7.0
framer-motion@13.0.0


### **External Services**
- **Ollama** (local LLM)
- **Faster-Whisper** (speech-to-text, local)
- **Kokoro-82M** (text-to-speech, local)
- **Google Gemini** (optional online AI)

---

## 📜 **License**

MIT License - Free to use and modify!

---

## 👨‍💻 **Author**

Built with ❤️ by Sharoon

---

## 🤝 **Contributing**

Want to improve MAYDAY OS? Contributions welcome!

1. Fork the project
2. Create your feature branch
3. Make your changes
4. Submit a pull request

---

## 📞 **Support**

Having issues? Check:
1. Troubleshooting section above
2. GitHub issues
3. Discord community (if applicable)

---

## 🎯 **Project Status**

✅ **Production Ready**
- All core features implemented
- Stable and tested
- Ready for daily use

---

**MAYDAY OS - The future is now. 🚀**