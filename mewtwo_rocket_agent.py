import os, json, sys, time, random
from collections import defaultdict, Counter

from cg.api import AreaType, CardType, EnergyType, Observation, SelectContext, OptionType, Card, Pokemon, all_card_data, to_observation_class

"""
rocket_mewtwo_evo_perfect_crustle: L'agente definitivo per Team Rocket's Mewtwo ex.
- Rilevamento Letale (Giovanni's Gust per chiudere sui 2 premi).
- Assegnamento adattivo dei Tool (Bangle per i tank Fase 2, Cape per la sopravvivenza).
- Swarm dinamico per massimizzare i danni di Spidops.
- COUNTER CRUSTLE: Shift totale del setup su Spidops se l'avversario gioca la linea Crustle.
"""

WEIGHTS = {
    "play_proton_early": 25000, "play_proton_emergency": 35000,
    "play_mewtwo": 8000, "play_mewtwo_need": 15000,
    
    # Pesi dinamici per Tarountula / Spidops
    "play_tarountula": 7500, "play_tarountula_vs_crustle": 25000,
    "play_rocket_fill_spidops": 28000, 
    
    "play_articuno_base": 5000, "play_articuno_vs_alakazam": 30000,
    "play_mimikyu_base": 4000, "play_mimikyu_vs_tera": 25000,
    "play_sneasel": 3500,
    
    "factory_stadium": 28000,
    "transceiver_proton": 19000, "transceiver_draw": 15000, "transceiver_gust": 20000,
    "bug_catching": 16000,
    "ultra_ball_grass_discard": 17000, "ultra_ball_base": 12000,
    
    "ariana_draw": 17000,
    "giovanni_lethal": 100000, "giovanni_gust": 19000,
    "archer_disrupt": 14500,
    "xerosic_disrupt": 14000,

    "cape_mewtwo_base": 19500, "cape_mewtwo_vital": 30000,
    "bangle_mewtwo_base": 15000, "bangle_mewtwo_vs_tanks": 35000, 

    "energy_tr_articuno_vs_alakazam": 25000,
    "energy_tr_mewtwo": 22000,
    "energy_grass_mewtwo": 10000,
    "energy_grass_spidops": 12000, "energy_grass_spidops_vs_crustle": 26000,

    "evolve_spidops": 18000, "evolve_spidops_vs_crustle": 28000,
    "ability_spidops": 22000, 
    "ability_factory": 25000,
    
    "retreat_to_articuno": 25000,
    "retreat_to_spidops_vs_crustle": 26000,
    
    "attack_lethal": 100000, "attack_mewtwo": 20000,
    "attack_articuno_vs_alakazam": 30000,
    "attack_spidops_max": 22000, "attack_spidops_base": 12000,
    "attack_spidops_vs_crustle": 40000
}

W = WEIGHTS

# DECK HARDCODED (Team Rocket's Mewtwo ex) — nessun caricamento da deck.csv esterno
my_deck = ([1]*8 + [15]*4 + [400]*4 + [401]*4 + [414]*2 + [431]*2 + [434]*2 + [464]
           + [1094]*3 + [1121] + [1134]*4 + [1152]*4 + [1159] + [1175] + [1197]
           + [1216]*4 + [1217] + [1218]*3 + [1220]*4 + [1225]*2 + [1227] + [1257]*3)
assert len(my_deck) == 60, f"mewtwo deck {len(my_deck)}"

all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}

# IDs
Grass_Energy, TR_Energy = 1, 15
Tarountula, Spidops, Articuno, Mewtwo_ex, Mimikyu, Sneasel = 400, 401, 414, 431, 434, 464
Bug_Catching, Ultra_Ball, Transceiver, Poke_Pad = 1094, 1121, 1134, 1152
Heros_Cape, Brave_Bangle = 1159, 1175
Xerosic, Ariana, Archer, Giovanni, Proton, Hilda, Lillie_Det, TR_Factory = 1197, 1216, 1217, 1218, 1220, 1225, 1227, 1257

ROCKET_POKEMON = {Tarountula, Spidops, Articuno, Mewtwo_ex, Mimikyu, Sneasel}
ALAKAZAM_LINE = {741, 742, 743} 
TERA_POKEMON = {121, 125, 108, 169} 
CRUSTLE_LINE = {344, 345, 532} # ID della linea di Crustle (incluso Dwebble)

