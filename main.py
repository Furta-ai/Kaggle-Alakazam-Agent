# ==============================================================================
# main.py - MULTI-AGENT ROUTER & ALAKAZAM CORE (KAGGLE-COMPATIBLE)
# ==============================================================================

import os
import sys
import random

# ------------------------------------------------------------------------------
# SETUP PATH: Assicura che la directory corrente sia accessibile
# ------------------------------------------------------------------------------
try:
    _AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    _AGENT_DIR = "/kaggle_simulations/agent"
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

from cg.api import Observation, to_observation_class, OptionType, SelectType

# ==============================================================================
# 1. RILEVAMENTO DINAMICO DEL MAZZO (ROUTER)
# ==============================================================================

def get_our_deck_ids() -> list[int]:
    """Legge il file deck.csv caricando in modo robusto i 60 ID delle carte."""
    candidates = []
    try:
        candidates.append(os.path.join(_AGENT_DIR, "deck.csv"))
    except Exception:
        pass
    candidates += ["deck.csv", "/kaggle_simulations/agent/deck.csv", "sample_submission/deck.csv"]
    for path in candidates:
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r") as file:
                ids = []
                for ln in file:
                    ln = ln.replace(',', ' ').strip()
                    for x in ln.split():
                        if x.lstrip("-").isdigit():
                            ids.append(int(x))
            if len(ids) >= 60:
                return ids[:60]
        except Exception:
            continue
    return []

def detect_our_active_archetype(deck_ids: list[int]) -> str:
    """Rileva l'archetipo che stiamo giocando analizzando le carte chiave."""
    if not deck_ids:
        print(">>> ROUTER: mazzo vuoto o non leggibile, fallback: alakazam")
        return "alakazam"
    
    unique_ids = set(deck_ids)
    
    # Firme dei mazzi
    if 190 in unique_ids or 169 in unique_ids:
        return "archaludon"  # Duraludon (169) / Archaludon ex (190)
    elif 345 in unique_ids or 344 in unique_ids:
        return "crustle"     # Dwebble (344) / Crustle (345)
    elif 270 in unique_ids or 271 in unique_ids:
        return "iono"        # Tadbulb / Bellibolt (Iono)
    elif 743 in unique_ids or 741 in unique_ids:
        return "alakazam"    # Abra (741) / Alakazam (743)
    
    return "pool"            # Altri mazzi generici gestiti da pool_agents

_DETECTED_ARCHETYPE = None
_MY_DECK_CSV = None
_AGENTS_CACHE = {}

def get_agent_for_archetype(archetype: str):
    """Importa dinamicamente l'agente solo quando necessario."""
    if archetype in _AGENTS_CACHE:
        return _AGENTS_CACHE[archetype]
    
    try:
        if archetype == "archaludon":
            import archaludon_agent as mod
            print(">>> ROUTER: Caricato Agente ARCHALUDON (archaludon_agent.py)")
        elif archetype == "crustle":
            import crustle_agent as mod
            print(">>> ROUTER: Caricato Agente CRUSTLE (crustle_agent.py)")
        elif archetype == "iono":
            import iono_agent as mod
            print(">>> ROUTER: Caricato Agente IONO (iono_agent.py)")
        else:
            import pool_agents as mod
            print(">>> ROUTER: Caricato Agente POOL (pool_agents.py)")
            
        _AGENTS_CACHE[archetype] = mod
        return mod
    except ImportError as e:
        print(f">>> ROUTER: Errore importazione agente {archetype}: {e}. Fallback su Alakazam.")
        return None

# ==============================================================================
# 2. LOGICA AGENTE ALAKAZAM (GAMESTATEPARSER ORIGINALE)
# ==============================================================================

# Database degli attacchi scaling (dal tuo source: 5)
SCALING_ATTACK_DATABASE = {
    743: {
        'name': 'Alakazam',
        'scaling_attacks': [{
            'name': 'Powerful Hand',
            'text': 'Place 2 damage counters on your opponent\'s Active Pokémon for each card in your hand.',
            'base_damage': 0, 'scale_type': 'hand_size', 'scale_value': 20,
        }]
    },
    521: {
        'name': 'Elgyem',
        'scaling_attacks': [{
            'name': 'Brainstorm',
            'text': 'Does 10 damage for each card in your hand.',
            'base_damage': 0, 'scale_type': 'hand_size', 'scale_value': 10,
        }]
    },
    142: {'name': 'Genesect', 'scaling_attacks': []},
    140: {'name': 'Fezandipiti ex', 'scaling_attacks': []},
    66:  {'name': 'Dudunsparce', 'scaling_attacks': []},
}

def get_scaling_attack_info(pokemon_id: int) -> list:
    pokemon = SCALING_ATTACK_DATABASE.get(pokemon_id)
    return pokemon.get('scaling_attacks', []) if pokemon else []

