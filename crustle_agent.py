import os, json, sys, time, random
from collections import defaultdict, Counter

from cg.api import AreaType, CardType, EnergyType, Observation, SelectContext, OptionType, Card, Pokemon, all_card_data, to_observation_class

"""
crustle_kangaskhan_evo_perfect: Agente completo Crustle / Mega Kangaskhan ex.
- Counter Alakazam: Setup immediato di Articuno in attivo con TR Energy.
- Counter EX: Priorità a Dwebble/Crustle se l'avversario gioca EX/V.
- Tank Setup: Mega Kangaskhan ex + Hero's Cape + Spiky Energy + Cure estreme.
- Search Layer 2-ply integrato per il calcolo letale e ottimizzazione turni.
"""

# ---- Tunable Priority Weights ----
WEIGHTS = {
    "play_kangaskhan": 15000, "play_kangaskhan_need": 20000,
    "play_dwebble": 14000, "play_dwebble_vs_ex": 22000,
    "play_articuno": 8000, "play_articuno_vs_alakazam": 25000,
    
    "poffin_early": 16000, "poffin_late": 8000,
    "ultra_ball": 14000,
    "night_stretcher": 12000,
    "pokegear": 15000,
    "switch_vs_ex": 25000, "switch_vs_alakazam": 25000,
    
    "boss_lethal": 100000, "boss_kill": 18000,
    "eri_disrupt": 13000,
    "xerosic_disrupt": 14000,
    "petrel_search": 16000,
    "hilda_search": 17000,
    "lillie_draw": 16000,
    
    "heal_bianca": 28000,
    "heal_ice_cream": 24000,
    
    "cape_kangaskhan": 30000, "cape_crustle": 20000,
    
    "energy_tr_articuno": 25000, "energy_tr_bad": -20000,
    "energy_spiky_kanga": 22000, "energy_spiky_crustle": 18000,
    "energy_grass_crustle": 20000, "energy_grass_kanga": 15000,
    "energy_water_articuno": 18000, "energy_water_kanga": 15000,
    
    "evolve_crustle": 15000, "evolve_crustle_vs_ex": 28000,
    
    "ability_run_errand": 30000,
    
    "retreat_to_crustle_vs_ex": 28000,
    "retreat_to_articuno_vs_alakazam": 28000,
    
    "attack_lethal": 100000,
    "attack_crustle_vs_ex": 30000,
    "attack_kangaskhan": 20000,
    "attack_articuno": 18000,
    "attack_crustle": 15000
}

W = WEIGHTS

# DECK HARDCODED (Crustle muro, = deck_crustle.csv) — nessun caricamento esterno
my_deck = ([756]*4 + [344]*3 + [345]*3 + [414]*3 + [1182]*4 + [1227]*4 + [1219]*3
           + [1186]*2 + [1225]*2 + [1197] + [1190] + [1147]*2 + [1122]*2 + [1086] + [1121]
           + [1123]*3 + [1159] + [1097] + [3]*4 + [18]*4 + [15]*4 + [14]*4 + [1]*3)
assert len(my_deck) == 60, f"crustle deck {len(my_deck)}"

all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}

# ---- Core IDs ----
Grass_Energy, Water_Energy, Spiky_Energy, TR_Energy, Grow_Grass_Energy = 1, 3, 14, 15, 18
Dwebble, Crustle, Articuno, M_Kangaskhan_ex = 344, 345, 414, 756
Buddy_Poffin, Night_Stretcher, Ultra_Ball, Pokegear, Switch = 1086, 1097, 1121, 1122, 1123
Jumbo_Ice_Cream, Heros_Cape = 1147, 1159
Boss_Orders, Eri, Bianca, Xerosic, Petrel, Hilda, Lillie = 1182, 1186, 1190, 1197, 1219, 1225, 1227

ALAKAZAM_LINE = {741, 742, 743}

pre_turn = 0
ability_used_run_errand = False