pre_turn = 0
ability_used_factory = False
ability_used_spidops = 0

def get_card(obs, area, index, player_index):
    ps = obs.current.players[player_index]
    match area:
        case AreaType.DECK: return obs.select.deck[index]
        case AreaType.HAND: return ps.hand[index]
        case AreaType.DISCARD: return ps.discard[index]
        case AreaType.ACTIVE: return ps.active[index]
        case AreaType.BENCH: return ps.bench[index]
        case AreaType.PRIZE: return ps.prize[index]
        case AreaType.STADIUM: return obs.current.stadium[index]
        case AreaType.LOOKING: return obs.current.looking[index]
        case _: return None

def heuristic_scores(obs):
    state = obs.current
    select = obs.select
    context = select.context
    my_index = state.yourIndex
    my_state = state.players[my_index]
    op_state = state.players[1 - my_index]

    global pre_turn, ability_used_factory, ability_used_spidops
    if pre_turn != state.turn:
        pre_turn = state.turn
        ability_used_factory = False
        ability_used_spidops = 0

    field_counts = defaultdict(int)
    hand_counts = defaultdict(int)
    discard_counts = defaultdict(int)
    my_field = []
    
    op_has_alakazam = False
    op_has_tera = False
    op_has_crustle = False
    op_active_is_crustle = False
    
    op_max_hp = 0
    op_has_lethal_target = False
    my_prize_count = len(my_state.prize)
    
    # Rilevamento Matchup Avversario
    for p in op_state.active + op_state.bench:
        if p:
            data = card_table[p.id]
            if p.id in ALAKAZAM_LINE: op_has_alakazam = True
            if p.id in CRUSTLE_LINE: op_has_crustle = True
            if p.id in TERA_POKEMON or "Tera" in data.name: op_has_tera = True
            if data.hp > op_max_hp: op_max_hp = data.hp
            
            # Controllo letale Boss/Giovanni
            if data.hp <= 280 and (data.ex or data.megaEx) and my_prize_count <= 2:
                op_has_lethal_target = True

    if op_state.active and op_state.active[0] and op_state.active[0].id in CRUSTLE_LINE:
        op_active_is_crustle = True

    for idx, card in enumerate(my_state.active):
        if card:
            field_counts[card.id] += 1
            my_field.append((0, card))
    for idx, card in enumerate(my_state.bench):
        if card:
            field_counts[card.id] += 1
            my_field.append((idx + 1, card))
            
    for card in my_state.hand: hand_counts[card.id] += 1
    for card in my_state.discard: discard_counts[card.id] += 1

    rockets_in_play = sum(field_counts[x] for x in ROCKET_POKEMON)
    power_saver_active = rockets_in_play < 4 
    spidops_needs_fill = rockets_in_play == 5 and my_state.active and my_state.active[0].id == Spidops
    
    bench_free = my_state.benchMax - len([b for b in my_state.bench if b])
    active_id = my_state.active[0].id if my_state.active else -1
    mewtwo_ready = active_id == Mewtwo_ex and not power_saver_active
    
    stadium_id = state.stadium[0].id if state.stadium else 0
    factory_up = stadium_id == TR_Factory

    scores = []
    for o in select.option:
        score = 0
        if o.type == OptionType.CARD:
            card = get_card(obs, o.area, o.index, o.playerIndex)
            if not card: scores.append(0); continue
            
            # --- Targeting Letale ---
            if context in (SelectContext.TARGET, SelectContext.CHOOSE_POKEMON) and o.playerIndex != my_index:
                data = card_table[card.id]
                hp_rim = card.hp
                is_2_prize = data.ex or data.megaEx
                
                if hp_rim <= 280 and is_2_prize and my_prize_count <= 2:
                    score = 100000 
                elif is_2_prize:
                    score = 30000
                elif hp_rim <= 180:
                    score = 15000
                else:
                    score = 1000

            # --- Discard Intelligente ---
            elif context == SelectContext.TO_DISCARD:
                if card.id == Grass_Energy: score = 25000 
                elif card.id == TR_Energy: score = -5000 
                elif card.cardType == CardType.POKEMON and card.id not in ROCKET_POKEMON: score = 15000
                else: score = 100

            # --- Setup ---
            elif context == SelectContext.SETUP_ACTIVE_POKEMON:
                if op_has_crustle and card.id == Tarountula: score = 60 # Shift primario su Tarountula vs Crustle
                elif op_has_alakazam and card.id == Articuno: score = 50
                elif op_has_tera and card.id == Mimikyu: score = 45
                elif card.id == Mewtwo_ex: score = 40
                elif card.id == Tarountula: score = 30
                else: score = 10
                
            elif context == SelectContext.SETUP_BENCH_POKEMON:
                if op_has_crustle and card.id == Tarountula: score = 110
                elif op_has_alakazam and card.id == Articuno: score = 100
                elif op_has_tera and card.id == Mimikyu: score = 90
                elif card.id == Tarountula: score = 80
                elif card.id == Mewtwo_ex: score = 70
                else: score = 50

            # --- Ricerca Mirata ---
            elif context == SelectContext.TO_HAND:
                if card.cardType == CardType.SUPPORTER:
                    if op_has_lethal_target and card.id == Giovanni and mewtwo_ready: score = 40000
                    elif power_saver_active and card.id == Proton: score = 30000
                    elif card.id == Ariana and hand_counts[Ariana] == 0: score = 15000
                    elif card.id == Giovanni and len(op_state.bench) > 0: score = 14000
                    elif card.id == Archer and op_state.handCount >= 5: score = 13000
                elif card.cardType == CardType.POKEMON:
                    # Rimodulazione ricerca contro Crustle
                    if op_has_crustle and card.id == Spidops and field_counts[Spidops] == 0: score = 210
                    elif op_has_crustle and card.id == Tarountula and field_counts[Tarountula] == 0: score = 205
                    elif spidops_needs_fill and card.id in ROCKET_POKEMON: score = 25000
                    elif op_has_alakazam and card.id == Articuno and field_counts[Articuno] == 0: score = 200
                    elif op_has_tera and card.id == Mimikyu and field_counts[Mimikyu] == 0: score = 190
                    elif card.id == Tarountula and field_counts[Tarountula] < 2: score = 180
                    elif card.id == Spidops and field_counts[Tarountula] > 0: score = 150
                    elif card.id == Mewtwo_ex and field_counts[Mewtwo_ex] == 0: score = 140
                elif card.id == TR_Energy: score = 160
                elif card.id == Grass_Energy: score = 100
                else: score = 10

        elif o.type == OptionType.PLAY:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            cid = card.id
            is_early = state.turn <= 2

            if card_table[cid].cardType == CardType.POKEMON:
                if spidops_needs_fill and cid in ROCKET_POKEMON: score = W["play_rocket_fill_spidops"]
                elif cid == Articuno: score = W["play_articuno_vs_alakazam"] if op_has_alakazam else W["play_articuno_base"]
                elif cid == Mimikyu: score = W["play_mimikyu_vs_tera"] if op_has_tera else W["play_mimikyu_base"]
                elif cid == Tarountula: score = W["play_tarountula_vs_crustle"] if op_has_crustle else W["play_tarountula"]
                elif cid == Mewtwo_ex: score = W["play_mewtwo_need"] if field_counts[Mewtwo_ex] == 0 else W["play_mewtwo"]
                elif cid == Sneasel: score = W["play_sneasel"]
                else: score = -1
                
            else:
                score = 500
                if cid == TR_Factory: 
                    score = -1 if factory_up else W["factory_stadium"]
                elif cid in (Proton, Ariana, Giovanni, Archer, Hilda):
                    if hand_counts[TR_Factory] > 0 and not factory_up: score -= 20000 
                    else:
                        if cid == Giovanni and op_has_lethal_target and mewtwo_ready: score = W["giovanni_lethal"]
                        elif cid == Giovanni: score = W["giovanni_gust"] if len(op_state.bench) > 0 else -1
                        elif cid == Proton: 
                            if power_saver_active: score = W["play_proton_emergency"]
                            elif is_early: score = W["play_proton_early"]
                            else: score = -1
                        elif cid == Ariana: score = W["ariana_draw"]
                        elif cid == Archer: score = W["archer_disrupt"] if op_state.handCount >= 5 else -1
                elif cid == Transceiver: 
                    if op_has_lethal_target and mewtwo_ready: score = W["transceiver_gust"]
                    elif power_saver_active: score = W["transceiver_proton"] 
                    else: score = W["transceiver_draw"]
                elif cid == Bug_Catching: score = W["bug_catching"]
                elif cid == Ultra_Ball: score = W["ultra_ball_grass_discard"] if hand_counts[Grass_Energy] > 0 else W["ultra_ball_base"]
                
                elif cid == Brave_Bangle:
                    score = W["bangle_mewtwo_vs_tanks"] if op_max_hp > 280 else W["bangle_mewtwo_base"]
                elif cid == Heros_Cape:
                    score = W["cape_mewtwo_vital"] if op_max_hp <= 280 else W["cape_mewtwo_base"]

        elif o.type == OptionType.ATTACH:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            pokemon = get_card(obs, o.inPlayArea, o.inPlayIndex, my_index)
            
            if card.id == TR_Energy:
                if op_has_alakazam and pokemon.id == Articuno: score = W["energy_tr_articuno_vs_alakazam"]
                elif pokemon.id == Mewtwo_ex: score = W["energy_tr_mewtwo"]
                else: score = 500
            elif card.id == Grass_Energy:
                if op_has_crustle and pokemon.id == Spidops: score = W["energy_grass_spidops_vs_crustle"]
                elif pokemon.id == Mewtwo_ex: score = W["energy_grass_mewtwo"]
                elif pokemon.id == Spidops: score = W["energy_grass_spidops"]
                else: score = 500
            elif card.id == Heros_Cape and pokemon.id == Mewtwo_ex: score = W["cape_mewtwo_vital"]
            elif card.id == Brave_Bangle and pokemon.id == Mewtwo_ex: score = W["bangle_mewtwo_vs_tanks"] if op_max_hp > 280 else W["bangle_mewtwo_base"]

        elif o.type == OptionType.EVOLVE:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            if card.id == Spidops: score = W["evolve_spidops_vs_crustle"] if op_has_crustle else W["evolve_spidops"]
            else: score = 500

        elif o.type == OptionType.ABILITY:
            card = get_card(obs, o.area, o.index, my_index)
            if card.id == Spidops and ability_used_spidops < field_counts[Spidops]:
                if discard_counts[Grass_Energy] > 0: score = W["ability_spidops"]
                else: score = -1
            elif card.id == TR_Factory and not ability_used_factory:
                score = W["ability_factory"]
            else:
                score = -1

        elif o.type == OptionType.RETREAT:
            if op_has_crustle and field_counts[Spidops] > 0 and active_id != Spidops: score = W["retreat_to_spidops_vs_crustle"]
            elif op_has_alakazam and field_counts[Articuno] > 0 and active_id != Articuno: score = W["retreat_to_articuno"]
            elif op_has_tera and field_counts[Mimikyu] > 0 and active_id != Mimikyu: score = W["retreat_to_articuno"] 
            elif active_id not in (Mewtwo_ex, Articuno, Spidops, Mimikyu): score = 5000
            else: score = -1

        elif o.type == OptionType.ATTACK:
            score = 1000
            
            # Non attaccare con Mewtwo ex se Crustle attivo è immune ai danni degli ex
            if op_active_is_crustle and active_id == Mewtwo_ex:
                score = -5000 
            else:
                # Controllo Letale immediato
                if op_state.active and op_state.active[0]:
                    active_op = op_state.active[0]
                    is_ex = card_table[active_op.id].ex or card_table[active_op.id].megaEx
                    if active_op.hp <= 280 and is_ex and my_prize_count <= 2 and active_id == Mewtwo_ex and not power_saver_active:
                        score = W["attack_lethal"]
                        
                if score != W["attack_lethal"]:
                    if op_active_is_crustle and active_id == Spidops: score = W["attack_spidops_vs_crustle"]
                    elif op_has_alakazam and active_id == Articuno: score = W["attack_articuno_vs_alakazam"]
                    elif op_has_tera and active_id == Mimikyu: score = 25000
                    elif active_id == Mewtwo_ex and not power_saver_active: score = W["attack_mewtwo"]
                    elif active_id == Spidops: score = W["attack_spidops_max"] if rockets_in_play >= 6 else W["attack_spidops_base"]
            
        scores.append(score)
    return scores

