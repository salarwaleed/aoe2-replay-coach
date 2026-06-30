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

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

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
# ECO GUIDE DATA  (gather rates accurate to AoE2 DE, apply 1:1 to 1.6)
# ─────────────────────────────────────────────────────────────────────────────
# Base gather rates (no upgrades, per second):
#   Farming: 0.34 food/s | Foraging: 0.31 | Gold: 0.38 | Wood: 0.39 | Stone: 0.36
# Production costs per unit:
#   Villager: 50 food, 25s train
#   Knight:   60f 75g  | Crossbow: 25w 45g | M@A: 60f 20g
#   Stable:   needs ≥1 farmer & ≥1 gold miner per knight slot
ECO_GUIDE = {
    "1TC_constant": {
        "label": "1 TC constant villager production",
        "cost": "50 food / 25s",
        "vills_needed": 5,
        "note": "5 farmers (on farms) give ~1.7 food/s, which covers 1 vill every 25s.",
    },
    "2TC_constant": {
        "label": "2 TC constant villager production",
        "cost": "100 food / 25s",
        "vills_needed": 10,
        "note": "~10 farmers to sustain both TCs. Each extra TC needs 5 more farmers.",
    },
    "knights_1stable": {
        "label": "1 Stable constant Knight production",
        "cost": "60f + 75g / 30s",
        "food_vills": 3,
        "gold_vills": 4,
        "note": "3 farmers (food) + 4 gold miners. Knights cost 60f/75g on 30s timer.",
    },
    "crossbow_1range": {
        "label": "1 Range constant Crossbow production",
        "cost": "25w + 45g / 27s",
        "wood_vills": 2,
        "gold_vills": 3,
        "note": "2 lumberjacks + 3 gold miners. Crossbows cost 25w/45g on 27s timer.",
    },
    "knight_2stable": {
        "label": "2 Stables constant Knight production",
        "cost": "120f + 150g / 30s",
        "food_vills": 6,
        "gold_vills": 7,
        "note": "6 farmers + 7 gold miners. Scale linearly: +3f +4g per additional stable.",
    },
    "dark_age_target": {
        "label": "Dark Age distribution target (pre-Feudal, 22-pop)",
        "split": "6 food (sheep/boar) → 4 wood → 6 food (farms) → 3 gold → 2 stone → 1 idle at TC",
        "note": (
            "Classic 22-pop Feudal:\n"
            "  Vills 1-6  → sheep\n"
            "  Vills 7-10 → wood\n"
            "  Vill 11    → boar lure (keeps food flowing)\n"
            "  Vills 12-17 → food (boar/sheep) + lure 2nd boar at ~14\n"
            "  Vills 18-21 → farm (build under TC fire range)\n"
            "  Vill 22    → gold (trigger Feudal)\n"
            "  Research Loom immediately after queuing Feudal."
        ),
    },
}

ECO_TABLE = """
```
╔════════════════════════════════╦══════════╦══════════╦══════════════════════════╗
║ Production Goal                ║ Food Vs  ║ Wood Vs  ║ Gold Vs                  ║
╠════════════════════════════════╬══════════╬══════════╬══════════════════════════╣
║ 1 TC constant vills            ║ 5 farms  ║ —        ║ —                        ║
║ 2 TC constant vills            ║ 10 farms ║ —        ║ —                        ║
║ 3 TC constant vills            ║ 15 farms ║ —        ║ —                        ║
╠════════════════════════════════╬══════════╬══════════╬══════════════════════════╣
║ 1 Stable constant Knights      ║ 3 farms  ║ —        ║ 4 miners                 ║
║ 2 Stables constant Knights     ║ 6 farms  ║ —        ║ 7 miners                 ║
║ 3 Stables constant Knights     ║ 9 farms  ║ —        ║ 11 miners                ║
╠════════════════════════════════╬══════════╬══════════╬══════════════════════════╣
║ 1 Range constant Crossbows     ║ —        ║ 2 woods  ║ 3 miners                 ║
║ 2 Ranges constant Crossbows    ║ —        ║ 4 woods  ║ 6 miners                 ║
╠════════════════════════════════╬══════════╬══════════╬══════════════════════════╣
║ 1 TC + 1 Stable (Knight boom)  ║ 8 farms  ║ —        ║ 4 miners                 ║
║ 1 TC + 2 Stables               ║ 11 farms ║ —        ║ 7 miners                 ║
╚════════════════════════════════╩══════════╩══════════╩══════════════════════════╝
Base gather rates (no upgrades): Farm 0.34/s  |  Wood 0.39/s  |  Gold 0.38/s
```
"""

