import os, json, sys, time, random
from collections import defaultdict, Counter

from cg.api import AreaType, CardType, EnergyType, Observation, SelectContext, OptionType, Card, Pokemon, all_card_data, to_observation_class

"""
grimmsnarl_evo_perfect_crustle: Agente completo per il deck Marnie's Grimmsnarl ex.
Include:
- Targeting Letale (Boss's Orders su 2-prizer).
- Sinergia Danni Passivi (Froslass + Munkidori).
- COUNTER CRUSTLE: Sfrutta Morgrem come attaccante (non-ex) e i danni passivi di Munkidori; 
  ritira Grimmsnarl ex e blocca l'evoluzione dell'attaccante per aggirare l'immunità.
"""

# ---- Tunable priority weights ----
WEIGHTS = {
    "play_pokemon_base": 20000,
    "play_impidimp_early": 600, "play_impidimp_need": 200, "play_impidimp_extra": 50,
    "play_snorunt_early": 500, "play_snorunt_late": 100,
    "play_munkidori": 550, "play_munkidori_extra": 150,
    
    # Priority shift vs Crustle
    "play_snorunt_vs_crustle": 25000,
    "play_munkidori_vs_crustle": 24000,
    
    "play_shaymin": 100,
    "play_bench_penalty": 5000,

    "poffin_early": 18000, "poffin_fallback": 8000, "poffin_late": 4000,
    "pokepad_early": 17000, "pokepad_need": 14000, "pokepad_ok": 12000,
    "rare_candy": 16000,
    "night_stretcher_mon": 13000, "night_stretcher_energy": 11000,
    "unfair_stamp": 19500, "unfair_stamp_fallback": 5000,
    
    "boss_lethal": 100000, "boss_kill": 18000, "boss_stall": 1500,
    "lillie": 3400, "lillie_emergency": 15000,
    "dawn_emergency": 16500, "dawn": 3100,
    "xerosic_disrupt": 14000, "xerosic_ok": 3250,

    "spikemuth_gym": 18000, "spikemuth_gym_replace": 19000,

    "energy_munkidori_need": 9500, 
    "energy_grimmsnarl": 9000,
    "energy_impidimp": 8000,
    "energy_morgrem": 8500, "energy_morgrem_vs_crustle": 20000,
    "energy_retreat": 7000,

    "evolve_grimmsnarl": 15000, 
    "evolve_froslass": 12000, "evolve_froslass_vs_crustle": 25000,
    "evolve_morgrem": 10000, 
    "evolve_base": 9000,
    
    "ability_munkidori": 30000, 
    "ability_spikemuth": 25000, 
    "ability_default": 10000,
    
    "retreat_promote": 2000,
    "retreat_grimmsnarl_vs_crustle": 25000,
    
    "attack_lethal": 100000, "attack_base": 1000, 
    "attack_grimmsnarl": 5000, 
    "attack_morgrem": 1500, "attack_morgrem_vs_crustle": 30000
}

W = WEIGHTS

# DECK HARDCODED (Marnie's Grimmsnarl ex) — nessun caricamento da deck.csv esterno
my_deck = ([7]*10 + [103]*2 + [104]*2 + [112]*4 + [343] + [646]*4 + [647]*3 + [648]*3
           + [1079]*4 + [1080] + [1086]*4 + [1097]*2 + [1152]*4 + [1182]*3 + [1197]*2
           + [1227]*4 + [1231]*3 + [1259]*4)
assert len(my_deck) == 60, f"grimmsnarl deck {len(my_deck)}"

all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}

# ---- Core IDs ----
Basic_Dark_Energy = 7
Snorunt = 103
Froslass = 104
Munkidori = 112
Shaymin = 343
Impidimp = 646
Morgrem = 647
Grimmsnarl_ex = 648
Rare_Candy = 1079
Unfair_Stamp = 1080
Buddy_Buddy_Poffin = 1086
Night_Stretcher = 1097
Poke_Pad = 1152
Boss_Orders = 1182
Xerosic = 1197
Lillie_Det = 1227
Dawn = 1231
Spikemuth_Gym = 1259

GRIMMSNARL_LINE = {Impidimp, Morgrem, Grimmsnarl_ex}
FROSLASS_LINE = {Snorunt, Froslass}
CRUSTLE_LINE = {344, 345, 532} 