def _post_pick(obs, picked_idx):
    global ability_used_factory, ability_used_spidops
    sel = obs.select
    if sel.context != SelectContext.MAIN: return
    o = sel.option[picked_idx]
    if o.type == OptionType.ABILITY:
        card = get_card(obs, o.area, o.index, obs.current.yourIndex)
        if card is not None:
            if card.id == TR_Factory: ability_used_factory = True
            elif card.id == Spidops: ability_used_spidops += 1

def _agent_impl(obs_dict):
    obs = to_observation_class(obs_dict)
    if obs.select is None: return my_deck
    scores = heuristic_scores(obs)
    desc = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    if desc: _post_pick(obs, desc[0])
    return desc[:obs.select.maxCount]

def _heuristic_agent(obs_dict):
    try: return _agent_impl(obs_dict)
    except:
        try:
            obs = to_observation_class(obs_dict)
            if obs.select is None: return my_deck
            n = len(obs.select.option)
            k = min(max(1, obs.select.minCount), n) if n else 0
            return list(range(k))
        except: return [0]

# ==================== SEARCH LAYER ====================
try:
    from cg.api import search_begin, search_step, search_end
    _SEARCH_IMPORT_OK = True
except Exception: _SEARCH_IMPORT_OK = False
    
USE_SEARCH = True
N_DET = 3
K_OPP = 3
MAX_SUBSTEPS = 40
TIME_BUDGET_S = 0.80
SEARCH_MAX_OPTS = 24
_MAX_CAND = 8
DUMMY_BASIC = 400 
DUMMY_ENERGY = 1  