# ─────────────────────────────────────────────────────────────────────────────
# BUILD ORDERS  (for !build command)
# ─────────────────────────────────────────────────────────────────────────────
BUILD_ORDERS = {
    "scouts": {
        "name": "Scout Rush (22-pop Feudal)",
        "color": 0x2ECC71,
        "steps": [
            "**Vills 1-6** → Sheep (build 2 houses while walking)",
            "**Vills 7-10** → Wood (build Lumber Camp)",
            "**Vill 11** → Boar lure (eat under TC fire)",
            "**Vills 12-17** → Mix sheep/boar food, lure 2nd boar at vill 14",
            "**Vills 18-21** → Build 4 Farms under TC",
            "**Vill 22** → Gold mine (build house + Mining Camp)",
            "**Click Feudal** at 22 pop — research Loom beforehand",
            "**In Feudal** → build Stable + Blacksmith with 2 forwarded vills",
            "**Research** Forging + Double-Bit Axe",
            "**Train scouts** as soon as Stable finishes",
            "**Raid enemy sheep** and wood line, deny scouting",
        ],
        "timing": "Feudal: ~9:30-10:00 | Scouts out: ~11:00",
    },
    "archers": {
        "name": "Archer Rush (22-pop Feudal)",
        "color": 0x3498DB,
        "steps": [
            "**Vills 1-6** → Sheep",
            "**Vills 7-10** → Wood (Lumber Camp)",
            "**Vill 11** → Boar lure",
            "**Vills 12-16** → Sheep/boar food",
            "**Vills 17-19** → Wood (second Lumber Camp or same)",
            "**Vills 20-21** → Farms",
            "**Vill 22** → Gold mine",
            "**Click Feudal** at 22 pop",
            "**In Feudal** → build 2 Archery Ranges with forwarded vills",
            "**Research** Fletching + Double-Bit Axe",
            "**Train 2 archers/range** continuously",
            "**Attack at ~18-20 archers**, focus villagers and TCs",
        ],
        "timing": "Feudal: ~9:30 | First archers: ~11:30 | Attack: ~14:00",
    },
    "maa": {
        "name": "Men-at-Arms into Archers",
        "color": 0xE67E22,
        "steps": [
            "**Vills 1-6** → Sheep",
            "**Vills 7-10** → Wood",
            "**Vill 11** → Boar lure",
            "**Vills 12-14** → Gold (Mining Camp early — key for M@A)",
            "**Vills 15-18** → Sheep/boar food",
            "**Vills 19-21** → Farms",
            "**Vill 22** → Wood",
            "**Click Feudal at 22 pop** — research Loom in Dark Age",
            "**Queue M@A upgrade immediately** on Feudal (research in Barracks, 100f/40g)",
            "**Send 4-5 M@A** to enemy early — they beat villagers, ignore archers badly",
            "**Meanwhile** build 1-2 Archery Ranges",
            "**Transition to Crossbows** in Castle Age",
        ],
        "timing": "Feudal: ~10:00 | M@A arrive: ~12:30 | Transition Castle: ~17:00",
    },
    "fast_castle": {
        "name": "Fast Castle (23-pop)",
        "color": 0x9B59B6,
        "steps": [
            "**Vills 1-6** → Sheep",
            "**Vills 7-10** → Wood",
            "**Vill 11** → Boar lure",
            "**Vills 12-17** → Sheep/boar/farms",
            "**Vills 18-21** → Gold (mining camp at gold)",
            "**Vill 22-23** → More food or wood",
            "**Click Feudal at 23 pop**",
            "**In Feudal** → build Market + Blacksmith ASAP with 2 forwarded vills",
            "**Click Castle Age** immediately (no military in Feudal)",
            "**Build Castle** on arrival — protect with walls",
            "**Train Knights** or unique units immediately",
            "**Research Bloodlines + Forging** in Castle Age",
        ],
        "timing": "Feudal: ~10:30 | Castle Age: ~15:30 | Knights out: ~17:00",
    },
    "drush_fc": {
        "name": "Dark Age Rush → Fast Castle (Drush FC)",
        "color": 0xE74C3C,
        "steps": [
            "**Vills 1-6** → Sheep",
            "**Vills 7-9** → Wood",
            "**Vill 10** → Boar lure",
            "**Vills 11-12** → Build 2 Barracks (Drush requires Barracks in Dark Age)",
            "**Train 3 Militia** (60f/20g each) — send straight to enemy",
            "**Militia harass** villagers, slow down enemy eco",
            "**Vills 13-17** → Gold rush",
            "**Vills 18-21** → Farms",
            "**Click Feudal at 21-22 pop**",
            "**In Feudal** build only Market + Blacksmith → skip to Castle immediately",
            "**Castle Age** with knights as your payoff",
        ],
        "timing": "Feudal: ~10:30 | Castle: ~16:00",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# TRAINER VOICE STEPS  (for !trainer command — spoken aloud in VC via gTTS)
# ─────────────────────────────────────────────────────────────────────────────
TRAINER_STEPS = [
    "Step 1. Game start. Your first 3 villagers go to sheep immediately. No exceptions.",
    "Step 2. Queue your 4th, 5th, and 6th villagers while walking. Watch for your first house — build it now.",
    "Step 3. Villagers 7 through 10 go to the nearest wood line. Build a Lumber Camp.",
    "Step 4. Villager 11 lures the first boar. Walk him to the boar, click attack, then immediately run back under your Town Center fire.",
    "Step 5. Villagers 12 through 17 go to food — sheep, boar, or forage bush depending on what is available.",
    "Step 6. Lure your second boar at villager 14. Same rule — attack it and run back to the Town Center.",
    "Step 7. Villagers 18 through 21 build farms directly under your Town Center. Four farms minimum.",
    "Step 8. Villager 22 goes to gold. Build a Mining Camp. This triggers your Feudal Age click.",
    "Step 9. Click Feudal Age now. Research Loom first if you haven't already. You should be at 22 population.",
    "Step 10. While aging up, send 2 villagers forward near the enemy base to prepare your military buildings.",
    "Step 11. When Feudal hits, build your military buildings immediately with the forwarded villagers.",
    "Step 12. In Castle Age, your goal is 3 Town Centers with constant villager production. That needs 15 farmers plus your gold miners.",
    "Step 13. Never let your Town Center go idle. The moment you have enough food, queue a villager. This is the most important habit.",
    "Step 14. Use your Select All Town Centers hotkey — press it every 10 to 15 seconds. Queue a villager. Make this muscle memory.",
    "Step 15. Go to idle villager frequently. Every idle second is lost economy. No idle villagers after minute 5.",
    "Congratulations. You have completed the economy trainer. Repeat this daily until it is automatic.",
]

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

@bot.command(name="eco")
async def eco(ctx: commands.Context, *, query: str = None):
    """
    !eco               — Full reference table
    !eco 3tc           — Exact vill split for 3 TCs + constant knight/archer production
    !eco 4tc           — 4 TC boom split
    !eco knights       — How many vills for 1-3 stables of knights
    !eco archers       — How many vills for 1-2 ranges of crossbows
    !eco boom          — Aggressive boom: fastest path to 3-4 TCs
    !eco rush          — Eco floor for all-in aggression
    !eco short food    — Fix a food shortage right now
    !eco short wood    — Fix a wood shortage right now
    !eco short gold    — Fix a gold shortage right now
    """
    if query is None:
        embed = discord.Embed(
            title="🌾 Eco Reference — 1.6 Villager Allocation",
            description=ECO_TABLE,
            color=C_ECO,
        )
        embed.add_field(
            name="💡 Dark Age Target (22-pop Feudal)",
            value=(
                "Vills 1-6 → Sheep\n"
                "Vills 7-10 → Wood\n"
                "Vill 11 → Boar lure (eat under TC)\n"
                "Vills 12-17 → Food (sheep/boar)\n"
                "Vills 18-21 → Farms\n"
                "Vill 22 → Gold (click Feudal)"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔍 In-game shortcuts",
            value=(
                "`!eco 3tc` · `!eco 4tc` · `!eco knights` · `!eco archers`\n"
                "`!eco boom` · `!eco rush` · `!eco short food/wood/gold`"
            ),
            inline=False,
        )
        embed.set_footer(text="Gather rates: Farm 0.34/s | Wood 0.39/s | Gold 0.38/s | Stone 0.36/s")
        await ctx.send(embed=embed)
        return

    q = query.lower().strip()

    # ── SHORT [resource] ──────────────────────────────────────────────────────
    if q.startswith("short"):
        resource = q.replace("short", "").strip()
        fixes = {
            "food": (
                "🌾 **Running low on food?**",
                [
                    "**Immediate:** Pull 2-3 gold miners → drop them on your nearest farm cluster.",
                    "**Check:** Are all farms adjacent to a Mill? Non-adjacent farms waste walk time.",
                    "**Rule of thumb:** Each TC needs 5 farmers to produce constantly. If you have 3 TCs, you need 15 farms staffed.",
                    "**Late game:** Research Heavy Plow + Crop Rotation to raise farm yield without extra vills.",
                    "**Emergency:** Drop a Market and sell 200 wood → 150ish food. Costs eco but saves a timing.",
                ],
                "Farm 0.34 food/s per villager (no upgrades). Wheelbarrow adds ~10%.",
            ),
            "wood": (
                "🪵 **Running low on wood?**",
                [
                    "**Immediate:** Shift 3-4 food/gold vills → nearest Lumber Camp. Chop the closest trees first.",
                    "**Check:** Have you researched Double-Bit Axe and Bow Saw? Those are +15% and +20% respectively — huge.",
                    "**Farms eat wood:** Each farm costs 60w. If you're booming farms, you need a big wood bank first.",
                    "**Wood floor:** Keep at least 2 dedicated lumberjacks per farm you intend to build.",
                    "**Emergency:** Sell 200 stone at Market for ~100 wood if you have stone surplus.",
                ],
                "Wood 0.39/s per villager (no upgrades). Double-Bit Axe → +15%, Bow Saw → +20%.",
            ),
            "gold": (
                "💰 **Running low on gold?**",
                [
                    "**Immediate:** Shift 2-3 food or wood vills → gold mine. Prioritise closer mines.",
                    "**Check:** Did you research Gold Mining and Gold Shaft Mining? That's +15% and +30% total.",
                    "**Relics:** 1 relic = ~0.5 gold/s. Grabbing 3 relics = ~1.5 gold/s — equivalent to ~4 miners.",
                    "**Trade:** Set up a Market + Trade Cart route if you're in late Castle/Imperial — safe passive income.",
                    "**Emergency:** Sell excess food or wood at the Market for gold.",
                    "**Turk tip:** Turkish players get Gold Shaft Mining free — switch to them if this is a recurring problem.",
                ],
                "Gold 0.38/s per villager. Gold Shaft Mining (Imperial): +30% total over base.",
            ),
            "stone": (
                "🪨 **Running low on stone?**",
                [
                    "**Shift vills:** Move 2-3 vills to stone. Research Stone Mining + Stone Shaft Mining ASAP.",
                    "**Prioritise:** Stone goes to Castles (650 stone each) and Town Centers (275 stone). Plan ahead.",
                    "**Market:** Sell food or wood for stone if you're mid-siege and need a Castle now.",
                    "**Korean bonus:** Koreans mine stone 20% faster — great civ if you plan to wall/castle heavily.",
                ],
                "Stone 0.36/s per villager. Stone Shaft Mining adds +15%.",
            ),
        }
        if resource not in fixes:
            await ctx.send(f"❌ Unknown resource `{resource}`. Try: `!eco short food`, `!eco short wood`, `!eco short gold`, `!eco short stone`.")
            return
        title, steps, footer = fixes[resource]
        embed = discord.Embed(title=f"🚨 Eco Fix: {title}", color=C_COUNTER)
        embed.add_field(name="What to do RIGHT NOW", value="\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)), inline=False)
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)
        return

    # ── TC COUNT SPLITS ───────────────────────────────────────────────────────
    tc_splits = {
        "2tc": {
            "title": "2 TC Boom Split",
            "description": "Standard Castle Age eco — sustain 2 TCs + 1 stable knights.",
            "split": [
                "🌾 **~18 Farmers** (farms under both TCs — aim for Mill adjacency)",
                "🪵 **8-10 Lumberjacks** (sustain farm builds + houses)",
                "💰 **6-8 Gold Miners** (1 stable knights needs 4 miners)",
                "🪨 **0-2 Stone** (only if building a Castle or 3rd TC)",
            ],
            "notes": "Drop 2nd TC at ~16:00. Immediately staff it with 4-5 farmers. Knights out of 1 stable.",
            "vills_total": "~35-40 villagers",
        },
        "3tc": {
            "title": "3 TC Aggressive Boom",
            "description": "The sweet spot for dominating the mid-game. Forces a timing window before enemy can mass an army.",
            "split": [
                "🌾 **22-25 Farmers** (5 per TC minimum = 15, extras absorb boom)",
                "🪵 **10-12 Lumberjacks** (wood for farms + buildings)",
                "💰 **10-12 Gold Miners** (2 stables = 7 miners; 3 stables = 11 miners)",
                "🪨 **2-3 Stone** (for 3rd TC at 275 stone or a Castle at 650)",
            ],
            "notes": (
                "Build 3rd TC at ~20:00 as you hit ~45 pop. "
                "Pair with 2 stables — you'll have Knights and constant vills. "
                "Attack window: ~24:00 with 10+ knights."
            ),
            "vills_total": "~50-55 villagers",
        },
        "4tc": {
            "title": "4 TC Full Boom",
            "description": "Maximum eco pressure. Win by out-producing everything.",
            "split": [
                "🌾 **28-32 Farmers** (20 base + extras on boom)",
                "🪵 **12-15 Lumberjacks** (heavy farm build queue)",
                "💰 **12-15 Gold Miners** (3 stables + upgrades)",
                "🪨 **0-2 Stone** (only for extra TC/Castle — sell rest at Market)",
            ],
            "notes": (
                "4th TC at ~24-26:00. You need ~900 stone total (275×3 extra TCs + Castle). "
                "By 30 min you should have 70+ vills and 3 stables pumping Knights. "
                "Wall up while booming — you are vulnerable until ~22 min."
            ),
            "vills_total": "~65-75 villagers at peak",
        },
    }
    if q in tc_splits:
        d = tc_splits[q]
        embed = discord.Embed(title=f"🏘️ {d['title']}", description=d["description"], color=C_ECO)
        embed.add_field(name="Villager Split", value="\n".join(d["split"]), inline=False)
        embed.add_field(name="📌 Notes", value=d["notes"], inline=False)
        embed.set_footer(text=f"Total vills: {d['vills_total']} | Farm 0.34/s | Wood 0.39/s | Gold 0.38/s")
        await ctx.send(embed=embed)
        return

    # ── PRODUCTION GOALS ─────────────────────────────────────────────────────
    if q in ("knights", "knight"):
        embed = discord.Embed(title="🐴 Knight Production Eco", color=C_ECO)
        embed.add_field(name="Per Stable (constant Knights, 30s each)", value=(
            "🌾 **3 farmers** for food (60f/30s = 2.0 food/s needed, 3 farms = 1.02/s → use surplus from TC food)\n"
            "💰 **4 gold miners** for gold (75g/30s = 2.5 gold/s needed, 4 miners = 1.52/s — supplement with 1 extra if short)\n"
            "**Practical:** 3 farms + 5 gold miners per stable is safer with no eco upgrades."
        ), inline=False)
        embed.add_field(name="Scale-up", value=(
            "1 Stable → 3 farms + 5 gold\n"
            "2 Stables → 6 farms + 9 gold\n"
            "3 Stables → 10 farms + 13 gold\n"
            "*(Plus 5 farms per TC for vill production)*"
        ), inline=False)
        embed.add_field(name="⚡ Aggressive tip", value=(
            "Going 3 stables at Castle Age entry? You need ~25 farmers + 13 gold miners just for knights + 2 TCs. "
            "Pre-build your gold mines and farms in Feudal so the switch is instant."
        ), inline=False)
        embed.set_footer(text="Bloodlines + Forging first. Then Castle → stables. Never idle your stables.")
        await ctx.send(embed=embed)
        return

    if q in ("archers", "archer", "crossbow", "crossbows"):
        embed = discord.Embed(title="🏹 Archer/Crossbow Production Eco", color=C_ECO)
        embed.add_field(name="Per Range (constant Crossbows, 27s each)", value=(
            "🪵 **2 lumberjacks** for wood (25w/27s ≈ 0.93 wood/s, 2 cutters = 0.78/s — top up with 1 extra early)\n"
            "💰 **3 gold miners** for gold (45g/27s ≈ 1.67 gold/s, 3 miners = 1.14/s — use 4 if no Gold Mining)\n"
            "**Practical:** 3 wood + 4 gold per range until Bow Saw is researched."
        ), inline=False)
        embed.add_field(name="Scale-up", value=(
            "1 Range → 3 wood + 4 gold\n"
            "2 Ranges → 5 wood + 7 gold\n"
            "3 Ranges → 8 wood + 11 gold\n"
            "*(Plus 5 farms per TC for vill production)*"
        ), inline=False)
        embed.add_field(name="⚡ Aggressive tip", value=(
            "2 ranges in Feudal is standard archer rush. "
            "Your wood line is your lifeline — never let it drop below 4 cutters while archers are pumping."
        ), inline=False)
        embed.set_footer(text="Fletching → Bodkin Arrow → Bracer. Research in that order. Never skip.")
        await ctx.send(embed=embed)
        return

    if q == "boom":
        embed = discord.Embed(
            title="💥 Aggressive Boom — Fastest Path to Dominance",
            description="This is the fastest way to get to 3 TCs + 3 stables without dying.",
            color=C_ECO,
        )
        embed.add_field(name="Timeline", value=(
            "🌑 **Dark Age** → 22-pop Feudal (9:30-10:00)\n"
            "⚔️ **Feudal** → Build Market + Blacksmith only. Skip military. Click Castle immediately.\n"
            "🏰 **Castle entry (~15:30)** → Drop 2nd TC + 1 Castle + 1 Stable simultaneously.\n"
            "⚡ **16-18 min** → Drop 2nd Stable as vill count hits 40.\n"
            "💪 **20-22 min** → Drop 3rd TC + 3rd Stable. You now have the strongest eco on the map."
        ), inline=False)
        embed.add_field(name="Vill distribution at 3 TCs", value=(
            "🌾 22+ Farmers | 🪵 10 Lumberjacks | 💰 11 Gold Miners | 🪨 2-3 Stone\n"
            "*(Adjust: if attacked, pull 5 gold miners → army support. Never stop TC production.)*"
        ), inline=False)
        embed.add_field(name="⚠️ Wall while you boom", value=(
            "You are **wide open** from min 12 to min 20. "
            "Use 2 villagers to lay stone walls around your base at ~11:30. "
            "This buys you 3-4 minutes against scouts/archers."
        ), inline=False)
        embed.set_footer(text="3 TCs + 3 stables at 20 min = game over for most opponents.")
        await ctx.send(embed=embed)
        return

    if q == "rush":
        embed = discord.Embed(
            title="⚔️ Eco Floor for All-In Aggression",
            description="Minimum eco to keep your army alive while pressuring hard.",
            color=C_COUNTER,
        )
        embed.add_field(name="Minimum eco while rushing", value=(
            "🌾 **10-12 Farmers** (enough for 1 TC + food drain of army)\n"
            "🪵 **6 Lumberjacks** (farms + buildings)\n"
            "💰 **5-6 Gold Miners** (keep military funded)\n"
            "⚠️ Do NOT go below this or your army dies mid-fight with no follow-up."
        ), inline=False)
        embed.add_field(name="What to do if your rush fails", value=(
            "1. Do NOT panic-idle your TC.\n"
            "2. Pull 2 gold miners → farms immediately.\n"
            "3. Add 2 more lumberjacks → prepare a 2nd TC.\n"
            "4. Use the pressure you created to buy time for a boom.\n"
            "5. Type `!eco 3tc` for the boom target to aim for."
        ), inline=False)
        embed.set_footer(text="Rushing is a timing attack, not a strategy. Always have an eco backup plan.")
        await ctx.send(embed=embed)
        return

    # ── FALLTHROUGH ───────────────────────────────────────────────────────────
    opts = "`!eco` · `!eco 2tc` · `!eco 3tc` · `!eco 4tc` · `!eco knights` · `!eco archers` · `!eco boom` · `!eco rush` · `!eco short food/wood/gold/stone`"
    await ctx.send(f"❌ Unknown eco query `{query}`.\nTry: {opts}")


BUILD_META = {
    "scouts": {
        "category": "🗡️ Aggressive",
        "tagline": "Fast pressure in Feudal. Scout harass denies enemy sheep, slows eco.",
        "attack":  "Hit enemy sheep line and wood line at ~11:00. Kill vills, not scouts.",
        "counter": "Enemy Spearman shuts down scouts. Transition to Archers if countered.",
        "defense": "Wall your base. Spearman + TC fire holds scout rush easily.",
        "best_civs": "Mongols, Franks, Magyars, Georgians",
    },
    "archers": {
        "category": "🗡️ Aggressive",
        "tagline": "Most common competitive opening. 2 ranges in Feudal, then 3+ in Castle.",
        "attack":  "Focus enemy villagers. Stay at max range. Micro back when Skirms appear.",
        "counter": "Skirmishers hard-counter archers. Mix in Swordsmen to zone Skirms.",
        "defense": "Skirms + Spears + TC fire beats archer rush. Walling limits angles.",
        "best_civs": "Britons, Mayans, Ethiopians, Vietnamese, Mongols",
    },
    "maa": {
        "category": "🗡️ Aggressive",
        "tagline": "Feudal Men-at-Arms pressure, then transition to Crossbows in Castle.",
        "attack":  "M@A kill vills and force bad fights. Follow up with Crossbows in Castle Age.",
        "counter": "Enemy Spearman + TC fire. If they have Spears + Skirms you must pull back.",
        "defense": "Spearman behind TC fire + walls. M@A can't breach walls without siege.",
        "best_civs": "Japanese, Goths, Vikings, Teutons, Bulgarians",
    },
    "fast_castle": {
        "category": "🏰 Boom",
        "tagline": "Skip Feudal military, Castle Age by ~15:30. Knights or unique unit payoff.",
        "attack":  "Castle entry timing: immediately drop Knights at ~17:00. Hit before walls are up.",
        "counter": "Enemy fast Feudal pressure (archers/scouts) can punish the boom window.",
        "defense": "Wall in Feudal. TC + 2-4 Spearman holds most rushes long enough.",
        "best_civs": "Franks, Persians, Lithuanians, Huns, Slavs",
    },
    "drush_fc": {
        "category": "🗡️ Aggressive Boom",
        "tagline": "Dark Age Militia rush slows enemy, then skip straight to Castle Age. Best of both.",
        "attack":  "3 Militia harass at ~8:00. Don't over-commit — pull back and boom.",
        "counter": "Enemy wall early and Militia die to TC fire. Risky if scouted.",
        "defense": "Walls in Dark Age completely neutralise Militia. Hard counter.",
        "best_civs": "Aztecs, Mayans, Slavs, Celts, Vikings",
    },
}

@bot.command(name="build")
async def build_order(ctx: commands.Context, *, opening: str = None):
    """
    !build               — Show all openings overview with attack/counter/defense angles
    !build scouts        — Full step-by-step scout rush build order
    !build archers       — Archer rush build order
    !build maa           — Men-at-Arms → Crossbow build order
    !build fast_castle   — Fast Castle / Knight boom
    !build drush_fc      — Dark Rus Militia → Fast Castle
    """
    if opening is None:
        embed = discord.Embed(
            title="🏗️ Build Orders — Strategy Overview",
            description="Pick an opening based on your civ and the situation. Click a name for full steps.",
            color=C_BUILD,
        )
        for key, meta in BUILD_META.items():
            bo = BUILD_ORDERS[key]
            embed.add_field(
                name=f"{meta['category']}  ·  `!build {key}`  ·  {bo['name']}",
                value=(
                    f"📌 {meta['tagline']}\n"
                    f"⚔️ **Attack:** {meta['attack']}\n"
                    f"🛡️ **Counter:** {meta['counter']}\n"
                    f"🏰 **Defense vs this:** {meta['defense']}\n"
                    f"🏅 **Best civs:** {meta['best_civs']}\n"
                    f"⏱️ {bo['timing']}"
                ),
                inline=False,
            )
        embed.set_footer(text="Type !build <name> for the full step-by-step build order.")
        await ctx.send(embed=embed)
        return

    key  = opening.lower().replace(" ", "_").replace("-", "_")
    data = BUILD_ORDERS.get(key)

    if data is None:
        close = [k for k in BUILD_ORDERS if opening.lower() in k]
        if not close:
            await ctx.send(f"❌ Build order `{opening}` not found. Type `!build` to see all options.")
            return
        key  = close[0]
        data = BUILD_ORDERS[key]

    meta  = BUILD_META.get(key, {})
    embed = discord.Embed(title=f"🏗️ {data['name']}", color=data["color"])

    if meta:
        embed.description = (
            f"⚔️ **Attack angle:** {meta['attack']}\n"
            f"🛡️ **How to counter this:** {meta['counter']}\n"
            f"🏰 **Defense vs this:** {meta['defense']}"
        )

    embed.add_field(name="Build Steps", value="\n".join(data["steps"]), inline=False)

    if meta.get("best_civs"):
        embed.add_field(name="🏅 Best civs for this", value=meta["best_civs"], inline=False)

    embed.set_footer(text=f"⏱️ {data['timing']}")
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


@bot.command(name="trainer")
async def trainer(ctx: commands.Context):
    """!trainer — Bot joins your VC and narrates the eco build order step by step. Type !next to advance."""
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
            f"Joined **{vc.name}**. Starting narration.\n\n"
            f"Total steps: **{len(TRAINER_STEPS)}**\n"
            "Type `!next` to advance manually, or `!trainer stop` to end."
        ),
        color=C_ECO,
    )
    await ctx.send(embed=embed)

    step = 0
    while step < len(TRAINER_STEPS) and guild_id in trainer_sessions:
        trainer_sessions[guild_id]["step"] = step
        text = TRAINER_STEPS[step]

        # Send text to channel so player can read along
        await ctx.send(
            embed=discord.Embed(
                title=f"🔊 Step {step + 1} / {len(TRAINER_STEPS)}",
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

    if step >= len(TRAINER_STEPS):
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
PROFILES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles.json")


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


def _build_profiles(games: list[dict]) -> dict:
    """Aggregate per-player stats across all parsed games."""
    raw: dict[str, dict] = defaultdict(lambda: {
        "games": 0, "wins": 0,
        "civs": defaultdict(int),
        "maps": defaultdict(int),
        "durations": [],
        "last_seen": "",
    })

    for g in games:
        if "error" in g:
            continue
        for p in g.get("players", []):
            name = p["name"]
            r = raw[name]
            r["games"] += 1
            if p["winner"]:
                r["wins"] += 1
            r["civs"][p["civ"]] += 1
            r["maps"][g["map"]] += 1
            if g["duration_min"]:
                r["durations"].append(g["duration_min"])
            if g["date"] > r["last_seen"]:
                r["last_seen"] = g["date"]

    profiles: dict[str, dict] = {}
    for name, r in raw.items():
        win_rate = round(r["wins"] / r["games"] * 100) if r["games"] else 0
        avg_len  = round(sum(r["durations"]) / len(r["durations"]), 1) if r["durations"] else None

        civs_sorted = sorted(r["civs"].items(), key=lambda x: -x[1])
        maps_sorted = sorted(r["maps"].items(), key=lambda x: -x[1])

        # Simple weakness heuristics based on available stats
        weaknesses = []
        if win_rate < 40:
            weaknesses.append("Win rate below 40% — review your Castle Age transition")
        if avg_len and avg_len > 35:
            weaknesses.append(f"Average game length {avg_len} min — games are going late, work on early pressure")
        if avg_len and avg_len < 12:
            weaknesses.append("Very short games — possibly early resigns, work on defensive play")
        civ_count = len(civs_sorted)
        if civ_count == 1:
            weaknesses.append(f"Only playing {civs_sorted[0][0]} — opponent can prepare a hard counter every game")
        if not weaknesses:
            weaknesses.append("No obvious weaknesses detected from available data")

        strengths = []
        if win_rate >= 60:
            strengths.append(f"Strong win rate ({win_rate}%)")
        if civ_count >= 4:
            strengths.append(f"Good civ variety ({civ_count} different civs played)")
        if avg_len and 18 <= avg_len <= 30:
            strengths.append(f"Efficient game pace ({avg_len} min avg) — strong mid-game")
        if not strengths:
            strengths.append("Keep playing — more data needed for strength analysis")

        profiles[name] = {
            "games":        r["games"],
            "wins":         r["wins"],
            "win_rate":     win_rate,
            "avg_game_min": avg_len,
            "favourite_civ":  civs_sorted[0][0] if civs_sorted else "Unknown",
            "civ_breakdown":  {k: v for k, v in civs_sorted[:5]},
            "favourite_map":  maps_sorted[0][0] if maps_sorted else "Unknown",
            "map_breakdown":  {k: v for k, v in maps_sorted[:5]},
            "last_seen":      r["last_seen"],
            "strengths":      strengths,
            "weaknesses":     weaknesses,
        }
    return profiles


def _load_profiles() -> dict:
    if os.path.exists(PROFILES_FILE):
        with open(PROFILES_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_profiles(profiles: dict):
    with open(PROFILES_FILE, "w", encoding="utf-8") as fh:
        json.dump(profiles, fh, indent=2, ensure_ascii=False)


@bot.command(name="analyze")
async def analyze(ctx: commands.Context):
    """!analyze — Scan all recorded games and build player profiles."""
    msg = await ctx.send("🔍 Scanning SaveGame folders for recordings…")

    recordings = _scan_recordings()
    if not recordings:
        await msg.edit(content="❌ No `.mgz` files found in your SaveGame folders.")
        return

    await msg.edit(content=f"📂 Found **{len(recordings)}** recordings. Parsing… (this may take 30-60 seconds)")

    games = []
    errors = 0
    skipped = 0
    for rec in recordings:
        parsed = await asyncio.get_event_loop().run_in_executor(None, _parse_recording, rec)
        if parsed is None:
            skipped += 1
            continue
        if "error" in parsed:
            errors += 1
        games.append(parsed)

    profiles = _build_profiles(games)
    _save_profiles(profiles)

    valid = len(games) - errors
    embed = discord.Embed(
        title="✅ Analysis Complete",
        description=(
            f"Parsed **{valid}/{len(recordings)}** recordings successfully."
            + (f" ({skipped} lobby/abandoned saves skipped)" if skipped else "")
        ),
        color=C_TEAMS,
    )
    embed.add_field(
        name="Players found",
        value="\n".join(
            f"**{name}** — {p['games']} games, {p['win_rate']}% WR, fav civ: {p['favourite_civ']}"
            for name, p in sorted(profiles.items(), key=lambda x: -x[1]["games"])
        ) or "No players found",
        inline=False,
    )
    if errors:
        embed.add_field(name="⚠️ Parse errors", value=f"{errors} files failed (run `pip install mgz` if not installed)", inline=False)
    embed.set_footer(text=f"Profiles saved to profiles.json | Use !profile <name> to view details")
    await msg.edit(content=None, embed=embed)


@bot.command(name="profile")
async def profile_cmd(ctx: commands.Context, *, player_name: str = None):
    """!profile [name] — Show a player's stats and strategic profile from recorded games."""
    profiles = _load_profiles()

    if not profiles:
        await ctx.send("❌ No profiles found. Run `!analyze` first.")
        return

    if player_name is None:
        names = ", ".join(f"`{n}`" for n in sorted(profiles.keys()))
        await ctx.send(f"Usage: `!profile PlayerName`\nKnown players: {names}")
        return

    # Fuzzy match
    key = next((k for k in profiles if k.lower() == player_name.lower()), None)
    if key is None:
        key = next((k for k in profiles if player_name.lower() in k.lower()), None)
    if key is None:
        await ctx.send(f"❌ Player `{player_name}` not found. Known: {', '.join(profiles.keys())}")
        return

    p = profiles[key]
    wr_icon = "🟢" if p["win_rate"] >= 55 else ("🟡" if p["win_rate"] >= 40 else "🔴")

    embed = discord.Embed(
        title=f"🧠 Strategic Profile: {key}",
        color=C_CIV,
    )
    embed.add_field(name="📊 Stats", value=(
        f"{wr_icon} **Win Rate:** {p['win_rate']}% ({p['wins']}/{p['games']} games)\n"
        f"⏱️ **Avg Game Length:** {p['avg_game_min']} min\n"
        f"🏅 **Favourite Civ:** {p['favourite_civ']}\n"
        f"🗺️ **Favourite Map:** {p['favourite_map']}\n"
        f"📅 **Last Seen:** {p['last_seen']}"
    ), inline=False)

    civ_breakdown = " · ".join(f"{c} ×{n}" for c, n in p["civ_breakdown"].items())
    embed.add_field(name="⚔️ Civs Played", value=civ_breakdown or "No data", inline=False)

    embed.add_field(
        name="✅ Strengths",
        value="\n".join(f"• {s}" for s in p["strengths"]),
        inline=False,
    )
    embed.add_field(
        name="⚠️ Weaknesses",
        value="\n".join(f"• {w}" for w in p["weaknesses"]),
        inline=False,
    )
    embed.set_footer(text="Run !analyze to refresh profiles after new games.")
    await ctx.send(embed=embed)


@bot.command(name="mygames")
async def mygames(ctx: commands.Context, *, player_name: str = None):
    """!mygames [name] — Show recent game history from recorded games."""
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

    embed = discord.Embed(
        title=f"📼 Recent Games{' for ' + player_name if player_name else ''}",
        color=C_DRAFT,
    )
    for g in results[:8]:
        winner_names = [p["name"] for p in g["players"] if p["winner"]]
        player_line = " vs ".join(
            f"**{p['name']}** ({p['civ']})" + (" 🏆" if p["winner"] else "")
            for p in g["players"]
        )
        embed.add_field(
            name=f"🗺️ {g['map']}  ·  {g['date']}  ·  {g['duration_min']} min",
            value=player_line,
            inline=False,
        )
    embed.set_footer(text=f"Showing last {len(results)} games from SaveGame folder")
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

    profiles = _load_profiles()
    target = player_name or ctx.author.display_name

    # Find profile (fuzzy)
    profile = None
    for k, v in profiles.items():
        if target.lower() in k.lower():
            profile = (k, v)
            break

    guild_id = ctx.guild.id
    if guild_id in trainer_sessions:
        old = trainer_sessions[guild_id].get("vc")
        if old and old.is_connected():
            await old.disconnect()

    vc_channel = ctx.author.voice.channel
    voice_client = await vc_channel.connect()
    trainer_sessions[guild_id] = {"vc": voice_client, "step": 0, "ctx": ctx}

    # Build personalised script
    script = [COACH_INTRO]

    if profile:
        name, p = profile
        script.append(
            f"I have found a profile for {name} with {p['games']} recorded games "
            f"and a {p['win_rate']} percent win rate."
        )
        script.append(
            f"Your favourite civilization is {p['favourite_civ']} "
            f"and your favourite map is {p['favourite_map']}."
        )
        for w in p["weaknesses"]:
            script.append(f"Area to improve: {w}")
        for s in p["strengths"]:
            script.append(f"Keep doing this: {s}")
    else:
        script.append(
            f"No profile found for {target}. Run exclamation mark analyze after your next games. "
            f"For now, I will give you general coaching."
        )

    script += COACH_GENERIC_TIPS
    script.append(
        "That concludes your coaching session. "
        "Type exclamation mark analyze after each game session to keep your profile updated. Good luck."
    )

    embed = discord.Embed(
        title=f"🎙️ Coach: {target}",
        description=f"Joined **{vc_channel.name}**. Delivering personalised coaching.\nType `!trainer stop` to end early.",
        color=C_ECO,
    )
    if profile:
        _, p = profile
        embed.add_field(name="Profile loaded", value=f"{p['games']} games · {p['win_rate']}% WR · {p['favourite_civ']}", inline=False)
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


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online and ready.")
    print(f"   Commands: !draft  !teams  !lobby  !reset  !civ  !has  !counter")
    print(f"             !eco  !build  !random  !hotkeys  !trainer")
    print(f"             !analyze  !profile  !mygames  !coach")


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