pre_turn = 0
ability_used_munkidori = 0

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

    global pre_turn, ability_used_munkidori
    if pre_turn != state.turn:
        pre_turn = state.turn
        ability_used_munkidori = 0

    my_prize_count = len(my_state.prize)
    deck_count = my_state.deckCount
    safe_draws = deck_count - my_prize_count - 1
    overdraw = safe_draws < 2
    
    field_counts = defaultdict(int)
    hand_counts = defaultdict(int)
    discard_counts = defaultdict(int)
    my_field = []
    
    op_has_crustle = False
    op_active_is_crustle = False
    op_has_lethal_target = False
    
    for p in op_state.active + op_state.bench:
        if p:
            data = card_table[p.id]
            if p.id in CRUSTLE_LINE: op_has_crustle = True
            if data.hp <= 280 and (data.ex or data.megaEx) and my_prize_count <= 2:
                op_has_lethal_target = True

    if op_state.active and op_state.active[0] and op_state.active[0].id in CRUSTLE_LINE:
        op_active_is_crustle = True
    
    for idx, card in enumerate(my_state.active):
        if card is not None:
            field_counts[card.id] += 1
            my_field.append((0, card))
    for idx, card in enumerate(my_state.bench):
        if card is not None:
            field_counts[card.id] += 1
            my_field.append((idx + 1, card))
            
    for card in my_state.hand: hand_counts[card.id] += 1
    for card in my_state.discard: discard_counts[card.id] += 1

    impidimp_line_on_field = sum(field_counts[x] for x in GRIMMSNARL_LINE)
    snorunt_line_on_field = sum(field_counts[x] for x in FROSLASS_LINE)
    munkidori_on_field = field_counts[Munkidori]
    
    bench_free = my_state.benchMax - len([b for b in my_state.bench if b])
    active_id = my_state.active[0].id if my_state.active else -1
    
    stadium_id = state.stadium[0].id if state.stadium else 0
    our_stadium_up = stadium_id == Spikemuth_Gym
    hand_size = len(my_state.hand) if my_state.hand else my_state.handCount

    scores = []
    for o in select.option:
        score = 0
        if o.type == OptionType.CARD:
            card = get_card(obs, o.area, o.index, o.playerIndex)
            if not card: scores.append(0); continue
            
            # --- 1. Logica di Targeting (Cecchino EX/V e Adrena Brain) ---
            if o.playerIndex != my_index and context in (SelectContext.TARGET, SelectContext.CHOOSE_POKEMON, SelectContext.TO_ACTIVE, SelectContext.SWITCH):
                max_hp = card_table[card.id].hp
                hp_rimanenti = card.hp
                is_ex_v = card_table[card.id].ex or card_table[card.id].megaEx
                
                if hp_rimanenti <= 30 and is_ex_v: score = 50000 
                elif hp_rimanenti <= 30: score = 30000
                elif hp_rimanenti <= 160: score = 10000
                else: score = 1000

            # --- 2. Setup Base ---
            elif context == SelectContext.SETUP_ACTIVE_POKEMON:
                if op_has_crustle and card.id == Snorunt: score = 60
                elif card.id == Snorunt: score = 15
                elif card.id == Shaymin: score = 12
                elif card.id == Impidimp: score = 10
                elif card.id == Munkidori: score = 5
                else: score = 1
                
            elif context == SelectContext.SETUP_BENCH_POKEMON:
                if op_has_crustle and card.id == Snorunt: score = 110
                elif op_has_crustle and card.id == Munkidori: score = 105
                elif card.id == Munkidori: score = 100 - (munkidori_on_field * 20)
                elif card.id == Impidimp: score = 90 - (impidimp_line_on_field * 15)
                elif card.id == Snorunt: score = 80 - (snorunt_line_on_field * 30)

            # --- 3. Ricerca Carte ---
            elif context == SelectContext.TO_HAND:
                if op_has_crustle and card.id == Froslass and field_counts[Snorunt] > 0: score = 200
                elif op_has_crustle and card.id == Munkidori and munkidori_on_field < 2: score = 190
                elif card.id == Grimmsnarl_ex: score = 150 if field_counts[Impidimp] > 0 else 50
                elif card.id == Froslass: score = 120 if field_counts[Snorunt] > 0 else 40
                elif card.id == Munkidori: score = 100 if munkidori_on_field < 2 else 30
                elif card.id == Basic_Dark_Energy: score = 80 if not state.energyAttached else 20
                else: score = 10

        elif o.type == OptionType.PLAY:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            is_early = state.turn <= 2
            cid = card.id
            data = card_table[cid]

            if data.cardType == CardType.POKEMON:
                if cid == Impidimp:
                    if is_early: score = W["play_impidimp_early"]
                    elif impidimp_line_on_field < 3: score = W["play_impidimp_need"]
                    elif bench_free <= 1: score = -1
                    else: score = W["play_impidimp_extra"]
                elif cid == Snorunt:
                    if op_has_crustle: score = W["play_snorunt_vs_crustle"]
                    elif snorunt_line_on_field < 2: score = W["play_snorunt_early"] if is_early else W["play_snorunt_late"]
                    else: score = -1
                elif cid == Munkidori:
                    if op_has_crustle and munkidori_on_field < 3: score = W["play_munkidori_vs_crustle"]
                    else: score = W["play_munkidori"] if munkidori_on_field < 2 else W["play_munkidori_extra"]
                else:
                    score = -1

                if bench_free <= 1 and score > 0 and cid != Impidimp:
                    score -= W["play_bench_penalty"]
            else:
                score = 10000
                if cid == Buddy_Buddy_Poffin:
                    if safe_draws < 2: score = -1
                    elif is_early: score = W["poffin_early"] if (impidimp_line_on_field < 3 or snorunt_line_on_field < 1) else W["poffin_fallback"]
                    else: score = W["poffin_late"] if (impidimp_line_on_field < 3 or snorunt_line_on_field < 2) else -1
                elif cid == Poke_Pad:
                    if safe_draws < 1 or overdraw: score = -1
                    elif is_early: score = W["pokepad_early"]
                    else: score = W["pokepad_need"] if impidimp_line_on_field < 3 else W["pokepad_ok"]
                elif cid == Rare_Candy:
                    score = W["rare_candy"] if (field_counts[Impidimp] >= 1 and hand_counts[Grimmsnarl_ex] >= 1 and safe_draws >= 3) else -1
                elif cid == Night_Stretcher:
                    dis_mons = sum(discard_counts[x] for x in GRIMMSNARL_LINE | FROSLASS_LINE | {Munkidori, Shaymin})
                    if dis_mons >= 1: score = W["night_stretcher_mon"]
                    elif discard_counts[Basic_Dark_Energy] >= 1: score = W["night_stretcher_energy"]
                    else: score = -1
                elif cid == Boss_Orders:
                    if len(my_field) <= 1: score = -1
                    elif op_has_lethal_target: score = W["boss_lethal"]
                    else: score = W["boss_kill"]
                elif cid == Dawn:
                    if overdraw: score = -1
                    elif len(my_field) <= 1 and safe_draws >= 3: score = W["dawn_emergency"]
                    elif safe_draws >= 3: score = W["dawn"]
                    else: score = -1
                elif cid == Lillie_Det:
                    if safe_draws < 6: score = -1
                    elif hand_size <= (5 if my_prize_count == 6 else 3): score = W["lillie"]
                    else: score = -1
                elif cid == Xerosic:
                    score = W["xerosic_disrupt"] if op_state.handCount >= 6 else -1
                elif cid == Unfair_Stamp:
                    score = W["unfair_stamp"] if op_state.handCount >= 4 else -1
                elif cid == Spikemuth_Gym:
                    if our_stadium_up: score = -1
                    elif stadium_id != 0: score = W["spikemuth_gym_replace"]
                    else: score = W["spikemuth_gym"]

        elif o.type == OptionType.ATTACH:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            pokemon = get_card(obs, o.inPlayArea, o.inPlayIndex, my_index)
            
            if card.id == Basic_Dark_Energy:
                if pokemon.id == Munkidori and len(pokemon.energyCards) == 0:
                    score = W["energy_munkidori_need"]
                elif op_has_crustle and pokemon.id == Morgrem:
                    score = W["energy_morgrem_vs_crustle"] # Potenzia Morgrem contro Crustle
                elif pokemon.id == Grimmsnarl_ex:
                    score = W["energy_grimmsnarl"]
                elif pokemon.id in (Impidimp, Morgrem):
                    score = W["energy_impidimp"]
                else:
                    score = 100

        elif o.type == OptionType.EVOLVE:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            pokemon = get_card(obs, o.inPlayArea, o.inPlayIndex, my_index)
            
            if card.id == Grimmsnarl_ex:
                # SE CRUSTLE E' ATTIVO E MORGREM E' IL NOSTRO ATTIVO: NON EVOLVERE!
                if op_active_is_crustle and pokemon.id == Morgrem and o.inPlayArea == AreaType.ACTIVE:
                    score = -5000
                else:
                    score = W["evolve_grimmsnarl"]
            elif card.id == Froslass: 
                score = W["evolve_froslass_vs_crustle"] if op_has_crustle else W["evolve_froslass"]
            elif card.id == Morgrem: 
                score = W["evolve_morgrem"]
            else: 
                score = W["evolve_base"]

        elif o.type == OptionType.ABILITY:
            card = get_card(obs, o.area, o.index, my_index)
            if card.id == Munkidori and ability_used_munkidori < munkidori_on_field:
                score = W["ability_munkidori"]
            elif card.id == Spikemuth_Gym:
                score = W["ability_spikemuth"]
            else:
                score = W["ability_default"]

        elif o.type == OptionType.RETREAT:
            active = my_state.active[0] if my_state.active else None
            if active:
                max_hp = card_table[active.id].hp
                # Se siamo di fronte a Crustle e abbiamo Grimmsnarl ex, SCAPPA
                if op_active_is_crustle and active.id == Grimmsnarl_ex and (field_counts[Morgrem] > 0 or munkidori_on_field > 0):
                    score = W["retreat_grimmsnarl_vs_crustle"]
                elif active.hp < max_hp and munkidori_on_field > 0 and active.id != Grimmsnarl_ex:
                    score = W["retreat_promote"] + 5000
                elif active.id in (Snorunt, Impidimp, Munkidori, Froslass, Shaymin) and field_counts[Grimmsnarl_ex] > 0:
                    score = W["retreat_promote"]
                else:
                    score = -1

        elif o.type == OptionType.ATTACK:
            score = W["attack_base"]
            
            if op_state.active and op_state.active[0]:
                active_op = op_state.active[0]
                is_ex = card_table[active_op.id].ex or card_table[active_op.id].megaEx
                if active_op.hp <= 260 and is_ex and my_prize_count <= 2 and active_id == Grimmsnarl_ex and not op_active_is_crustle:
                    score = W["attack_lethal"]
            
            if score != W["attack_lethal"]:
                if op_active_is_crustle and active_id == Grimmsnarl_ex:
                    score = -5000 # DANNO 0, evita
                elif op_active_is_crustle and active_id == Morgrem:
                    score = W["attack_morgrem_vs_crustle"] # EROE NON-EX
                elif active_id == Grimmsnarl_ex: 
                    score = W["attack_grimmsnarl"]
                elif active_id == Morgrem: 
                    score = W["attack_morgrem"]
            
        scores.append(score)
    return scores

