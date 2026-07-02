"""
Age of Empires II – 1.6 Community Patch Discord Bot
Commands: !draft, !teams, !civ, !has, !counter, !eco, !build, !random, !hotkeys, !reset, !trainer
"""

import os
import sys
import asyncio
import random
from datetime import datetime

# Ensure emoji/unicode output doesn't crash when stdout/stderr aren't a UTF-8
# console (e.g. redirected to a log file on Windows, which defaults to cp1252).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import discord
from discord.ext import commands
from dotenv import load_dotenv

# Daytime-capture watcher (TELEMETRY_PLAN.md §2 stage ①) — periodically
# re-stages new SaveGame .mgz files into ChromaDB via Pipeline 1. Separate
# system from the legacy !analyze/!profile/!mygames/!coach commands below.
from savegame_watcher import start_savegame_watcher

# Unified cloud-LLM backbone — every LLM-driven command routes through this
# module rather than calling an HTTP API directly. See cloud_llm.py.
import cloud_llm

# Voice listening — wake-word sink and PCM helpers.
import voice_listen

# Static ruleset reference data injected into LLM system prompts.
import reference_loader

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# ── Voice listener config ─────────────────────────────────────────────────────
WAKE_WORD           = os.getenv("VOICE_WAKE_WORD", "teletron")
REPLY_MAX_TOKENS    = int(os.getenv("VOICE_REPLY_MAX_TOKENS", "300"))

# Maps Discord display names to Voobly usernames for profile lookup.
# Edit this dict to add new players. Key = Discord display name, Value = Voobly username.
DISCORD_TO_VOOBLY: dict[str, str] = {
    "SalarWaleed": "SalarWaleed",
    "Player2": "Player2",
    "Player3": "Player3",
    "Player4": "Player4",
    "Player5": "Player5",
    "Player6": "Player6",
    "Player6": "Player6",
    "Player7": "Player7",
    "Player9": "Player9",
    "Player8": "Player8",
}

_match_session: dict[str, list[str]] = {"ally": [], "enemy": []}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────────────────────────────────────────────────────
# COLOUR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
C_DRAFT   = 0xE67E22   # orange
C_TEAMS   = 0x2ECC71   # green
C_CIV     = 0x3498DB   # blue
C_ECO     = 0xF1C40F   # yellow
C_COUNTER = 0xE74C3C   # red
C_BUILD   = 0x9B59B6   # purple
C_INFO    = 0x95A5A6   # grey
C_GG      = 0x5865F2   # blurple (general chatbot)

# ─────────────────────────────────────────────────────────────────────────────
# 55-MAP POOL  (1.6 Map Pack, confirmed from local directory)
# ─────────────────────────────────────────────────────────────────────────────
ALL_MAPS = [
    "Acropolis", "Amazon Tunnel", "Atacama", "Baltic", "Bedouins",
    "Big Freeze", "Bog Islands", "Budapest", "Caribbean", "Cenotes",
    "Chaos Pit", "Clearing", "Cross", "Desert", "Dry River",
    "El Dorado", "Fortress", "Ghost Lake", "Glade", "Gold Rush",
    "Gold Volcano", "Golden Pit", "Golden Swamp", "Gorge", "Graveyards",
    "Hamburger", "Hideout", "Highland", "Hillfort", "Houseboat",
    "Islands", "Lombardia", "Mangrove Jungle", "Mediterranean", "Megarandom",
    "Mongolia", "Mountain Pass", "Mt Fuji", "Oasis", "Rift Island",
    "Rooster", "Sahara", "Salt Marsh", "Sandbank", "Scandinavia",
    "Serengeti", "Socotra", "Steppe", "Team Acropolis", "Team Islands",
    "Team Causeways", "Twin Puddles", "Valley", "Water Nomad", "Yucatan",
    "Arabia", "Arena", "Nomad", "Green Arabia", "Black Forest",
]

# Default competitive draft map pool (subset used when picking, full pool for banning)
DRAFT_MAP_POOL = [
    "Arabia", "Arena", "Nomad", "Green Arabia", "Black Forest",
    "Gold Rush", "Hideout", "Baltic", "Acropolis", "Mongolia",
    "Highland", "Ghost Lake", "Islands", "Megarandom", "Steppe",
]

# ─────────────────────────────────────────────────────────────────────────────
# CIV ID → NAME  (Voobly 1.6 Game Data, IDs 0-45)
# Used to convert mgz integer civ IDs to human-readable names.
# Ids 1-20 were originally listed alphabetically, which doesn't match the id
# order this Voobly build actually encodes (classic AoC release order).
# Corrected against aocref's bundled reference data and verified against two
# live ground-truth test matches (civ=15 confirmed Aztecs via an observed
# Elite Eagle Warrior; civ=29 confirmed Malay by the player who recorded the
# match). Ids 32+ are Definitive-Edition-only civs with no equivalent in this
# pre-DE Voobly build and are left unverified/unused.
# ─────────────────────────────────────────────────────────────────────────────
CIV_ID_TO_NAME: dict[int, str] = {
    0:  "Gaia",         1:  "Britons",      2:  "Franks",
    3:  "Goths",        4:  "Teutons",      5:  "Japanese",
    6:  "Chinese",      7:  "Byzantines",   8:  "Persians",
    9:  "Saracens",     10: "Turks",        11: "Vikings",
    12: "Mongols",      13: "Celts",        14: "Spanish",
    15: "Aztecs",       16: "Mayans",       17: "Huns",
    18: "Koreans",      19: "Italians",     20: "Indians",
    21: "Incas",        22: "Magyars",      23: "Slavs",
    24: "Portuguese",   25: "Ethiopians",   26: "Malians",
    27: "Berbers",      28: "Khmer",        29: "Malay",
    30: "Burmese",      31: "Vietnamese",   32: "Cumans",
    33: "Lithuanians",  34: "Bulgarians",   35: "Tatars",
    36: "Burgundians",  37: "Sicilians",    38: "Poles",
    39: "Bohemians",    40: "Dravidians",   41: "Bengalis",
    42: "Gurjaras",     43: "Romans",       44: "Armenians",
    45: "Georgians",
}

