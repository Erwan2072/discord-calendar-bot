import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import json
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Charger le token
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Config bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Fichiers de stockage
DATA_FILE = "calendar.json"
CHANNEL_FILE = "calendar_channel.json"

# ---- Fonctions utilitaires ----
def load_tasks():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_tasks(tasks):
    with open(DATA_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

def load_channel_data():
    if os.path.exists(CHANNEL_FILE):
        with open(CHANNEL_FILE, "r") as f:
            return json.load(f)
    return {}

def save_channel_data(data):
    with open(CHANNEL_FILE, "w") as f:
        json.dump(data, f)

def validate_date_format(date_str: str) -> bool:
    """Vérifie que la date est au format JJ/MM/AAAA"""
    try:
        datetime.strptime(date_str, "%d/%m/%Y")
        return True
    except ValueError:
        return False

# ---- Bouton pour valider une tâche ----
class ValidateButton(Button):
    def __init__(self, task_id, title):
        super().__init__(label=f"✅ {title}", style=discord.ButtonStyle.success)
        self.task_id = task_id

    async def callback(self, interaction: discord.Interaction):
        tasks = load_tasks()
        for task in tasks:
            if task["id"] == self.task_id:
                task["done"] = True
                task["validated_by"] = interaction.user.display_name
        save_tasks(tasks)

        await interaction.response.send_message(
            f"✅ **{interaction.user.display_name}** a validé la tâche : *{self.label[2:]}*",
            ephemeral=False
        )
        await update_planning_message(interaction.guild)

# ---- Vue interactive avec navigation et validation ----
class WeekView(View):
    def __init__(self, week_offset=0):
        super().__init__(timeout=None)
        self.week_offset = week_offset
        self.refresh_buttons()

    def refresh_buttons(self):
        self.clear_items()
        tasks = load_tasks()
        today = datetime.today() + timedelta(days=7 * self.week_offset)
        start_week = today - timedelta(days=today.weekday())
        end_week = start_week + timedelta(days=6)

        for task in tasks:
            try:
                task_date = datetime.strptime(task["date"], "%d/%m/%Y")
                if start_week <= task_date <= end_week and not task["done"]:
                    self.add_item(ValidateButton(task["id"], task["title"]))
            except Exception:
                continue

        # Navigation
        self.add_item(Button(label="⬅️ Semaine précédente", style=discord.ButtonStyle.primary, custom_id="prev"))
        self.add_item(Button(label="➡️ Semaine suivante", style=discord.ButtonStyle.primary, custom_id="next"))

    async def build_embed(self):
        tasks = load_tasks()
        today = datetime.today() + timedelta(days=7 * self.week_offset)
        start_week = today - timedelta(days=today.weekday())  # lundi
        end_week = start_week + timedelta(days=6)  # dimanche

        embed = discord.Embed(
            title=f"📅 Tâches de la semaine ({start_week.strftime('%d/%m')} → {end_week.strftime('%d/%m')})",
            color=0xe67e22
        )

        has_task = False
        for task in tasks:
            try:
                task_date = datetime.strptime(task["date"], "%d/%m/%Y")
                if start_week <= task_date <= end_week:
                    status = "✅ Terminé" if task["done"] else "❌ En attente"
                    if "validated_by" in task and task["done"]:
                        status += f" (par {task['validated_by']})"
                    embed.add_field(
                        name=f"[ID {task['id']}] {task['date']} – {task['title']}",
                        value=status,
                        inline=False
                    )
                    has_task = True
            except Exception:
                continue

        if not has_task:
            embed.description = "📭 Aucune tâche prévue cette semaine."

        return embed

    async def update_message(self, interaction_or_message):
        self.refresh_buttons()
        embed = await self.build_embed()
        if isinstance(interaction_or_message, discord.Interaction):
            await interaction_or_message.response.edit_message(embed=embed, view=self)
        else:
            await interaction_or_message.edit(embed=embed, view=self)

# ---- Mise à jour auto du planning dans le salon ----
async def update_planning_message(guild):
    data = load_channel_data()
    channel_id = data.get("channel_id")
    message_id = data.get("message_id")

    if not channel_id or not message_id:
        return

    channel = guild.get_channel(channel_id)
    if not channel:
        return

    try:
        message = await channel.fetch_message(message_id)
        view = WeekView()
        embed = await view.build_embed()
        await message.edit(embed=embed, view=view)
    except Exception as e:
        print(f"Erreur mise à jour planning : {e}")

# ---- Quand le bot démarre ----
@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 {len(synced)} commandes slash synchronisées.")
    except Exception as e:
        print(e)

# ---- Commandes ----

# ➕ Ajouter une tâche (admin)
@bot.tree.command(name="calendar_add", description="Ajoute une tâche (admin seulement)")
async def calendar_add(interaction: discord.Interaction, titre: str, date: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Seuls les admins peuvent ajouter des tâches.", ephemeral=True)
        return

    if not validate_date_format(date):
        await interaction.response.send_message("⚠️ Format de date invalide. Utilise JJ/MM/AAAA.", ephemeral=True)
        return

    tasks = load_tasks()
    task_id = len(tasks) + 1
    tasks.append({"id": task_id, "title": titre, "date": date, "done": False})
    save_tasks(tasks)

    await interaction.response.send_message(f"✅ Tâche ajoutée : {date} – {titre}", ephemeral=True)
    await update_planning_message(interaction.guild)

# ✏️ Modifier une tâche (admin)
@bot.tree.command(name="calendar_edit", description="Modifie une tâche par son ID (admin seulement)")
async def calendar_edit(interaction: discord.Interaction, task_id: int, nouveau_titre: str = None, nouvelle_date: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Seuls les admins peuvent modifier une tâche.", ephemeral=True)
        return

    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            if nouveau_titre:
                task["title"] = nouveau_titre
            if nouvelle_date:
                if not validate_date_format(nouvelle_date):
                    await interaction.response.send_message("⚠️ Format de date invalide. Utilise JJ/MM/AAAA.", ephemeral=True)
                    return
                task["date"] = nouvelle_date
            save_tasks(tasks)
            await interaction.response.send_message(
                f"✏️ Tâche ID {task_id} mise à jour : {task['date']} – {task['title']}",
                ephemeral=True
            )
            await update_planning_message(interaction.guild)
            return

    await interaction.response.send_message(f"⚠️ Tâche ID {task_id} introuvable.", ephemeral=True)

# 📋 Voir toutes les tâches
@bot.tree.command(name="calendar_list", description="Liste toutes les tâches")
async def calendar_list(interaction: discord.Interaction):
    tasks = load_tasks()
    if not tasks:
        await interaction.response.send_message("📭 Aucune tâche enregistrée.")
        return

    embed = discord.Embed(title="📅 Planning complet", color=0x3498db)
    for task in tasks:
        status = "✅ Terminé" if task["done"] else "❌ En attente"
        if "validated_by" in task and task["done"]:
            status += f" (par {task['validated_by']})"
        embed.add_field(name=f"[ID {task['id']}] {task['date']} – {task['title']}", value=status, inline=False)

    await interaction.response.send_message(embed=embed)

# 📅 Voir la semaine (manuel)
@bot.tree.command(name="calendar_week", description="Affiche la semaine en cours (manuel)")
async def calendar_week(interaction: discord.Interaction):
    view = WeekView()
    embed = await view.build_embed()
    await interaction.response.send_message(embed=embed, view=view)

# 🗑️ Supprimer une tâche précise (admin)
@bot.tree.command(name="calendar_remove", description="Supprime une tâche précise par son ID (admin seulement)")
async def calendar_remove(interaction: discord.Interaction, task_id: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Seuls les admins peuvent supprimer une tâche.", ephemeral=True)
        return

    tasks = load_tasks()
    tasks = [task for task in tasks if task["id"] != task_id]

    # Réattribuer les ID pour garder une suite propre
    for i, task in enumerate(tasks, start=1):
        task["id"] = i

    save_tasks(tasks)
    await interaction.response.send_message(f"🗑️ Tâche ID {task_id} supprimée.")
    await update_planning_message(interaction.guild)

# 🗑️ Vider (admin)
@bot.tree.command(name="calendar_clear", description="Supprime toutes les tâches (admin seulement)")
async def calendar_clear(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Seuls les admins peuvent supprimer les tâches.", ephemeral=True)
        return

    save_tasks([])
    await interaction.response.send_message("🗑️ Toutes les tâches ont été supprimées.")
    await update_planning_message(interaction.guild)

# ⚙️ Configurer le salon d’affichage (admin)
@bot.tree.command(name="calendar_channel", description="Configure le salon où afficher le planning (admin seulement)")
async def calendar_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⛔ Seuls les admins peuvent configurer le salon.", ephemeral=True)
        return

    # Envoie le message principal du calendrier
    view = WeekView()
    embed = await view.build_embed()
    message = await channel.send(embed=embed, view=view)

    # Sauvegarde ID salon + message
    save_channel_data({"channel_id": channel.id, "message_id": message.id})
    await interaction.response.send_message(f"✅ Planning configuré dans {channel.mention}")
