import os, re, logging, asyncio
import discord
from discord import app_commands
from openai import OpenAI

# --- ENV ---
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Support channel can be set via ID or fallback to name
SUPPORT_CHANNEL_ID = os.getenv("SUPPORT_CHANNEL_ID")
SUPPORT_CHANNEL_ID = int(SUPPORT_CHANNEL_ID) if SUPPORT_CHANNEL_ID and SUPPORT_CHANNEL_ID.isdigit() else 1423351008209141842
SUPPORT_CHANNEL_NAME = os.getenv("SUPPORT_CHANNEL_NAME", "support")

ASSISTANT_GREETING_NAME = os.getenv("ASSISTANT_GREETING_NAME", "Melanie")

# System instructions for “Melanie”
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

# --- Logging ---
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("melanie")

# --- OpenAI ---
client = OpenAI(api_key=OPENAI_API_KEY)
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # fast + capable

# Simple explicit/inappropriate filter
EXPLICIT_PAT = re.compile(
    r"(sex|nude|explicit|onlyfans|nsfw|send pics|dick|pussy|naked|porn|blowjob|anal)",
    re.I
)

intents = discord.Intents.default()
intents.message_content = True  # enable in Discord portal too!
intents.guilds = True
intents.members = False

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

    async def on_message(self, msg: discord.Message):
        # ignore self / bots
        if msg.author.bot or msg.author == self.user:
            return

        # respond only in the support channel (prefer ID, fallback to name)
        if SUPPORT_CHANNEL_ID:
            if msg.channel.id != SUPPORT_CHANNEL_ID:
                return
        else:
            if msg.channel.name != SUPPORT_CHANNEL_NAME:
                return

        # respond when mentioned OR if reply to Melanie OR starts with her name
        mentioned = self.user in msg.mentions
        name_called = msg.content.strip().lower().startswith(("melanie", "mel", "@melanie"))
        replying_to_mel = bool(msg.reference and msg.reference.cached_message and
                               msg.reference.cached_message.author == self.user)
        if not (mentioned or name_called or replying_to_mel):
            return

        # explicit filter
        if EXPLICIT_PAT.search(msg.content):
            try:
                await msg.add_reaction("🚫")
            except Exception:
                pass
            return

        user_text = msg.content.replace(f"<@{self.user.id}>", "").strip()
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
        except Exception as e:
            log.exception("OpenAI error")
            reply = ("I’m having trouble reaching our help brain right now. "
                     "Please email info@tgfx-academy.com and we’ll take care of you.")

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