# ─────────────────────────────────────────────────────────────────────────────
# CIVILIZATION DATA  (1.6 = DE patch 169123, accurate to May 2026)
# ─────────────────────────────────────────────────────────────────────────────
# role: "flank" = archer/infantry, "pocket" = cavalry/boom, "flex" = both
CIVS = {
    "Armenians": {
        "role": "pocket",
        "bonuses": [
            "Cavalry Archers +1 attack vs. buildings every Age from Feudal",
            "Monks +5 HP per Monastery technology researched",
            "Start with +100 stone; Fortified Church available (replaces Monastery)",
            "Town Centers can garrison 10 units (+5 vs default)",
            "Composite Bowmen trainable from Archery Range",
        ],
        "unique_units": ["Composite Bowman (ranged cavalry archer substitute)"],
        "unique_techs": [
            "Cilician Fleet (Feudal): Ships +2/+2 armor",
            "Flint and Steel (Castle): Cavalry Archers fire +10% faster",
        ],
        "missing_key": ["Plate Mail Armor", "Plate Barding Armor"],
        "notes": "Strong all-round civ with stone bonus. Good on water and hybrid maps.",
    },
    "Aztecs": {
        "role": "flank",
        "bonuses": [
            "Villagers +5 carry capacity",
            "Military units created 11% faster",
            "Monks +5 HP per Monastery technology",
            "Start with +50 gold",
            "Loom free at game start",
        ],
        "unique_units": ["Jaguar Warrior (infantry anti-infantry)"],
        "unique_techs": [
            "Atlatl (Castle): Skirmishers +1 attack, +1 range",
            "Garland Wars (Imperial): Infantry +4 attack",
        ],
        "missing_key": ["Cavalry (no stable)", "Gold Shaft Mining"],
        "notes": "Best infantry civ in the game. Exceptional monks. No cavalry.",
    },
    "Bengalis": {
        "role": "pocket",
        "bonuses": [
            "Elephant units +2 melee armor, +2 pierce armor",
            "Town Centers spawn a villager when a Ratha is trained",
            "Ships have +15% HP",
            "Monks can convert siege weapons",
        ],
        "unique_units": ["Ratha (cavalry/ranged switch mode)"],
        "unique_techs": [
            "Paiks (Castle): Rathas and Elephant Archers attack 20% faster",
            "Mahayana (Imperial): Villagers take up −5 pop space (max 5 saved)",
        ],
        "missing_key": ["Plate Barding Armor", "Husbandry", "Bloodlines"],
        "notes": "Strong elephant eco civ. Rathas are versatile. Weak cavalry otherwise.",
    },
    "Berbers": {
        "role": "pocket",
        "bonuses": [
            "Villagers move 10% faster",
            "Stable units cost 15% less in Feudal, 20% less in Castle+",
            "Ships move 10% faster",
            "Genitours available at Archery Range (Feudal)",
        ],
        "unique_units": ["Camel Archer (ranged camel)", "Genitour (skirmisher on horse)"],
        "unique_techs": [
            "Kasbah (Castle): Team Castles work 25% faster",
            "Maghrebi Camels (Imperial): Camel units regenerate HP",
        ],
        "missing_key": ["Plate Barding Armor"],
        "notes": "Cheap fast cavalry. Genitour is a strong team unit. Solid on open maps.",
    },
    "Bohemians": {
        "role": "flex",
        "bonuses": [
            "Mining technologies free",
            "Blacksmith and University technologies research simultaneously",
            "Hand Cannoneers and Hussite Wagons +1 range",
            "Monks +2 attack (can fight in melee)",
            "Fervor and Sanctity free",
        ],
        "unique_units": ["Hussite Wagon (mobile defensive siege)", "Houfnice (upgraded bombard cannon)"],
        "unique_techs": [
            "Wagenburg Tactics (Castle): Gunpowder units move 15% faster",
            "Hussite Reforms (Imperial): Monks and Monasteries use gold as if it were food",
        ],
        "missing_key": ["Paladin", "Bloodlines"],
        "notes": "Unique gunpowder civ with monk synergy. Strong on closed maps.",
    },
    "Britons": {
        "role": "flank",
        "bonuses": [
            "Foot archers (except Skirmishers) +1 range per Age from Castle Age (max +2)",
            "Archery Ranges work 20% faster",
            "Town Centers cost −50% wood after Feudal Age",
            "Shepherd gather food 25% faster",
        ],
        "unique_units": ["Longbowman (long-range archer)"],
        "unique_techs": [
            "Yeoman (Castle): Foot archers +1 range; Towers +2 attack",
            "Warwolf (Imperial): Trebuchets 100% accurate; splash damage",
        ],
        "missing_key": ["Cavalry Armor", "Hoardings", "Sappers"],
        "notes": "Premier archer civ. Extra range makes Longbows nearly untouchable vs melee.",
    },
    "Bulgarians": {
        "role": "pocket",
        "bonuses": [
            "Militia line upgrades free",
            "Blacksmith upgrades available one Age earlier",
            "Kreposts (mini-castles) can be built from Dark Age",
            "Town Centers built 50% faster",
        ],
        "unique_units": ["Konnik (cavalry that dismounts on death)"],
        "unique_techs": [
            "Stirrups (Castle): Cavalry attack 33% faster",
            "Bagains (Imperial): Militia line +5 melee armor",
        ],
        "missing_key": ["Arbalester", "Heavy Cavalry Archer", "Thumb Ring"],
        "notes": "Strong aggressive cavalry + militia civ. Stirrups Knight-line is dangerous.",
    },
    "Burgundians": {
        "role": "pocket",
        "bonuses": [
            "Economic upgrades available one Age earlier",
            "Cavalier upgrade available in Castle Age",
            "Flemish Militia trainable from Barracks in Feudal Age (30f/30g) — reworked 1.6",
            "Relics generate +33% gold",
        ],
        "unique_units": ["Coustillier (cavalry with charge attack)", "Flemish Militia (powerful infantry)"],
        "unique_techs": [
            "Burgundian Vineyards (Castle): 100 food → 75 gold (once per Age)",
            "Flemish Revolution (Imperial): All Villagers become Flemish Militia",
        ],
        "missing_key": ["Bracer", "Arbalester", "Halberdier"],
        "notes": "Eco-ahead civ. Early Cavalier is a huge timing threat. Flemish Revolution as panic button.",
    },
    "Burmese": {
        "role": "flex",
        "bonuses": [
            "Lumber Camp upgrades free",
            "Monks +50% sight range",
            "Elephants +1/+1 armor",
            "Manipur Cavalry: cavalry and Arambai +6 attack vs buildings",
        ],
        "unique_units": ["Arambai (ranged cavalry, low accuracy high damage)"],
        "unique_techs": [
            "Howdah (Castle): Battle Elephants +1/+1 armor",
            "Manipur Cavalry (Imperial): Cavalry and Arambai +6 attack vs buildings",
        ],
        "missing_key": ["Eagle Warrior", "Plate Mail Armor"],
        "notes": "Cheap wood upgrades. Arambai shreds buildings in groups. Good on closed maps.",
    },
    "Byzantines": {
        "role": "flex",
        "bonuses": [
            "Buildings have more HP per Age (+10/20/30/40%)",
            "Camel, Skirmisher, Spearman line cost −25%",
            "Monks heal 2x as fast",
            "Fire Ships attack 20% faster",
            "Imperial Age costs −33%",
        ],
        "unique_units": ["Cataphract (heavy cavalry anti-infantry)"],
        "unique_techs": [
            "Greek Fire (Castle): Fire Ships +1 range",
            "Logistica (Imperial): Cataphracts trample damage, +6 attack vs infantry",
        ],
        "missing_key": ["Paladin"],
        "notes": "Counter-unit specialists. Cheap counters make them dominant late game. Great on water.",
    },
    "Celts": {
        "role": "flank",
        "bonuses": [
            "Infantry move 15% faster",
            "Siege Workshops work 20% faster",
            "Lumberjacks work 15% faster",
            "Enemy sheep auto-convert when in LoS of Celtic unit",
        ],
        "unique_units": ["Woad Raider (fast infantry)"],
        "unique_techs": [
            "Stronghold (Castle): Castles and Towers fire 33% faster",
            "Furor Celtica (Imperial): Siege Workshop units +40% HP",
        ],
        "missing_key": ["Cavalry Archer", "Thumb Ring", "Hussar"],
        "notes": "Best siege civ. Fast infantry harass is strong early. Woad Raiders + siege is deadly.",
    },
    "Chinese": {
        "role": "flex",
        "bonuses": [
            "Start with +3 villagers but −200 food",
            "Technologies cost −10/15% in Castle/Imperial Age",
            "Demolition Ships +50% HP",
            "Farms produce 10% more food (team bonus)",
        ],
        "unique_units": ["Chu Ko Nu (fast-firing crossbow)"],
        "unique_techs": [
            "Great Wall (Castle): Stone Walls and Gates +30% HP",
            "Rocketry (Imperial): Chu Ko Nu +2 attack; Scorpions +4 attack",
        ],
        "missing_key": ["Plate Barding Armor"],
        "notes": "Strong early with extra vills. Cheap techs in late game. Chu Ko Nu excellent vs massed units.",
    },
    "Cumans": {
        "role": "pocket",
        "bonuses": [
            "TC and Siege Workshop can be built in Feudal Age",
            "Cavalry move 10% faster in Feudal/Castle; 5% faster in Imperial",
            "Steppe Lancers available; upgrade cost −50%",
            "Battering Rams available in Feudal Age",
        ],
        "unique_units": ["Kipchak (ranged cavalry, multi-arrow)"],
        "unique_techs": [
            "Steppe Husbandry (Castle): Cavalry Archers and Steppe Lancers train 50% faster",
            "Cuman Mercenaries (Imperial): Team gets 10 free Elite Kipchaks",
        ],
        "missing_key": ["Plate Barding Armor", "Paladin"],
        "notes": "Fastest cavalry in the game. Feudal TC is a strong eco move. Kipchaks melt infantry.",
    },
    "Dravidians": {
        "role": "flank",
        "bonuses": [
            "Fishermen work 10% faster and carry +15",
            "Barracks units +3 attack vs. archers",
            "Elephant Archers available at Archery Range",
            "Urumi Swordsman available from Dark Age",
        ],
        "unique_units": ["Urumi Swordsman (whip-chain infantry)", "Thirisadai (mega warship)"],
        "unique_techs": [
            "Medical Corps (Castle): Elephant units regenerate HP",
            "Wootz Steel (Imperial): Infantry and Cavalry attacks ignore armor",
        ],
        "missing_key": ["Plate Barding Armor", "Paladin", "Hussar"],
        "notes": "Infantry ignore-armor tech is very strong late game. Solid on water maps.",
    },
    "Ethiopians": {
        "role": "flank",
        "bonuses": [
            "Archer units +1 attack per Age from Feudal (max +3 in Imperial)",
            "Free Pikeman and Arbalester upgrades",
            "Each new Age: free 100 food + 100 gold",
            "Towers and Outposts fire 20% faster (team bonus)",
        ],
        "unique_units": ["Shotel Warrior (fast-training fragile infantry)"],
        "unique_techs": [
            "Royal Heirs (Castle): Shotel Warriors train in 6s",
            "Torsion Engines (Imperial): Siege Workshop units have wider splash",
        ],
        "missing_key": ["Plate Barding Armor", "Paladin", "Hussar"],
        "notes": "Best archer attack in the game. Age bonuses give eco lead. Free upgrades save a lot of gold.",
    },
    "Franks": {
        "role": "pocket",
        "bonuses": [
            "Cavalry +20% HP",
            "Farm upgrades free",
            "Foragers work 15% faster",
            "Castles cost −25%",
            "Cavalry Archers available one Age earlier (Castle Age: HCA already in Castle)",
        ],
        "unique_units": ["Throwing Axeman (short-range foot)"],
        "unique_techs": [
            "Bearded Axe (Castle): Throwing Axemen +1 range",
            "Chivalry (Imperial): Stables work 40% faster",
        ],
        "missing_key": ["Arbalester", "Thumb Ring", "Bracer"],
        "notes": "Best cavalry HP civ. Cheap Castles enable fast Castle timing. Top 1v1 pocket.",
    },
    "Georgians": {
        "role": "pocket",
        "bonuses": [
            "Cavalry regenerate HP: 2/8/14 HP/min per Age (Feudal/Castle/Imperial) — nerfed in patch 141935",
            "Buildings cost −15% stone",
            "Monks +10 HP for each Monastery tech researched",
            "Team bonus: Cavalry Archers +2 LoS",
        ],
        "unique_units": ["Monaspa (elite cavalry with charge)"],
        "unique_techs": [
            "Svan Towers (Castle): Towers +2 attack and garrison +5",
            "Aznauri Cavalry (Imperial): Cavalry get +1 attack per 3 relics held",
        ],
        "missing_key": ["Hussar", "Plate Barding Armor"],
        "notes": "Self-healing cavalry is powerful on maps with fighting. Regen nerfed from 5/10/15 to 2/8/14.",
    },
    "Goths": {
        "role": "flank",
        "bonuses": [
            "Infantry cost −20/25/30/35% per age (Dark/Feudal/Castle/Imperial) — reduced in recent patch",
            "Villagers +5 attack vs boars; Loom free",
            "+10 pop cap in Imperial Age",
            "Infantry +1 attack vs buildings (team bonus)",
        ],
        "unique_units": ["Huskarl (pierce-armor infantry)"],
        "unique_techs": [
            "Anarchy (Castle): Huskarls trainable from Barracks",
            "Perfusion (Imperial): Barracks work 100% faster",
        ],
        "missing_key": ["Cavalry (no cavalry upgrades past Feudal)", "Arbalester"],
        "notes": "Infantry flood civ. Discount reduced but still cheapest infantry. Huskarls counter archers.",
    },
    "Gurjaras": {
        "role": "pocket",
        "bonuses": [
            "Forage Bushes last 33% longer",
            "Camel Scouts available in Dark Age",
            "Cavalry take −10% damage from ranged attacks",
            "Mill and Lumber Camp technologies free (team bonus)",
        ],
        "unique_units": ["Shrivamsha Rider (dodges projectiles)", "Chakram Thrower (ranged infantry)"],
        "unique_techs": [
            "Kshatriyas (Castle): Military units −25% food cost",
            "Frontier Guards (Imperial): Camel Riders and Elephant Archers +4 melee armor",
        ],
        "missing_key": ["Paladin", "Plate Mail Armor"],
        "notes": "Shrivamsha dodge mechanic is strong vs archers. Cheap food military units.",
    },
    "Hindustani": {
        "role": "pocket",
        "bonuses": [
            "Villagers cost −10% per Age (max −40% in Imperial)",
            "Gunpowder units +1/+1 armor",
            "Camels +1 attack vs buildings (team bonus)",
            "Imperial Camel Rider available",
        ],
        "unique_units": ["Ghulam (anti-archer infantry)", "Imperial Camel Rider"],
        "unique_techs": [
            "Grand Trunk Road (Castle): Traders +25% gold",
            "Shatagni (Imperial): Hand Cannoneers +1 range",
        ],
        "missing_key": ["Halberdier", "Plate Mail Armor"],
        "notes": "Villager discount leads to pop-efficient eco. Camels are strong counters. Ghulam vs archer floods.",
    },
    "Huns": {
        "role": "pocket",
        "bonuses": [
            "No need to build Houses (never need houses)",
            "Cavalry Archers cost −10/20% in Castle/Imperial",
            "Trebuchets +33% accuracy",
            "Stables work 20% faster (team bonus)",
        ],
        "unique_units": ["Tarkan (cavalry anti-building)"],
        "unique_techs": [
            "Marauders (Castle): Tarkans can be trained at Stable",
            "Atheism (Imperial): +100 years wonder/relic victory; enemy relic gold −50%",
        ],
        "missing_key": ["Plate Mail Armor", "Halberdier"],
        "notes": "No houses = instant eco advantage. Best Cav Archer civ. Excellent pocket in team games.",
    },
    "Incas": {
        "role": "flex",
        "bonuses": [
            "Villagers +5 HP; Buildings +25% HP in Dark Age",
            "Farm upgrades free",
            "Barracks units +1/+1 armor per Age from Feudal",
            "Llama (extra herdable) at game start",
            "Houses support 10 pop",
        ],
        "unique_units": ["Kamayuk (spear infantry vs cavalry)", "Slinger (ranged anti-infantry)"],
        "unique_techs": [
            "Andean Sling (Castle): Slingers and Skirmishers +1 range, no min range",
            "Fabric Shields (Imperial): Kamayuks, Slingers, Eagles −3 pierce armor cost upgrade",
        ],
        "missing_key": ["Cavalry (no cavalry)", "Gold Shaft Mining"],
        "notes": "Strong eagles + kamayuks combo. Good defensive civ with cheap food.",
    },
    "Italians": {
        "role": "flex",
        "bonuses": [
            "Advancing in Age costs −15%",
            "Dock technologies cost −33%",
            "Fishing Ships cost −15%",
            "Gunpowder technologies cost −50%",
            "Foot archers and Condottieri +1/+1 armor (replaces Pavise in 1.6)",
        ],
        "unique_units": ["Genoese Crossbowman (anti-cavalry archer)", "Condottiero (fast imperial infantry)"],
        "unique_techs": [
            "Pavise removed in 1.6 (replaced by armor bonus)",
            "Silk Road (Imperial): Trade units cost −50%",
        ],
        "missing_key": ["Plate Mail Armor", "Hussar", "Paladin"],
        "notes": "Cheap ages + dock techs = good eco. Condottiero available to team allies. Anti-cav archer.",
    },
    "Japanese": {
        "role": "flank",
        "bonuses": [
            "Fishing Ships work 5/10/15% faster per Age",
            "Infantry attack 33% faster",
            "Mill, Lumber, Mining, and Dock work rates increased",
            "Galleys +50% LoS (team bonus)",
        ],
        "unique_units": ["Samurai (fast-attacking unique-unit counter)"],
        "unique_techs": [
            "Yasama (Castle): Towers fire extra arrows",
            "Kataparuto (Imperial): Trebuchets fire and pack 33% faster",
        ],
        "missing_key": ["Plate Barding Armor", "Hussar"],
        "notes": "Fast-attack infantry is terrifying in closed-range fights. Strong eco on water maps.",
    },
    "Khmer": {
        "role": "pocket",
        "bonuses": [
            "No buildings required for tech tree",
            "Villagers can garrison in houses",
            "Battle Elephants move 10% faster",
            "Scorpions +1 range (team bonus)",
        ],
        "unique_units": ["Ballista Elephant (mounted scorpion)"],
        "unique_techs": [
            "Tusk Swords (Castle): Battle Elephants +3 attack",
            "Double Crossbow (Imperial): Ballista Elephants fire two bolts",
        ],
        "missing_key": ["Plate Mail Armor", "Thumb Ring"],
        "notes": "No building pre-reqs = fast aging. Ballista Elephants are devastating AoE damage dealers.",
    },
    "Koreans": {
        "role": "flex",
        "bonuses": [
            "Stone Miners work 20% faster",
            "Towers cost −25% wood; Guard and Keep free",
            "Archers and Skirmishers +1 LoS",
            "Mangonel minimum range eliminated",
            "Villagers +3 LoS (team bonus)",
        ],
        "unique_units": ["War Wagon (heavy ranged cavalry)", "Turtle Ship (armored war ship)"],
        "unique_techs": [
            "Eupseong (Castle): Towers and Castles +2 range",
            "Shinkichon (Imperial): Mangonels +1 range",
        ],
        "missing_key": ["Plate Barding Armor", "Paladin"],
        "notes": "Strong tower rushing and defensive play. War Wagons are tanky. Dominant on water.",
    },
    "Lithuanians": {
        "role": "pocket",
        "bonuses": [
            "Start with +150 food",
            "Monastery technologies research 20% faster",
            "Spearman line +1 attack per 2 relics held",
            "Cavalry +1 attack per relic held (max +4)",
        ],
        "unique_units": ["Leitis (cavalry that ignores armor)"],
        "unique_techs": [
            "Hill Forts (Castle): TCs +3 range",
            "Tower Shields (Imperial): Spearman line +2 pierce armor",
        ],
        "missing_key": ["Plate Barding Armor", "Arbalester"],
        "notes": "Relic cavalry bonus is powerful. Leitis ignores melee armor. Food start = fast Feudal.",
    },
    "Magyars": {
        "role": "pocket",
        "bonuses": [
            "Scout Cavalry and Hussars cost 15% less",
            "Forging, Iron Casting, Blast Furnace free",
            "Hungarian Tactics: free attack upgrades for Cavalry Archers",
            "Villagers +2 attack vs boar",
        ],
        "unique_units": ["Magyar Huszar (cheap fast cavalry)"],
        "unique_techs": [
            "Corvinian Army (Castle): Magyar Huszars cost −15 gold",
            "Recurve Bow (Imperial): Cavalry Archers +1 range, +1 attack",
        ],
        "missing_key": ["Plate Barding Armor"],
        "notes": "Free blacksmith techs = huge gold savings. Cheap scouts + Magyar Huszar = strong raiding.",
    },
    "Malians": {
        "role": "flex",
        "bonuses": [
            "Gold Miners work 10% faster",
            "Buildings cost −15% wood",
            "Farimba: cavalry +5 attack",
            "Infantry +1 pierce armor per Age from Feudal (team bonus)",
        ],
        "unique_units": ["Gbeto (fragile but fast throwing-women infantry)"],
        "unique_techs": [
            "Tigui (Castle): TCs fire arrows without garrison",
            "Farimba (Imperial): Cavalry +5 attack",
        ],
        "missing_key": ["Arbalester", "Bracer"],
        "notes": "Cheap buildings = fast walling. Gold efficiency is great. Cavalry gets huge attack bonus.",
    },
    "Malay": {
        "role": "flex",
        "bonuses": [
            "Age Advance costs −66% food",
            "Battle Elephants cost −30%",
            "Docks cost −33%",
            "Fish Traps work 2x; cost nothing to build",
            "Harbors available",
        ],
        "unique_units": ["Karambit Warrior (1 pop cheapest unit)", "Harbor (building/unit hybrid)"],
        "unique_techs": [
            "Thalassocracy (Castle): Docks become Harbors (+2 attack)",
            "Forced Levy (Imperial): Militia line gold cost → food (0 gold)",
        ],
        "missing_key": ["Plate Barding Armor", "Paladin"],
        "notes": "Fastest aging civ by food. Forced Levy + Karambits = zero-gold spam. Dominant on water.",
    },
    "Mayans": {
        "role": "flank",
        "bonuses": [
            "Start with +1 Eagle Scout",
            "Resources last 15% longer",
            "Archery Range units cost −10/15/20% per Age",
            "El Dorado: Eagle Warriors +40 HP",
        ],
        "unique_units": ["Plumed Archer (fast cheap archer)"],
        "unique_techs": [
            "Obsidian Arrows (Castle): Archers +6 attack vs buildings",
            "El Dorado (Imperial): Eagle Warriors +40 HP",
        ],
        "missing_key": ["Cavalry (no cavalry)", "Gold Shaft Mining"],
        "notes": "Best archer eco civ. Cheap archers last the whole game. El Dorado Eagles are unstoppable.",
    },
    "Mongols": {
        "role": "flank",
        "bonuses": [
            "Cavalry Archers fire 25% faster",
            "Light Cavalry and Hussars +30% HP",
            "Shepherds work 50% faster",
            "Scout Cavalry LoS doubled in Dark Age",
        ],
        "unique_units": ["Mangudai (anti-siege cavalry archer)"],
        "unique_techs": [
            "Nomads (Castle): Houses not required; existing houses grant +5 pop when destroyed",
            "Drill (Imperial): Siege Workshop units move 50% faster",
        ],
        "missing_key": ["Plate Mail Armor", "Halberdier"],
        "notes": "Best Cav Archer + Hussars. Mobile siege. Drill makes Siege Rams terrifying.",
    },
    "Persians": {
        "role": "pocket",
        "bonuses": [
            "Start with +50 food and +50 wood",
            "Town Centers and Docks work 10/15/20% faster per Age",
            "Knights and Cavaliers +2 attack vs archers (team bonus)",
        ],
        "unique_units": ["War Elephant (massive tanky elephant)"],
        "unique_techs": [
            "Kamandaran (Castle): Archers cost no wood (only gold)",
            "Mahouts (Imperial): War Elephants move 30% faster",
        ],
        "missing_key": ["Halberdier"],
        "notes": "Fastest TC/Dock = best booming civ. War Elephants win in deathball. Top pocket pick.",
    },
    "Poles": {
        "role": "pocket",
        "bonuses": [
            "Folwark (replaces Mill) collects food from nearby farms",
            "Stone → Gold conversion: 75 stone = 100 gold (free Villager builds, converts at Folwark)",
            "Cavalry +1 attack per age (Feudal Castle Imperial)",
            "Scouts regenerate HP (team bonus)",
        ],
        "unique_units": ["Obuch (infantry that removes enemy armor)", "Winged Hussar (upgrade of Hussar)"],
        "unique_techs": [
            "Szlachta Privileges (Castle): Knight line −60% gold cost",
            "Lechitic Legacy (Imperial): Light cavalry deal small trample damage",
        ],
        "missing_key": ["Plate Mail Armor"],
        "notes": "Folwark eco is extremely strong. Cheap Knights in Castle Age. Obuch is a support unit.",
    },
    "Portuguese": {
        "role": "flex",
        "bonuses": [
            "All units cost −20% gold",
            "Technologies research 30% faster",
            "Ships have +10% HP",
            "Feitoria available (passively generates resources)",
        ],
        "unique_units": ["Organ Gun (multi-shot siege)", "Caravel (ship with splash projectile)"],
        "unique_techs": [
            "Carrack (Castle): Ships +1/+1 armor",
            "Arquebus (Imperial): Gunpowder units hit moving targets accurately",
        ],
        "missing_key": ["Hussars", "Paladin"],
        "notes": "Tech speed is great for boom. Gold discount makes late game strong. Best water civ with Caravel.",
    },
    "Romans": {
        "role": "flank",
        "bonuses": [
            "Legionary (replaces Man-at-Arms and up) available — upgrades overlap with militia line",
            "Barracks and Stable technologies cost −20%",
            "Town Centers support 10 pop each",
            "Legionary units have bonus armor vs. archers and rams",
        ],
        "unique_units": ["Legionary (heavy infantry with bonus armor)"],
        "unique_techs": [
            "Ballistas (Castle): Scorpions and Ballistas +1 range",
            "Comitatenses (Imperial): Legionaries +8 HP",
        ],
        "missing_key": ["Cavalry Archer", "Hussar"],
        "notes": "Infantry specialists with TC pop bonus. Legionary is a strong alternative to Champions.",
    },
    "Saracens": {
        "role": "flex",
        "bonuses": [
            "Market trade costs only 5%",
            "Archers +3 attack vs buildings",
            "Camels have +10 HP (team bonus)",
            "Transport Ships 2x HP, 2x carry capacity",
        ],
        "unique_units": ["Mameluke (ranged anti-cavalry camel)"],
        "unique_techs": [
            "Madrasah (Castle): 33% of Monk gold cost returned when he dies",
            "Zealotry (Imperial): Camel Riders and Mamelukes +30 HP",
        ],
        "missing_key": ["Hussar"],
        "notes": "Best market eco. Mamelukes hard-counter cavalry. Great on mixed/water maps.",
    },
    "Sicilians": {
        "role": "pocket",
        "bonuses": [
            "Town Centers and Castles built 100% faster",
            "First Crusade: each TC spawns 7 Serjeants (Imperial Age)",
            "Cavalry and Infantry take −33% damage from bonus damage",
            "Farm upgrades give +75% yield (instead of +50%)",
        ],
        "unique_units": ["Serjeant (infantry that can build Donjons)"],
        "unique_techs": [
            "Scutage (Castle): Each TC pays 15 gold tribute per enemy Knight-line unit",
            "First Crusade (Imperial): Spawn Serjeants; team Serjeant HP +50",
        ],
        "missing_key": ["Plate Barding Armor", "Hussar"],
        "notes": "Fastest TC/Castle build. Bonus damage resistance makes cavalry/infantry very tanky.",
    },
    "Slavs": {
        "role": "pocket",
        "bonuses": [
            "Farmers work 10% faster",
            "Siege Workshop units cost −15%",
            "Boyar (knight-line replacement) available",
            "Military units created at Docks 10% faster (team bonus)",
        ],
        "unique_units": ["Boyar (high melee armor cavalry)"],
        "unique_techs": [
            "Detinets (Castle): Enemy buildings blocked from within 4 tiles of a friendly building",
            "Druzhina (Imperial): Infantry deal trample damage",
        ],
        "missing_key": ["Arbalester", "Thumb Ring"],
        "notes": "Strongest Boyar in the game for tanking. Cheap siege + farm bonus = booming powerhouse.",
    },
    "Spanish": {
        "role": "flex",
        "bonuses": [
            "Builders work 30% faster",
            "Trade units generate +25% more gold",
            "Missionaries available (mounted Monks)",
            "Cannon Galleons fire with no ballistics delay (team bonus)",
        ],
        "unique_units": ["Conquistador (mounted hand cannoneer)", "Missionary (mounted Monk)"],
        "unique_techs": [
            "Inquisition (Castle): Monks convert faster",
            "Supremacy (Imperial): Villagers +6 attack, +4 armor combat stats",
        ],
        "missing_key": ["Bloodlines", "Hussar"],
        "notes": "Fast buildings + trade bonus. Conquistadors are powerful hit-and-run cavalry.",
    },
    "Tatars": {
        "role": "pocket",
        "bonuses": [
            "Flocks spawn on Steppe Lancers (own units bring food)",
            "Cavalry Archers +2 attack from high ground",
            "Sheep provide +50% food",
            "Cavalry Archers fire 10% faster (team bonus)",
        ],
        "unique_units": ["Keshik (cavalry that generates gold on attack)", "Flaming Camel (suicide unit)"],
        "unique_techs": [
            "Silk Armor (Castle): Scout Cavalry, Cav Archers, Steppe Lancers +1/+1 armor",
            "Timurid Siegecraft (Imperial): Trebuchets +2 range; Flaming Camels available",
        ],
        "missing_key": ["Plate Mail Armor", "Halberdier"],
        "notes": "High-ground bonus makes maps with hills very strong. Keshik generates gold. Top Cav Archer civ.",
    },
    "Teutons": {
        "role": "pocket",
        "bonuses": [
            "Monks +15 HP (Teutonic Knights have 100/110 HP — buffed in 1.6)",
            "Towers garrison 2x units; Towers +1 range",
            "Murder Holes free; Herbal Medicine free",
            "Farms built 40% faster; cost −40% in late game",
            "Conversion resistance (units resist 4x longer)",
        ],
        "unique_units": ["Teutonic Knight (ultra-tanky slow melee infantry)"],
        "unique_techs": [
            "Ironclad (Castle): Siege Workshop units +4 melee armor",
            "Crenellations (Imperial): Castles garrison 2x; garrisoned infantry fire arrows",
        ],
        "missing_key": ["Hoardings", "Thumb Ring", "Bloodlines"],
        "notes": "Best defensive civ. Conversion resistance + tanky TK = excellent pocket. Farms are free late.",
    },
    "Turkish": {
        "role": "pocket",
        "bonuses": [
            "Gunpowder units have +25% HP",
            "Gold Miners work 15% faster",
            "Chemistry free",
            "Light Cavalry and Hussar upgrades free",
            "Scouts +1 attack (team bonus)",
        ],
        "unique_units": ["Janissary (powerful Hand Cannoneer)"],
        "unique_techs": [
            "Sipahi (Castle): Cavalry Archers and Janissaries +20 HP",
            "Artillery (Imperial): Bombard Towers, Bombard Cannons, Cannon Galleons +2 range",
        ],
        "missing_key": ["Halberdier", "Arbalester", "Plate Mail Armor"],
        "notes": "Free Chemistry = gunpowder spam. Free Hussar = infinite raider. Free gold upgrades.",
    },
    "Vietnamese": {
        "role": "flank",
        "bonuses": [
            "Reveal enemy positions at game start",
            "Archery Range units +20% HP",
            "Imperial Skirmisher upgrade available",
            "Eco upgrades free",
        ],
        "unique_units": ["Rattan Archer (high pierce armor archer)", "Imperial Skirmisher"],
        "unique_techs": [
            "Chatras (Castle): Battle Elephants +50 HP",
            "Paper Money (Imperial): Team gets 500 gold tribute",
        ],
        "missing_key": ["Plate Barding Armor", "Hussar", "Paladin"],
        "notes": "Free eco upgrades = boom powerhouse. Rattan Archers are tanky vs ranged. Good reveal power.",
    },
    "Vikings": {
        "role": "flex",
        "bonuses": [
            "Warships cost −20%",
            "Infantry have +10/15/20% HP per Age",
            "Wheelbarrow and Hand Cart free",
            "Berserks and Longboats available",
        ],
        "unique_units": ["Berserk (self-healing infantry)", "Longboat (multi-arrow ship)"],
        "unique_techs": [
            "Chieftains (Castle): Infantry +5 attack vs cavalry and camel",
            "Berserkergang (Imperial): Berserks regenerate faster",
        ],
        "missing_key": ["Paladin", "Bracer"],
        "notes": "Free hand cart = strongest eco boom. Berserks are excellent with regen. Top water civ.",
    },
}

