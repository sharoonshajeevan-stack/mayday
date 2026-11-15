# 🚀 MAYDAY OS - Complete Setup Guide

Step-by-step instructions to get MAYDAY OS running on your Windows 11 PC.

---

## ✅ **Prerequisites Check**

- [ ] Windows 11
- [ ] Python 3.12.10 installed
- [ ] Node.js installed (v16+)
- [ ] ~20GB free disk space
- [ ] Microphone connected
- [ ] Speakers/Headphones connected

---

## 📦 **Step 1: Install Dependencies**

### **1.1 Install Ollama**

1. Go to https://ollama.ai
2. Click "Download" → Windows
3. Run installer (`OllamaSetup.exe`)
4. Follow installation wizard
5. **Restart your computer**

**Verify installation:**
```powershell
ollama --version
# Should show version number
```

### **1.2 Download AI Model**

Open PowerShell and run:
```powershell
ollama pull mistral
```

⏳ **Wait 5-10 minutes** (downloads ~4GB model)

When done, you'll see:
pulling manifest
...
success


### **1.3 Verify Python**

```powershell
python --version
# Should show: Python 3.12.10
```

If not installed, download from https://python.org

### **1.4 Verify Node.js**

```powershell
node --version
npm --version
# Should show version numbers
```

If not installed, download from https://nodejs.org

---

## 📁 **Step 2: Setup Project Folders**

### **2.1 Create Main Directory**

```powershell
mkdir D:\MAYDAY-OS
cd D:\MAYDAY-OS
```

### **2.2 Organize Folders**

Your structure should look like:

D:\MAYDAY-OS
├── frontend\ (React UI)
├── backend\ (Python API)
└── README.md


---

## 🐍 **Step 3: Setup Backend**

### **3.1 Create Backend Folder**

```powershell
mkdir D:\MAYDAY-OS\backend
mkdir D:\MAYDAY-OS\backend\logs
mkdir D:\MAYDAY-OS\backend\memory
cd D:\MAYDAY-OS\backend
```

### **3.2 Create Requirements File**

Create `D:\MAYDAY-OS\backend\requirements.txt`:

Flask==3.0.0
Flask-CORS==4.0.0
python-dotenv==1.0.0
pyaudio
faster-whisper>=1.2.1
kokoro>=0.9.4
psutil
requests==2.31.0


### **3.3 Install Dependencies**

```powershell
pip install -r requirements.txt
```

⏳ **Wait 10-15 minutes** for all packages to install

### **3.4 Create .env File**

Create `D:\MAYDAY-OS\backend\.env`:

FLASK_ENV=development
FLASK_DEBUG=True
API_PORT=5000
API_HOST=0.0.0.0
OLLAMA_HOST=http://localhost:11434


### **3.5 Add Python Files**

Copy all `.py` files from documentation into backend folder:
- main.py
- ai_engine.py
- personality.py
- speech_to_text.py
- text_to_speech.py
- wake_word_detector.py
- system_commands.py
- memory_system.py
- ollama_service.py

---

## ⚛️ **Step 4: Setup Frontend**

### **4.1 Create Frontend Folder**

```powershell
mkdir D:\MAYDAY-OS\frontend
cd D:\MAYDAY-OS\frontend
npm create vite@latest . -- --template react
```

### **4.2 Install Dependencies**

```powershell
npm install
```

⏳ **Wait 5 minutes**

### **4.3 Install 3D Graphics**

```powershell
npm install three react-three-fiber @react-three/drei @react-three/postprocessing framer-motion
```

### **4.4 Copy React Files**

Create the following files in `D:\MAYDAY-OS\frontend\src\`:

**folders to create:**
- components/
- components/hud/
- services/
- scenes/
- context/
- config/
- hooks/
- materials/
- shaders/
- styles/
- utils/

**Files to copy:**
- App.jsx
- main.jsx
- index.css
- App.css
- AIStateProvider.jsx (in context/)
- CoreScene.jsx (in scenes/)
- HUD.jsx (in components/hud/)
- APITest.jsx (in components/)
- WakeWordDetector.jsx (in components/)
- AIConsole.jsx (in components/)
- SpeechToText.jsx (in components/)
- SystemCommands.jsx (in components/)
- TextToSpeech.jsx (in components/)
- api.js (in services/)

---

## 🚀 **Step 5: Run MAYDAY OS**

### **Terminal 1: Start Ollama**

```powershell
ollama serve
```

**Wait for:**

listening on 127.0.0.1:11434


✅ **Keep this running!**

### **Terminal 2: Start Backend**

```powershell
cd D:\MAYDAY-OS\backend
python main.py
```

**Wait for:**

Running on http://127.0.0.1:5000


✅ **Keep this running!**

### **Terminal 3: Start Frontend**

```powershell
cd D:\MAYDAY-OS\frontend
npm run dev
```

**Wait for:**

Local: http://localhost:5173/


✅ **Keep this running!**

### **Open Browser**

Go to: `http://localhost:5173/`

🎉 **MAYDAY OS is running!**

---

## 🧪 **Test Everything**

### **Test 1: AI Console**
- Type "hello"
- Click "Send Test"
- Should see response