_search_ok = _SEARCH_IMPORT_OK
_search_reported = False

_TEMPLATES = []
for _d in ("/kaggle_simulations/agent/top20_decks", "top20_decks", "../top20_decks", os.path.join(os.path.dirname(os.path.abspath(".")), "top20_decks")):
    if os.path.isdir(_d):
        for _fn in sorted(os.listdir(_d)):
            if not _fn.endswith(".csv"): continue
            try:
                with open(os.path.join(_d, _fn)) as _f:
                    _ids = [int(x) for x in _f.read().split() if x.strip()][:60]
                if len(_ids) == 60: _TEMPLATES.append((_fn, Counter(_ids), _ids))
            except: pass
        break

_BASIC_ENERGY = {i: i for i in range(1, 9)}
def _pokemon_ids(counter): return {cid for cid in counter if card_table.get(cid) and card_table[cid].cardType == CardType.POKEMON}
_TEMPLATE_SIG = [(n, _pokemon_ids(c), c, ids) for (n, c, ids) in _TEMPLATES]

def _my_visible(state, me_i):
    me = state.players[me_i]
    seen = Counter()
    for c in (me.hand or []): seen[c.id] += 1
    for c in me.discard: seen[c.id] += 1
    for c in me.prize:
        if c is not None: seen[c.id] += 1
    for p in me.active + me.bench:
        if p is None: continue
        seen[p.id] += 1
        for c in p.energyCards: seen[c.id] += 1
        for c in p.tools: seen[c.id] += 1
        for c in p.preEvolution: seen[c.id] += 1
    if state.stadium and state.stadium[0].playerIndex == me_i: seen[state.stadium[0].id] += 1
    return seen