# Quick-access sets for !has command
FLANK_CIVS = [c for c, d in CIVS.items() if d["role"] == "flank"]
POCKET_CIVS = [c for c, d in CIVS.items() if d["role"] == "pocket"]
FLEX_CIVS = [c for c, d in CIVS.items() if d["role"] == "flex"]

# ─────────────────────────────────────────────────────────────────────────────
# TECH/UNIT ACCESS MAP  (for !has command)
# ─────────────────────────────────────────────────────────────────────────────
TECH_UNIT_MAP = {
    "paladin":          ["Franks", "Lithuanians", "Persians", "Bulgarians", "Teutons",
                         "Celts", "Berbers", "Tatars", "Mongols", "Slavs", "Poles",
                         "Georgians", "Armenians", "Sicilians", "Byzantines", "Cumans"],
    "hussar":           ["Huns", "Turks", "Lithuanians", "Franks", "Mongols", "Poles",
                         "Cumans", "Bulgarians", "Tatars", "Berbers", "Malians", "Slavs",
                         "Georgians", "Celts"],
    "halberdier":       ["Aztecs", "Britons", "Celts", "Chinese", "Ethiopians", "Goths",
                         "Incas", "Italians", "Japanese", "Koreans", "Malians", "Mayans",
                         "Mongols", "Portuguese", "Saracens", "Spanish", "Teutons",
                         "Vietnamese", "Vikings", "Armenians", "Georgians", "Bohemians",
                         "Poles", "Dravidians", "Romans"],
    "arbalester":       ["Britons", "Celts", "Chinese", "Ethiopians", "Franks", "Huns",
                         "Incas", "Japanese", "Khmer", "Koreans", "Malians", "Mayans",
                         "Mongols", "Persians", "Portuguese", "Saracens", "Slavs",
                         "Spanish", "Vikings", "Teutons", "Byzantines", "Lithuanians",
                         "Armenians", "Georgians", "Bohemians", "Dravidians", "Romans"],
    "heavy cavalry archer": ["Mongols", "Huns", "Turks", "Tatars", "Cumans", "Lithuanians",
                              "Berbers", "Ethiopians", "Bulgarians", "Khmer", "Magyars",
                              "Vietnamese", "Armenians", "Georgians"],
    "elite skirmisher": list(CIVS.keys()),  # All civs
    "thumbring":        ["Britons", "Ethiopians", "Mongols", "Mayans", "Huns", "Turks",
                          "Celts", "Persians", "Bulgarians", "Chinese", "Berbers",
                          "Cumans", "Tatars", "Vietnamese", "Armenians", "Bohemians"],
    "bloodlines":       ["Franks", "Huns", "Persians", "Teutons", "Lithuanians",
                          "Berbers", "Bulgarians", "Cumans", "Tatars", "Poles",
                          "Georgians", "Armenians", "Sicilians", "Magyars", "Malians",
                          "Slavs", "Portuguese", "Spanish", "Japanese"],
    "bracer":           ["Britons", "Celts", "Ethiopians", "Koreans", "Mayans",
                          "Mongols", "Vietnamese", "Chinese", "Japanese", "Tatars",
                          "Persians", "Saracens", "Huns", "Turks", "Lithuanians",
                          "Armenians", "Dravidians", "Romans"],
    "supplies":         [],  # Removed from 1.6; Militia line now baseline 50f/20g
    "plate mail armor": ["Aztecs", "Britons", "Celts", "Chinese", "Ethiopians",
                          "Franks", "Goths", "Incas", "Italians", "Japanese",
                          "Koreans", "Lithuanians", "Magyars", "Malians", "Mayans",
                          "Portuguese", "Romans", "Saracens", "Slavs", "Spanish",
                          "Teutons", "Turkish", "Vikings", "Bohemians", "Poles",
                          "Dravidians", "Sicilians", "Armenians", "Georgians"],
    "siege onager":     ["Celts", "Chinese", "Franks", "Huns", "Koreans", "Mongols",
                          "Slavs", "Teutons", "Turkish", "Vikings", "Byzantines",
                          "Persians", "Armenians", "Georgians", "Bohemians", "Romans"],
    "siege ram":        ["Aztecs", "Bulgarians", "Celts", "Chinese", "Ethiopians",
                          "Franks", "Goths", "Huns", "Incas", "Japanese", "Khmer",
                          "Koreans", "Lithuanians", "Malians", "Mayans", "Mongols",
                          "Persians", "Portuguese", "Saracens", "Slavs", "Spanish",
                          "Teutons", "Turkish", "Vietnamese", "Vikings", "Armenians",
                          "Georgians", "Bohemians", "Poles"],
    "eagle warrior":    ["Aztecs", "Incas", "Mayans"],
    "condottiero":      ["Italians", "Byzantines", "Portuguese", "Spanish", "Berbers",
                          "Sicilians", "Bohemians"],  # team bonus: all Italian allies
    "leitis":           ["Lithuanians"],
    "mangudai":         ["Mongols"],
    "longbowman":       ["Britons"],
    "cataphract":       ["Byzantines"],
    "huskarl":          ["Goths"],
    "war elephant":     ["Persians"],
    "throwing axeman":  ["Franks"],
    "samurai":          ["Japanese"],
    "plumed archer":    ["Mayans"],
    "woad raider":      ["Celts"],
    "jaguar warrior":   ["Aztecs"],
    "tarkan":           ["Huns"],
    "boyar":            ["Slavs"],
    "magyar huszar":    ["Magyars"],
    "teutonic knight":  ["Teutons"],
    "janissary":        ["Turkish"],
}

