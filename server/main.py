from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"

# 启动时加载本地 env 文件（override=True：让文件里的值覆盖外部 shell 已存在的变量）
load_dotenv(ROOT_DIR / ".env", override=True)
load_dotenv(ROOT_DIR / "llm.env", override=True)

# 必须在 load_dotenv 之后再 import 用到 env 的模块
from . import characters  # noqa: E402
from .game import Game, GameError  # noqa: E402
from .schemas import TauntRequest  # noqa: E402

app = FastAPI(title="yxp_game_demo")
game = Game()


class BidRequest(BaseModel):
    player_id: int = Field(ge=0, le=2)
    score: int = Field(ge=0, le=3)


class PlayRequest(BaseModel):
    player_id: int = Field(ge=0, le=2)
    cards: list[int]


class PassRequest(BaseModel):
    player_id: int = Field(ge=0, le=2)


class NewGameRequest(BaseModel):
    ai_characters: list[str] = Field(default_factory=lambda: ["qwen", "deepseek"])
    output_language: str = "zh"


class AiStepRequest(BaseModel):
    output_language: str = "zh"


@app.get("/api/state")
def get_state():
    return game.to_api()


@app.post("/api/new-game")
def new_game(req: NewGameRequest):
    global game
    try:
        for character_id in req.ai_characters:
            character = characters.get_character(character_id)
            if not characters.is_available(character):
                raise GameError(f"角色 {character.name} 缺少 {character.api_key_env}")
        game = Game(ai_characters=req.ai_characters, output_language=req.output_language)
    except (GameError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return game.to_api()


@app.post("/api/bid")
def bid(req: BidRequest):
    try:
        game.bid(req.player_id, req.score)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return game.to_api()


@app.post("/api/play")
def play(req: PlayRequest):
    try:
        game.play(req.player_id, req.cards)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return game.to_api()


@app.post("/api/pass")
def pass_turn(req: PassRequest):
    try:
        game.pass_turn(req.player_id)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return game.to_api()


@app.post("/api/taunt")
def taunt(req: TauntRequest):
    try:
        game.taunt(req.target_seat, req.message)
    except GameError as e:
        status = 409 if "本回合已被嘴炮过" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from e
    return game.to_api()


@app.post("/api/ai-step")
def ai_step(req: AiStepRequest):
    try:
        game.set_output_language(req.output_language)
        game.advance_ai()
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return game.to_api()


@app.get("/api/characters")
def get_characters():
    """返回 8 张角色卡 + 可用性。前端选人界面用。"""
    return {"characters": characters.list_for_api()}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
