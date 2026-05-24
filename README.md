# Dou Dizhu Demo

Dou Dizhu Demo is a local browser game for testing how different LLMs play Dou Dizhu against a human challenger. It includes a FastAPI backend, a vanilla HTML/CSS/JavaScript frontend, model-based AI seats, table talk, bilingual UI, and post-game AI recap.

## Features

- Three-player Dou Dizhu: one human challenger and two AI model seats.
- Traditional card rules including straights, consecutive pairs, bombs, rockets, and planes.
- AI bidding and play decisions through configured LLM providers.
- Table talk system that can influence the target AI's next decision.
- Bilingual UI: Chinese and English.
- Post-game AI recap with reason, thought summary, assessment, and mood.
- A 15-second AI action timeout so the game keeps moving.

## Requirements

- Tested on macOS. Other Unix-like environments may work, but have not been verified.
- Conda, either Miniconda or Anaconda
- Python 3.11, created automatically by `run.sh` if the `game_demo` environment does not exist

## **Configuration**

The server loads environment variables from `.env` and `llm.env` at startup. The local `llm.env` file is intended for real API keys and should not be committed.

**A `.env` or `llm.env` file is not required to start the project.** If no provider API keys are configured, the game can still run, and AI actions fall back to conservative default behavior such as no-bid or pass when the model call cannot be made.

Create or edit `llm.env` in the repository root if you want real LLM opponents. `.env.example` can be used as a reference for the supported variable names, but do not overwrite an existing `llm.env` that already contains real keys.

```bash
touch llm.env
```

Then add the providers you want to use:

```bash
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DASHSCOPE_API_KEY=
```

Optional base URLs are also supported:

```bash
ANTHROPIC_BASE_URL=
OPENAI_BASE_URL=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

## Run On macOS

From the repository root:

```bash
./run.sh
```

Then open:

```text
http://127.0.0.1:8000/
```

You can also activate the environment manually first:

```bash
conda activate game_demo
./run.sh
```

The script will:

1. Find Conda.
2. Create the `game_demo` environment if needed.
3. Install or update dependencies from `requirements.txt`.
4. Start the FastAPI server with Uvicorn.

Useful overrides:

```bash
PORT=8010 ./run.sh
HOST=0.0.0.0 ./run.sh
CONDA_ENV_NAME=my_env ./run.sh
```

## References And Authorship

The Dou Dizhu rule implementation and utilities were written with reference to:

- [kwai/DouZero](https://github.com/kwai/DouZero): *[ICML 2021] DouZero: Mastering DouDizhu with Self-Play Deep Reinforcement Learning*
- [datamllab/rlcard](https://github.com/datamllab/rlcard): Dou Dizhu utility logic, especially `doudizhu/utils.py`

Authorship notes:

- The frontend code was completed entirely by AI.
- The test work was completed entirely by AI.
- `server/cards.py` was completed by a human worker.
- The other Python files were completed collaboratively by human and AI contributors.

## Project Layout

```text
server/              FastAPI app, game state, rules, LLM routing, prompts
tests/               Rule and game-state tests
web/index.html       Browser UI
requirements.txt     Python dependencies
run.sh               macOS-friendly one-command launcher
work.md              Development notes and milestone tracking
```

## Notes

- `llm.env` and `.env` are loaded by `server/main.py`.
- The browser UI is served by the FastAPI app at `/`.
- If port `8000` is already in use, run with another port, for example `PORT=8010 ./run.sh`.