# ─────────────────────────────────────────────────────────────────────────────
# COUNTER DATA  (for !counter command)
# ─────────────────────────────────────────────────────────────────────────────
COUNTERS = {
    "knight": {
        "hard": ["Halberdier", "Camel Rider", "Leitis (ignores armor)"],
        "soft": ["Skirmisher mass", "Monk", "Mangonels vs groups"],
        "note": "Knights beat archers and infantry 1v1. Spread them vs Halbs to avoid pathing trample.",
    },
    "archer": {
        "hard": ["Skirmisher", "Eagle Warrior", "Huskarl", "Man-at-Arms"],
        "soft": ["Scout rush", "Cavalry into archers", "Siege (Mangonel)"],
        "note": "Archers die to Skirmishers at equal resources every time. Mangonels zone them.",
    },
    "skirmisher": {
        "hard": ["Archer / Crossbow", "Cavalry", "Siege"],
        "soft": ["Eagle Warriors", "Infantry"],
        "note": "Skirmishers are purely reactive. They lose badly to archers and cavalry.",
    },
    "mangonel": {
        "hard": ["Cavalry", "Onager (counter-siege)", "Monks", "Hussar rush"],
        "soft": ["Spaced-out infantry", "Ranged units at long range"],
        "note": "Always flank Mangonels with cavalry. They devastate massed units.",
    },
    "trebuchet": {
        "hard": ["Mangudai", "Hussar", "Eagle Warriors", "Monks"],
        "soft": ["Archers at range", "Counter-trebuchet"],
        "note": "Treb must pack/unpack. Fast moving units snipe them before they fire.",
    },
    "war elephant": {
        "hard": ["Halberdier spam", "Monks", "Flaming Camel"],
        "soft": ["Mangonels (trample splash)", "Ranged units kiting"],
        "note": "Slow movement is the weakness. Block retreat with cheap units, convert with monks.",
    },
    "hussar": {
        "hard": ["Halberdier", "Camel Rider"],
        "soft": ["Massed archers", "Scorpions"],
        "note": "Hussars are raiders. Don't mass vs them — block with Halbs, deny with walls.",
    },
    "camel": {
        "hard": ["Halberdier", "Archer mass", "Infantry"],
        "soft": ["Skirmishers", "Monks"],
        "note": "Camels beat cavalry but lose to everything else. Halbs are the best cost-efficient answer.",
    },
    "eagle warrior": {
        "hard": ["Archer / Crossbow", "Skirmisher", "Cavalry"],
        "soft": ["Infantry", "Monks"],
        "note": "Eagles die fast to archers. Use Skirms or Knights to shut them down.",
    },
    "monk": {
        "hard": ["Fast units (Hussar, Eagle)", "Relics denial", "Heresy tech"],
        "soft": ["Spread out units", "Archers at range"],
        "note": "Monks convert instantly at close range. Kill them before they reach your army.",
    },
    "scorpion": {
        "hard": ["Cavalry", "Monks", "Hussars"],
        "soft": ["Spread infantry", "Ranged units"],
        "note": "Scorpions fire in a line. Spread your units horizontally. Cavalry bypass/flank them.",
    },
    "bombard cannon": {
        "hard": ["Hussars (fastest approach)", "Mangudai", "Trebuchet"],
        "soft": ["Siege Rams (absorb shots)", "Counter-siege"],
        "note": "High damage vs buildings but slow. Fast cavalry snipe them before reload.",
    },
    "crossbow": {
        "hard": ["Skirmisher", "Cavalry", "Mangonel"],
        "soft": ["Woad Raider", "Man-at-Arms mass"],
        "note": "Crossbows are the bread-and-butter of Feudal/Castle. Counter with Skirms or cav.",
    },
    "ram": {
        "hard": ["Cavalry (ignores garrison)", "Mangonels", "Monks"],
        "soft": ["Infantry", "Town Center fire"],
        "note": "Ram pushes must be met with cavalry + TC fire. Monks can snag unguarded rams.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# DRAFT SYSTEM
# ─────────────────────────────────────────────────────────────────────────────
# Format:
#   MAP PHASE:   Cap1 bans 2, Cap2 bans 2, snake pick (Cap1 picks 1)
#   CIV PHASE:   6 alternating bans (3 each), then each captain picks 1 civ
# ─────────────────────────────────────────────────────────────────────────────

DRAFT_PHASE_MAP = [
    ("ban", 0),   # Cap1 bans a map
    ("ban", 1),   # Cap2 bans a map
    ("ban", 0),   # Cap1 bans a map
    ("ban", 1),   # Cap2 bans a map
    ("pick", 0),  # Cap1 picks the map (snake: first pick goes to first banner)
]

DRAFT_PHASE_CIV = [
    ("ban", 0),   # Cap1 bans civ
    ("ban", 1),   # Cap2 bans civ
    ("ban", 0),
    ("ban", 1),
    ("ban", 0),
    ("ban", 1),
    ("pick", 0),  # Cap1 picks civ
    ("pick", 1),  # Cap2 picks civ
]

# Active draft sessions keyed by message id
draft_sessions: dict[int, dict] = {}


def build_draft_embed(session: dict) -> discord.Embed:
    phase = session["phase"]  # "map" or "civ"
    step  = session["step"]
    cap0  = session["captains"][0]
    cap1  = session["captains"][1]

    sequence = DRAFT_PHASE_MAP if phase == "map" else DRAFT_PHASE_CIV
    action, actor_idx = sequence[step] if step < len(sequence) else ("done", -1)

    actor = session["captains"][actor_idx] if actor_idx >= 0 else None
    title = "🗺️ Map Draft" if phase == "map" else "⚔️ Civ Draft"
    color = C_DRAFT

    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="Captain 1", value=cap0.display_name, inline=True)
    embed.add_field(name="Captain 2", value=cap1.display_name, inline=True)

    bans_m  = session.get("map_bans",  [])
    picks_m = session.get("map_picks", [])
    bans_c  = session.get("civ_bans",  [])
    picks_c = session.get("civ_picks", {})

    if bans_m:
        embed.add_field(name="🚫 Map Bans",  value=", ".join(bans_m),  inline=False)
    if picks_m:
        embed.add_field(name="✅ Map Picked", value=picks_m[0],        inline=False)
    if bans_c:
        embed.add_field(name="🚫 Civ Bans",  value=", ".join(bans_c),  inline=False)
    for cap_name, civ in picks_c.items():
        embed.add_field(name=f"✅ {cap_name}'s Civ", value=civ,        inline=True)

    if action == "done":
        embed.set_footer(text="Draft complete!")
    else:
        verb = "BAN" if action == "ban" else "PICK"
        obj  = "a MAP" if phase == "map" else "a CIV"
        embed.set_footer(text=f"➡️  {actor.display_name}: {verb} {obj}")

    return embed


class DraftSelectView(discord.ui.View):
    """Shows paginated buttons for banning/picking a map or civ."""

    def __init__(self, session: dict, options: list[str], action: str, actor: discord.Member):
        super().__init__(timeout=120)
        self.session = session
        self.actor   = actor
        self.action  = action   # "ban" or "pick"
        self.options  = options
        self.page    = 0
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        start = self.page * 20
        chunk = self.options[start:start + 20]
        for name in chunk:
            btn = discord.ui.Button(
                label=name[:80],
                style=discord.ButtonStyle.danger if self.action == "ban" else discord.ButtonStyle.success,
                custom_id=f"draft_{name}",
            )
            btn.callback = self._make_callback(name)
            self.add_item(btn)

        if len(self.options) > 20:
            if self.page > 0:
                prev_btn = discord.ui.Button(label="◀ Prev", style=discord.ButtonStyle.secondary)
                prev_btn.callback = self._prev_page
                self.add_item(prev_btn)
            if start + 20 < len(self.options):
                next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
                next_btn.callback = self._next_page
                self.add_item(next_btn)

    def _make_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.actor.id:
                await interaction.response.send_message(
                    "❌ It's not your turn to pick/ban.", ephemeral=True
                )
                return

            session = self.session
            phase   = session["phase"]
            step    = session["step"]

            if phase == "map":
                sequence = DRAFT_PHASE_MAP
                action, _ = sequence[step]
                if action == "ban":
                    session["map_bans"].append(choice)
                    session["map_pool"].remove(choice)
                else:
                    session["map_picks"].append(choice)
                session["step"] += 1
                # Advance to civ phase if map phase done
                if session["step"] >= len(DRAFT_PHASE_MAP):
                    session["phase"] = "civ"
                    session["step"]  = 0
                    await interaction.response.edit_message(
                        embed=build_draft_embed(session),
                        view=make_draft_view(session),
                    )
                    return
            else:
                sequence = DRAFT_PHASE_CIV
                action, actor_idx = sequence[step]
                if action == "ban":
                    session["civ_bans"].append(choice)
                    session["civ_pool"].remove(choice)
                else:
                    cap_name = session["captains"][actor_idx].display_name
                    session["civ_picks"][cap_name] = choice
                    session["civ_pool"].remove(choice)
                session["step"] += 1

            embed = build_draft_embed(session)

            if (phase == "civ" and session["step"] >= len(DRAFT_PHASE_CIV)) or \
               (phase == "map" and session["step"] >= len(DRAFT_PHASE_MAP) and session["phase"] == "map"):
                # Done
                await interaction.response.edit_message(embed=embed, view=None)
                return

            new_view = make_draft_view(session)
            await interaction.response.edit_message(embed=embed, view=new_view)
        return callback

    async def _prev_page(self, interaction: discord.Interaction):
        self.page -= 1
        self._build_buttons()
        await interaction.response.edit_message(view=self)

    async def _next_page(self, interaction: discord.Interaction):
        self.page += 1
        self._build_buttons()
        await interaction.response.edit_message(view=self)


def make_draft_view(session: dict) -> discord.ui.View | None:
    phase    = session["phase"]
    step     = session["step"]
    sequence = DRAFT_PHASE_MAP if phase == "map" else DRAFT_PHASE_CIV

    if step >= len(sequence):
        return None

    action, actor_idx = sequence[step]
    actor   = session["captains"][actor_idx]
    pool    = session["map_pool"] if phase == "map" else session["civ_pool"]

    return DraftSelectView(session, list(pool), action, actor)


@bot.command(name="draft")
async def draft(ctx: commands.Context, cap1: discord.Member = None, cap2: discord.Member = None):
    """!draft @player1 @player2 — Start a captains draft."""
    if cap1 is None or cap2 is None:
        await ctx.send("Usage: `!draft @Captain1 @Captain2`")
        return
    if cap1 == cap2:
        await ctx.send("❌ Captains must be two different players.")
        return

    civ_pool = list(CIVS.keys())
    random.shuffle(civ_pool)

    session = {
        "captains":  [cap1, cap2],
        "phase":     "map",
        "step":      0,
        "map_pool":  list(DRAFT_MAP_POOL),
        "map_bans":  [],
        "map_picks": [],
        "civ_pool":  civ_pool,
        "civ_bans":  [],
        "civ_picks": {},
    }

    embed = build_draft_embed(session)
    view  = make_draft_view(session)
    msg   = await ctx.send(embed=embed, view=view)
    draft_sessions[msg.id] = session


# ─────────────────────────────────────────────────────────────────────────────
# TEAMS COMMAND
# ─────────────────────────────────────────────────────────────────────────────

# Track active team voice channels for !reset
team_channels: dict[int, list[int]] = {}  # guild_id → [vc_id, vc_id]

@bot.command(name="teams")
async def teams(ctx: commands.Context):
    """!teams — Split voice channel into two teams with roles and civs, auto-move to Team VCs."""
    if ctx.author.voice is None:
        await ctx.send("❌ You must be in a voice channel to use `!teams`.")
        return

    vc = ctx.author.voice.channel
    members = [m for m in vc.members if not m.bot]

    if len(members) < 2:
        await ctx.send("❌ Need at least 2 players in the voice channel.")
        return
    if len(members) % 2 != 0:
        await ctx.send(f"⚠️ Odd number of players ({len(members)}). One player will sit out.")
        members = members[:-1]

    team_size = len(members) // 2
    random.shuffle(members)
    team1 = members[:team_size]
    team2 = members[team_size:]

    def assign_roles_and_civs(team: list[discord.Member]):
        result = []
        half = len(team) // 2 if len(team) > 1 else 1
        for i, m in enumerate(team):
            if len(team) == 1:
                role = "Pocket"
            elif i < half:
                role = "Flank"
            else:
                role = "Pocket"

            if role == "Flank":
                civ = random.choice(FLANK_CIVS + FLEX_CIVS)
            else:
                civ = random.choice(POCKET_CIVS + FLEX_CIVS)
            result.append((m, role, civ))
        return result

    t1_assigned = assign_roles_and_civs(team1)
    t2_assigned = assign_roles_and_civs(team2)

    def fmt_team(team_data):
        lines = []
        for member, role, civ in team_data:
            icon = "🏹" if role == "Flank" else "🐴"
            lines.append(f"{icon} **{member.display_name}** — {role} → {civ}")
        return "\n".join(lines)

    embed = discord.Embed(title="⚔️ Teams", color=C_TEAMS)
    embed.add_field(name="🔵 Team 1", value=fmt_team(t1_assigned), inline=False)
    embed.add_field(name="🔴 Team 2", value=fmt_team(t2_assigned), inline=False)
    embed.set_footer(text="Moving players to Team VCs... create 'Team 1' and 'Team 2' voice channels if absent.")

    await ctx.send(embed=embed)

    # Try to move players into Team 1 / Team 2 voice channels
    guild = ctx.guild
    t1_vc = discord.utils.get(guild.voice_channels, name="Team 1")
    t2_vc = discord.utils.get(guild.voice_channels, name="Team 2")

    created = []
    if t1_vc is None:
        t1_vc = await guild.create_voice_channel("Team 1", category=vc.category)
        created.append(t1_vc.id)
    if t2_vc is None:
        t2_vc = await guild.create_voice_channel("Team 2", category=vc.category)
        created.append(t2_vc.id)

    # Accumulate rather than overwrite, so a !teams re-run before !lobby
    # doesn't forget channels created by an earlier run.
    team_channels.setdefault(guild.id, []).extend(created)

    errors = []
    for member, _, _ in t1_assigned:
        try:
            await member.move_to(t1_vc)
        except Exception:
            errors.append(member.display_name)

    for member, _, _ in t2_assigned:
        try:
            await member.move_to(t2_vc)
        except Exception:
            errors.append(member.display_name)

    if errors:
        await ctx.send(f"⚠️ Could not move: {', '.join(errors)} (they may have left VC).")
    else:
        await ctx.send("✅ Players moved to their team channels. Type `!lobby` when the game ends to bring everyone back.")


async def _move_to_lobby(guild: discord.Guild) -> tuple[int, str]:
    """
    Shared helper: move everyone from Team 1 / Team 2 back to Lobby/General,
    delete channels this session created. Returns (moved_count, lobby_name).
    """
    lobby = (
        discord.utils.get(guild.voice_channels, name="Lobby")
        or discord.utils.get(guild.voice_channels, name="General")
    )
    if lobby is None:
        return -1, ""

    moved = 0
    for vc in list(guild.voice_channels):
        if vc.name not in ("Team 1", "Team 2"):
            continue
        for member in list(vc.members):
            try:
                await member.move_to(lobby)
                moved += 1
            except Exception:
                pass
        created = team_channels.get(guild.id, [])
        if vc.id in created:
            try:
                await vc.delete(reason="!lobby cleanup")
            except Exception:
                pass

    team_channels.pop(guild.id, None)
    return moved, lobby.name


@bot.command(name="lobby")
async def lobby_cmd(ctx: commands.Context):
    """!lobby — Move all players from Team 1 / Team 2 back to Lobby and delete temp channels."""
    moved, name = await _move_to_lobby(ctx.guild)
    if moved == -1:
        await ctx.send("❌ Couldn't find a 'Lobby' or 'General' voice channel. Create one first.")
        return
    await ctx.send(f"✅ {moved} player(s) moved back to **{name}**. Temp channels cleaned up.")


@bot.command(name="reset")
async def reset(ctx: commands.Context):
    """!reset — Alias for !lobby (backwards compatibility)."""
    await ctx.invoke(lobby_cmd)


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

@bot.command(name="civ")
async def civ_info(ctx: commands.Context, *, civ_name: str = None):
    """!civ [name] — Show civ bonuses, unique units, and unique techs."""
    if civ_name is None:
        await ctx.send("Usage: `!civ Franks`")
        return

    key = civ_name.strip().title()
    data = CIVS.get(key)

    if data is None:
        # Fuzzy search
        matches = [c for c in CIVS if civ_name.lower() in c.lower()]
        if not matches:
            await ctx.send(f"❌ Civ `{civ_name}` not found. Try `!civ Franks`.")
            return
        if len(matches) == 1:
            key = matches[0]
            data = CIVS[key]
        else:
            await ctx.send(f"Multiple matches: {', '.join(matches)}. Be more specific.")
            return

    role_icon = {"flank": "🏹 Flank", "pocket": "🐴 Pocket", "flex": "🔄 Flex"}[data["role"]]

    embed = discord.Embed(title=f"📖 {key}", color=C_CIV, description=f"**Role:** {role_icon}")
    embed.add_field(name="Civilization Bonuses",
                    value="\n".join(f"• {b}" for b in data["bonuses"]),
                    inline=False)
    embed.add_field(name="Unique Units",
                    value="\n".join(f"• {u}" for u in data["unique_units"]),
                    inline=False)
    embed.add_field(name="Unique Technologies",
                    value="\n".join(f"• {t}" for t in data["unique_techs"]),
                    inline=False)
    if data.get("missing_key"):
        embed.add_field(name="❌ Missing Key Techs",
                        value=", ".join(data["missing_key"]),
                        inline=False)
    if data.get("notes"):
        embed.set_footer(text=data["notes"])

    await ctx.send(embed=embed)


@bot.command(name="has")
async def has_tech(ctx: commands.Context, *, query: str = None):
    """!has [tech/unit] — List all 1.6 civs that have access to that tech or unit."""
    if query is None:
        await ctx.send("Usage: `!has paladin` or `!has thumbring`")
        return

    key = query.strip().lower()
    matches = TECH_UNIT_MAP.get(key)

    if matches is None:
        # Fuzzy search
        close = [k for k in TECH_UNIT_MAP if key in k]
        if not close:
            await ctx.send(f"❌ `{query}` not found in tech/unit database.")
            return
        if len(close) > 1:
            await ctx.send(f"Multiple matches: {', '.join(close)}. Be more specific.")
            return
        key = close[0]
        matches = TECH_UNIT_MAP[key]

    if not matches:
        await ctx.send(f"⚠️ No civs in 1.6 have **{key}** (tech may have been removed).")
        return

    embed = discord.Embed(
        title=f"🔍 Civs with: {key.title()}",
        description=", ".join(sorted(matches)),
        color=C_CIV,
    )
    embed.set_footer(text=f"{len(matches)} civilizations | 1.6 patch 169123")
    await ctx.send(embed=embed)


@bot.command(name="counter")
async def counter(ctx: commands.Context, *, unit: str = None):
    """!counter [unit] — Hard/soft counters and tactical note."""
    if unit is None:
        await ctx.send(f"Usage: `!counter knight`\nAvailable: {', '.join(COUNTERS.keys())}")
        return

    key = unit.strip().lower()
    data = COUNTERS.get(key)

    if data is None:
        close = [k for k in COUNTERS if key in k]
        if not close:
            await ctx.send(f"❌ `{unit}` not in counter database. Available: {', '.join(COUNTERS.keys())}")
            return
        if len(close) > 1:
            await ctx.send(f"Multiple matches: {', '.join(close)}. Be more specific.")
            return
        key = close[0]
        data = COUNTERS[key]

    embed = discord.Embed(title=f"⚔️ Counters: {key.title()}", color=C_COUNTER)
    embed.add_field(name="🔴 Hard Counters",
                    value="\n".join(f"• {c}" for c in data["hard"]),
                    inline=False)
    embed.add_field(name="🟡 Soft Counters",
                    value="\n".join(f"• {c}" for c in data["soft"]),
                    inline=False)
    embed.add_field(name="📝 Tactical Note", value=data["note"], inline=False)
    await ctx.send(embed=embed)


@bot.command(name="random")
async def random_civ(ctx: commands.Context, role: str = "any"):
    """!random [flank|pocket|flex|any] — Draw a random 1.6 civ."""
    role = role.lower()
    if role == "flank":
        pool = FLANK_CIVS
    elif role == "pocket":
        pool = POCKET_CIVS
    elif role == "flex":
        pool = FLEX_CIVS
    else:
        pool = list(CIVS.keys())

    if not pool:
        await ctx.send("❌ No civs found for that role.")
        return

    chosen = random.choice(pool)
    data   = CIVS[chosen]
    icon   = {"flank": "🏹", "pocket": "🐴", "flex": "🔄"}[data["role"]]

    embed = discord.Embed(
        title=f"🎲 Random Civ: {chosen}",
        description=f"{icon} **{data['role'].title()}** | {data['notes']}",
        color=C_CIV,
    )
    embed.add_field(name="Key Bonuses",
                    value="\n".join(f"• {b}" for b in data["bonuses"][:3]),
                    inline=False)
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
# ECO & TRAINING COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

ECO_SYSTEM_PROMPT = (
    "You are an expert Age of Empires II economy coach for a custom Voobly "
    "v1.6 ruleset used on this server — NOT vanilla Age of Conquerors. In "
    "this ruleset every player starts the match already in the IMPERIAL "
    "AGE with large starting stockpiles (roughly 1000 food, 750 wood, and "
    "300 stone observed in real scoreboards). There is no Dark Age "
    "villager allocation, no Feudal Age click, and no age-up timing to "
    "discuss — that vanilla advice does not apply here and you should not "
    "give it. The dominant economic strategy is aggressive 'pocket "
    "booming': immediately dropping a second and third Town Center to "
    "flood villager production and snowball resource income before the "
    "opponent can match your output. You don't have live search or "
    "lookup tools — apply your own general AoE2 economic knowledge "
    "(gather rates, building/unit costs, resource math) to reason about "
    "THIS specific high-resource, multi-TC ruleset. Give concise, "
    "actionable advice on villager allocation across multiple TCs, "
    "resource splits, booming pace, and eco recovery. Use short "
    "paragraphs or bullet points. Keep answers tight enough to fit in a "
    "Discord embed — a few hundred words at most. Do not pad with "
    "disclaimers."
) + (("\n\n## Server Reference Data\n" + reference_loader.VOOBLY_V16) if reference_loader.VOOBLY_V16 else "") \
  + (("\n\n## Game Rates Reference\n" + reference_loader.GAME_RATES) if reference_loader.GAME_RATES else "")

GG_SYSTEM_PROMPT = (
    "You are a helpful, knowledgeable Age of Empires II assistant for this "
    "server's community, which plays a custom Voobly v1.6 ruleset (Imperial "
    "Age start, high starting resources, multi-TC pocket boom meta — NOT "
    "vanilla Age of Conquerors). Answer the user's question directly and "
    "concisely, suitable for a Discord message. You may be given a block of "
    "player profiles tagged <player name=\"...\">; when the question is about "
    "specific players or comparisons between them, base your answer ONLY on "
    "those profiles and say so plainly if a player has no profile or the data "
    "doesn't cover what was asked — never invent stats. For general strategy "
    "questions, apply your AoE2 knowledge grounded in the server ruleset and "
    "game rates provided. Keep answers tight (a few hundred words max). Use "
    "bullet points where it helps. Do not pad with disclaimers."
) + (("\n\n## Server Reference Data\n" + reference_loader.VOOBLY_V16) if reference_loader.VOOBLY_V16 else "") \
  + (("\n\n## Game Rates Reference\n" + reference_loader.GAME_RATES) if reference_loader.GAME_RATES else "")


def _build_profile_addendum(profile: dict | None) -> str:
    """Build a short 'tailor your advice' addendum from a synthesized
    strategic profile, for appending to the user-facing prompt (not the
    system prompt). Returns "" if there's nothing usable."""
    if not profile:
        return ""
    bits = []
    for key, label in (
        ("playstyle", "Playstyle"),
        ("economy", "Economy"),
        ("tendencies", "Tendencies"),
    ):
        text = (profile.get(key) or "").strip()
        if text:
            bits.append(f"{label}: {text}")
    if not bits:
        return ""
    return (
        "\n\nHere is this player's known tendencies, tailor your advice to "
        "them:\n" + "\n".join(bits)
    )


def _lookup_profile_silently(target: str) -> dict | None:
    """Fetch a synthesized strategic profile from MinIO the same way !coach
    does. Returns None (silently) if no profile exists or storage is
    unreachable — callers should fall back to generic advice."""
    try:
        from pipeline.s3_store import get_profile
        profile, _ = get_profile(target)
        return profile
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _format_profile_for_context(profile: dict) -> str:
    lines = []
    for key, label in (
        ("playstyle", "Playstyle"),
        ("economy", "Economy"),
        ("aggression", "Aggression"),
        ("defense", "Defense"),
        ("tendencies", "Tendencies"),
    ):
        text = (profile.get(key) or "").strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def _build_match_context() -> str:
    parts = []
    for role in ("ally", "enemy"):
        for name in _match_session.get(role, []):
            profile = _lookup_profile_silently(name)
            if profile:
                inner = _format_profile_for_context(profile)
                parts.append(f'<player role="{role}" name="{name}">\n{inner}\n</player>')
            else:
                parts.append(f'<player role="{role}" name="{name}">No match history available.</player>')
    return "\n".join(parts)


# Cache the assembled all-profiles context: profiles only change when pipeline 3
# reruns (nightly), so we avoid re-fetching every profile on every !gg call.
_ALL_PROFILES_CACHE: dict = {"ts": 0.0, "text": ""}
_ALL_PROFILES_TTL = 300.0  # seconds


def _build_all_profiles_context() -> str:
    """Fetch every stored player profile and build one tagged context block.
    Cached for _ALL_PROFILES_TTL seconds. Returns "" if storage is unreachable."""
    import time
    now = time.time()
    if _ALL_PROFILES_CACHE["text"] and (now - _ALL_PROFILES_CACHE["ts"]) < _ALL_PROFILES_TTL:
        return _ALL_PROFILES_CACHE["text"]
    text = ""
    try:
        from pipeline.s3_store import list_profiles, get_profile
        parts = []
        for name in list_profiles():
            try:
                profile, _ = get_profile(name)
            except Exception:
                continue
            inner = _format_profile_for_context(profile)
            if inner:
                parts.append(f'<player name="{name}">\n{inner}\n</player>')
        text = "\n".join(parts)
    except Exception:
        text = ""
    _ALL_PROFILES_CACHE["ts"] = now
    _ALL_PROFILES_CACHE["text"] = text
    return text


@bot.command(name="eco")
async def eco(ctx: commands.Context, *, query: str = None):
    """
    !eco               — General eco overview (AI-generated)
    !eco 3tc           — Vill split for 3 TCs + constant production
    !eco knights       — How many vills to support knight production
    !eco boom          — Aggressive boom strategy
    !eco short food    — Fix a food shortage right now
    (any free-text economy/build question works)
    """
    if query is None:
        prompt = (
            "Give a general economy overview for this server's pocket-boom "
            "ruleset: how to split villagers across multiple Town Centers "
            "from the start of the match, the order to drop a 2nd and 3rd "
            "TC, and a quick reminder of base gather rates. Keep it tight."
        )
        title = "🌾 Eco Reference — Overview"
    else:
        prompt = f"Age of Empires II economy question: {query}"
        title = f"🌾 Eco: {query}"

    profile = _lookup_profile_silently(ctx.author.display_name)
    prompt += _build_profile_addendum(profile)

    match_ctx = _build_match_context()
    if match_ctx:
        prompt += f"\n\n<match_context>\n{match_ctx}\n</match_context>"
    _sys = ECO_SYSTEM_PROMPT + (MATCHUP_CHAIN_OF_THOUGHT if match_ctx else "")

    async with ctx.typing():
        answer = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.safe_ask(prompt, system=_sys),
        )

    embed = discord.Embed(title=title, description=answer, color=C_ECO)
    await ctx.send(embed=embed)


