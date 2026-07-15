// Sample text passages for the 🎲 Random button when generating speech.
// Mix of narration styles, lengths, and use cases so you can hear how
// different TTS models render different content.
//
// DESIGN RULE: keep these strings as plain spoken text only. Do NOT include:
//   - Bark-style tags like [laughter], [singing], [MUSIC], [whispers]
//   - Emotion / state markers like (sad and slow) or *excited*
//   - Stage directions ("she said in a quiet voice")
//   - Performance notes (♪ ♫ symbols)
//
// Why: those things are model-specific. Bark interprets [laughter] as a
// non-verbal cue; every OTHER engine in our catalog (Kokoro, VoxCPM,
// Qwen3-TTS, VoxCPM2-MLX, F5-TTS, Chatterbox, Spark-TTS, XTTS) will read
// them literally ("open bracket laughter close bracket") or hallucinate
// trying to parse them as text. Bad UX.
//
// Emotion / tone / style belongs in the dedicated UI fields:
//   - `instruct` / "Emotion / tone control" — VoxCPM v1, Qwen3 CustomVoice
//   - `voice_design_prompt` — Qwen3 VoiceDesign, VoxCPM2-MLX voice design
// The random sampler stays neutral so it works across every engine.
window.SAMPLE_PROMPTS = [
  // ─── Short test phrases (10)
  "Hello, this is a test of the text-to-speech system.",
  "The quick brown fox jumps over the lazy dog.",
  "She sells seashells by the seashore.",
  "Welcome back. How can I help you today?",
  "Generating audio... one moment, please.",
  "Good morning. Today's forecast: sunny with a high of 72.",
  "Press one for English. Press two for Spanish.",
  "Your package has been delivered. Enjoy your day.",
  "I'd be happy to help with that. Let me check.",
  "Recording will begin in three, two, one.",

  // ─── Narration / audiobook style (10)
  "It was the best of times, it was the worst of times, it was the age of wisdom, it was the age of foolishness.",
  "Call me Ishmael. Some years ago — never mind how long precisely — I thought I would sail about a little.",
  "In a hole in the ground there lived a hobbit. Not a nasty, dirty, wet hole, but a hobbit-hole, and that means comfort.",
  "The morning fog rolled across the harbor as the fishing boats returned with their catch, gulls wheeling overhead.",
  "She closed the book carefully, set it on the windowsill, and watched the rain trace patterns down the glass.",
  "Through the dense forest, the path wound steadily upward, the air growing thinner with each careful step.",
  "He had not expected the letter to arrive so quickly, nor for its contents to change everything he knew.",
  "The old lighthouse keeper smiled to himself as he climbed the spiral stairs one final time.",
  "Across the meadow, the wildflowers bowed in unison as a gentle breeze carried their scent over the hills.",
  "By the time the sun rose over the mountains, the village below had already begun its quiet morning rituals.",

  // ─── Dialog / conversational (10)
  "Hey! Long time no see. How have you been? It must be what, three years now?",
  "Wait, you're telling me you actually went there? In the middle of winter? That's wild.",
  "Sorry, could you repeat that? I didn't quite catch the last part.",
  "Honestly, I don't know what to say. That was incredible.",
  "Yeah, I think we should probably head out before traffic gets bad.",
  "You'll never believe what happened at the meeting today. Seriously, never in a million years.",
  "It's a long story, but the short version is: don't ever lend that guy your car.",
  "I mean, sure, technically he's right, but did he have to say it like that?",
  "Look, all I'm saying is, maybe next time we plan ahead a little better. That's all.",
  "Okay so picture this: it's 2 AM, we're in the parking lot, and the keys are gone.",

  // ─── Voice cloning reference scripts (10)
  // These are short and contain a balanced set of phonemes — good for
  // recording a 5-10 second reference clip yourself if you want to clone
  // your own voice.
  "The five boxing wizards jump quickly. Pack my box with five dozen liquor jugs.",
  "How vexingly quick daft zebras jump! The job requires extra pluck and zeal from every young wage earner.",
  "Sphinx of black quartz, judge my vow. Bright vixens jump; dozy fowl quack.",
  "Quick zephyrs blow, vexing daft Jim. A wizard's job is to vex chumps quickly in fog.",
  "Two driven jocks help fax my big quiz. Crazy Fredrick bought many very exquisite opal jewels.",
  "We promptly judged antique ivory buckles for the next prize. Big quacking zephyrs vex bold Jim.",
  "Six big devils from Japan quickly forgot how to waltz. The wizards quickly jinxed the gnomish dwarf.",
  "Pack my red box with five dozen quality jugs. By Jove, my quick study of lexicography won a prize.",
  "The five boxing wizards jump quickly at the zoo. Brave young phantom waltzed at the jinxed disco.",
  "Heavy boxes perform quick waltzes and jigs. Five or six big jet planes zoomed quickly by the new tower.",

  // ─── Longer-form narration (10) — exercises pacing + breath groups
  "There is something almost magical about a morning that begins before sunrise. The world is quiet, the air still cool, and even small sounds carry an unusual weight.",
  "The library smelled of old paper and ink. Rows of shelves stretched into the dim light, each one heavy with books that had not been opened in years.",
  "When the train finally pulled into the station, she stepped off into the cold night air and pulled her coat tight against the wind.",
  "He paused before answering, weighing each word carefully. What he said next would matter more than he was ready to admit.",
  "The clock on the kitchen wall ticked steadily, marking the seconds the way it had for thirty-two years, indifferent to everything that had changed.",
  "Long shadows stretched across the field as the sun began its slow descent behind the line of dark pines that bordered the western edge.",
  "She turned the brass key in the lock with both hands. The door swung open easily, as if it had been waiting for someone to remember it.",
  "The waiter brought two glasses of water and a small plate of warm bread. They sat in comfortable silence, neither of them in a hurry to begin.",
  "Outside the window, a thin rain had started to fall, and the streetlights doubled themselves in the wet pavement below.",
  "It took several minutes for the meaning of the message to settle in. When it did, the rest of the afternoon felt suddenly far away.",
];

