import os, json, sys, time, random
from collections import defaultdict, Counter

from cg.api import AreaType, CardType, EnergyType, Observation, SelectContext, OptionType, Card, Pokemon, all_card_data, to_observation_class

"""
ns_zoroark_evo_perfect_slot: Agente definitivo per il deck N's Zoroark ex.
- Gestione slot di panchina riservato (lascia sempre spazio per N's Zekrom).
- Motore di pescata "Trade" ottimizzato con scarti strategici (combinato con N's PP Up).
- Selezione adattiva dell'attacco tramite "Night Joker" (Zekrom per i danni, Shred vs Muri, Darmanitan per punire gli scarti).
- Search Layer 2-ply inlined per il calcolo letale.
"""

WEIGHTS = {
    # PLAY POKEMON (con riserva slot per Zekrom)
    "play_zorua": 18000, "play_zorua_need": 25000,
    "play_darumaka": 15000, 
    "play_zekrom_reserved": 28000, # Priorità alta per assicurarsi lo slot protetto
    "play_reshiram": 13000,
    "play_munkidori": 10000,
    "play_fezandipiti": 16000,
    "play_pecharunt": 9000,
    
    # TRAINERS
    "poffin_early": 22000, "poffin_late": 10000,
    "ultra_ball_energy_discard": 18000, "ultra_ball": 15000,
    "ns_pp_up": 26000,
    "cyrano": 20000,
    "night_stretcher": 12000,
    "poke_pad": 11000,
    
    # SUPPORTERS
    "boss_lethal": 100000, "boss_kill": 19000,
    "judge_disrupt": 15000,
    "lillie_draw": 17000,
    
    # STADIUMS
    "ns_castle": 16000,
    "tr_watchtower": 18000,
    
    # TOOLS & ENERGY
    "cape_zoroark": 25000,
    "energy_dark_zoroark": 22000,
    "energy_dark_zorua": 18000,
    "energy_dark_munkidori": 15000,
    
    # EVOLVE
    "evolve_zoroark": 30000,
    "evolve_darmanitan": 20000,
    
    # ABILITIES
    "ability_trade": 28000,
    "ability_fezandipiti": 27000,
    "ability_munkidori": 20000,
    "ability_pecharunt": 15000,
    
    # ATTACK
    "attack_lethal": 100000,
    "attack_night_joker": 30000,
    "attack_shred_vs_wall": 35000,
    "attack_rampaging_thunder": 28000,
    "attack_back_draft": 25000
}

W = WEIGHTS

# DECK HARDCODED (N's Zoroark ex) — nessun caricamento da deck.csv esterno, zero rischi
my_deck = ([7]*10 + [141] + [257] + [258] + [292]*4 + [293]*4 + [303]*2 + [112] + [140]
           + [906]*2 + [1086]*4 + [1097]*2 + [1113]*4 + [1121]*3 + [1152]*4 + [1159]
           + [1182]*2 + [1205]*3 + [1213]*2 + [1227]*4 + [1253]*2 + [1256]*2)
assert len(my_deck) == 60, f"zoroark deck {len(my_deck)}"

all_card = all_card_data()
card_table = {c.cardId: c for c in all_card}

# ---- Core IDs ----
Basic_Dark_Energy = 7
Pecharunt_ex = 141
Darumaka = 257
Darmanitan = 258
Zorua = 292
Zoroark_ex = 293
Reshiram = 303
Munkidori = 112
Fezandipiti_ex = 140
Zekrom = 906

Buddy_Poffin = 1086
Night_Stretcher = 1097
Ns_PP_Up = 1113
Ultra_Ball = 1121
Poke_Pad = 1152
Heros_Cape = 1159
Boss_Orders = 1182
Cyrano = 1205
Judge = 1213
Lillie_Det = 1227
Ns_Castle = 1253
TR_Watchtower = 1256

NS_POKEMON = {Darumaka, Darmanitan, Zorua, Zoroark_ex, Reshiram, Zekrom}

pre_turn = 0
ability_used_fezandipiti = False
ability_used_pecharunt = False

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
        case AreaType.LOOKING: return getattr(obs.current, "looking", [None])[index]
        case _: return None