@bot.command(name="match")
async def match_session(ctx: commands.Context, *, args: str = ""):
    """
    !match ally salar player3 enemy player2 player6  — set current match teams
    !match status                                — show current session
    !match reset                                 — clear session
    """
    global _match_session
    tokens = args.strip().split() if args.strip() else []

    if not tokens or tokens[0] == "status":
        ally = ", ".join(_match_session["ally"]) or "none"
        enemy = ", ".join(_match_session["enemy"]) or "none"
        embed = discord.Embed(title="⚔️ Match Session", color=0x2ECC71)
        embed.add_field(name="Ally", value=ally, inline=False)
        embed.add_field(name="Enemy", value=enemy, inline=False)
        await ctx.send(embed=embed)
        return

    if tokens[0] == "reset":
        _match_session = {"ally": [], "enemy": []}
        await ctx.send("Match session cleared.")
        return

    # Parse: !match ally a b c enemy x y z  (ally/enemy keywords as separators)
    new_session: dict[str, list[str]] = {"ally": [], "enemy": []}
    current_role: str | None = None
    for tok in tokens:
        if tok.lower() in ("ally", "allies", "team"):
            current_role = "ally"
        elif tok.lower() in ("enemy", "enemies", "vs", "opponent", "opponents"):
            current_role = "enemy"
        elif current_role is not None:
            new_session[current_role].append(tok)

    if not new_session["ally"] and not new_session["enemy"]:
        await ctx.send(
            "Usage: `!match ally salar player3 enemy player2 player6` | `!match status` | `!match reset`"
        )
        return

    _match_session = new_session
    ally = ", ".join(_match_session["ally"]) or "none"
    enemy = ", ".join(_match_session["enemy"]) or "none"
    embed = discord.Embed(title="⚔️ Match Session Set", color=0x2ECC71)
    embed.add_field(name="Ally", value=ally, inline=False)
    embed.add_field(name="Enemy", value=enemy, inline=False)
    await ctx.send(embed=embed)