def get_card(obs, area, index, player_index):
    ps = obs.current.players[player_index]
    match area:
        case AreaType.DECK: return obs.select.deck[index]
        case AreaType.HAND: return getattr(ps, "hand", [None])[index]
        case AreaType.DISCARD: return getattr(ps, "discard", [None])[index]
        case AreaType.ACTIVE: return getattr(ps, "active", [None])[index]
        case AreaType.BENCH: return getattr(ps, "bench", [None])[index]
        case AreaType.PRIZE: return getattr(ps, "prize", [None])[index]
        case AreaType.STADIUM: return obs.current.stadium[index] if obs.current.stadium else None
        case AreaType.LOOKING: return obs.current.looking[index] if obs.current.looking else None
        case _: return None

def heuristic_scores(obs):
    state = obs.current
    select = obs.select
    context = select.context
    my_index = state.yourIndex
    my_state = state.players[my_index]
    op_state = state.players[1 - my_index]

    global pre_turn, ability_used_run_errand
    if pre_turn != state.turn:
        pre_turn = state.turn
        ability_used_run_errand = False

    my_prize_count = len(my_state.prize)
    
    field_counts = defaultdict(int)
    my_field = []
    
    op_has_ex_active = False
    op_has_ex = False
    op_has_alakazam = False
    op_has_lethal_target = False
    
    # Rilevamento Matchup Avversario
    for p in op_state.active:
        if p:
            data = card_table.get(p.id)
            if data and (data.ex or data.megaEx):
                op_has_ex_active = True
                op_has_ex = True
            if p.id in ALAKAZAM_LINE: op_has_alakazam = True

    for p in op_state.bench:
        if p:
            data = card_table.get(p.id)
            if data and (data.ex or data.megaEx): op_has_ex = True
            if p.id in ALAKAZAM_LINE: op_has_alakazam = True
            if data and data.hp <= 200 and (data.ex or data.megaEx) and my_prize_count <= 2:
                op_has_lethal_target = True

    for idx, card in enumerate(my_state.active):
        if card:
            field_counts[card.id] += 1
            my_field.append((0, card))
    for idx, card in enumerate(my_state.bench):
        if card:
            field_counts[card.id] += 1
            my_field.append((idx + 1, card))
            
    active_id = my_state.active[0].id if my_state.active and my_state.active[0] else -1

    scores = []
    for o in select.option:
        score = 0
        if o.type == OptionType.CARD:
            card = get_card(obs, o.area, o.index, o.playerIndex)
            if not card: scores.append(0); continue
            
            # --- 1. Targeting (Boss, Switch, Cure) ---
            if context in (SelectContext.TARGET, SelectContext.CHOOSE_POKEMON, SelectContext.TO_ACTIVE, SelectContext.SWITCH):
                if o.playerIndex != my_index: 
                    data = card_table.get(card.id)
                    hp = card.hp
                    is_ex = data.ex or data.megaEx if data else False
                    
                    if hp <= 200 and is_ex and my_prize_count <= 2: score = 100000 
                    elif is_ex: score = 30000
                    else: score = 1000
                else:
                    if getattr(select, "effect", None): 
                        max_hp = card_table.get(card.id).hp if card.id in card_table else getattr(card, 'maxHp', 300)
                        score = (max_hp - card.hp) * 10
                        
                    if context in (SelectContext.TO_ACTIVE, SelectContext.SWITCH):
                        if op_has_alakazam and card.id == Articuno: score = 60000
                        elif op_has_ex_active and card.id == Crustle: score = 50000
                        elif card.id == M_Kangaskhan_ex: score = 20000
                        elif card.id == Dwebble and op_has_ex_active: score = 15000
                        else: score = 1000

            # --- 2. Setup Base ---
            elif context == SelectContext.SETUP_ACTIVE_POKEMON:
                if op_has_alakazam and card.id == Articuno: score = 60
                elif op_has_ex and card.id == Dwebble: score = 55
                elif card.id == M_Kangaskhan_ex: score = 50
                elif card.id == Dwebble: score = 40
                elif card.id == Articuno: score = 30
                else: score = 10
                
            elif context == SelectContext.SETUP_BENCH_POKEMON:
                if op_has_alakazam and card.id == Articuno: score = 110
                elif op_has_ex and card.id == Dwebble: score = 105
                elif card.id == Dwebble: score = 100
                elif card.id == M_Kangaskhan_ex: score = 90
                elif card.id == Articuno: score = 80
                else: score = 50

            # --- 3. Scarti Forzati ---
            elif context == SelectContext.TO_DISCARD:
                if card.id in (Water_Energy, Grass_Energy): score = 15000
                elif card.id == Articuno and not op_has_alakazam: score = 10000
                elif card.id == TR_Energy: score = W["energy_tr_bad"]
                else: score = 100

            # --- 4. Ricerca (Petrel, Ultra Ball) ---
            elif context == SelectContext.TO_HAND:
                if op_has_alakazam and card.id == Articuno and field_counts[Articuno] == 0: score = 210
                elif op_has_alakazam and card.id == TR_Energy: score = 205
                elif card.id == Crustle and field_counts[Dwebble] > 0: score = 200
                elif card.id == M_Kangaskhan_ex and field_counts[M_Kangaskhan_ex] == 0: score = 190
                elif card.id == Heros_Cape: score = 180
                elif card.id == Grow_Grass_Energy: score = 170
                elif card.id == Spiky_Energy: score = 160
                else: score = 50

        elif o.type == OptionType.PLAY:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            cid = card.id
            is_early = state.turn <= 2

            if cid in card_table and card_table[cid].cardType == CardType.POKEMON:
                if cid == M_Kangaskhan_ex: score = W["play_kangaskhan_need"] if field_counts[M_Kangaskhan_ex] == 0 else W["play_kangaskhan"]
                elif cid == Dwebble: score = W["play_dwebble_vs_ex"] if op_has_ex else W["play_dwebble"]
                elif cid == Articuno: score = W["play_articuno_vs_alakazam"] if op_has_alakazam else W["play_articuno"]
                else: score = 500
            else:
                score = 5000
                if cid == Heros_Cape:
                    if field_counts[M_Kangaskhan_ex] > 0: score = W["cape_kangaskhan"]
                    elif field_counts[Crustle] > 0: score = W["cape_crustle"]
                    else: score = -100
                elif cid == Bianca:
                    # Heal full se un nostro pokemon è sceso a <= 30 HP
                    if any(p[1].hp <= 30 for p in my_field): score = W["heal_bianca"]
                    else: score = -5000
                elif cid == Jumbo_Ice_Cream:
                    # Cura 80 solo se ci sono >= 3 energie
                    if any(p[1].hp < card_table.get(p[1].id, p[1]).hp and len(getattr(p[1], 'energies', [])) >= 3 for p in my_field): 
                        score = W["heal_ice_cream"]
                    else: score = -5000
                elif cid == Buddy_Poffin: score = W["poffin_early"] if is_early else W["poffin_late"]
                elif cid == Ultra_Ball: score = W["ultra_ball"]
                elif cid == Boss_Orders: score = W["boss_lethal"] if op_has_lethal_target else W["boss_kill"]
                elif cid == Petrel: score = W["petrel_search"]
                elif cid == Hilda: score = W["hilda_search"]
                elif cid == Lillie: score = W["lillie_draw"] if len(my_state.hand) <= 4 else 5000
                elif cid == Pokegear: score = W["pokegear"]
                elif cid == Night_Stretcher: score = W["night_stretcher"]
                elif cid == Xerosic: score = W["xerosic_disrupt"] if op_state.handCount >= 5 else -100
                elif cid == Eri: score = W["eri_disrupt"] if op_state.handCount >= 4 else -100
                elif cid == Switch:
                    if op_has_alakazam and active_id != Articuno and field_counts[Articuno] > 0: score = W["switch_vs_alakazam"]
                    elif op_has_ex_active and active_id != Crustle and field_counts[Crustle] > 0: score = W["switch_vs_ex"]
                    else: score = -500

        elif o.type == OptionType.ATTACH:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            pokemon = get_card(obs, o.inPlayArea, o.inPlayIndex, my_index)
            
            if card.id == TR_Energy:
                if pokemon.id == Articuno: score = W["energy_tr_articuno"]
                else: score = W["energy_tr_bad"]
                
            elif card.id == Heros_Cape:
                if pokemon.id == M_Kangaskhan_ex: score = W["cape_kangaskhan"]
                elif pokemon.id == Crustle: score = W["cape_crustle"]
                else: score = 5000
                
            elif card.id in (Grass_Energy, Grow_Grass_Energy):
                if pokemon.id in (Dwebble, Crustle): score = W["energy_grass_crustle"]
                elif pokemon.id == M_Kangaskhan_ex: score = W["energy_grass_kanga"]
                else: score = 5000
                
            elif card.id == Spiky_Energy:
                if pokemon.id == M_Kangaskhan_ex: score = W["energy_spiky_kanga"]
                elif pokemon.id == Crustle: score = W["energy_spiky_crustle"]
                else: score = 10000
                
            elif card.id == Water_Energy:
                if pokemon.id == Articuno: score = W["energy_water_articuno"]
                elif pokemon.id == M_Kangaskhan_ex: score = W["energy_water_kanga"]
                else: score = 5000

        elif o.type == OptionType.EVOLVE:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            if card.id == Crustle: score = W["evolve_crustle_vs_ex"] if op_has_ex else W["evolve_crustle"]
            else: score = 5000

        elif o.type == OptionType.ABILITY:
            card = get_card(obs, o.area, o.index, my_index)
            if card.id == M_Kangaskhan_ex and not ability_used_run_errand: score = W["ability_run_errand"]
            else: score = 1000

        elif o.type == OptionType.RETREAT:
            if op_has_alakazam and active_id != Articuno and field_counts[Articuno] > 0: score = W["retreat_to_articuno_vs_alakazam"]
            elif op_has_ex_active and active_id != Crustle and field_counts[Crustle] > 0: score = W["retreat_to_crustle_vs_ex"]
            elif active_id != M_Kangaskhan_ex and field_counts[M_Kangaskhan_ex] > 0 and not op_has_ex_active and not op_has_alakazam: score = 10000
            else: score = -5000

        elif o.type == OptionType.ATTACK:
            score = 1000
            if op_state.active and op_state.active[0]:
                active_op = op_state.active[0]
                data = card_table.get(active_op.id)
                is_ex = data.ex or data.megaEx if data else False
                
                dmg = 0
                if active_id == M_Kangaskhan_ex: dmg = 200
                elif active_id == Crustle: dmg = 120
                elif active_id == Articuno: dmg = 120 if any(getattr(e, 'id', -1) == TR_Energy for e in getattr(my_state.active[0], "energyCards", [])) else 60
                
                if active_op.hp <= dmg and (is_ex and my_prize_count <= 2 or not is_ex and my_prize_count <= 1): score = W["attack_lethal"]
                else:
                    if active_id == Crustle and op_has_ex_active: score = W["attack_crustle_vs_ex"]
                    elif active_id == M_Kangaskhan_ex: score = W["attack_kangaskhan"]
                    elif active_id == Articuno: score = W["attack_articuno"]
                    elif active_id == Crustle: score = W["attack_crustle"]
            
        scores.append(score)
    return scores