def heuristic_scores(obs):
    state = obs.current
    select = obs.select
    context = select.context
    my_index = state.yourIndex
    my_state = state.players[my_index]
    op_state = state.players[1 - my_index]

    global pre_turn, ability_used_fezandipiti, ability_used_pecharunt
    if pre_turn != state.turn:
        pre_turn = state.turn
        ability_used_fezandipiti = False
        ability_used_pecharunt = False

    my_prize_count = len(my_state.prize)
    
    field_counts = defaultdict(int)
    my_field = []
    
    op_has_wall = False
    op_has_lethal_target = False
    op_discard_energy = sum(1 for c in op_state.discard if c and c.id in range(1, 9))
    
    for p in op_state.active:
        if p:
            if p.id in {345, 434, 414}: op_has_wall = True

    for p in op_state.bench:
        if p:
            data = card_table.get(p.id)
            if data and data.hp <= 250 and (data.ex or data.megaEx) and my_prize_count <= 2:
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
    zoroark_ready = active_id == Zoroark_ex and len(getattr(my_state.active[0], "energyCards", [])) >= 2
    
    bench_count = len([b for b in my_state.bench if b])
    bench_max = my_state.benchMax
    bench_free = bench_max - bench_count
    
    # Regola Slot Riservato per Zekrom
    zekrom_in_play = field_counts[Zekrom] > 0
    must_reserve_slot_for_zekrom = not zekrom_in_play

    hand_counts = Counter(c.id for c in my_state.hand if c)
    
    scores = []
    for o in select.option:
        score = 0
        if o.type == OptionType.CARD:
            card = get_card(obs, o.area, o.index, o.playerIndex)
            if not card: scores.append(0); continue
            
            if context in (SelectContext.TARGET, SelectContext.CHOOSE_POKEMON, SelectContext.TO_ACTIVE, SelectContext.SWITCH):
                if o.playerIndex != my_index: 
                    data = card_table.get(card.id)
                    hp = card.hp
                    is_ex = data.ex or data.megaEx if data else False
                    
                    if hp <= 250 and is_ex and my_prize_count <= 2: score = 100000 
                    elif is_ex: score = 30000
                    elif hp <= 250: score = 15000
                    else: score = 1000
                else:
                    if context in (SelectContext.TO_ACTIVE, SelectContext.SWITCH):
                        if card.id == Zoroark_ex: score = 50000
                        elif card.id == Zorua: score = 15000
                        else: score = 1000
                        
                    if active_id == Zoroark_ex and card.id in NS_POKEMON:
                        if op_has_wall and card.id == Zekrom: score = W["attack_shred_vs_wall"]
                        # bersaglio >250 HP: Zekrom (250) non OHKO e salta il turno dopo ->
                        # Reshiram (170, senza malus) 2HKO in 2 turni = piu' veloce
                        elif op_state.active and op_state.active[0] and op_state.active[0].hp > 250 and card.id == Reshiram: score = 29000
                        elif op_state.active and op_state.active[0] and op_state.active[0].hp > 150 and card.id == Zekrom: score = W["attack_rampaging_thunder"]
                        elif op_discard_energy >= 6 and card.id == Darmanitan: score = W["attack_back_draft"]
                        elif my_state.active[0] and (card_table[Zoroark_ex].hp - my_state.active[0].hp) >= 120 and card.id == Reshiram: score = 26000
                        else: score = 10000

            elif context == SelectContext.TO_DISCARD:
                if card.id == Basic_Dark_Energy and hand_counts[Ns_PP_Up] > 0: score = 30000
                elif card.id == Basic_Dark_Energy: score = 15000
                elif card.id == TR_Watchtower and field_counts[TR_Watchtower] > 0: score = 25000
                elif card.id == Ns_Castle and field_counts[Ns_Castle] > 0: score = 25000
                elif card.cardType == CardType.POKEMON and field_counts[card.id] >= 2 and card.id != Zekrom: score = 10000
                else: score = 100

            elif context == SelectContext.SETUP_ACTIVE_POKEMON:
                if card.id == Zorua: score = 50
                elif card.id == Zekrom and not zekrom_in_play: score = 45
                else: score = 10
                
            elif context == SelectContext.SETUP_BENCH_POKEMON:
                if card.id == Zekrom and not zekrom_in_play: score = 120 # Priorità massima per posizionare Zekrom riservato
                elif card.id == Zorua: score = 110
                elif card.id == Darumaka: score = 100
                else: score = 50

            elif context == SelectContext.TO_HAND:
                if card.id == Zekrom and not zekrom_in_play: score = 220
                elif card.id == Zoroark_ex and field_counts[Zoroark_ex] == 0: score = 210
                elif card.id == Darmanitan and field_counts[Darmanitan] == 0: score = 190
                elif card.id == Fezandipiti_ex and field_counts[Fezandipiti_ex] == 0: score = 180
                elif card.id == Zorua and field_counts[Zorua] < 3: score = 170
                elif card.id == Basic_Dark_Energy: score = 160
                elif card.id == Ns_PP_Up: score = 150
                else: score = 50

        elif o.type == OptionType.PLAY:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            cid = card.id
            is_early = state.turn <= 2

            if cid in card_table and card_table[cid].cardType == CardType.POKEMON:
                # SE LO SLOT E' DA RISERVARE PER ZEKROM, BLOCCA LA GIOCATA DI ALTRI POKEMON EXTRA IN PANCHINA
                if must_reserve_slot_for_zekrom and bench_free <= 1 and cid != Zekrom:
                    score = -5000
                else:
                    if cid == Zekrom: score = W["play_zekrom_reserved"] if not zekrom_in_play else 1000
                    elif cid == Zorua: score = W["play_zorua_need"] if field_counts[Zorua] < 2 else W["play_zorua"]
                    elif cid == Darumaka: score = W["play_darumaka"]
                    elif cid == Reshiram: score = W["play_reshiram"]
                    elif cid == Fezandipiti_ex: score = W["play_fezandipiti"]
                    elif cid == Munkidori: score = W["play_munkidori"]
                    elif cid == Pecharunt_ex: score = W["play_pecharunt"]
                    else: score = 500
            else:
                score = 5000
                if cid == Ns_PP_Up:
                    if op_discard_energy > 0: score = W["ns_pp_up"]
                    else: score = -5000
                elif cid == Heros_Cape:
                    if field_counts[Zoroark_ex] > 0: score = W["cape_zoroark"]
                    else: score = -100
                elif cid == Cyrano: score = W["cyrano"]
                elif cid == Buddy_Poffin:
                    if must_reserve_slot_for_zekrom and bench_free <= 1: score = -2000 # Evita di riempire l'ultimo slot con Poffin se manca Zekrom
                    else: score = W["poffin_early"] if is_early else W["poffin_late"]
                elif cid == Ultra_Ball: score = W["ultra_ball_energy_discard"] if hand_counts[Basic_Dark_Energy] > 0 else W["ultra_ball"]
                elif cid == Boss_Orders: score = W["boss_lethal"] if op_has_lethal_target and zoroark_ready else W["boss_kill"]
                elif cid == Lillie_Det: score = W["lillie_draw"] if len(my_state.hand) <= 5 else 5000
                elif cid == Judge: score = W["judge_disrupt"] if op_state.handCount >= 5 else 3000
                elif cid == Poke_Pad: score = W["poke_pad"]
                elif cid == Night_Stretcher: score = W["night_stretcher"]
                elif cid == Ns_Castle: score = W["ns_castle"] if not state.stadium or state.stadium[0].id != Ns_Castle else -100
                elif cid == TR_Watchtower: score = W["tr_watchtower"] if not state.stadium or state.stadium[0].id != TR_Watchtower else -100

        elif o.type == OptionType.ATTACH:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            pokemon = get_card(obs, o.inPlayArea, o.inPlayIndex, my_index)
            
            if card.id == Basic_Dark_Energy:
                if pokemon.id == Zoroark_ex: score = W["energy_dark_zoroark"]
                elif pokemon.id == Zorua: score = W["energy_dark_zorua"]
                elif pokemon.id == Munkidori and len(getattr(pokemon, "energyCards", [])) == 0: score = W["energy_dark_munkidori"]
                else: score = 5000
                
            elif card.id == Heros_Cape:
                if pokemon.id == Zoroark_ex: score = W["cape_zoroark"]
                else: score = 5000

        elif o.type == OptionType.EVOLVE:
            card = get_card(obs, AreaType.HAND, o.index, my_index)
            if card.id == Zoroark_ex: score = W["evolve_zoroark"]
            elif card.id == Darmanitan: score = W["evolve_darmanitan"]
            else: score = 5000

        elif o.type == OptionType.ABILITY:
            card = get_card(obs, o.area, o.index, my_index)
            if card.id == Zoroark_ex: score = W["ability_trade"]
            elif card.id == Fezandipiti_ex and not ability_used_fezandipiti: score = W["ability_fezandipiti"]
            elif card.id == Pecharunt_ex and not ability_used_pecharunt and active_id != Zoroark_ex and field_counts[Zoroark_ex] > 0: score = W["ability_pecharunt"]
            elif card.id == Munkidori: score = W["ability_munkidori"]
            else: score = 1000

        elif o.type == OptionType.RETREAT:
            if active_id != Zoroark_ex and field_counts[Zoroark_ex] > 0: score = 10000
            else: score = -5000

        elif o.type == OptionType.ATTACK:
            score = 1000
            if active_id == Zoroark_ex: score = W["attack_night_joker"]
            elif active_id == Darmanitan: score = W["attack_back_draft"]
            
        scores.append(score)
    return scores

def _post_pick(obs, picked_idx):
    global ability_used_fezandipiti, ability_used_pecharunt
    sel = obs.select
    if sel.context != SelectContext.MAIN: return
    o = sel.option[picked_idx]
    if o.type == OptionType.ABILITY:
        card = get_card(obs, o.area, o.index, obs.current.yourIndex)
        if card is not None:
            if card.id == Fezandipiti_ex: ability_used_fezandipiti = True
            elif card.id == Pecharunt_ex: ability_used_pecharunt = True

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
DUMMY_BASIC = 292 
DUMMY_ENERGY = 7  

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
        if cs is None or cur.select is None or cur.select.context == SelectContext.MAIN or (cs.result is not None and cs.result >= 0): break
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