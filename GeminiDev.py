# meta developer: @Komarik228Komary
# meta name: GeminiDev
# meta version: 3.1

from .. import loader, utils
import aiohttp
import json
import io
import re
import asyncio
import random

@loader.tds
class GeminiDev(loader.Module):
    """Генератор модулей через Gemini"""

    strings = {
        "name": "GeminiDev",
        "no_key": "❌ <b>API ключи не найдены. Укажи:\n.config GeminiDev gemini_api_keys ключ1,ключ2</b>",
        "prompt_set": "✅ <b>Системный промпт установлен.</b>",
        "no_txt": "❌ <b>Ответь на .txt файл</b>",
        "no_query": "❌ <b>Укажи описание</b>",
        "generating": "🧠 <b>Генерация модуля...</b>",
        "checking": "🧪 <b>Анализ и проверка...</b>",
        "fixing": "🔧 <b>Исправление кода...</b>",
        "refining": "📈 <b>Улучшение по описанию...</b>",
        "merging": "🧬 <b>Анализ и объединение модулей...</b>",
        "result_info": (
            "<b>📦 Название:</b> <code>{name}</code>\n"
            "<b>👤 Автор:</b> <code>{author}</code>\n"
            "<b>🧩 Команды:</b> <code>{commands}</code>\n"
            "<b>📎 Версия:</b> <code>1.0</code>\n"
            "<b>🔌 Зависимости:</b> <code>{deps}</code>"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "gemini_api_keys",
                "",
                lambda: "Ключи Gemini API (через запятую)",
                validator=loader.validators.String(),
            )
        )
        self.base_prompt = ""
        self._keys = []
        self._key_index = 0
        self._merge_buffer = {}

    async def client_ready(self, client, db):
        self.db = db
        self.base_prompt = self.db.get("GeminiDev", "prompt", "")
        raw_keys = self.config["gemini_api_keys"]
        self._keys = [k.strip().replace("\u200e", "") for k in raw_keys.split(",") if k.strip()]
        random.shuffle(self._keys)

    async def promtcmd(self, message):
        """<reply to .txt> — установить системный промпт"""
        reply = await message.get_reply_message()
        if not reply or not reply.file or not reply.file.name.endswith(".txt"):
            return await utils.answer(message, self.strings("no_txt"))

        buf = io.BytesIO()
        await reply.download_media(buf)
        prompt = buf.getvalue().decode("utf-8")
        self.base_prompt = prompt
        self.db.set("GeminiDev", "prompt", prompt)

        await utils.answer(message, self.strings("prompt_set"))

    async def geminicall(self, user_prompt: str) -> str:
        if not self._keys:
            return self.strings("no_key")

        prompt = f"{self.base_prompt.strip()}\n\n{user_prompt.strip()}"
        headers = {"Content-Type": "application/json"}
        data = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 999999
            }
        }

        tried = set()
        while len(tried) < len(self._keys):
            key = self._keys[self._key_index]
            self._key_index = (self._key_index + 1) % len(self._keys)
            tried.add(key)

            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=150)) as session:
                    async with session.post(url, headers=headers, json=data) as r:
                        res = await r.json()
                        if "candidates" in res:
                            return res["candidates"][0]["content"]["parts"][0]["text"]
                        if "error" in res:
                            msg = res["error"].get("message", "")
                            code = str(res["error"].get("code", ""))
                            if any(x in msg.lower() for x in ["exceeded", "limit", "quota", "unavailable"]) or code in {"429", "403", "503"}:
                                continue
                            return f"❌ Ошибка Gemini:\n<code>{msg or code or 'неизвестно'}</code>"
                        return f"❌ Неизвестный ответ:\n<code>{json.dumps(res, indent=2)}</code>"
            except Exception:
                continue

        return "❌ Все ключи исчерпаны или недоступны."

    def extract_code(self, raw: str) -> str:
        if "```" in raw:
            parts = re.findall(r"```(?:python)?(.*?)```", raw, re.S)
            return parts[0].strip() if parts else raw.strip()
        return raw.strip()

    def extract_deps(self, code: str, hint: str = "") -> str:
        stdlib = {
            "re", "io", "sys", "os", "math", "time", "random", "json", "typing",
            "datetime", "logging", "asyncio", "builtins"
        }
        found = set(re.findall(r"^\s*(?:from|import)\s+([a-zA-Z0-9_]+)", code, re.M))
        for line in re.findall(r"(?i)pip install (.+)", hint):
            for lib in re.split(r"[,\s]+", line):
                if lib and lib not in stdlib:
                    found.add(lib)
        return ", ".join(sorted(found - stdlib)) if found else "нету"

    def extract_commands(self, code: str) -> str:
        cmd_regex = re.compile(r"@loader\.command[^\n]*\n\s*async\s+def\s+([a-zA-Z0-9_]+cmd)\s*\(")
        matches = cmd_regex.findall(code)
        if not matches:
            matches = re.findall(r"async def ([a-zA-Z0-9_]+cmd)\s*\(", code)
        return ", ".join(matches[:5]) or "—"

    async def send_result(self, message, code: str, hint: str):
        name_match = re.search(r"class\s+(\w+)\s*\(", code)
        name = name_match.group(1) if name_match else "GeneratedModule"
        commands = self.extract_commands(code)
        deps = self.extract_deps(code, hint)

        user = await message.client.get_entity(message.sender_id)
        author = f"@{user.username}" if user.username else f"id:{user.id}"

        msg = self.strings("result_info").format(name=name, author=author, commands=commands, deps=deps)
        f = io.BytesIO(code.encode("utf-8"))
        f.name = f"{name}.py"
        await message.reply(file=f, message=msg)

    async def gencmd(self, message):
        """<описание> — сгенерировать модуль по описанию"""
        query = utils.get_args_raw(message)
        if not query:
            return await utils.answer(message, self.strings("no_query"))

        await utils.answer(message, self.strings("generating"))

        prompt = (
            "Создай Telethon-модуль для Telegram-юзербота.\n"
            "Выходной результат — .py файл с loader.Module.\n"
            "Добавь минимум одну команду и описания к ней.\n\n"
            f"Описание:\n{query}"
        )

        raw = await self.geminicall(prompt)
        code = self.extract_code(raw)

        await utils.answer(message, self.strings("checking"))
        _ = await self.geminicall(f"Проанализируй этот код на ошибки:\n```python\n{code}\n```")

        await utils.answer(message, self.strings("fixing"))
        fixed = await self.geminicall(f"Исправь ошибки в этом коде:\n```python\n{code}\n```")
        final = self.extract_code(fixed)

        await self.send_result(message, final, fixed)

    async def refinecmd(self, message):
        """<описание> — доработать .py модуль по описанию"""
        args = utils.get_args_raw(message)
        reply = await message.get_reply_message()
        if not args or not reply or not reply.file or not reply.file.name.endswith(".py"):
            return await utils.answer(message, "❌ <b>Ответь на .py файл и укажи описание</b>")

        buf = io.BytesIO()
        await reply.download_media(buf)
        code = buf.getvalue().decode("utf-8")

        await utils.answer(message, self.strings("refining"))

        prompt = (
            "Улучши этот Telethon-модуль по описанию, сохранив структуру loader.Module.\n\n"
            f"```python\n{code}\n```\n\n"
            f"Описание улучшений:\n{args}"
        )

        improved = await self.geminicall(prompt)
        improved_code = self.extract_code(improved)

        await utils.answer(message, self.strings("checking"))
        _ = await self.geminicall(f"Проверь этот код Python:\n```python\n{improved_code}\n```")

        await utils.answer(message, self.strings("fixing"))
        fixed = await self.geminicall(f"Исправь ошибки в этом коде:\n```python\n{improved_code}\n```")
        final = self.extract_code(fixed)

        await self.send_result(message, final, fixed)

    async def mergecmd(self, message):
        """Обьединение двух модулей в один"""
        reply = await message.get_reply_message()
        if not reply or not reply.file or not reply.file.name.endswith(".py"):
            return await utils.answer(message, "❌ <b>Ответь на .py модуль</b>")

        buf = io.BytesIO()
        await reply.download_media(buf)
        code = buf.getvalue().decode("utf-8")

        user_id = str(message.sender_id)

        if user_id not in self._merge_buffer:
            self._merge_buffer[user_id] = code
            return await utils.answer(message, "✅ <b>Модуль добавлен. Отправь второй через .merge</b>")

        old_code = self._merge_buffer.pop(user_id)
        await utils.answer(message, self.strings("merging"))

        _ = await self.geminicall(
            f"Проанализируй два модуля Telegram userbot и определи сильные стороны каждого:\n\n"
            f"Модуль 1:\n```python\n{old_code}\n```\n\n"
            f"Модуль 2:\n```python\n{code}\n```"
        )

        merged = await self.geminicall(
            f"Объедини два модуля, используя лучшие части каждого. Удали дубли и оставь одну loader.Module структуру.\n\n"
            f"Модуль 1:\n```python\n{old_code}\n```\n\n"
            f"Модуль 2:\n```python\n{code}\n```"
        )
        merged_code = self.extract_code(merged)

        fixed = await self.geminicall(
            f"Проверь и исправь ошибки в объединённом коде:\n```python\n{merged_code}\n```"
        )
        final_code = self.extract_code(fixed)

        await self.send_result(message, final_code, fixed)