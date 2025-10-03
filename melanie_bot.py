import os, re, logging, asyncio, time
import discord
from discord import app_commands
from openai import OpenAI

# ---------- ENV ----------
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
ASSISTANT_ID = os.environ["ASSISTANT_ID"]

SUPPORT_CHANNEL_ID = os.getenv("SUPPORT_CHANNEL_ID")
SUPPORT_CHANNEL_ID = int(SUPPORT_CHANNEL_ID) if SUPPORT_CHANNEL_ID and SUPPORT_CHANNEL_ID.isdigit() else None
SUPPORT_CHANNEL_NAME = os.getenv("SUPPORT_CHANNEL_NAME", "support")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------- LOGGING ----------
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
log = logging.getLogger("melanie")

# ---------- OPENAI ----------
client = OpenAI(api_key=OPENAI_API_KEY)

# Filters
EXPLICIT_PAT = re.compile(r"(sex|nude|explicit|onlyfans|nsfw|send pics|dick|pussy|naked|porn|blowjob|anal)", re.I)
AFFIRM_RE = re.compile(r"^(y(es|up|eah)?|sure|please|pls|do it|go ahead|send it|ok(ay)?|bet|yep|yeah|yes please)\b", re.I)

# Canned responses for quick follow-ups
JOIN_INFO = (
    "Awesome! Here’s how to join TGFX Academy:\n"
    "• Sign up on Whop → https://whop.com/tgfx-trade-lab/\n"
    "• After purchase, open the **TGFX Academy hub** in Whop.\n"
    "• Join the Discord from the hub and you’ll get access once your role syncs.\n"
    "Need help with checkout or access? Email **info@tgfx-academy.com**."
)
CANCEL_INFO = (
    "No problem—here’s how to cancel:\n"
    "• Go to **Whop → TGFX Trade Lab**: https://whop.com/tgfx-trade-lab/\n"
    "• Manage Subscription → Cancel. You’ll keep access until the end of the billing period.\n"
    "If you run into any issues, email **info@tgfx-academy.com**."
)
LIVESTREAM_INFO = (
    "Livestreams are hosted in Discord under **📈│live stream**.\n"
    "• You must have the **trade-lab-premium** role to see the channel.\n"
    "• If you don’t see it, claim your role via the **TGFX Academy hub** on Whop."
)
ROLE_CLAIM_INFO = (
    "If your sub is active but you don’t see channels:\n"
    "1) Open the **TGFX Academy hub** in Whop\n"
    "2) Click **Claim Discord Role**\n"
    "3) Discord will refresh and add **trade-lab-premium** automatically.\n"
    "Still stuck? Email **info@tgfx-academy.com**."
)
TRAINING_VIDS_INFO = (
    "Our full **Trading Course** videos are in the **TGFX Academy hub** on Whop.\n"
    "Log into Whop → TGFX Academy hub → Training Course. If you can’t access, ping **info@tgfx-academy.com**."
)

# Simple intent extraction from Melanie's last reply
def extract_offer_intent(text: str) -> str | None:
    t = text.lower()
    # Join/Signup
    if "info on how to join" in t or "how to join" in t or "join tgfx" in t or "sign up" in t or "tgfx trade lab" in t:
        return "JOIN_INFO"
    # Cancel
    if "cancel" in t and ("subscription" in t or "member" in t or "billing" in t):
        return "CANCEL_HELP"
    # Livestreams
    if "livestream" in t or "live stream" in t:
        return "LIVESTREAM_INFO"
    # Role claim / access
    if "claim your discord role" in t or "trade-lab-premium" in t or "don’t see the channel" in t or "don't see the channel" in t:
        return "ROLE_CLAIM"
    # Training videos
    if "training videos" in t or "trading course" in t or "videos are hosted" in t:
        return "TRAINING_VIDEOS"
    return None