def _op_visible(state, op_i):
    op = state.players[op_i]
    seen = Counter()
    etype = Counter()
    for c in op.discard: seen[c.id] += 1
    for p in op.active + op.bench:
        if p is None: continue
        seen[p.id] += 1
        for c in p.energyCards: seen[c.id] += 1
        for c in p.tools: seen[c.id] += 1
        for c in p.preEvolution: seen[c.id] += 1
        for e in p.energies: etype[int(e)] += 1
    if state.stadium and state.stadium[0].playerIndex == op_i: seen[state.stadium[0].id] += 1
    for c in op.prize:
        if c is not None: seen[c.id] += 1
    return seen, etype

def _match_archetype(op_seen):
    op_mons = {cid for cid in op_seen if card_table.get(cid) and card_table[cid].cardType == CardType.POKEMON}
    if not op_mons or not _TEMPLATE_SIG: return None
    best, best_n = None, 0
    for name, sig, cnt, ids in _TEMPLATE_SIG:
        n = len(sig & op_mons)
        if n > best_n: best, best_n = (cnt, ids), n
    return best if best_n >= 1 else None

def _sample_hidden(state, me_i):
    me = state.players[me_i]
    op_i = 1 - me_i
    op = state.players[op_i]
    seen = _my_visible(state, me_i)
    remain = []
    for cid, n in Counter(my_deck).items(): remain.extend([cid] * max(0, n - seen.get(cid, 0)))
    n_prize_hidden = sum(1 for c in me.prize if c is None)
    need = me.deckCount + n_prize_hidden
    if len(remain) < need: remain += [DUMMY_ENERGY] * (need - len(remain))
    random.shuffle(remain)
    your_deck = remain[:me.deckCount]
    fill = iter(remain[me.deckCount:need])
    your_prize = [c.id if c is not None else next(fill, DUMMY_ENERGY) for c in me.prize]

    op_seen, etype = _op_visible(state, op_i)
    tpl = _match_archetype(op_seen)
    if tpl is not None:
        cnt, _ = tpl
        pool = []
        for cid, n in cnt.items(): pool.extend([cid] * max(0, n - op_seen.get(cid, 0)))
    else:
        etop = max(etype.items(), key=lambda x: x[1])[0] if etype else 7
        energy_id = _BASIC_ENERGY.get(etop, 7)
        top_card = max(op_seen.items(), key=lambda x: x[1])[0] if op_seen else None
        pool = ([top_card] * 30 if top_card else []) + [energy_id] * 30 + [DUMMY_BASIC] * 8
    n_op_prize_hidden = sum(1 for c in op.prize if c is None)
    op_need = op.deckCount + n_op_prize_hidden + op.handCount
    if len(pool) < op_need: pool += [DUMMY_ENERGY] * (op_need - len(pool))
    random.shuffle(pool)
    opponent_deck = pool[:op.deckCount]
    off = op.deckCount
    fill_op = iter(pool[off:off + n_op_prize_hidden])
    opponent_prize = [c.id if c is not None else next(fill_op, DUMMY_ENERGY) for c in op.prize]
    off += n_op_prize_hidden
    opponent_hand = pool[off:off + op.handCount]
    opponent_active = [DUMMY_BASIC] if (op.active and op.active[0] is None) else []
    return dict(your_deck=your_deck, your_prize=your_prize, opponent_deck=opponent_deck, opponent_prize=opponent_prize, opponent_hand=opponent_hand, opponent_active=opponent_active)