BUILD_SYSTEM_PROMPT = (
    "You are an expert build-order coach for this server's custom Voobly "
    "v1.6 ruleset — NOT vanilla Age of Conquerors. Every player starts "
    "already in the IMPERIAL AGE with large starting stockpiles (roughly "
    "1000 food, 750 wood, and 300 stone observed in real scoreboards). "
    "There is no Dark Age, no Feudal Age click, and no age-progression "
    "build order to give — early-tech and age-up advice is irrelevant "
    "here and you should not produce it. Builds in this ruleset are about "
    "what to do with the huge starting stockpile from second zero: how "
    "many Town Centers to drop and in what order (the dominant pattern is "
    "an aggressive multi-TC 'pocket boom' — 2nd and 3rd TC immediately to "
    "flood villager and unit production), villager allocation across "
    "those TCs, and the fastest path to overwhelming military production. "
    "You don't have live search or lookup tools — apply your own general "
    "AoE2 strategic knowledge to reason about THIS specific high-resource, "
    "multi-TC ruleset. Include villager allocation, approximate timings, "
    "and a short note on attack angle, how it's countered, and best civs "
    "for it when relevant. Keep the answer tight enough for a Discord "
    "embed — a few hundred words at most. Use bullet points or numbered "
    "steps."
) + (("\n\n## Server Reference Data\n" + reference_loader.VOOBLY_V16) if reference_loader.VOOBLY_V16 else "") \
  + (("\n\n## Game Rates Reference\n" + reference_loader.GAME_RATES) if reference_loader.GAME_RATES else "")


@bot.command(name="build")
async def build_order(ctx: commands.Context, *, opening: str = None):
    """
    !build               — AI overview of this server's pocket-boom strategy
    !build 3tc           — Full step-by-step 3-TC pocket boom build order
    !build archers       — Archer-focused build order for this ruleset
    !build turtle        — Defensive multi-TC build order
    (any build-order name or free-text request works)
    """
    if opening is None:
        prompt = (
            "Give a brief overview of this server's pocket-boom ruleset "
            "(players start in Imperial Age with ~1000 food/750 wood/300 "
            "stone): the core idea of dropping a 2nd and 3rd Town Center "
            "immediately, a couple of variations on how aggressively to "
            "boom vs. transition to military, and what counters an "
            "opponent who out-booms you. One or two lines per point."
        )
        title = "🏗️ Build Orders — Pocket Boom Overview"
    else:
        prompt = f"Build order request for this server's pocket-boom ruleset: {opening}"
        title = f"🏗️ Build Order: {opening}"

    profile = _lookup_profile_silently(ctx.author.display_name)
    prompt += _build_profile_addendum(profile)

    match_ctx = _build_match_context()
    if match_ctx:
        prompt += f"\n\n<match_context>\n{match_ctx}\n</match_context>"
    _sys = BUILD_SYSTEM_PROMPT + (MATCHUP_CHAIN_OF_THOUGHT if match_ctx else "")

    async with ctx.typing():
        answer = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.safe_ask(prompt, system=_sys),
        )

    embed = discord.Embed(title=title, description=answer, color=C_BUILD)
    await ctx.send(embed=embed)


@bot.command(name="hotkeys")
async def hotkeys(ctx: commands.Context):
    """!hotkeys — Idle villager rotation training checklist."""
    embed = discord.Embed(
        title="⌨️ Hotkey Training Checklist",
        description="Build muscle memory to eliminate idle villagers.",
        color=C_BUILD,
    )
    embed.add_field(name="Core Loop (every 10-15 seconds)", value=(
        "1️⃣ **Select All Town Centers** — queue a villager if food allows\n"
        "2️⃣ **Go to Idle Villager** (H by default) — assign idle vills to resource\n"
        "3️⃣ **Go to Town Center** (H or custom) — verify TC is producing\n"
        "4️⃣ Repeat after every attack move or group command"
    ), inline=False)
    embed.add_field(name="Production Shortcuts", value=(
        "🏰 **Go to Castle** — train unique unit\n"
        "⚔️ **Go to Barracks** — queue M@A or Huskarl\n"
        "🐴 **Go to Stable** — queue Knight/Scout\n"
        "🏹 **Go to Archery Range** — queue Archers/Skirms\n"
        "🔨 **Go to Lumber Camp** — reassign choppers\n"
        "⛏️ **Go to Mining Camp** — reassign miners"
    ), inline=False)
    embed.add_field(name="Practice Drill", value=(
        "In a skirmish vs Easy AI:\n"
        "• Set a **10-second timer**\n"
        "• Each ring: Select All TCs → queue vill → Go To Idle Vill → assign task\n"
        "• After 20 minutes with zero idle villagers, you have the muscle memory"
    ), inline=False)
    embed.set_footer(text="Hotkey paths: hotkey.xml → NextIdleVillager / SelectAllTCs / GoToTownCenter")
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────────────────────────────────────
# VOICE TRAINER COMMAND
# ─────────────────────────────────────────────────────────────────────────────
# The bot joins the user's voice channel and reads out economy build steps one
# at a time using gTTS + FFmpeg. After each step the user can type !next to
# advance, or the bot auto-advances after a configurable delay.
#
# Requirements: pip install gTTS PyNaCl discord.py[voice]
#               FFmpeg must be installed and on PATH.
# ─────────────────────────────────────────────────────────────────────────────

import tempfile
import pathlib

# Active trainer sessions: guild_id → {"vc": voice_client, "step": int, "ctx": ctx}
trainer_sessions: dict[int, dict] = {}

TRAINER_AUTO_ADVANCE_DELAY = 0  # 0 = manual (!next only), set to seconds for auto