INTENT_TO_REPLY = {
    "JOIN_INFO": JOIN_INFO,
    "CANCEL_HELP": CANCEL_INFO,
    "LIVESTREAM_INFO": LIVESTREAM_INFO,
    "ROLE_CLAIM": ROLE_CLAIM_INFO,
    "TRAINING_VIDEOS": TRAINING_VIDS_INFO,
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

class MelanieClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.user_threads: dict[str, str] = {}     # per-user Assistant thread
        self.pending_offer: dict[str, str] = {}    # per-user pending intent

    async def setup_hook(self):
        @self.tree.command(name="ping", description="Check Melanie’s status")
        async def _ping(interaction: discord.Interaction):
            await interaction.response.send_message("Melanie is online ✅", ephemeral=True)
        await self.tree.sync()

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (id: {self.user.id})")
        for g in self.guilds:
            log.info(f"In guild: {g.name} ({g.id})")
            for ch in g.text_channels:
                if SUPPORT_CHANNEL_ID and ch.id == SUPPORT_CHANNEL_ID:
                    log.info(f"✅ Found support channel by ID: #{ch.name} ({ch.id})")
                elif (not SUPPORT_CHANNEL_ID) and (ch.name == SUPPORT_CHANNEL_NAME):
                    log.info(f"✅ Found support channel by NAME: #{ch.name} ({ch.id})")
        log.info(f"Support filter → {'ID='+str(SUPPORT_CHANNEL_ID) if SUPPORT_CHANNEL_ID else 'NAME='+SUPPORT_CHANNEL_NAME}")

    async def on_message(self, msg: discord.Message):
        # basic debug
        try:
            snippet = (msg.content or "")[:80].replace("\n", "\\n")
            log.debug(f"RX msg in #{msg.channel.name} ({msg.channel.id}) from {msg.author}: {snippet}")
        except Exception:
            pass

        if msg.author.bot or msg.author == self.user:
            return

        # Only in support channel
        if SUPPORT_CHANNEL_ID:
            if msg.channel.id != SUPPORT_CHANNEL_ID:
                return
        else:
            if msg.channel.name != SUPPORT_CHANNEL_NAME:
                return

        # Mention / name / reply gating (keep channel tidy)
        mentioned = self.user in msg.mentions
        name_called = (msg.content or "").strip().lower().startswith(("melanie", "mel", "@melanie"))
        replying_to_mel = bool(msg.reference and msg.reference.cached_message and
                               msg.reference.cached_message.author == self.user)
        if not (mentioned or name_called or replying_to_mel):
            return

        # Block explicit
        if EXPLICIT_PAT.search(msg.content or ""):
            try: await msg.add_reaction("🚫")
            except: pass
            return

        user_id = str(msg.author.id)
        text_clean = (msg.content or "").replace(f"<@{self.user.id}>", "").strip()

        # ---- OFFER SHORT-CIRCUIT: if user says "yes" and an offer is pending
        if AFFIRM_RE.match(text_clean) and user_id in self.pending_offer:
            intent = self.pending_offer.pop(user_id, None)
            if intent and intent in INTENT_TO_REPLY:
                await self.safe_send(msg.channel, INTENT_TO_REPLY[intent], reference=msg)
                return  # handled, no API call

        # Otherwise, talk to the Assistant (dashboard-managed prompt + files)
        try:
            reply = await self.ask_assistant(text_clean or "User needs TGFX help.", discord_user_id=user_id)
            # After getting reply, detect if Melanie made an offer we should remember
            intent = extract_offer_intent(reply or "")
            if intent:
                self.pending_offer[user_id] = intent
                log.debug(f"Pending offer set for user {user_id}: {intent}")
        except Exception:
            log.exception("Assistants API error")
            reply = ("I’m having trouble reaching our help brain right now. "
                     "Please email info@tgfx-academy.com and we’ll take care of you.")

        # Friendly intro if greeted
        if any(w in (text_clean.lower()) for w in ["hi", "hey", "hello", "how are you"]):
            reply = f"Hey there! I’m doing awesome, thanks for asking 🌟 How can I help?\n\n{reply}"

        await self.safe_send(msg.channel, reply, reference=msg)

    async def ask_assistant(self, message_text: str, discord_user_id: str) -> str:
        # Reuse per-user thread for memory continuity
        thread_id = self.user_threads.get(discord_user_id)
        if not thread_id:
            thread = client.beta.threads.create(metadata={"discord_user_id": discord_user_id})
            thread_id = thread.id
            self.user_threads[discord_user_id] = thread_id
            log.debug(f"Created Assistant thread {thread_id} for {discord_user_id}")

        client.beta.threads.messages.create(thread_id=thread_id, role="user", content=message_text)
        run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID)

        start = time.time()
        while True:
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if run.status in ("completed", "failed", "cancelled", "expired"):
                break
            if time.time() - start > 60:
                log.warning("Assistant run timeout")
                break
            await asyncio.sleep(0.7)

        if run.status != "completed":
            raise RuntimeError(f"Assistant run not completed: {run.status}")

        msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=5)
        for m in msgs.data:
            if m.role == "assistant":
                for part in m.content:
                    if part.type == "text":
                        return part.text.value.strip()
        return "I’m here and ready to help—could you try that again?"

    async def safe_send(self, channel, text, reference=None):
        chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
        for i, ch in enumerate(chunks):
            await channel.send(ch, reference=reference if i == 0 else None)
            await asyncio.sleep(0.1)

if __name__ == "__main__":
    MelanieClient().run(DISCORD_TOKEN)