def _post_pick(obs, picked_idx):
    global ability_used_munkidori
    sel = obs.select
    if sel.context != SelectContext.MAIN: return
    o = sel.option[picked_idx]
    if o.type == OptionType.ABILITY:
        card = get_card(obs, o.area, o.index, obs.current.yourIndex)
        if card is not None and card.id == Munkidori: 
            ability_used_munkidori += 1

def _agent_impl(obs_dict):
    obs = to_observation_class(obs_dict)
    if obs.select is None: return my_deck
    scores = heuristic_scores(obs)
    desc = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    if desc: _post_pick(obs, desc[0])
    return desc[:obs.select.maxCount]

def _heuristic_agent(obs_dict):
    try:
        return _agent_impl(obs_dict)
    except Exception:
        try:
            obs = to_observation_class(obs_dict)
            if obs.select is None: return my_deck
            n = len(obs.select.option)
            k = min(max(1, obs.select.minCount), n) if n else 0
            return list(range(k))
        except Exception:
            return [0]

# ==================== SEARCH LAYER ====================
try:
    from cg.api import search_begin, search_step, search_end
    _SEARCH_IMPORT_OK = True
except Exception:
    _SEARCH_IMPORT_OK = False
    
USE_SEARCH = True
N_DET = 3
K_OPP = 3
MAX_SUBSTEPS = 40
TIME_BUDGET_S = 0.80
SEARCH_MAX_OPTS = 24
_MAX_CAND = 8
DUMMY_BASIC = 646 # Impidimp
DUMMY_ENERGY = 7  # Dark

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
                if len(_ids) == 60:
                    _TEMPLATES.append((_fn, Counter(_ids), _ids))
            except: pass
        break

_BASIC_ENERGY = {i: i for i in range(1, 9)}
def _pokemon_ids(counter):
    return {cid for cid in counter if card_table.get(cid) and card_table[cid].cardType == CardType.POKEMON}
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
    if state.stadium and state.stadium[0].playerIndex == me_i:
        seen[state.stadium[0].id] += 1
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
    if state.stadium and state.stadium[0].playerIndex == op_i:
        seen[state.stadium[0].id] += 1
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
    for cid, n in Counter(my_deck).items():
        remain.extend([cid] * max(0, n - seen.get(cid, 0)))
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
    
    op_damage_counters = sum((card_table[p.id].hp - p.hp) for p in op_field if p.id in card_table)
    
    my_en = sum(len(p.energies) for p in my_field)
    op_en = sum(len(p.energies) for p in op_field)
    no_active = 0 if (me.active and me.active[0]) else 1
    
    return (1000.0 * (len(op.prize) - len(me.prize))
            + 20.0 * op_damage_counters 
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
    except:
        return None
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