async def _speak_step(voice_client: discord.VoiceClient, text: str, guild_id: int):
    """Generate TTS audio for `text` and play it in the voice channel."""
    try:
        from gtts import gTTS
    except ImportError:
        return False  # gTTS not installed

    # Write to a temp file
    tmp = pathlib.Path(tempfile.mktemp(suffix=".mp3"))
    tts = gTTS(text=text, lang="en", slow=False)
    await asyncio.get_event_loop().run_in_executor(None, tts.save, str(tmp))

    if voice_client.is_playing():
        voice_client.stop()

    finished = asyncio.Event()

    def after(error):
        tmp.unlink(missing_ok=True)
        bot.loop.call_soon_threadsafe(finished.set)

    voice_client.play(discord.FFmpegPCMAudio(str(tmp)), after=after)
    await finished.wait()
    return True


TRAINER_SYSTEM_PROMPT = (
    "You are a build-order trainer narrating steps out loud over "
    "text-to-speech in a voice channel, for this server's custom Voobly "
    "v1.6 ruleset — NOT vanilla Age of Conquerors. Every player starts "
    "already in the IMPERIAL AGE with large starting stockpiles (roughly "
    "1000 food, 750 wood, and 300 stone). There is no Dark Age villager "
    "allocation and no Feudal Age click to narrate — do not include that "
    "vanilla advice. Produce a numbered, step-by-step training script for "
    "the requested build order, centered on this ruleset's dominant "
    "pattern: aggressive multi-TC 'pocket booming' (dropping a 2nd and "
    "3rd Town Center immediately from the starting stockpile) and the "
    "early production habits that follow from it. You don't have live "
    "search or lookup tools — apply your own general AoE2 knowledge to "
    "this specific high-resource, multi-TC ruleset. Output ONE concise "
    "spoken instruction per line, numbered like 'Step 1. ...', 'Step 2. "
    "...', and so on. Each line should be a short, complete sentence "
    "suitable for being read aloud by TTS — no markdown, no bullet "
    "symbols, no headers, just plain numbered sentences. Aim for 10-16 "
    "steps covering Town Center placement and villager allocation through "
    "the transition into early production habits."
) + (("\n\n## Server Reference Data\n" + reference_loader.VOOBLY_V16) if reference_loader.VOOBLY_V16 else "")

MATCHUP_CHAIN_OF_THOUGHT = (
    "\n\nYou have been given player profiles tagged <player role=\"ally\"> and "
    "<player role=\"enemy\">. Reason in this exact sequence: "
    "1) THREAT — when and how will the enemies attack based on their profile? "
    "2) MATH — using the game rates above, what resources/villagers does the ally need to counter? "
    "3) BUILD — give a numbered step-by-step recommendation (8–12 steps). "
    "Be specific to the profiles given. Do not give generic advice."
)

DEFAULT_TRAINER_BUILD = "standard pocket-boom opening with a 2nd and 3rd Town Center"


def _parse_trainer_steps(raw: str) -> list[str]:
    """Turn the LLM's numbered-line response into a list of step strings."""
    import re
    steps = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading numbering like "1.", "1)", "Step 1.", "Step 1:" etc.
        cleaned = re.sub(r"^(?:step\s*)?\d+[\.\):]\s*", "", line, flags=re.IGNORECASE).strip()
        if cleaned:
            steps.append(cleaned)
    return steps


@bot.command(name="trainer")
async def trainer(ctx: commands.Context, *, build: str = None):
    """!trainer [build] — Bot joins your VC and narrates an AI-generated build order step by step. Type !next to advance."""
    if not cloud_llm.is_configured():
        await ctx.send(
            "⚠️ The voice trainer needs the AI backend configured first. "
            "Set OPENCLAW_ENDPOINT, OPENCLAW_API_KEY, and OPENCLAW_MODEL in "
            "the bot's .env, then run `!trainer` again."
        )
        return

    if ctx.author.voice is None:
        await ctx.send("❌ Join a voice channel first, then run `!trainer`.")
        return

    # Check gTTS available
    try:
        import gtts as _  # noqa: F401
    except ImportError:
        await ctx.send(
            "❌ `gTTS` is not installed. Run `pip install gTTS` and ensure FFmpeg is on your PATH."
        )
        return

    build_request = build or DEFAULT_TRAINER_BUILD
    async with ctx.typing():
        raw_steps = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.ask(
                f"Age of Empires II build order to narrate: {build_request}",
                system=TRAINER_SYSTEM_PROMPT,
            ),
        )
    trainer_steps = _parse_trainer_steps(raw_steps)

    if not trainer_steps:
        await ctx.send("⚠️ The AI didn't return any usable steps. Try `!trainer` again or with a different build.")
        return

    guild_id = ctx.guild.id

    # Disconnect existing session if any
    if guild_id in trainer_sessions:
        old_vc = trainer_sessions[guild_id].get("vc")
        if old_vc and old_vc.is_connected():
            await old_vc.disconnect()
        trainer_sessions.pop(guild_id, None)

    vc = ctx.author.voice.channel
    voice_client = await vc.connect()

    trainer_sessions[guild_id] = {
        "vc":   voice_client,
        "step": 0,
        "ctx":  ctx,
    }

    embed = discord.Embed(
        title="🎙️ Economy Trainer — Voice Mode",
        description=(
            f"Joined **{vc.name}**. Starting narration for: **{build_request}**\n\n"
            f"Total steps: **{len(trainer_steps)}**\n"
            "Type `!next` to advance manually, or `!trainer stop` to end."
        ),
        color=C_ECO,
    )
    await ctx.send(embed=embed)

    step = 0
    while step < len(trainer_steps) and guild_id in trainer_sessions:
        trainer_sessions[guild_id]["step"] = step
        text = trainer_steps[step]

        # Send text to channel so player can read along
        await ctx.send(
            embed=discord.Embed(
                title=f"🔊 Step {step + 1} / {len(trainer_steps)}",
                description=text,
                color=C_ECO,
            )
        )

        # Speak it
        ok = await _speak_step(voice_client, text, guild_id)
        if not ok:
            await ctx.send("⚠️ TTS failed. Continuing in text-only mode.")

        if TRAINER_AUTO_ADVANCE_DELAY > 0:
            await asyncio.sleep(TRAINER_AUTO_ADVANCE_DELAY)
            step += 1
        else:
            # Wait for !next
            def check(m: discord.Message):
                return (
                    m.author == ctx.author
                    and m.channel == ctx.channel
                    and m.content.lower() in ("!next", "!trainer stop")
                )
            try:
                msg = await bot.wait_for("message", check=check, timeout=300)
                if msg.content.lower() == "!trainer stop":
                    break
                step += 1
            except asyncio.TimeoutError:
                await ctx.send("⏰ Trainer timed out after 5 minutes of inactivity.")
                break

    if voice_client.is_connected():
        await voice_client.disconnect()

    trainer_sessions.pop(guild_id, None)

    if step >= len(trainer_steps):
        await ctx.send(
            embed=discord.Embed(
                title="🏆 Training Complete!",
                description="You've heard all economy steps. Practice them in a real game and run `!trainer` again to repeat.",
                color=C_TEAMS,
            )
        )
    else:
        await ctx.send("👋 Trainer session ended.")


@trainer.error
async def trainer_error(ctx, error):
    if isinstance(error, commands.CommandInvokeError):
        await ctx.send(f"❌ Trainer error: {error.original}")


# ─────────────────────────────────────────────────────────────────────────────
# BOT EVENTS
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# RECORDED GAME ANALYSIS  (!analyze  !profile  !mygames  !coach)
# ─────────────────────────────────────────────────────────────────────────────
# Requires: pip install mgz
# Reads .mgz files directly from your local SaveGame folders (no upload needed).
# Profiles are cached in profiles.json next to bot.py.
# ─────────────────────────────────────────────────────────────────────────────

import glob
import json
from collections import defaultdict

# Both SaveGame folders on this machine
# Only scan the Voobly v1.6 SaveGame folder. The base-game SaveGame folder is
# intentionally excluded — it holds 4 older/off-version recordings we don't want.
SAVEGAME_PATHS = [
    r"D:\Program Files (x86)\Microsoft Games\Age of Empires II\Voobly Mods\AOC\Data Mods\v1.6 Game Data\SaveGame",
]


def _scan_recordings() -> list[str]:
    files = []
    for folder in SAVEGAME_PATHS:
        files.extend(glob.glob(os.path.join(folder, "*.mgz")))
    return sorted(set(files))


def _parse_recording(filepath: str) -> dict:
    """Return a dict of key game stats from one .mgz file."""
    try:
        from mgz.summary import Summary
        with open(filepath, "rb") as fh:
            s = Summary(fh)
            players = s.get_players()
            duration_ms = s.get_duration()
            map_info = s.get_map()
            settings = s.get_settings() or {}

            # Normalise map name
            map_name = "Unknown"
            if isinstance(map_info, dict):
                map_name = map_info.get("name", "Unknown")
            elif map_info:
                map_name = str(map_info)
            # Strip DE_ prefix used in 1.6 map pack filenames
            if map_name.upper().startswith("DE_"):
                map_name = map_name[3:]

            # Extract date string from filename  rec.YYYYMMDD-HHMMSS.mgz
            basename = os.path.basename(filepath)
            date_str = basename[4:12] if len(basename) > 16 else "unknown"
            try:
                date_fmt = datetime.strptime(date_str, "%Y%m%d").strftime("%b %d %Y")
            except ValueError:
                date_fmt = date_str

            game = {
                "file":         basename,
                "date":         date_fmt,
                "duration_min": round(duration_ms / 60000, 1) if duration_ms else None,
                "map":          map_name,
                "players":      [],
            }

            for p in (players or []):
                raw_civ = p.get("civilization", None)
                if isinstance(raw_civ, int):
                    civ_name = CIV_ID_TO_NAME.get(raw_civ, f"Civ{raw_civ}")
                else:
                    civ_name = str(raw_civ).replace("Civilization.", "").title() if raw_civ else "Unknown"
                game["players"].append({
                    "name":    p.get("name", "Unknown"),
                    "civ":     civ_name,
                    "team":    p.get("team", 0),
                    "winner":  bool(p.get("winner", False)),
                })
            return game

    except ImportError:
        return {"file": os.path.basename(filepath), "error": "mgz not installed — run: pip install mgz"}
    except Exception as exc:
        err = str(exc)
        # Silently drop lobby/unstarted saves — they have no useful data
        if "initial" in err.lower() or "lobby" in err.lower():
            return None
        return {"file": os.path.basename(filepath), "error": err}


MYGAMES_SYSTEM_PROMPT = (
    "You are an Age of Empires II analyst. You're given a compact summary "
    "of a player's recent recorded games (map, date, duration, players, "
    "civs, winner) and you produce a short natural-language recap: overall "
    "results, civ variety/preferences, common matchups, and any trends "
    "worth noting (e.g. frequently losing on certain maps, repeating a "
    "civ). Be concise and concrete — reference actual games from the data, "
    "don't invent details that aren't there. Keep it to a few short "
    "paragraphs or bullet points, fitting in a Discord embed."
)


def _summarize_games_for_llm(games: list[dict], player_name: str | None) -> str:
    lines = []
    for g in games:
        player_bits = ", ".join(
            f"{p['name']} ({p['civ']}{', winner' if p['winner'] else ''})"
            for p in g["players"]
        )
        lines.append(
            f"- {g['map']} | {g['date']} | {g['duration_min']} min | {player_bits}"
        )
    header = f"Recent games for {player_name}:" if player_name else "Recent games:"
    return header + "\n" + "\n".join(lines)


@bot.command(name="mygames")
async def mygames(ctx: commands.Context, *, player_name: str = None):
    """!mygames [name] — AI recap/analysis of recent game history from recorded games."""
    recordings = _scan_recordings()
    if not recordings:
        await ctx.send("❌ No recordings found in SaveGame folders.")
        return

    # Search most recent 15 for speed
    recent = recordings[-15:]
    results = []
    for rec in reversed(recent):
        parsed = await asyncio.get_event_loop().run_in_executor(None, _parse_recording, rec)
        if parsed is not None and "error" not in parsed:
            results.append(parsed)

    if player_name:
        results = [
            g for g in results
            if any(player_name.lower() in p["name"].lower() for p in g["players"])
        ]

    if not results:
        await ctx.send("❌ No games found.")
        return

    games_for_summary = results[:8]
    summary_text = _summarize_games_for_llm(games_for_summary, player_name)
    prompt = (
        f"{summary_text}\n\n"
        "Write a recap/analysis of these recent games."
    )

    async with ctx.typing():
        answer = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.safe_ask(prompt, system=MYGAMES_SYSTEM_PROMPT),
        )

    embed = discord.Embed(
        title=f"📼 Recent Games Recap{' for ' + player_name if player_name else ''}",
        description=answer,
        color=C_DRAFT,
    )
    embed.set_footer(text=f"Based on last {len(games_for_summary)} games from SaveGame folder")
    await ctx.send(embed=embed)


# ── ASK  (!ask <player_name>) ───────────────────────────────────────────────
# Separate, new system: reads a player's *synthesized* strategic profile
# (playstyle/economy/aggression/defense/teamwork/tendencies/caveats) from
# MinIO via pipeline/s3_store.py — NOT the local profiles.json used by
# !profile above. See ask_command.py for the implementation.
# ─────────────────────────────────────────────────────────────────────────────
from ask_command import fetch_and_build_embed as _ask_fetch_and_build_embed