def calculate_scaling_damage(pokemon_id: int, hand_count: int) -> int:
    attacks = get_scaling_attack_info(pokemon_id)
    max_damage = 0
    for attack in attacks:
        if attack.get('scale_type') == 'hand_size':
            damage = attack.get('base_damage', 0) + (attack.get('scale_value', 0) * hand_count)
            if damage > max_damage: max_damage = damage
    return max_damage

# Tutta la logica e le funzioni di supporto Alakazam (Semplificate e incorporate)
class GameStateParser:
    def __init__(self):
        self.opp_known_hand = []
        self.opp_deck_prediction = "Sconosciuto"
        self.opp_deck_key = None
        self.game_plan = "setup"
        self.turn_counter = 0
        self.current_turn_number = -1
        self.actions_this_turn = 0
        self.my_state = None
        self.opp_state = None
        
        # Flags base
        self.has_abra, self.has_kadabra, self.has_alakazam = False, False, False
        self.has_dunsparce, self.has_dudunsparce = False, False
        self.abra_in_play, self.kadabra_in_play = False, False
        self.energy_count, self.energy_on_alakazam, self.energy_on_abra, self.energy_on_active = 0, 0, 0, 0
        self.abra_in_hand, self.kadabra_in_hand, self.alakazam_in_hand, self.rare_candy_in_hand = False, False, False, False
        self.win_condition_found = None
        
        self.good_active_pokemon = {305, 66, 343, 222, 142, 140, 521}
        self.pokemon_cards = {741, 742, 743, 305, 66, 343, 222, 142, 140, 521, 343}
        self.ability_map = {
            741: (True, "Abra - Teleport"), 742: (True, "Kadabra - Teleport"),
            743: (False, "Alakazam - Psychic Draw"), 66: (False, "Dudunsparce - Excavate")
        }
        
    def check_immediate_win_condition(self) -> dict:
        if not self.my_state or not self.opp_state or not self.opp_state.active or not self.opp_state.active[0]:
            return None
        hand_count = len(self.my_state.hand)
        opp_hp = getattr(self.opp_state.active[0], 'hp', 0)
        
        if self.abra_in_play and self.rare_candy_in_hand:
            dmg = calculate_scaling_damage(743, hand_count)
            if dmg >= opp_hp: return {'action': 'win_condition', 'message': f'Vittoria Mind Jack ({dmg})'}
        return None

    def should_use_abra_ability(self) -> bool:
        if not self.my_state: return False
        if self.rare_candy_in_hand and (self.alakazam_in_hand or self.kadabra_in_hand): return False
        return True # Fallback di base

    def get_option_type(self, option):
        return getattr(option, 'type', option.get('type', 14) if isinstance(option, dict) else 14)

    def get_option_area(self, option):
        return getattr(option, 'area', option.get('area', 0) if isinstance(option, dict) else 0)

    def get_option_index(self, option):
        return getattr(option, 'index', option.get('index', 0) if isinstance(option, dict) else 0)

    def get_option_card_id(self, option):
        if not self.my_state: return None
        opt_type = self.get_option_type(option)
        idx = self.get_option_index(option)
        area = self.get_option_area(option)
        
        if opt_type == OptionType.PLAY and idx is not None and 0 <= idx < len(self.my_state.hand):
            return self.my_state.hand[idx].id
        if area == 2 and idx is not None and 0 <= idx < len(self.my_state.hand):
            return self.my_state.hand[idx].id
        if area == 4 and self.my_state.active and self.my_state.active[0]:
            return self.my_state.active[0].id
        if area == 5 and idx is not None and 0 <= idx < len(self.my_state.bench):
            return self.my_state.bench[idx].id
        return None

    def is_ability_safe(self, option) -> bool:
        cid = self.get_option_card_id(option)
        if cid in self.ability_map and self.ability_map[cid][0]:
            return len(self.my_state.bench) > 0 if self.my_state.bench else False
        return True

    def is_safe_to_remove_active(self, option) -> bool:
        if not self.my_state.active or not self.my_state.active[0]: return True
        if self.my_state.bench and len(self.my_state.bench) > 0: return True
        opt_type = self.get_option_type(option)
        if opt_type == OptionType.RETREAT: return False
        if opt_type == OptionType.ABILITY: return self.is_ability_safe(option)
        return True

    def update(self, obs: Observation):
        if not obs.current: return
        me = obs.current.yourIndex
        opp = 1 - me
        if obs.current.turn != self.current_turn_number:
            self.current_turn_number = obs.current.turn
            self.actions_this_turn = 0
            self.turn_counter += 1
            
        self.my_state = obs.current.players[me]
        self.opp_state = obs.current.players[opp]
        self.win_condition_found = self.check_immediate_win_condition()
        
        # Semplificazione update per sicurezza: rileva carte in mano e in gioco
        self.rare_candy_in_hand = any(c.id == 1079 for c in self.my_state.hand) if self.my_state.hand else False
        self.alakazam_in_hand = any(c.id == 743 for c in self.my_state.hand) if self.my_state.hand else False
        self.kadabra_in_hand = any(c.id == 742 for c in self.my_state.hand) if self.my_state.hand else False
        self.abra_in_hand = any(c.id == 741 for c in self.my_state.hand) if self.my_state.hand else False
        
        pokes = []
        if self.my_state.active and self.my_state.active[0]: pokes.append(self.my_state.active[0])
        pokes.extend([p for p in self.my_state.bench if p])
        self.abra_in_play = any(p.id == 741 for p in pokes)
        self.has_alakazam = any(p.id == 743 for p in pokes)

