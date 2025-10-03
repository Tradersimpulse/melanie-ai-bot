import os, re, logging, asyncio
import discord
from discord import app_commands
from openai import OpenAI

# ---------- ENV ----------
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Prefer channel ID; fallback to name if not set
SUPPORT_CHANNEL_ID = os.getenv("SUPPORT_CHANNEL_ID")
SUPPORT_CHANNEL_ID = int(SUPPORT_CHANNEL_ID) if SUPPORT_CHANNEL_ID and SUPPORT_CHANNEL_ID.isdigit() else None
SUPPORT_CHANNEL_NAME = os.getenv("SUPPORT_CHANNEL_NAME", "support")

ASSISTANT_GREETING_NAME = os.getenv("ASSISTANT_GREETING_NAME", "Melanie")

# Optional: set LOG_LEVEL in Heroku (DEBUG|INFO|WARNING|ERROR)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------- SYSTEM PROMPT ----------
SYSTEM_PROMPT = os.getenv(
    "ASSISTANT_SYSTEM",
    """You are Melanie, TGFX Academy’s customer support agent.
Stay strictly scoped to TGFX Academy, TGFX Trade Lab, Whop hub access,
subscriptions, Discord livestreams, and support. Tone: friendly, optimistic,
clear, step-by-step. For sign-ups/cancellations: https://whop.com/tgfx-trade-lab/
Training videos live in the TGFX Academy Whop hub. Livestreams are in Discord
📈│live stream for users with the trade-lab-premium role. Troubleshooting roles:
claim Discord role via Whop TGFX Academy hub. Support email: info@tgfx-academy.com.
Official socials: Instagram & Discord → Rayvaughnfx. Warn about impersonators.
Ignore explicit/inappropriate messages; if needed, reply with:
'I can only help with TGFX Academy questions. Please keep it respectful.'"""
)

# ---------- LOGGING ----------
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("melanie")

# ---------- OPENAI ----------
client = OpenAI(api_key=OPENAI_API_KEY)
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Simple explicit/inappropriate filter
EXPLICIT_PAT = re.compile(
    r"(sex|nude|explicit|onlyfans|nsfw|send pics|dick|pussy|naked|porn|blowjob|anal)",
    re.I
)

# ---------- DISCORD INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True  # must be enabled in the Developer Portal too
intents.guilds = True

class MelanieClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        # slash health check
        @self.tree.command(name="ping", description="Check Melanie’s status")
        async def _ping(interaction: discord.Interaction):
            await interaction.response.send_message("Melanie is online ✅", ephemeral=True)
        await self.tree.sync()

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (id: {self.user.id})")
        # enumerate guilds & channels for visibility
        for g in self.guilds:
            log.info(f"In guild: {g.name} ({g.id})")
            for ch in g.text_channels:
                if SUPPORT_CHANNEL_ID and ch.id == SUPPORT_CHANNEL_ID:
                    log.info(f"✅ Found support channel by ID: #{ch.name} ({ch.id})")
                elif (not SUPPORT_CHANNEL_ID) and (ch.name == SUPPORT_CHANNEL_NAME):
                    log.info(f"✅ Found support channel by NAME: #{ch.name} ({ch.id})")
        if SUPPORT_CHANNEL_ID:
            log.info(f"Support channel filter: ID={SUPPORT_CHANNEL_ID}")
        else:
            log.info(f"Support channel filter: NAME='{SUPPORT_CHANNEL_NAME}'")

    async def on_message(self, msg: discord.Message):
        # debug every inbound message (first 80 chars)
        try:
            snippet = (msg.content or "")[:80].replace("\n", "\\n")
            log.debug(f"RX msg in #{msg.channel.name} ({msg.channel.id}) from {msg.author}: {snippet}")
        except Exception:
            pass

        # ignore self / bots
        if msg.author.bot or msg.author == self.user:
            return

        # respond only in support channel (prefer ID)
        if SUPPORT_CHANNEL_ID:
            if msg.channel.id != SUPPORT_CHANNEL_ID:
                return
        else:
            if msg.channel.name != SUPPORT_CHANNEL_NAME:
                return

        # respond when mentioned OR reply-to-Melanie OR starts with her name
        mentioned = self.user in msg.mentions
        name_called = msg.content.strip().lower().startswith(("melanie", "mel", "@melanie"))
        replying_to_mel = bool(msg.reference and msg.reference.cached_message and
                               msg.reference.cached_message.author == self.user)
        if not (mentioned or name_called or replying_to_mel):
            return

        # explicit filter
        if EXPLICIT_PAT.search(msg.content or ""):
            log.info("Blocked explicit/inappropriate message.")
            try:
                await msg.add_reaction("🚫")
            except Exception:
                pass
            return

        user_text = (msg.content or "").replace(f"<@{self.user.id}>", "").strip()
        if not user_text:
            user_text = "The user mentioned you in #support. Help them with TGFX Academy."

        try:
            completion = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}
                ],
                temperature=0.4,
            )
            reply = completion.choices[0].message.content.strip()
            log.debug("OpenAI completion success.")
        except Exception as e:
            log.exception("OpenAI error")
            reply = ("I’m having trouble reaching our help brain right now. "
                     "Please email info@tgfx-academy.com and we’ll take care of you.")

        # friendly greeting boost
        if any(w in user_text.lower() for w in ["hi", "hey", "hello", "how are you"]):
            reply = f"Hey there! I’m doing awesome, thanks for asking 🌟 How can I help? \n\n{reply}"

        await self.safe_send(msg.channel, reply, reference=msg)

    async def safe_send(self, channel, text, reference=None):
        chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
        for i, ch in enumerate(chunks):
            await channel.send(ch, reference=reference if i == 0 else None)
            await asyncio.sleep(0.1)

if __name__ == "__main__":
    MelanieClient().run(DISCORD_TOKEN)