def _leaf_eval(state, me_i):
    if state is None: return 0.0
    if state.result is not None and state.result >= 0:
        if state.result == me_i: return 1e7
        if state.result == 2: return 0.0
        return -1e7
    me = state.players[me_i]
    op = state.players[1 - me_i]
    my_field = [p for p in (me.active + me.bench) if p]
    op_field = [p for p in (op.active + op.bench) if p]
    
    my_hp = sum(p.hp for p in my_field)
    op_hp = sum(p.hp for p in op_field)
    my_en = sum(len(p.energies) for p in my_field)
    op_en = sum(len(p.energies) for p in op_field)
    no_active = 0 if (me.active and me.active[0]) else 1
    
    return (1000.0 * (len(op.prize) - len(me.prize))
            + my_hp - op_hp
            + 5.0 * (my_en - op_en)
            - 4000.0 * no_active)

def _greedy_pick(obs):
    sel = obs.select
    n = len(sel.option)
    if n == 0: return [], []
    try: sc = heuristic_scores(obs)
    except: sc = list(range(n, 0, -1))
    order = sorted(range(n), key=lambda i: sc[i], reverse=True)
    k = max(min(sel.maxCount, n), min(max(1, sel.minCount), n))
    return order[:k], order

def _greedy_complete_turn(sid, cur, owner, deadline):
    for _ in range(MAX_SUBSTEPS):
        if time.monotonic() > deadline: return sid, cur
        cs = cur.current
        if cs is None or (cs.result is not None and cs.result >= 0): return sid, cur
        if cs.yourIndex != owner or cur.select is None: return sid, cur
        choice, _ = _greedy_pick(cur)
        if not choice: return sid, cur
        try: ss = search_step(sid, choice)
        except: return sid, cur
        sid, cur = ss.searchId, ss.observation
    return sid, cur

def _advance_forced(sid, cur, owner, deadline, limit=8):
    for _ in range(limit):
        if time.monotonic() > deadline: break
        cs = cur.current
        if cs is None or cur.select is None or cs.yourIndex != owner or cur.select.context == SelectContext.MAIN or (cs.result is not None and cs.result >= 0): break
        ch, _ = _greedy_pick(cur)
        if not ch: break
        try: ss = search_step(sid, ch)
        except: break
        sid, cur = ss.searchId, ss.observation
    return sid, cur