# Variabile Globale Parser Alakazam
parser = None

def score_alakazam_option(option, P: GameStateParser) -> float:
    opt_type = P.get_option_type(option)
    cid = P.get_option_card_id(option)
    
    if P.win_condition_found and opt_type in [OptionType.EVOLVE, OptionType.PLAY, OptionType.ATTACK]:
        return 9999.0
        
    if opt_type == OptionType.EVOLVE and cid == 1079 and P.abra_in_play: return 2000.0 # Rare Candy
    if opt_type == OptionType.PLAY and cid == 741 and P.rare_candy_in_hand: return 1900.0
    if opt_type == OptionType.EVOLVE and P.has_abra and P.kadabra_in_hand: return 1500.0
    
    if opt_type == OptionType.ATTACK:
        return 1500.0 if P.has_alakazam else 500.0
        
    if opt_type == OptionType.PLAY and cid == 1086: return 900.0 # Poffin
    if opt_type == OptionType.PLAY and cid in [1225, 1231]: return 800.0 # Support pescata
    
    if opt_type == OptionType.ABILITY:
        return 800.0 if P.is_ability_safe(option) else -5000.0
        
    if opt_type == OptionType.END: return -100.0
    if not P.is_safe_to_remove_active(option): return -9999.0
    return 150.0 + (random.random() * 0.1)

def run_alakazam_agent(obs_dict: dict, P: GameStateParser) -> list[int]:
    obs = to_observation_class(obs_dict)
    if obs.select is None or not obs.select.option: return []
    
    P.update(obs)
    options = obs.select.option
    
    if obs.select.type == SelectType.MAIN:
        P.actions_this_turn += 1
        if P.actions_this_turn > 15:
            for i, opt in enumerate(options):
                if P.get_option_type(opt) == OptionType.END: return [i]
            return [0]
            
        scored = sorted(((i, score_alakazam_option(o, P)) for i, o in enumerate(options)),
                        key=lambda x: x[1], reverse=True)
        return [scored[0][0]] if scored else [0]
    else:
        # Contesti di sottomenù semplici (Setup, Attivo, ecc)
        scored_options = []
        for i, opt in enumerate(options):
            score = 0.5
            cid = P.get_option_card_id(opt)
            if cid in (743, 742, 741): score += 1.0 # Preferisci linea Alakazam
            if cid in (305, 66): score += 0.5       # Poi Dunsparce
            scored_options.append((i, score + random.random() * 0.05))
            
        scored_options.sort(key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in scored_options[:obs.select.maxCount]]

# ==============================================================================
# 3. ENTRY POINT KAGGLE (ROUTER PRINCIPALE)
# ==============================================================================

def agent(obs_dict: dict) -> list[int]:
    """Router principale. Identifica il mazzo, importa e lancia l'agente corretto."""
    global _DETECTED_ARCHETYPE, _MY_DECK_CSV, parser
    
    # 1. SETUP INIZIALE E RILEVAMENTO MAZZO
    if _MY_DECK_CSV is None:
        _MY_DECK_CSV = get_our_deck_ids()
        _DETECTED_ARCHETYPE = detect_our_active_archetype(_MY_DECK_CSV)
        print(f">>> MULTI-ROUTER: Rilevato archetipo attivo per il nostro Mazzo: [{_DETECTED_ARCHETYPE.upper()}]")
    
    obs = to_observation_class(obs_dict)
    if obs.select is None:
        return _MY_DECK_CSV

    # 2. INSTRADAMENTO VERSO ALAKAZAM
    if _DETECTED_ARCHETYPE == "alakazam":
        if parser is None:
            parser = GameStateParser()
        return run_alakazam_agent(obs_dict, parser)

    # 3. INSTRADAMENTO VERSO AGENTI ESTERNI (Crustle, Archaludon, Iono)
    active_agent_mod = get_agent_for_archetype(_DETECTED_ARCHETYPE)
    
    if active_agent_mod is None:
        # Fallback in caso l'agente esterno sia rotto o mancante
        if parser is None: parser = GameStateParser()
        return run_alakazam_agent(obs_dict, parser)
        
    try:
        # Se usiamo il POOL (es. deck sconosciuto)
        if _DETECTED_ARCHETYPE == "pool":
            return active_agent_mod.agent(obs_dict, "crustle")
            
        # Per gli altri agenti standard (archaludon_agent, crustle_agent)
        return active_agent_mod.agent(obs_dict)
        
    except Exception as e:
        print(f">>> ROUTER CRASH nell'agente {_DETECTED_ARCHETYPE}: {e}. Fallback emergenza.")
        if parser is None: parser = GameStateParser()
        return run_alakazam_agent(obs_dict, parser)