### **Test 2: Wake Word**
- Click "Start Listening"
- Status should show "Listening for Mayday"
- Click "Test Detection"
- Should see "MAYDAY DETECTED!"

### **Test 3: Speech-to-Text**
- Click "Start Recording"
- Speak into microphone
- Click "Stop Recording"
- Should see transcript

### **Test 4: System Commands**
- Click "Google" button
- Should open in browser
- Click "Notepad"
- Should launch Notepad

### **Test 5: Ollama AI**
In browser console (F12):
```javascript
fetch('http://localhost:5000/api/ollama/generate', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({ prompt: 'What is your name?' })
}).then(r => r.json()).then(d => console.log(d.data.data.response))
```

Should get response from Mistral AI!

---

## 🎭 **Personality**

MAYDAY's character lives in one place: `backend/personality.py`. It builds the
system prompt used by **both** the online (Gemini) and offline (Ollama) engines
and adds short, contextual commentary to deterministic system actions (opening
apps/sites, playing media, screenshots, errors, ...). No extra language model is
loaded for it.

### **Defaults**

| Setting | Default | Meaning |
| --- | --- | --- |
| `personality_enabled` | `true` | Master switch for the personality layer |
| `sarcasm_level` | `70` | 0-100; naturally sarcastic, never rude |
| `humour_level` | `75` | 0-100; funny without forcing it |
| `commentary_frequency` | `balanced` | `off` / `minimal` / `balanced` / `chatty` |
| `spoken_response_length` | `short` | `short` / `medium` / `detailed` |
| `quiet_mode` | `false` | Suppresses optional commentary |
| `voice` | `bf_emma` | Kokoro voice (natural British English female) |

Settings are saved to `backend/personality.json` (git-ignored) and survive a
restart.

### **Settings panel**

Open the HUD and click the gear button labelled **PERSONALITY** (top-right,
under the frame corner). From there you can toggle personality/quiet mode,
adjust the sarcasm and humour levels, pick the commentary frequency and spoken
length, choose the voice, and reset everything to the defaults.

### **API**

```powershell
# Read the current settings
GET  http://localhost:5000/api/personality

# Update one or more settings
POST http://localhost:5000/api/personality
     {"sarcasm_level": 50, "commentary_frequency": "minimal"}

# Restore the defaults
POST http://localhost:5000/api/personality
     {"reset": true}
```

### **Behaviour notes**

- Actions are always executed first; MAYDAY only comments *after* the result is
  known and never claims success the result did not confirm.
- Written replies may stay detailed; the **spoken** reply follows
  `spoken_response_length` and stays short by default.
- Commentary has a cooldown (default 12s) so repeated commands do not trigger a
  fresh remark every time; errors always get one.
- Follow-ups keep context: say "open YouTube", then "play Arijit Singh" and
  MAYDAY searches YouTube for it.

---

## 📋 **Troubleshooting**

### **Port 5000 Already in Use**
```powershell
netstat -ano | findstr :5000
taskkill /PID <PID> /F
```

### **Port 11434 Already in Use**
Ollama is already running. Just proceed!

### **Microphone Not Working**
1. Check Windows sound settings
2. Ensure microphone is default device
3. Test in Windows Sound settings
4. Restart PyAudio: `pip install --upgrade pyaudio`

### **Faster-Whisper Model Not Found**
```powershell
pip install --upgrade faster-whisper
```
The model downloads automatically on first use. If it fails, check your internet
connection and try `WHISPER_MODEL=base` in `backend/.env`.

### **Kokoro Voice Not Found / No Audio**
```powershell
pip install --upgrade kokoro
```
The voice pack downloads automatically on first use. List the available voices
with `GET http://localhost:5000/api/tts/voices` and set a valid one in
`KOKORO_VOICE` inside `backend/.env`.

### **Voice Starts Slowly or Sounds Choppy**
MAYDAY speaks in small pieces so the first words play almost immediately and
the rest is synthesized while the current piece is still playing. These optional
`backend/.env` values tune that behaviour:

- `KOKORO_FIRST_CHARS` (default `30`) - length of the very first piece; a
  smaller value starts speaking sooner.
- `KOKORO_CHUNK_CHARS` (default `160`) - size of the remaining pieces.
- `KOKORO_SPEED` (default `1.0`) - speech rate.

### **"open <app> for me" Does Nothing**
Say the app name after "open", "launch", "start", or "run". Common apps
(notepad, calculator, chrome, paint, task manager, settings, ...) are built in,
any executable on your `PATH` works, and everything else is answered by the AI.

### **Ollama "Model Not Found"**
```powershell
ollama pull mistral
```

### **Python Version Wrong**
```powershell
python --version
# If not 3.12.10, update Python
```

---

## ✅ **You're Done!**

MAYDAY OS is ready to use! 🎉

**Quick Start Next Time:**
1. Open Terminal 1: `ollama serve`
2. Open Terminal 2: `cd D:\MAYDAY-OS\backend && python main.py`
3. Open Terminal 3: `cd D:\MAYDAY-OS\frontend && npm run dev`
4. Open browser: `http://localhost:5173/`

---

**Have fun with MAYDAY OS!** 🚀