@bot.command(name="ask")
async def ask_cmd(ctx: commands.Context, *, player_name: str = None):
    """!ask <player_name> — Show a player's synthesized strategic profile (from MinIO)."""
    if player_name is None:
        await ctx.send("Usage: `!ask PlayerName`")
        return

    async with ctx.typing():
        embed = await asyncio.get_event_loop().run_in_executor(
            None, _ask_fetch_and_build_embed, player_name
        )
    await ctx.send(embed=embed)


@bot.command(name="gg")
async def gg(ctx: commands.Context, *, question: str = None):
    """
    !gg <anything>   — ask the bot any AoE2 / server / player question
    Examples:
      !gg who is the most aggressive player?
      !gg how do I beat a knight rush?
      !gg compare player2 and player6
    """
    if not question:
        await ctx.send(
            "Ask me anything about the server, players, or strategy. "
            "Example: `!gg who should I watch out for?`"
        )
        return

    profiles_ctx = _build_all_profiles_context()
    prompt = f"Question: {question}"
    if profiles_ctx:
        prompt += f"\n\n<player_profiles>\n{profiles_ctx}\n</player_profiles>"

    async with ctx.typing():
        answer = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.safe_ask(prompt, system=GG_SYSTEM_PROMPT, max_tokens=900),
        )

    # Discord embed description hard limit is 4096 chars.
    if len(answer) > 4000:
        answer = answer[:3997] + "..."
    embed = discord.Embed(title=f"💬 {question[:200]}", description=answer, color=C_GG)
    await ctx.send(embed=embed)


# ── VOICE COACH ───────────────────────────────────────────────────────────────
# !coach [player_name]
# Bot joins VC and narrates personalised coaching based on their recorded profile.
# Falls back to generic advice if no profile exists.
# ─────────────────────────────────────────────────────────────────────────────

COACH_INTRO = (
    "Welcome to your personalised coaching session. "
    "I will walk you through your known weaknesses and how to fix them, "
    "followed by a pre-game checklist. Let's begin."
)
COACH_GENERIC_TIPS = [
    "Focus on never letting your Town Center go idle. Queue a villager the moment you have 50 food.",
    "Scout your opponent in Dark Age. Knowing their build early lets you counter before it hurts.",
    "Wall your base at 11 to 12 minutes. Even two layers of palisade buys you 3 minutes against a rush.",
    "Click Feudal Age at exactly 22 population for a standard build. Earlier costs eco. Later loses timing.",
    "In Castle Age, your first goal is a second Town Center. Two TCs means twice as many villagers.",
    "Always research Bloodlines and Forging before training knights. Unupgraded knights die too fast.",
    "Keep 5 farmers per Town Center at minimum. Every TC needs constant food to produce villagers.",
    "Use Select All Town Centers every 10 to 15 seconds. This is the single most important habit.",
]


@bot.command(name="coach")
async def coach_cmd(ctx: commands.Context, *, player_name: str = None):
    """!coach [name] — Bot joins your VC and gives personalised voice coaching from your profile."""
    if ctx.author.voice is None:
        await ctx.send("❌ Join a voice channel first, then run `!coach`.")
        return

    try:
        import gtts as _  # noqa: F401
    except ImportError:
        await ctx.send("❌ `gTTS` not installed. Run `pip install gTTS` and ensure FFmpeg is on PATH.")
        return

    target = player_name or ctx.author.display_name

    # Fetch the player's synthesized strategic profile from MinIO (written by
    # pipeline 3) — the same source as !ask. Replaces the old local
    # profiles.json system.
    profile = None
    try:
        from pipeline.s3_store import get_profile
        profile, _ = get_profile(target)
    except FileNotFoundError:
        profile = None
    except Exception as exc:  # storage unreachable — degrade to general coaching
        await ctx.send(
            f"⚠️ Couldn't reach the profile store (`{type(exc).__name__}`); "
            "giving general coaching instead."
        )
        profile = None

    guild_id = ctx.guild.id
    if guild_id in trainer_sessions:
        old = trainer_sessions[guild_id].get("vc")
        if old and old.is_connected():
            await old.disconnect()

    vc_channel = ctx.author.voice.channel
    voice_client = await vc_channel.connect()
    trainer_sessions[guild_id] = {"vc": voice_client, "step": 0, "ctx": ctx}

    # Build personalised script from the synthesized profile's behavioural
    # sections (caveats omitted — it's a data-coverage note, not coaching).
    script = [COACH_INTRO]

    if profile:
        pname = profile.get("player_name", target)
        n_matches = profile.get("n_matches", "several")
        script.append(
            f"I found a strategic profile for {pname}, "
            f"synthesized from {n_matches} recorded matches."
        )
        for key, label in (
            ("playstyle", "Your overall playstyle"),
            ("economy", "On your economy"),
            ("aggression", "On aggression"),
            ("defense", "On defense"),
            ("teamwork", "On teamwork"),
            ("tendencies", "Your tendencies and strengths"),
        ):
            text = (profile.get(key) or "").strip()
            if text:
                script.append(f"{label}: {text}")
    else:
        script.append(
            f"No profile found for {target} yet. Profiles are built "
            f"automatically from your replays. For now, here is general coaching."
        )

    # If a match session is active, inject a match-aware coaching segment.
    match_ctx = _build_match_context()
    if match_ctx and cloud_llm.is_configured():
        coach_prompt = (
            f"You are coaching {target} for an upcoming match. "
            "Give 3 to 5 spoken coaching tips specifically about this matchup. "
            "Each tip should be one short sentence, suitable for text-to-speech. "
            "Focus on the opponent threats and how to counter them."
            f"\n\n<match_context>\n{match_ctx}\n</match_context>"
        )
        _coach_sys = ECO_SYSTEM_PROMPT + MATCHUP_CHAIN_OF_THOUGHT
        raw_match_tips = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: cloud_llm.safe_ask(coach_prompt, system=_coach_sys),
        )
        for tip in _parse_trainer_steps(raw_match_tips):
            script.append(tip)

    script += COACH_GENERIC_TIPS
    script.append(
        "That concludes your coaching session. "
        "Your profile updates automatically as you play more games. Good luck."
    )

    embed = discord.Embed(
        title=f"🎙️ Coach: {target}",
        description=f"Joined **{vc_channel.name}**. Delivering personalised coaching.\nType `!trainer stop` to end early.",
        color=C_ECO,
    )
    if profile:
        embed.add_field(
            name="Profile loaded",
            value=f"{profile.get('n_matches', '?')} matches · model `{profile.get('model', '?')}`",
            inline=False,
        )
    await ctx.send(embed=embed)

    for i, line in enumerate(script):
        if guild_id not in trainer_sessions:
            break
        await ctx.send(
            embed=discord.Embed(
                title=f"🔊 {i+1}/{len(script)}",
                description=line,
                color=C_ECO,
            )
        )
        ok = await _speak_step(voice_client, line, guild_id)
        if not ok:
            await ctx.send("⚠️ TTS unavailable — showing text only.")

        # Wait for !next or auto-continue after 4s pause
        def check(m: discord.Message):
            return m.author == ctx.author and m.channel == ctx.channel and \
                   m.content.lower() in ("!next", "!trainer stop")
        try:
            msg = await bot.wait_for("message", check=check, timeout=300)
            if msg.content.lower() == "!trainer stop":
                break
        except asyncio.TimeoutError:
            break

    if voice_client.is_connected():
        await voice_client.disconnect()
    trainer_sessions.pop(guild_id, None)
    await ctx.send("✅ Coaching session complete.")


# ── VOICE LISTEN ─────────────────────────────────────────────────────────────
# !listen           — start wake-word listening in the caller's voice channel
# !listen test      — start in test mode: post every transcript to the channel
# !listen stop      — stop listening and disconnect
# ─────────────────────────────────────────────────────────────────────────────

from discord.ext import voice_recv as _voice_recv


@bot.command(name="listen")
async def listen_cmd(ctx: commands.Context, *, mode: str = ""):
    """
    !listen          — start Teletron-1 voice assistant in your voice channel
    !listen test     — post transcripts to channel (useful for debugging STT)
    !listen stop     — disconnect and stop listening
    """
    if ctx.guild is None:
        await ctx.send("This command only works in a server.")
        return

    guild_id = ctx.guild.id
    mode = mode.strip().lower()

    # ── STOP ────────────────────────────────────────────────────────────────
    if mode == "stop":
        stopped = False

        session = trainer_sessions.pop(guild_id, None)
        if session:
            sink = session.get("sink")
            if sink:
                try:
                    sink.cleanup()
                except Exception:
                    pass
            vc = session.get("vc")
            if vc and vc.is_connected():
                await vc.disconnect(force=True)
                stopped = True

        # Also clear any untracked/ghost voice connection: trainer_sessions is
        # in-memory, so after a bot restart it's empty even though Discord may
        # still show this bot connected (leftover from the killed process).
        # Previously "!listen stop" reported nothing to stop while the bot
        # visibly sat in the channel.
        leftover = ctx.guild.voice_client
        if leftover is not None:
            try:
                if hasattr(leftover, "stop_listening"):
                    leftover.stop_listening()
            except Exception:
                pass
            try:
                await leftover.disconnect(force=True)
                stopped = True
            except Exception:
                pass

        await ctx.send(
            "Stopped listening." if stopped
            else "Not connected to voice — nothing to stop."
        )
        return

    # ── START ────────────────────────────────────────────────────────────────
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("You need to be in a voice channel first.")
        return

    channel = ctx.author.voice.channel

    # Disconnect any existing session (trainer / coach / listen)
    if guild_id in trainer_sessions:
        old = trainer_sessions[guild_id]
        old_sink = old.get("sink")
        if old_sink:
            try:
                old_sink.cleanup()
            except Exception:
                pass
        old_vc = old.get("vc")
        if old_vc and old_vc.is_connected():
            await old_vc.disconnect()
        trainer_sessions.pop(guild_id, None)

    # Clear any untracked/ghost voice connection left over from a previous
    # process — channel.connect() raises ClientException if a stale voice
    # client is still registered for this guild.
    leftover = ctx.guild.voice_client
    if leftover is not None:
        try:
            if hasattr(leftover, "stop_listening"):
                leftover.stop_listening()
        except Exception:
            pass
        try:
            await leftover.disconnect(force=True)
        except Exception:
            pass

    # Connect with voice-recv client
    vc = await channel.connect(cls=_voice_recv.VoiceRecvClient)

    loop = asyncio.get_event_loop()

    # Closure: on_utterance is called from run_coroutine_threadsafe
    async def on_utterance(user, wav_bytes: bytes) -> None:
        # Transcribe off the event loop thread so requests() doesn't block it
        try:
            text = await loop.run_in_executor(
                None, lambda: cloud_llm.transcribe(wav_bytes)
            )
        except Exception as exc:
            print(f"[listen] transcribe error: {exc}")
            return

        if not text:
            return  # silence or unintelligible — skip

        # ── TEST MODE: just echo transcript ─────────────────────────────────
        if mode == "test":
            await ctx.send(f"\U0001f5e3️ {user.display_name}: {text}")
            return

        # ── NORMAL MODE: wake-word gating ────────────────────────────────────
        query = voice_listen.match_wake_word(text, WAKE_WORD)
        if query is None:
            return  # not addressed to the bot

        if query == "":
            # Just the wake word — prompt for a question
            await _speak_step(vc, "Yes? Ask your question.", guild_id)
            return

        # Build grounded prompt (same pattern as !gg)
        profiles_ctx = _build_all_profiles_context()
        prompt = f"Question: {query}"
        if profiles_ctx:
            prompt += f"\n\n<player_profiles>\n{profiles_ctx}\n</player_profiles>"

        match_ctx = _build_match_context()
        if match_ctx:
            prompt += f"\n\n<match_context>\n{match_ctx}\n</match_context>"

        try:
            answer = await loop.run_in_executor(
                None,
                lambda: cloud_llm.safe_ask(
                    prompt, system=GG_SYSTEM_PROMPT, max_tokens=REPLY_MAX_TOKENS
                ),
            )
        except Exception as exc:
            print(f"[listen] LLM error: {exc}")
            return

        # Speak the answer
        await _speak_step(vc, answer, guild_id)

        # Also post a text embed for reference
        short = answer[:2000] if len(answer) > 2000 else answer
        embed = discord.Embed(
            title=f"\U0001f3a4 {user.display_name}: {query[:150]}",
            description=short,
            color=C_GG,
        )
        await ctx.send(embed=embed)

    # Build and start the sink
    sink = voice_listen.WakeSink(loop, on_utterance)
    vc.listen(sink)

    trainer_sessions[guild_id] = {"vc": vc, "listen": True, "sink": sink}

    if mode == "test":
        await ctx.send(
            f"\U0001f399️ Listening in **{channel.name}** (test mode) — "
            "I'll post every transcript here. Say anything!"
        )
    else:
        await ctx.send(
            f"\U0001f399️ Listening in **{channel.name}**. "
            f"Say “**{WAKE_WORD.title()}, <your question>**” to get an answer. "
            "Use `!listen stop` to disconnect."
        )


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online and ready.")
    print(f"   Commands: !draft  !teams  !lobby  !reset  !civ  !has  !counter")
    print(f"             !eco  !build  !random  !hotkeys  !trainer")
    print(f"             !mygames  !coach  !ask  !gg  !listen")
    start_savegame_watcher()


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"⚠️ Missing argument. Try `!help {ctx.command.name}`.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Could not find that member. Make sure you @mention them.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Ignore unknown commands silently
    else:
        await ctx.send(f"❌ An error occurred: `{error}`")
        raise error


# ─────────────────────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        raise ValueError("DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here")
    bot.run(TOKEN)