def _post_pick(obs, picked_idx):
    global ability_used_run_errand
    sel = obs.select
    if sel.context != SelectContext.MAIN: return
    o = sel.option[picked_idx]
    if o.type == OptionType.ABILITY:
        card = get_card(obs, o.area, o.index, obs.current.yourIndex)
        if card is not None and card.id == M_Kangaskhan_ex: 
            ability_used_run_errand = True

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
DUMMY_BASIC = 344 
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
    for c in (getattr(me, "hand", []) or []): seen[c.id] += 1
    for c in getattr(me, "discard", []): seen[c.id] += 1
    for c in getattr(me, "prize", []):
        if c is not None: seen[c.id] += 1
    for p in getattr(me, "active", []) + getattr(me, "bench", []):
        if p is None: continue
        seen[p.id] += 1
        for c in getattr(p, "energyCards", []): seen[c.id] += 1
        for c in getattr(p, "tools", []): seen[c.id] += 1
        for c in getattr(p, "preEvolution", []): seen[c.id] += 1
    if getattr(state, "stadium", None) and state.stadium[0].playerIndex == me_i: seen[state.stadium[0].id] += 1
    return seen

def _op_visible(state, op_i):
    op = state.players[op_i]
    seen = Counter()
    etype = Counter()
    for c in getattr(op, "discard", []): seen[c.id] += 1
    for p in getattr(op, "active", []) + getattr(op, "bench", []):
        if p is None: continue
        seen[p.id] += 1
        for c in getattr(p, "energyCards", []): seen[c.id] += 1
        for c in getattr(p, "tools", []): seen[c.id] += 1
        for c in getattr(p, "preEvolution", []): seen[c.id] += 1
        for e in getattr(p, "energies", []): etype[int(e)] += 1
    if getattr(state, "stadium", None) and state.stadium[0].playerIndex == op_i: seen[state.stadium[0].id] += 1
    for c in getattr(op, "prize", []):
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
    
    n_prize_hidden = sum(1 for c in getattr(me, "prize", []) if c is None)
    need = getattr(me, "deckCount", 0) + n_prize_hidden
    if len(remain) < need: remain += [DUMMY_ENERGY] * (need - len(remain))
    random.shuffle(remain)
    
    deck_c = getattr(me, "deckCount", 0)
    your_deck = remain[:deck_c]
    fill = iter(remain[deck_c:need])
    your_prize = [c.id if c is not None else next(fill, DUMMY_ENERGY) for c in getattr(me, "prize", [])]

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
        
    n_op_prize_hidden = sum(1 for c in getattr(op, "prize", []) if c is None)
    op_need = getattr(op, "deckCount", 0) + n_op_prize_hidden + getattr(op, "handCount", 0)
    if len(pool) < op_need: pool += [DUMMY_ENERGY] * (op_need - len(pool))
    random.shuffle(pool)
    
    op_deck_c = getattr(op, "deckCount", 0)
    opponent_deck = pool[:op_deck_c]
    off = op_deck_c
    fill_op = iter(pool[off:off + n_op_prize_hidden])
    opponent_prize = [c.id if c is not None else next(fill_op, DUMMY_ENERGY) for c in getattr(op, "prize", [])]
    off += n_op_prize_hidden
    opponent_hand = pool[off:off + getattr(op, "handCount", 0)]
    opponent_active = [DUMMY_BASIC] if (getattr(op, "active", []) and op.active[0] is None) else []
    
    return dict(your_deck=your_deck, your_prize=your_prize, opponent_deck=opponent_deck, opponent_prize=opponent_prize, opponent_hand=opponent_hand, opponent_active=opponent_active)

def _leaf_eval(state, me_i):
    if state is None: return 0.0
    if state.result is not None and state.result >= 0:
        if state.result == me_i: return 1e7
        if state.result == 2: return 0.0
        return -1e7
    me = state.players[me_i]
    op = state.players[1 - me_i]
    my_field = [p for p in getattr(me, "active", []) + getattr(me, "bench", []) if p]
    op_field = [p for p in getattr(op, "active", []) + getattr(op, "bench", []) if p]
    
    # Valuta la tankiness (Kangaskhan curato)
    my_hp = sum(p.hp for p in my_field)
    op_hp = sum(p.hp for p in op_field)
    
    my_en = sum(len(getattr(p, "energies", [])) for p in my_field)
    op_en = sum(len(getattr(p, "energies", [])) for p in op_field)
    no_active = 0 if getattr(me, "active", []) and me.active[0] else 1
    
    return (1000.0 * (len(getattr(op, "prize", [])) - len(getattr(me, "prize", [])))
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

def agent(obs_dict, deck_name=None):   # deck_name accettato per retro-compatibilita' coi chiamanti (alak_search_ro/pool_agents)
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