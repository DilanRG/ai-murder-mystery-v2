# 🔪 AI Murder Mystery

> **Redesign in progress:** The repository's controlling specification is now
> [the turn-based MVP project brief](docs/project_brief.md). The downloadable
> v2.0 prototype described below is preserved as a baseline while the validated,
> turn-based vertical slice is built in small checkpoints.

A murder mystery game where the suspects are powered by AI. They move around, talk to each other, lie, and try to cover their tracks — all in real time. Your job is to figure out who did it before time runs out.

---

## Download & Play

**No installation required.** Just download, run, and play.

👉 **[Download the latest release](https://github.com/DilanRG/ai-murder-mystery-v2/releases/latest)**

| Platform | File |
|---|---|
| Windows | `ai-murder-mystery.exe` |
| macOS | `ai-murder-mystery` |
| Linux | `ai-murder-mystery` |

> **You'll need a free API key** from [OpenRouter](https://openrouter.ai) to power the AI. Sign up, copy your key, and paste it into the game's Settings screen when prompted. Free models are available.

---

## How to Play

1. **Launch** the downloaded file — it opens your browser automatically
2. **Enter your name** and choose a difficulty
3. **Explore** the map by clicking locations
4. **Question suspects** — type your questions and read their responses
5. **Search rooms** to find physical clues
6. **Watch the event log** — the suspects are doing things in real time
7. **Make your accusation** when you think you know who did it

If you're right, you solved the case. If you're wrong... the killer walks free.

---

## What makes it different?

Unlike a normal mystery game, the suspects here are **fully autonomous AI agents**. Each one has a secret briefing — their alibi, what they know, what they're hiding. The killer knows who they are, and will actively try to mislead you: moving evidence, telling half-truths, and avoiding your questions.

Every game generates a completely new mystery: new characters, new locations, new motive, new story.

---

## Screenshots

*Coming soon*

---

## Troubleshooting

**The game won't start?**
- On macOS/Linux you may need to make the file executable first:
  `chmod +x ai-murder-mystery` then double-click or run it

**Nothing happens after I click Send?**
- Check that your API key is set in Settings (top-right gear icon)

**The AI responses are slow?**
- This depends on the model you've chosen. Free models can be slower during busy periods. Try a different one in Settings.

---

## License

MIT — free to use, modify, and share.