// Multilingual sampler — only sensible for engines that actually support these
// languages. Read via `getRandomPromptFor(model)` in app.js if you want to
// gate by language capability per engine. For now `SAMPLE_PROMPTS` above is
// English-only so the Random button is safe to click on ANY model in the
// catalog, including engines that only expose English voices.
//
// Engines that handle these well:
//   - VoxCPM2-MLX (30 languages)  ← all of these
//   - Qwen3-TTS (en/zh/ja/ko/+more) ← all of these
//   - Kokoro-MLX (9 voice languages) ← supported entries only
//   - VoxCPM v1 (en/zh)             ← only fr/es/de/it/pt are iffy
//   - Bark (13 languages)           ← all except hi/ar/pl
//   - XTTS-v2 (17 languages)        ← all of these
window.SAMPLE_PROMPTS_MULTILINGUAL = [
  "Bonjour, et bienvenue. Je m'appelle Marie. Comment puis-je vous aider aujourd'hui?",
  "Hola, ¿cómo estás? Espero que tengas un día maravilloso.",
  "Guten Morgen. Heute haben wir wunderschönes Wetter, finden Sie nicht?",
  "Ciao, mi chiamo Marco. Sono molto felice di conoscerti.",
  "Olá, tudo bem? Como posso ajudá-lo hoje?",
  "你好，欢迎使用语音合成系统。今天我能为你做些什么？",
  "こんにちは。今日はいい天気ですね。何かお手伝いできることはありますか？",
  "안녕하세요. 만나서 반갑습니다. 오늘 기분이 어떠세요?",
  "Здравствуйте. Меня зовут Анна. Чем я могу вам помочь?",
];