def _search_decide(obs, base_order, base_scores):
    global _search_ok, _search_reported
    if not (USE_SEARCH and _search_ok): return None
    st = obs.current
    sel = obs.select
    if st is None or sel is None or sel.context != SelectContext.MAIN: return None
    n = len(sel.option)
    if n < 3 or n > SEARCH_MAX_OPTS or st.turn < 2: return None
    if getattr(obs, "search_begin_input", None) is None:
        _search_ok = False
        return None

    me_i = st.yourIndex
    heur_top = base_order[0]
    cand = [heur_top]
    for i in base_order[1:]:
        if sel.option[i].type in (OptionType.ATTACK, OptionType.END): continue
        if base_scores[i] < 0: continue
        cand.append(i)
        if len(cand) >= _MAX_CAND: break
    if len(cand) < 2: return None

    t0 = time.monotonic()
    deadline = t0 + TIME_BUDGET_S
    acc = {i: 0.0 for i in cand}
    n_eval = {i: 0 for i in cand}
    began = False
    
    try:
        for det in range(N_DET):
            if time.monotonic() > deadline: break
            hidden = _sample_hidden(st, me_i)
            try:
                ss0 = search_begin(obs, **hidden)
                began = True
            except:
                _search_ok = False
                return None
            root_sid = ss0.searchId

            for idx in cand:
                if time.monotonic() > deadline: break
                try: ss = search_step(root_sid, [idx])
                except: continue
                sid1, cur = ss.searchId, ss.observation
                sid1, cur = _greedy_complete_turn(sid1, cur, me_i, deadline)
                cs = cur.current
                if cs is None or (cs.result is not None and cs.result >= 0) or cs.yourIndex == me_i or cur.select is None:
                    acc[idx] += _leaf_eval(cs, me_i)
                    n_eval[idx] += 1
                    continue
                sid1, cur = _advance_forced(sid1, cur, 1 - me_i, deadline)
                cs = cur.current
                if cs is None or cur.select is None or cur.select.context != SelectContext.MAIN or cs.yourIndex == me_i:
                    acc[idx] += _leaf_eval(cs, me_i)
                    n_eval[idx] += 1
                    continue
                
                _, op_order = _greedy_pick(cur)
                worst = None
                for k in range(min(K_OPP, len(op_order))):
                    if time.monotonic() > deadline: break
                    try: ss2 = search_step(sid1, [op_order[k]])
                    except: continue
                    sid2, cur2 = ss2.searchId, ss2.observation
                    sid2, cur2 = _greedy_complete_turn(sid2, cur2, 1 - me_i, deadline)
                    sid2, cur2 = _advance_forced(sid2, cur2, me_i, deadline, limit=6)
                    v = _leaf_eval(cur2.current, me_i)
                    worst = v if worst is None else min(worst, v)
                if worst is None: worst = _leaf_eval(cs, me_i)
                acc[idx] += worst
                n_eval[idx] += 1

            try: search_end()
            except: pass
            began = False

        n_top = n_eval.get(heur_top, 0)
        if n_top == 0: return None
        evaluated = [i for i in cand if n_eval[i] == n_top]
        avg = {i: acc[i] / n_eval[i] + 1e-6 * base_scores[i] for i in evaluated}
        best = max(evaluated, key=lambda i: avg[i])
        
        if best == heur_top or avg[best] < avg[heur_top] + 500.0: return None
        return best
    except: return None
    finally:
        if began:
            try: search_end()
            except: pass

def agent(obs_dict):
    global _search_ok
    try: obs = to_observation_class(obs_dict)
    except: return _heuristic_agent(obs_dict)
    if obs.select is None:
        _search_ok = _SEARCH_IMPORT_OK 
        return my_deck

    fallback = _heuristic_agent(obs_dict)
    sel = obs.select
    if sel.context != SelectContext.MAIN: return fallback
    
    try:
        base_scores = heuristic_scores(obs)
        n = len(sel.option)
        base_order = sorted(range(n), key=lambda i: base_scores[i], reverse=True)
    except: return fallback

    pick = _search_decide(obs, base_order, base_scores)
    if pick is None: return fallback
    return [pick]